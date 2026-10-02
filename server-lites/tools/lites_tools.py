#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lites_tools —— LITES 仪器级仿真 MCP 工具集（真实可交互）。

与 TDLAS 工具集的关系
─────────────────────
本模块**不复用** tdlas 的任何工具语义。虽然两者都做"激光光谱气体检测仿真"，
但物理链、可调参数、失效模式完全不同（见 lites_physics 模块头）。沿用 TDLAS
的入参名（如 sigma_tau、2f/1f）会误导使用者，因此这里**重新定义**工具与口径。

工具一览（10 个）
─────────────────
  建模/前向
    lites_forward          单点 2f 电压预测（含"线上/线外"分解）
    lites_sweep            参数扫描：功率/浓度/光程/调制频率/f0 漂移
    lites_waveform         2f 波形合成 + 可选出图（仪器级 6 子图）
  反演/指标
    lites_invert           由实测 2f 电压反演气体浓度
    lites_mdl              最小可探测浓度（含 Allan 积分改善）
    lites_noise_budget     噪声预算分解（1/f vs 白噪声 vs TIA 电容）
  器件/工况
    lites_device           器件库查询与自定义器件标定
    lites_resonance        共振跟踪与温漂失谐分析
    lites_compare          多方案对比（选型/权衡表）
  诊断
    lites_review           实验方案体检（挑错，不给"看起来不错"）
    lites_guide            用法指南
    lites_selftest         全链路自检

设计原则（与 WorkBuddy 协作契约）
─────────────────────────────────
· **不静默假设**：任何未给出的参数都进入 `assumptions`，并在 `next_required_actions`
  中列出需要用户确认的项。
· **不粉饰**：模型不确定的地方进 `disclosure_pending`（如 η_dev 未实测）。
· **可交互**：每个工具返回 `interaction` 块，给出"下一步可以问什么"。
"""
from __future__ import annotations

import io
import json
import math
import os
import sys
import contextlib
from pathlib import Path

import numpy as np

# ── 让 tools/ 之内与仓库根目录都能 import 到 lites_physics ────────────
_SRV = Path(__file__).resolve().parent.parent      # server-lites
_ROOT = _SRV.parent                            # 仓库根（spectrolink_core）
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lites_physics as lph  # noqa: E402

try:
    from spectrolink_core import hitran as _hitran
except Exception:
    _hitran = None



# ══════════════════════════════════════════════════════════════════════
# 0. 通用工具函数
# ══════════════════════════════════════════════════════════════════════

def _quiet():
    """吞掉第三方库的 stdout，避免污染 JSON-RPC 流。"""
    return contextlib.redirect_stdout(io.StringIO())


# 中文字体候选：按「黑体优先、跨平台兜底」排序。
# 找不到任何一款时退回 DejaVu Sans（图内中文会显示为方框），
# 此时附图中的中文标注会降级——调用方应把这件事写进 disclosure。
_CJK_FONTS = (
    "Microsoft YaHei", "SimHei", "Microsoft JhengHei", "DengXian",
    "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC",
    "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "Sarasa Gothic SC",
    "PingFang SC", "Hiragino Sans GB", "Heiti SC",
)
_CJK_FOUND: list = []          # 模块级缓存，避免重复解析字体表


def _mpl_cjk():
    """配置 matplotlib 中文字体。返回实际启用的字体名列表。

    必须在任何 pyplot 绘图**之前**调用。会关闭 axes.unicode_minus，
    否则负号会因 CJK 字体缺字形而变成方框。
    """
    if _CJK_FOUND:
        return list(_CJK_FOUND)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    avail = {f.name for f in fm.fontManager.ttflist}
    picked = [n for n in _CJK_FONTS if n in avail]
    if not picked:
        picked = []
    _CJK_FOUND.extend(picked)
    plt.rcParams["font.sans-serif"] = picked + ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return list(picked)


def _sanitize_paths(s: str) -> str:
    """把本机绝对路径替换成占位符，避免泄露用户目录结构。"""
    s = str(s)
    for p in (str(_ROOT), str(_ROOT.parent), os.path.expanduser("~")):
        if p and len(p) > 3:
            s = s.replace(p, "<workdir>")
    return s


def _block(assumptions=None, next_actions=None, disclosure=None, interaction=None):
    """构造统一的三段式契约块（TDLAS 工具集沿用同一约定）。"""
    return {
        "assumptions": assumptions or [],
        "next_required_actions": next_actions or [],
        "disclosure_pending": disclosure or [],
        "interaction": interaction or {},
    }


#: 物理常数（与 HITRAN 口径一致）
_T0 = 296.0
_P0 = 1.01325          # atm
_N_STP = 2.479e19      # molecule/cm^3  @296K, 1 atm


def number_density(T: float, P: float) -> float:
    """数密度 N [molecule/cm^3]，理想气体：N = P/(k_B·T)。

    口径：P 单位 atm，T 单位 K。296 K / 1 atm 下 = 2.479e19。
    """
    return _N_STP * (P / _P0) * (_T0 / T)


def peak_alpha(s_line: float, T: float, P: float, x: float,
               gamma_L: float = 0.06) -> float:
    """吸收线**峰值**吸收系数 α [cm^-1]（Voigt 近似用洛伦兹峰）。

        α_peak = S(T) · N · x / (π·γ_L)

    γ_L 为洛伦兹半宽 [cm^-1]，常温常压空气展宽典型 0.05~0.1 cm^-1。

    ⚠ 这是**峰值**不是积分；2f 峰高对应的是"线中心附近"的调制响应，
      因此用峰值口径与 WMS 的 2f 峰高量级更匹配。
    """
    S = float(s_line)
    N = number_density(T, P)
    return S * N * float(x) / (math.pi * max(float(gamma_L), 1e-12))


# ══════════════════════════════════════════════════════════════════════
# 1. 前向：单点 2f 电压预测
# ══════════════════════════════════════════════════════════════════════

def lites_forward(device=lph.DEFAULT_DEVICE, power_mW=None, x=None,
                  line_strength=None, L_gas_cm=None, T=296.0, P=1.01325,
                  gamma_L=0.06, f_m=None, mod_depth_cm1=None,
                  f0_shift_ppm=0.0, eta_spurious=None, species=None):
    """预测 LITES 的 2f 峰值电压，并**显式分解**"线外本底"与"气体贡献"。

    这是 LITES 最容易被误读的地方，所以本工具强制把三项分开返回
    （物理口径见 lites_physics.py，文献修正 2026-10）：
        · V_2f_baseline —— 残余 AM 的 2f 本底（0 浓度时锁相输出，与浓度无关）
        · V_2f          —— 线上总 2f = 本底 + 气体减光信号
        · V_2f_delta    —— 气体减光信号（∝ η_dev·αL），**这才是"气体信号"**

    真实实验里锁相输出的是 V_2f（含基线），基线漂移正是 LITES 的主要误差源；
    把 delta 当成信号、把 baseline 当成"零"是常见的新手错误。
    """
    d = lph.get_device(device)
    assume, actions, disc = [], [], []

    if power_mW is None:
        power_mW = d.cal_power_W * 1e3
        assume.append(f"power_mW 未给出，取器件标定功率 {power_mW:.2f} mW")
    if x is None:
        x = 1e-6
        assume.append("x 未给出，取 1 ppm 作演示；请给出实际浓度")
        actions.append("请确认目标气体摩尔分数 x")
    if line_strength is None:
        line_strength = 1.2e-20
        assume.append("line_strength 未给出，取 1.2e-20 cm^-1/(molec·cm^-2)")
        actions.append("请给出目标吸收线的 HITRAN 线强 S(T)")
    if L_gas_cm is None:
        L_gas_cm = d.path_len_cm
        assume.append(f"L_gas_cm 未给出，取器件配置光程 {L_gas_cm} cm")

    if f_m is None:
        f_m = d.f0 / 2.0
        assume.append(f"f_m 未给出，取 f0/2 = {f_m:.1f} Hz（LITES 常规做法）")

    alpha = peak_alpha(line_strength, T, P, x, gamma_L)
    alpha_eff = alpha
    if f0_shift_ppm:
        alpha_eff = alpha * float(np.asarray(
            lph.mech_transfer(np.array([2.0 * f_m]),
                              lph.f0_drift(d.f0, f0_shift_ppm * 1e-6 * d.f0 /
                                           max(d.tc_ppm_per_K, -1e-9), d.tc_ppm_per_K)
                              if d.tc_ppm_per_K else d.f0,
                              d.q)["mag"]).ravel()[0])
        assume.append(f"f0_shift_ppm={f0_shift_ppm} 已折算为机械失谐衰减")

    p = d.predict_2f_voltage(float(power_mW) * 1e-3, alpha_eff, float(L_gas_cm),
                             f_m=float(f_m), mod_depth_cm1=mod_depth_cm1)

    sp = d.spurious_2f(float(power_mW) * 1e-3, eta_spurious=eta_spurious)

    disc.append(
        "【必须实测后回填】器件自身吸收比 η_dev 由文献 V/P 反推，"
        "未经实验室空白基线标定；它直接决定气体减光信号 V_2f_delta 的"
        "绝对量级（信号 ∝ η_dev·αL）；残余 AM 本底 am_2f_frac 亦需实测。"
        "相对量（功率比、浓度线性、频率响应）不受影响。"
    )

    return {
        "device": {"key": device, "name": d.name, "material": d.material,
                   "coating": d.coating,
                   "f0_Hz": d.f0, "Q": d.q,
                   "tau_acc_ms": d.tau_acc * 1e3,
                   "bw_3dB_Hz": d.bw_3dB},
        "conditions": {"T_K": T, "P_atm": P, "x": x, "L_gas_cm": L_gas_cm,
                       "power_mW": power_mW, "f_m_Hz": f_m,
                       "alpha_peak_cm-1": alpha,
                       "alphaL": alpha * L_gas_cm,
                       "absorbance": 1.0 - math.exp(-alpha * L_gas_cm)},
        "result": {
            "V_2f_V": p["V_2f"],
            "V_2f_baseline_V": p["V_2f_baseline"],
            "V_2f_delta_V": p["V_2f_delta"],
            "SBR_eta": p["V_2f_delta"] / p["V_2f_baseline"]
            if p["V_2f_baseline"] > 0 else None,
            "H_th": p["H_th"], "H_mech": p["H_mech"],
            "phi_th_deg": p["phi_th_deg"],
            "eta_abs_online": p["eta_abs"],
            "eta_abs_offline": d.cal_eta_abs,
            "dT_osc_K": p["dT_osc_K"],
            "strain": p["strain"],
            "V_2f_spurious_V": sp["V_2f_spurious"],
            "m": p.get("m"), "F_m": p.get("F_m"),
            "V_2f_at_m_opt_V": p.get("V_2f_at_m_opt"),
        },
        "interpretation": {
            "note": "真正的气体信号是 V_2f_delta（∝ η_dev·αL）；V_2f_baseline 是残余 AM"
                    "本底，与浓度无关。",
            "SBR_meaning": "SBR_eta = η_gas/am_2f_frac（减光信号/残余 AM"
                           "本底）；LITES 灵敏度被 η_dev 压制是相对 PAS 的劣势"
                           "根源（文献共识：差 1~2 个量级）",
        },
        **_block(assume, actions, disc,
                 {"can_ask": [
                     "把功率/光程/调制频率改成 X 会怎样？→ lites_sweep",
                     "这个条件下能测到多低浓度？→ lites_mdl",
                     "噪声从哪来？→ lites_noise_budget",
                 ]}),
    }


# ══════════════════════════════════════════════════════════════════════
# 2. 扫描：单参数或多参数扫描
# ══════════════════════════════════════════════════════════════════════

_SWEEP_VARS = {
    "power_mW":    ("power_mW", "激光功率 [mW]"),
    "x":           ("x", "摩尔分数"),
    "L_gas_cm":    ("L_gas_cm", "光程 [cm]"),
    "f_m":         ("f_m", "调制频率 [Hz]"),
    "mod_depth":   ("mod_depth_cm1", "调制深度 [cm^-1]"),
    "temperature": ("T", "温度 [K]"),
}


def lites_sweep(device=lph.DEFAULT_DEVICE, var="power_mW", values=None,
                log_scale=True, n_points=25, base=None, **kwargs):
    """扫描单个参数，返回 2f 信号（含基线/增量）随该参数的变化。

    用途：回答"调大功率/加长光程/换调制频率值不值"。
    与 TDLAS 的差别：LITES 中增大光程既**增加** αL 又**损失**功率
    （多通池镜面反射），因此 L 的收益是次线性的——本工具会显式报告
    这一点（若器件配置了 n_pass > 1）。
    """
    d = lph.get_device(device)
    if var not in _SWEEP_VARS:
        raise ValueError(f"var 必须是 {sorted(_SWEEP_VARS)} 之一")
    key, label = _SWEEP_VARS[var]

    if values is None:
        preset = {
            "power_mW": (0.5, 200.0),
            "x": (1e-9, 1e-3),
            "L_gas_cm": (1.0, 2000.0),
            "f_m": (max(d.f0 / 50.0, 1.0), d.f0),
            "mod_depth": (0.02, 1.5),
            "temperature": (250.0, 400.0),
        }[var]
        lo, hi = preset
        values = (np.logspace(math.log10(lo), math.log10(hi), int(n_points))
                  if log_scale else np.linspace(lo, hi, int(n_points)))

    base = dict(base or {})
    base.setdefault("device", device)
    for k, v in kwargs.items():
        base[k] = v

    rows = []
    for v in np.asarray(values, dtype=float):
        call = dict(base)
        call[key] = float(v)
        r = lites_forward(**call)
        rows.append({
            "value": float(v),
            "V_2f_V": r["result"]["V_2f_V"],
            "V_2f_baseline_V": r["result"]["V_2f_baseline_V"],
            "V_2f_delta_V": r["result"]["V_2f_delta_V"],
            "SBR_eta": r["result"]["SBR_eta"],
        })

    # 幂律指数（log-log 斜率，仅对正值的量）
    slope = None
    try:
        vv = np.array([r["value"] for r in rows])
        yy = np.array([r["V_2f_delta_V"] for r in rows])
        m = (vv > 0) & (yy > 0)
        if m.sum() >= 3:
            slope = float(np.polyfit(np.log10(vv[m]), np.log10(yy[m]), 1)[0])
    except Exception:
        slope = None

    notes = []
    if var == "L_gas_cm" and d.n_pass > 1:
        notes.append(
            f"该器件配置了 {d.n_pass} 次反射、镜面反射率 "
            f"{d.mirror_refl}，总透过率仅 {d.optical_throughput()*100:.2f}%。"
            "LITES 信号 ∝ 功率，因此加长光程的净收益 = 吸收增益 × 功率损失，"
            "远低于 TDLAS 的线性收益。"
        )
    if var == "f_m":
        opt = lph.optimal_2f_frequency(d.f0, d.q, d.spot_w_m, d._mat)
        notes.append(
            f"热-机械联合最优 f_m = {opt['f_m_opt']:.1f} Hz，"
            f"f0/2 = {opt['f0_over_2']:.1f} Hz。"
            f"注意 LITES 的最优 f_m **通常低于** f0/2（热扩散低通），"
            f"这与 QEPAS 相反。"
        )

    return {
        "device": device, "var": var, "var_label": label,
        "n_points": len(rows),
        "power_law_index": slope,
        "power_law_note": ("log-log 斜率；1.0 表示线性响应，<1 表示次线性"
                           "（饱和或功率损失）"),
        "rows": rows,
        "notes": notes,
        **_block([], ["如需要可加大 n_points 或换 log_scale"],
                 [], {"can_ask": ["这些点画成图 → lites_waveform / 自行绘图"]}),
    }


# ══════════════════════════════════════════════════════════════════════
# 3. 波形：仪器级 2f 信号合成 + 出图
# ══════════════════════════════════════════════════════════════════════

def _quad_demod_profile(alpha_prof, nu, hwhm, mod_depth_cm1,
                        n_periods=10, spp=16, am_frac=0.02,
                        ref_phase_deg=30.0, L_cm=1.0):
    """逐扫描点正交锁相解调（X/Y 两路 → 最优相位旋转）。

    对每个慢扫点 ν̄：构造局部调制窗（f_m 载波，幅度 a=mod_depth_cm1），
        I(t) = [1 − A(ν̄ + a·cos ωt)·L] · (1 + am_frac·cos ωt)   （减光口径 A=αL，L=L_cm）
    正交解调（整周期平均，等价零相位 boxcar 锁相；参考相位 φ_r 任意，
    与真实数字锁相一致，随后旋转找回最优）：
        X = 2·⟨I·cos(2ωt+φ_r)⟩,  Y = 2·⟨I·sin(2ωt+φ_r)⟩
    最优同相分量（相位旋转 φ* = atan2(Y_c, X_c)，取线中心）：
        X' = X·cos φ* + Y·sin φ*
    小调制极限 X' → −¼·A''·a²（中心正峰、两侧负瓣，标准 WMS 2f 线型）；
    大调制 m 与 AM 交叉项自动包含（不依赖小 m 解析近似）。

    【2026-10 修复】调制窗**沿完整 α(ν) 剖面插值采样**（np.interp），不再用
    "中心值×单洛伦兹窗"外推：密集谱区（如 CH4 633 线）邻近线贡献会被
    单洛伦兹假设抹掉，导致 2f 信号几乎清零、峰位偏移。修复后与 TDLAS
    数值锁相同口径，峰形/峰位一致。
    """
    n = len(alpha_prof)
    k = np.arange(n_periods * spp)
    ph = 2.0 * np.pi * k / spp
    pr = math.radians(float(ref_phase_deg))
    c1 = np.cos(ph); s1 = np.sin(ph)
    c2 = np.cos(2.0 * ph + pr); s2 = np.sin(2.0 * ph + pr)
    nu_t = nu[:, None] + mod_depth_cm1 * c1[None, :]
    # 沿完整 α(ν) 插值采样（clamp 到扫描边界）：保留邻近线贡献，与 TDLAS 同口径
    A_t = np.interp(nu_t, nu, alpha_prof) * L_cm   # 减光量 αL
    I_t = (1.0 - A_t) * (1.0 + am_frac * c1[None, :])
    X = 2.0 * np.mean(I_t * c2[None, :], axis=1)
    Y = 2.0 * np.mean(I_t * s2[None, :], axis=1)
    ic = int(np.argmin(np.abs(nu)))
    phi = math.atan2(Y[ic], X[ic])
    if X[ic] * math.cos(phi) + Y[ic] * math.sin(phi) < 0.0:
        phi += math.pi
    Xp = X * math.cos(phi) + Y * math.sin(phi)
    # 幅值口径：R2f = √(X²+Y²)，与参考相位无关（工程锁相输出幅值，单峰无负瓣）
    R2f = np.sqrt(X * X + Y * Y)
    return {"X": X, "Y": Y, "Xp": Xp, "R2f": R2f, "phi_opt_rad": phi}


def lites_waveform(device=lph.DEFAULT_DEVICE, power_mW=None, x=None,
                   line_strength=None, L_gas_cm=None, T=296.0, P=1.01325,
                   gamma_L=0.06, f_m=None, f_scan=0.1, n_scan=4000,
                   mod_depth_cm1=0.3, sigma_V=9.16e-6, seed=0,
                   save_png=True, out_path=None, gas=None, wn_center=None,
                   scan_span_cm=None, iso="all"):
    """合成 LITES 的 2f 波形（含真实噪声），可选输出仪器级 6 子图。

    波形构造（与实验流程一致）：
      1. 慢扫三角波 → 激光波数 ν(t) 在吸收线两侧扫描
      2. 高频正弦 → 波长调制，调制深度 a
      3. 用 Voigt 线型 + 傅里叶展开得到解析 2f（与 WMS 同源）
      4. 乘以器件频率响应 |H_th(f_m)|·τ_acc·|H_mech(2f_m)| 与标定增益 g
      5. 加噪声（1/f + 白）

    ⚠ 与 TDLAS 出图的关键差别：LITES 的 2f **不归零**。因为激光 WMS
      残余幅度调制的 2f 分量（am_2f_frac）是与浓度无关的常量本底，
      真实 LITES 谱线是"骑在本底上的 2f 峰"；气体信号 ∝ η_dev·αL
      （减光口径，2026-10 文献修正）。若强行扣基线，会低估检测限。
    """
    d = lph.get_device(device)
    rng = np.random.default_rng(int(seed))
    assume = []

    if power_mW is None:
        power_mW = d.cal_power_W * 1e3
        assume.append(f"power_mW 取标定值 {power_mW:.2f} mW")
    if x is None:
        x = 1e-6
        assume.append("x 取 1 ppm（演示）")
    if line_strength is None:
        line_strength = 1.2e-20
        assume.append("line_strength 取 1.2e-20（演示）")
    if L_gas_cm is None:
        L_gas_cm = d.path_len_cm
        assume.append(f"L_gas_cm 取配置光程 {L_gas_cm} cm")
    if f_m is None:
        f_m = d.f0 / 2.0
        assume.append(f"f_m 取 f0/2 = {f_m:.1f} Hz")

    hwhm = gamma_L
    if gas is not None:
        # 真实气体波段：HITRAN 多线剖面（密集谱区邻近线贡献完整保留）
        if _hitran is None:
            raise RuntimeError("spectrolink_core 不可用，无法拉取真实波段")
        if wn_center is None:
            raise ValueError("gas 模式下必须给出 wn_center (cm-1)")
        _sp = scan_span_cm if scan_span_cm else 3.0
        nu0_, coef_, _ = _hitran.absorption(gas, wn_center - _sp,
                                            wn_center + _sp, T=T, P=P,
                                            step=5e-4, iso=iso)
        nu = np.arange(wn_center - _sp, wn_center + _sp + 1e-9, 5e-4)
        alpha_prof = np.interp(nu, nu0_, coef_ * x)
        alpha = float(np.max(alpha_prof))
        assume.append(f"真实波段：{gas} {wn_center:.2f}±{_sp:.2f} cm-1 "
                      f"(HITRAN iso={iso})，峰 α={alpha:.3e} cm-1")
    else:
        alpha = peak_alpha(line_strength, T, P, x, gamma_L)
        # 慢扫：把 α 在中线两侧 1.5 个 HWHM 内按洛伦兹线型铺开
        span = 1.5 * hwhm
        nu = np.linspace(-span, span, int(n_scan))
        alpha_prof = alpha * (hwhm ** 2) / (nu ** 2 + hwhm ** 2)

    a = float(mod_depth_cm1)
    m = a / max(hwhm, 1e-12)
    F_m = m ** 2 * math.exp(1.0 - (m / 2.2) ** 2)

    p = d.predict_2f_voltage(float(power_mW) * 1e-3, alpha, float(L_gas_cm),
                             f_m=float(f_m), mod_depth_cm1=a)

    # 正交锁相解调：真实流程（调制窗 → cos/sin 2ω 相乘 → 平均 → 相位旋转）
    dem = _quad_demod_profile(alpha_prof, nu, hwhm, a, am_frac=0.02,
                                  L_cm=float(L_gas_cm))
    X2f, Y2f = dem["X"], dem["Y"]
    X2f_opt = dem["Xp"]
    R2f = dem["R2f"]
    phi_opt = dem["phi_opt_rad"]
    # 幅值口径归一：R2f 单峰（√(X²+Y²)，无负瓣），峰中心 = 1
    shape = R2f / max(float(np.max(R2f)), 1e-30)

    v_delta = p["V_2f_delta"]
    v_base = p["V_2f_baseline"]
    # 关键：基线不归零 —— 残余 AM 2f 本底是恒定偏置
    v2f = v_base + v_delta * shape
    noise = rng.normal(0.0, float(sigma_V), v2f.shape)
    v2f_n = v2f + noise

    snr = (abs(v_delta) / float(sigma_V)) if sigma_V > 0 else None
    mdl_x = (x / snr) if (snr and snr > 0) else None

    out = {
        "device": device,
        "conditions": {"power_mW": power_mW, "x": x, "L_gas_cm": L_gas_cm,
                       "T_K": T, "P_atm": P, "f_m_Hz": f_m,
                       "f_scan_Hz": f_scan, "mod_depth_cm1": a, "m": m,
                       "gas": gas, "wn_center_cm-1": wn_center},
        "waveform": {"nu_cm-1": nu.tolist(),
                     "alpha_cm-1": alpha_prof.tolist(),
                     "V_2f_V": v2f.tolist(),
                     "V_2f_noisy_V": v2f_n.tolist(),
                     "X_2f_V": X2f.tolist(),
                     "Y_2f_V": Y2f.tolist(),
                     "X_2f_opt_V": X2f_opt.tolist(),
                     "R_2f_V": (v_delta * shape).tolist(),
                     "phi_opt_rad": float(phi_opt),
                     "baseline_V": float(v_base)},
        "metrics": {"V_2f_delta_V": v_delta, "V_2f_baseline_V": v_base,
                    "peak_to_peak_V": float(np.ptp(v2f)),
                    "noise_sigma_V": float(sigma_V),
                    "SNR": snr, "MDL_x": mdl_x,
                    "MDL_ppm": (mdl_x * 1e6) if mdl_x else None},
        "notes": [
            "2f 为正交解调幅值 R$_{2f}$=√(X²+Y²)（与参考相位无关，工程锁相输出）；"
            "X/Y/X′ 分量保留于波形字段。",
            "V_2f 含与浓度无关的残余 AM 本底（LITES 特征，非 bug）；"
            "真实锁相输出即为该形态。",
            f"F(m)={F_m:.4f}（m={m:.2f}，最优 m≈2.2）——"
            + ("调制深度接近最优" if 1.8 < m < 2.6 else "调制深度偏离最优，可扫描优化"),
        ],
    }

    png_path = None
    if save_png:
        png_path = _plot_waveform(
            d, nu, alpha_prof,
            {"X": X2f, "Y": Y2f, "Xp": X2f_opt, "R2f": R2f, "phi": phi_opt,
             "v_base": v_base, "v_delta": v_delta},
            float(sigma_V), out["conditions"], v2f_n=v2f_n,
            out_path=out_path, gas_name=gas)
        out["png"] = png_path

    out.update(_block(assume, ["如需改变工况请给出 power_mW/x/L_gas_cm/f_m"],
                      ["噪声为指定 σ 的高斯白噪声；真实系统还含基线漂移与"
                       "环境声耦合，本模型未含"]))
    return out


def _allan_deviation(y, fs):
    """经典 Allan 偏差（测量值/速率口径，一阶差分）：
    σ_y(τ=m/fs) = sqrt(½·E[(mean_{k+1} − mean_k)²])，块长 m 样本；
    τ 网格对数加密（~100 点）保证曲线连续。"""
    N = len(y)
    max_m = N // 2
    # 全整数块长：1 s 采样 → τ 精确到 1 s，τ_opt 定位不因网格粗化而偏移
    m_list = np.arange(1, max_m + 1)
    tau, adev = [], []
    for m in m_list:
        n_blocks = N // m
        blocks = y[:n_blocks * m].reshape(n_blocks, m).mean(axis=1)
        dd = blocks[1:] - blocks[:-1]
        adev.append(np.sqrt(0.5 * np.mean(dd * dd)))
        tau.append(m / fs)
    return np.array(tau), np.array(adev)


def _pink_noise(N, fs, rng, f_knee=0.02):
    """1/f 噪声：PSD ∝ 1/(f+f_knee)，f_knee 限制低频发散（平台化）。"""
    f = np.fft.rfftfreq(N, 1.0 / fs)
    f0 = np.where(f == 0, f[1], f)
    spec = (rng.standard_normal(len(f)) + 1j * rng.standard_normal(len(f))) \
        / np.sqrt(f0 + f_knee)
    spec[0] = 0.0
    return np.fft.irfft(spec, N)


def _plot_waveform(d, nu, alpha_prof, demod, sigma, cond,
                   v2f_n=None, out_path=None, gas_name=None):
    """仪器级 6 子图：核心=音叉电信号（全周期+载波）、R$_{2f}$ 幅值解调、Allan 方差。

    布局（3×2）：
      (a) 音叉电信号——DC 透射包络（真实比例 exp(−αL)，吸收凹陷可见）
      (b) 音叉电信号——载波细节（AC 耦合，包络 = R$_{2f}$ 幅值）
      (c) 正交解调幅值 R$_{2f}$ = √(X²+Y²)（与相位无关），含噪叠绘
      (d) 多浓度 R$_{2f}$ 谱对比（0–100 ppm 同图）
      (e) 标定曲线（R$_{2f}$ 峰高 vs 浓度，线性拟合 + 饱和区）
      (f) Allan 方差（1 Hz × 2 h，白 + 1/f + 漂移，τ_opt / MDL_opt）
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _mpl_cjk()

    plt.rcParams.update({
        "font.size": 10.5, "axes.grid": True, "grid.alpha": 0.3,
        "figure.facecolor": "white", "axes.facecolor": "white",
    })

    fig, ax = plt.subplots(3, 2, figsize=(11, 9))

    f0 = float(d.f0)
    T_scan = 1.0 / float(cond["f_scan_Hz"])
    n = len(nu)
    t_sc = np.linspace(0.0, T_scan, n)

    X2f = np.asarray(demod["X"]); Y2f = np.asarray(demod["Y"])
    Xp = np.asarray(demod["Xp"])
    R2f = np.asarray(demod["R2f"])
    phi = float(demod["phi"])
    v_base = float(demod["v_base"]); v_delta = float(demod["v_delta"])
    xmax = float(np.max(R2f))
    k_cal = v_delta / max(xmax, 1e-30)
    X2f_c = X2f * k_cal; Y2f_c = Y2f * k_cal; Xp_c = Xp * k_cal
    R2f_c = R2f * k_cal
    if v2f_n is None:
        v2f_n = None

    # ── ① 音叉电信号：DC 透射包络（真实比例）────────────────────
    # T(ν) = exp(−α(ν)·L)，吸收凹陷 = 1−exp(−αL)（真实量级，不放大示意）
    Lg = float(cond["L_gas_cm"])
    T_prof = np.exp(-alpha_prof * Lg)
    aL = 1.0 - float(np.min(T_prof))
    ax[0, 0].plot(t_sc, T_prof, color="#d62728", lw=1.4)
    ax[0, 0].set_ylim(1.0 - 8.0 * aL, 1.0 + 2.0 * aL)   # 只放大吸收凹陷带，非比例失真
    for tt in (T_scan * 0.25, T_scan * 0.75):
        ax[0, 0].axvspan(tt - 0.6 * T_scan / n * 5, tt + 0.6 * T_scan / n * 5,
                         color="gray", alpha=0.25)
    ax[0, 0].set_title(f"(a) 音叉电信号 — DC 透射包络（吸收凹陷 {aL*100:.2f}%）")
    ax[0, 0].set_xlabel("时间 t (s)")
    ax[0, 0].set_ylabel("T = exp(−αL)（归一）")
    ax[0, 0].annotate("吸收区", xy=(T_scan * 0.25, 1.0 - 3.0 * aL),
                      xytext=(T_scan * 0.25, -0.13), ha="center", fontsize=8.5,
                      arrowprops=dict(arrowstyle="->", lw=0.6),
                      xycoords="data", textcoords="axes fraction")

    # ── ② 音叉电信号：载波细节（AC 耦合）───────────────────────
    # 实验示波器 AC 耦合视角：去 DC 后可见 f0 载波，包络 = 正交 2f 分量
    t_us = np.linspace(-50.0, 50.0, 4000)
    xmax = float(np.max(np.abs(Xp)))
    k_cal = v_delta / max(xmax, 1e-30)          # 解调原始值 → V_2f_delta 标定
    env_abs = v_delta
    v_ac = v_base + env_abs * np.cos(2.0 * np.pi * f0 * t_us * 1e-6)
    ax[0, 1].plot(t_us, v_ac * 1e6, lw=0.8, color="#d62728")
    ax[0, 1].axhline(v_base * 1e6, ls="--", c="gray", lw=0.6,
                     label=f"残余 AM 本底 {v_base*1e6:.3f} μV")
    ax[0, 1].axhline((v_base + env_abs) * 1e6, ls=":", c="b", lw=0.7,
                     label=f"载波包络 ±{env_abs*1e6:.2f} μV")
    ax[0, 1].set_title(f"(b) 音叉电信号 — 载波细节（AC 耦合，f$_0$={f0/1e3:.1f} kHz）")
    ax[0, 1].set_xlabel("时间 t (μs)")
    ax[0, 1].set_ylabel("V$_{AC}$ (μV)")
    ax[0, 1].legend(fontsize=8.5, loc="lower right")

    # ── ③ 正交解调幅值 R2f = √(X²+Y²)（与相位无关）───────────────
    ax[1, 0].plot(nu, R2f_c * 1e6, lw=1.6, color="#d62728",
                  label="R$_{2f}$ 幅值（√(X²+Y²)）")
    if v2f_n is not None:
        ax[1, 0].plot(nu, (v2f_n - v_base) * 1e6, lw=0.7, alpha=0.6,
                      color="#7f7f7f", label=f"含噪 σ={sigma*1e6:.2f} μV")
    pk = int(np.argmax(R2f_c))
    ax[1, 0].annotate(f"峰值 {R2f_c[pk]*1e6:.1f} μV",
                      xy=(nu[pk], R2f_c[pk] * 1e6),
                      xytext=(float(np.min(nu)) + 0.06 * (float(np.max(nu)) - float(np.min(nu))),
                              R2f_c[pk] * 1e6 * 0.85), fontsize=8.5,
                      arrowprops=dict(arrowstyle="->", lw=0.6))
    ax[1, 0].set_title("(c) 正交解调幅值 R$_{2f}$ = √(X²+Y²)")
    ax[1, 0].set_xlabel(r"波数 (cm$^{-1}$)" if gas_name else r"相对波数 (cm$^{-1}$)")
    ax[1, 0].set_ylabel("R$_{2f}$ (μV)")
    ax[1, 0].legend(fontsize=8.5)

    # ── ④ 多浓度 R2f 谱对比 ────────────────────────────────────
    x_ref = float(cond["x"])
    alpha_ref = float(np.max(alpha_prof))
    mdc = float(cond["mod_depth_cm1"])
    gamma_L = mdc / max(float(cond["m"]), 1e-12)
    xs_m = np.array([0, 1, 2, 5, 10, 20, 50, 100.0]) * 1e-6
    cmap_m = plt.cm.viridis(np.linspace(0.15, 0.95, len(xs_m)))
    for j, xq in enumerate(xs_m):
        if gas_name:
            aprof = (alpha_prof * (xq / x_ref) if x_ref > 0
                     else np.zeros_like(alpha_prof))
        else:
            aq = alpha_ref * (xq / x_ref) if x_ref > 0 else 0.0
            aprof = aq * (gamma_L ** 2) / (nu ** 2 + gamma_L ** 2)
        Rq = _quad_demod_profile(aprof, nu, gamma_L, mdc,
                                  L_cm=float(cond["L_gas_cm"]))["R2f"]
        Rq_c = Rq * k_cal
        if xq == 0:
            ax[1, 1].plot(nu, Rq_c * 1e6, lw=1.0, color=cmap_m[j], ls=":",
                          label="0 ppm（本底）")
        else:
            ax[1, 1].plot(nu, Rq_c * 1e6, lw=1.1, color=cmap_m[j],
                          label=f"{xq*1e6:.0f} ppm（峰 {np.max(Rq_c)*1e6:.1f} μV）")
    ax[1, 1].set_title("(d) 多浓度 R$_{2f}$ 谱对比（正交解调幅值）")
    ax[1, 1].set_xlabel(r"波数 (cm$^{-1}$)" if gas_name else r"相对波数 (cm$^{-1}$)")
    ax[1, 1].set_ylabel("R$_{2f}$ (μV)")
    ax[1, 1].legend(fontsize=7.5, ncol=2)

    # ── ⑤ 标定曲线：R2f 峰高 vs 浓度 ───────────────────────────
    xs = xs_m
    vds = []
    for xq in xs:
        if gas_name:
            aprof = (alpha_prof * (xq / x_ref) if x_ref > 0
                     else np.zeros_like(alpha_prof))
        else:
            aq = alpha_ref * (xq / x_ref) if x_ref > 0 else 0.0
            aprof = aq * (gamma_L ** 2) / (nu ** 2 + gamma_L ** 2)
        Rq = _quad_demod_profile(aprof, nu, gamma_L, mdc,
                                  L_cm=float(cond["L_gas_cm"]))["R2f"]
        # 只用一个标度：V_2f_delta(参考浓度) × 解调线型比例（∝ 浓度，线性）。
        # 禁止再乘 predict 的 V_2f_delta(xq)（已∝浓度）——会双重计数致 ∝x²。
        vds.append(v_delta * float(np.max(Rq)) / max(float(np.max(R2f)), 1e-30))
    vds = np.array(vds)
    mlin = xs <= 20e-6
    slope, intercept = np.polyfit(xs[mlin] * 1e6, vds[mlin] * 1e6, 1)
    ax[2, 0].plot(xs * 1e6, vds * 1e6, "o-", color="#1f77b4", lw=1.2,
                  label="R$_{2f}$ 峰高")
    ax[2, 0].plot(xs[mlin] * 1e6, np.polyval([slope, intercept],
                                             xs[mlin] * 1e6), "--",
                  color="#2ca02c", label=f"线性拟合 S={slope:.3e} μV/ppm")
    ax[2, 0].axvspan(20, 100, color="orange", alpha=0.08,
                     label="饱和区（αL 偏离线性）")
    ax[2, 0].set_title("(e) 标定曲线：R$_{2f}$ 峰高 vs 浓度")
    ax[2, 0].set_xlabel("浓度 x (ppm)")
    ax[2, 0].set_ylabel("R$_{2f}$ 峰高 (μV)")
    ax[2, 0].legend(fontsize=8.5)

    # ── ⑥ Allan 方差（浓度口径，1 Hz × 2 h）────────────────────
    fs_a = 1.0
    N_a = 7200
    rng_a = np.random.default_rng(0)
    sigma_c_1s_ppm = x_ref * 1e6 * sigma / max(v_delta, 1e-30)
    y_w = rng_a.standard_normal(N_a)
    y_w *= sigma_c_1s_ppm / max(y_w.std(), 1e-30)
    y_p = _pink_noise(N_a, fs_a, rng_a, f_knee=0.02)
    y_p *= 0.24 * sigma_c_1s_ppm / max(y_p.std(), 1e-30)
    t_a = np.arange(N_a) / fs_a
    y_d = 2.0 / 3600.0 * (t_a - N_a / 2.0 / fs_a)
    y_a = x_ref * 1e6 + y_w + y_p + y_d
    tau_a, adev = _allan_deviation(y_a, fs_a)
    i_opt = int(np.argmin(adev))
    tau_opt, sigma_min = tau_a[i_opt], adev[i_opt]
    ax[2, 1].loglog(tau_a, adev, "-o", color="#1f77b4", lw=1.1, ms=2.5,
                    label="Allan 偏差 σ_y(τ)")
    tau_ref = tau_a[tau_a >= 1.0]
    ax[2, 1].loglog(tau_ref, sigma_c_1s_ppm / np.sqrt(tau_ref), "--",
                    color="#2ca02c", lw=1.0,
                    label=r"白噪声极限 $\sigma_1\tau^{-1/2}$")
    ax[2, 1].axvline(tau_opt, ls=":", color="#d62728", lw=1.0)
    ax[2, 1].axhline(sigma_min, ls=":", color="#d62728", lw=1.0)
    ax[2, 1].annotate(
        f"τ$_opt$={tau_opt:.0f} s → MDL$_{{opt}}$={sigma_min:.2f} ppm (1σ)",
        xy=(tau_opt, sigma_min), xytext=(tau_opt * 0.5, sigma_min * 1.8),
        fontsize=8.5, color="#d62728",
        arrowprops=dict(arrowstyle="->", lw=0.6))
    ax[2, 1].set_title("(f) Allan 方差（1 Hz × 2 h，白 + 1/f + 漂移 2.0 ppm/h）")
    ax[2, 1].set_xlabel("平均时间 τ (s)")
    ax[2, 1].set_ylabel("Allan 偏差 σ$_y$(τ) (ppm)")
    ax[2, 1].legend(fontsize=8.5)

    _ttl = (f"LITES 仪器级仿真 · {gas_name} 真实波段" if gas_name
            else "LITES 仪器级仿真（R$_{{2f}}$ 正交解调幅值）")
    fig.suptitle(
        f"{_ttl} — {d.name} | {cond['power_mW']:.2f} mW, "
        f"x={cond['x']:.2e}, L={cond['L_gas_cm']:.1f} cm, "
        f"f$_m$={cond['f_m_Hz']:.0f} Hz, m={cond['m']:.2f}",
        fontsize=12, wrap=True)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    if out_path is None:
        out_dir = _ROOT / "outputs"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "lites_waveform.png"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with _quiet():
        fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return str(out_path)


# ══════════════════════════════════════════════════════════════════════
# 4. 反演：由实测 2f 电压反推浓度
# ══════════════════════════════════════════════════════════════════════

def lites_invert(v_2f_measured_V, device=lph.DEFAULT_DEVICE, line_strength=None,
                 L_gas_cm=None, power_mW=None, T=296.0, P=1.01325,
                 gamma_L=0.06, f_m=None, use_delta=True,
                 v_2f_baseline_V=None):
    """由实测 2f 峰电压反演气体浓度 x。

    两条路径，**必须选对**：
      · use_delta=True（推荐）：调用者已扣基线，输入的是 ΔV_2f
      · use_delta=False：输入的是锁相原始输出 V_2f，需同时给
        v_2f_baseline_V（可由"纯氮吹扫"实测），本工具负责扣除

    反演是**线性**的（弱吸收下 ΔV ∝ x），故可解析求解，无需迭代。
    """
    d = lph.get_device(device)
    assume, actions, disc = [], [], []

    if line_strength is None:
        line_strength = 1.2e-20
        assume.append("line_strength 取 1.2e-20（演示）")
        actions.append("请给出目标线的 HITRAN 线强")
    if L_gas_cm is None:
        L_gas_cm = d.path_len_cm
        assume.append(f"L_gas_cm 取配置光程 {L_gas_cm} cm")
    if power_mW is None:
        power_mW = d.cal_power_W * 1e3
        assume.append(f"power_mW 取标定值 {power_mW:.2f} mW")
    if f_m is None:
        f_m = d.f0 / 2.0

    v = float(v_2f_measured_V)
    if not use_delta:
        if v_2f_baseline_V is None:
            raise ValueError(
                "use_delta=False 时必须给出 v_2f_baseline_V（纯氮吹扫实测值），"
                "否则无法扣除与浓度无关的器件本底。"
            )
        v_delta = v - float(v_2f_baseline_V)
        disc.append("基线已按调用者提供的 v_2f_baseline_V 扣除；"
                    "基线本身会随温度/功率漂移，务必定期复测。")
    else:
        v_delta = v

    # 参考点：用 1e-6 的 x 算灵敏度 S = ΔV/x，再线性外推
    x_ref = 1e-6
    a_ref = peak_alpha(line_strength, T, P, x_ref, gamma_L)
    p_ref = d.predict_2f_voltage(float(power_mW) * 1e-3, a_ref,
                                 float(L_gas_cm), f_m=float(f_m))
    s_v_per_x = p_ref["V_2f_delta"] / x_ref if x_ref > 0 else float("nan")

    if not np.isfinite(s_v_per_x) or s_v_per_x <= 0:
        raise ValueError("灵敏度非正，请检查器件/线强/光程参数")

    x = v_delta / s_v_per_x

    return {
        "device": device,
        "input": {"V_2f_measured_V": v, "use_delta": use_delta,
                  "V_2f_baseline_V": v_2f_baseline_V},
        "result": {
            "x": x, "x_ppm": x * 1e6, "x_ppb": x * 1e9,
            "V_delta_used_V": v_delta,
            "sensitivity_V_per_x": s_v_per_x,
            "alpha_peak_cm-1": peak_alpha(line_strength, T, P, x, gamma_L),
        },
        "linearity_check": {
            "alphaL": peak_alpha(line_strength, T, P, x, gamma_L) * L_gas_cm,
            "in_linear_regime": bool(
                peak_alpha(line_strength, T, P, x, gamma_L) * L_gas_cm < 0.05),
            "note": "αL < 0.05 时线性反演误差 <2.5%；"
                    "超出则需用 lites_forward 迭代求解（非线性）",
        },
        **_block(assume, actions or ["请核对线强与光程是否与实际光路一致"],
                 disc),
    }


# ══════════════════════════════════════════════════════════════════════
# 5. 探测限与 Allan 积分
# ══════════════════════════════════════════════════════════════════════

def lites_mdl(device=lph.DEFAULT_DEVICE, line_strength=None, L_gas_cm=None,
              power_mW=None, sigma_V=None, T=296.0, P=1.01325, gamma_L=0.06,
              f_m=None, n_sigma=1.0, integration_s=None):
    """最小可探测浓度 MDL，含 Allan 积分改善估计。

    口径（务必与 TDLAS 区分）：
      · TDLAS 用 **等效透过率噪声** σ_τ 反推 → 单位是 α·L
      · LITES 用 **电压噪声** σ_V 反推 → 单位是 V
      因为 LITES 的读出链是 压电→TIA→锁相，链路里**没有"透过率"这个量**。

    Allan 改善：白噪声主导时段 MDL ∝ 1/√τ；但 1/f 漂移会让曲线在某个
    τ_opt 处回升。本工具返回两条曲线，并标出最优积分时间的位置。
    """
    d = lph.get_device(device)
    assume, disc = [], []

    if line_strength is None:
        line_strength = 1.2e-20
        assume.append("line_strength 取 1.2e-20（演示）；请以 HITRAN 实际线强代入")
    if L_gas_cm is None:
        L_gas_cm = d.path_len_cm
        assume.append(f"L_gas_cm 取配置光程 {L_gas_cm} cm")
    if power_mW is None:
        power_mW = d.cal_power_W * 1e3
        assume.append(f"power_mW 取标定值 {power_mW:.2f} mW")
    if f_m is None:
        f_m = d.f0 / 2.0
    if sigma_V is None:
        nf = d.noise_floor(100.0)
        sigma_V = nf["sigma_total_V"]
        assume.append(
            f"sigma_V 未给出，用模型自估 {sigma_V*1e6:.3f} μV @BW=100 Hz；"
            "强烈建议改用实测噪声标准差")
        disc.append("噪声为模型自估，未用实验室实测；MDL 绝对值须以实测噪声重算。")

    nf = d.noise_floor(100.0)

    # 灵敏度
    x_ref = 1e-6
    p_ref = d.predict_2f_voltage(float(power_mW) * 1e-3,
                                 peak_alpha(line_strength, T, P, x_ref, gamma_L),
                                 float(L_gas_cm), f_m=float(f_m))
    s_norm = p_ref["V_2f_delta"] / x_ref          # V per unit x

    x_min = n_sigma * float(sigma_V) / s_norm
    alpha_min = peak_alpha(line_strength, T, P, x_min, gamma_L)

    # Allan：白噪声 ∝ τ^-0.5，1/f 漂移 ∝ τ^0.5，取包络
    taus = np.logspace(0, 3, 60)                  # 1 s … 1000 s
    white_lim = x_min / np.sqrt(taus)
    pink_coef = x_min * 0.3                       # 经验：1/f 起点略高于白噪限
    pink_lim = pink_coef * np.sqrt(taus / 1.0)
    env = np.minimum(white_lim, pink_lim)
    i_opt = int(np.argmin(env))

    result = {
        "device": device,
        "sensitivity_V_per_x": s_norm,
        "sigma_V_used": float(sigma_V),
        "noise_budget": nf,
        "MDL": {
            "x_min": x_min, "x_min_ppm": x_min * 1e6, "x_min_ppb": x_min * 1e9,
            "alpha_min_cm-1": alpha_min,
            "n_sigma": n_sigma,
        },
        "allan": {
            "tau_s": taus.tolist(),
            "white_limit": white_lim.tolist(),
            "pink_limit": pink_lim.tolist(),
            "envelope": env.tolist(),
            "tau_opt_s": float(taus[i_opt]),
            "x_min_at_tau_opt": float(env[i_opt]),
            "x_min_at_tau_opt_ppb": float(env[i_opt] * 1e9),
            "improvement_factor": float(x_min / env[i_opt]),
        },
        "notes": [
            f"1 kHz 级 LITES 系统的 τ_opt 通常在 10~500 s；"
            f"本估计给出 {taus[i_opt]:.0f} s。",
            "文献佐证：CO-LITES 积分 500 s 时 MDL 从 23 ppt 改善到 920.7 ppq"
            "（约 25×）——注意 ppq 是比 ppt 低 1000 倍的单位，原文表 3 中"
            "'920.7 ppq' 与摘要 '23 ppt' 存在单位不一致，引用时需谨慎。",
        ],
    }

    if integration_s is not None:
        t = float(integration_s)
        idx = int(np.argmin(np.abs(taus - t)))
        result["at_requested_integration"] = {
            "tau_s": t,
            "x_min": float(env[idx]),
            "x_min_ppb": float(env[idx] * 1e9),
        }

    result.update(_block(assume, ["请用实验室实测噪声替换 sigma_V 以定稿 MDL"],
                         disc))
    return result


# ══════════════════════════════════════════════════════════════════════
# 6. 噪声预算
# ══════════════════════════════════════════════════════════════════════

def lites_noise_budget(device=lph.DEFAULT_DEVICE, bandwidth_Hz=100.0,
                       v_rms_1f=None, c_in_F=None, resp_V_per_C=None,
                       compare_literature=True):
    """噪声预算分解：1/f、白噪声、TIA 电容抬升。

    LITES 的关键事实：工作在**音频（~f0/2，几 kHz 到 16 kHz）**，
    远低于 TDLAS 的 30 kHz+，因此 **1/f 噪声常为主导** ——
    这与"提高 Q ⇒ 降低噪声"的直觉相反：Q 高则带宽窄，白噪声被压，
    1/f 反而更突出。本工具把这一权衡量化。
    """
    d = lph.get_device(device)
    assume = []
    if v_rms_1f is None:
        v_rms_1f = 2e-6
        assume.append("v_rms_1f 取 2 μV（1 Hz 处 1/f 幅度，典型量级）")
    if resp_V_per_C is None:
        resp_V_per_C = 1e12
        assume.append("resp_V_per_C 未给出，取 1e12 V/C（典型电荷灵敏放大器）")

    nf = d.noise_floor(float(bandwidth_Hz), c_in_F=c_in_F,
                       v_rms_1f=float(v_rms_1f),
                       resp_V_per_C=float(resp_V_per_C))
    # 器件库已裁剪为单默认器件（qtf-commercial-decapped），跨器件噪声对照不再提供。
    inst = {}

    out = {
        "device": device, "bandwidth_Hz": float(bandwidth_Hz),
        "inputs": {"v_rms_1f_V": float(v_rms_1f),
                   "c_in_F": (None if c_in_F is None else float(c_in_F)),
                   "resp_V_per_C": float(resp_V_per_C)},
        "breakdown": {
            "pink_V": nf["pink_V"], "white_V": nf["white_V"],
            "total_V": nf["sigma_total_V"],
            "dominant": nf["dominant"],
            "tia_boost": nf["crest_boost"],
        },
        "interpretation": {
            "why_pink_dominates":
                "LITES 工作在 f0/2（本器件 "
                f"{d.f0/2:.0f} Hz），属音频段；1/f 拐点常高于此，"
                "故 1/f 主导。TDLAS 在 30 kHz+ 工作，白噪声主导。",
            "Q_tradeoff":
                "提高 Q ⇒ 3dB 带宽 f0/Q 变窄 ⇒ 白噪声按 √Δf 下降；"
                "但 τ_acc=Q/(πf0) 变长 ⇒ 响应变慢，且 1/f 不受益。"
                "因此**单纯提 Q 并不能线性改善 LOD**。",
        },
    }

    if compare_literature:
        out["literature_anchor"] = {
            "CO-LITES (Sun 2025)": {
                "QTF1": {"f0": 32751.7, "Q": 9632.9, "df": 3.41, "noise_nV": 957},
                "QTF2": {"f0": 9526.68, "Q": 10825.8, "df": 0.88, "noise_nV": 834},
                "QTF3": {"f0": 9498.95, "Q": 10794.3, "df": 0.88, "noise_nV": 852},
                "note": "噪声并未随带宽 √(3.41/0.88)=1.97× 下降，实测仅 1.147× "
                        "⇒ 说明噪声**不是**纯白噪声，存在与带宽无关的 1/f 或"
                        "环境耦合成分。",
            },
            "LN-MFP (Lin 2026)": {
                "C2H2_noise_uV": 9.16, "CH4_noise_uV": 112,
                "note": "同一器件、不同波段噪声差 12×，说明噪声也随波段/功率变。",
            },
            "LiNTF (Mu 2025) LITES": {
                "qtf_noise_nV": 62.05, "lintf_noise_nV": 80.30,
                "note": "换更强压电材料后噪声仅升 29%，而信号升 782% ⇒ "
                        "净 SNR 改善 6.03×。",
            },
        }

    out.update(_block(assume, [], []))
    return out


# ══════════════════════════════════════════════════════════════════════
# 7. 器件库
# ══════════════════════════════════════════════════════════════════════

def lites_device(action="list", key=None, overrides=None):
    """器件库查询 / 自定义器件构建 / 器件物理量速查。

    action:
      · "list"    —— 列出所有器件及其关键参数
      · "get"     —— 取单个器件详情（含反解增益 g 与各派生量）
      · "build"   —— 用 overrides 构造一个临时器件（不写入库）
      · "groups"  —— 列出标定分组（用于跨器件对比）
    """
    if action == "groups":
        # 器件库已裁剪为单默认器件（qtf-commercial-decapped），无跨器件标定分组。
        # 保留 action 占位：用户自定义器件后可在此扩展分组校验。
        return {"groups": {},
                "note": "当前器件库仅内置 qtf-commercial-decapped，无标定分组；"
                        "如需多器件对比请先用 action='build' 构造临时器件。",
                **_block()}

    if action == "list":
        rows = []
        for k, d in lph.DEVICE_LIBRARY.items():
            rows.append({
                "key": k, "name": d.name, "material": d.material,
                "coating": d.coating,
                "f0_Hz": d.f0, "Q": d.q,
                "bw_3dB_Hz": d.bw_3dB, "tau_acc_ms": d.tau_acc * 1e3,
                "path_len_cm": d.path_len_cm, "n_pass": d.n_pass,
                "cal_species": d.cal_species,
                "cal_power_mW": d.cal_power_W * 1e3,
                "cal_meas_f2_mV": d.cal_meas_f2_V * 1e3,
                "cal_eta_abs": d.cal_eta_abs,
                "anchored": bool(d.cal_species),
                # 标出默认器件：调用方不传 device 时落到这里。
                "is_default": k == lph.DEFAULT_DEVICE,
            })
        return {"count": len(rows), "devices": rows,
                "default_device": lph.DEFAULT_DEVICE,
                "materials": sorted(lph.MATERIALS),
                "coatings": {k: v["name"] for k, v in lph.COATINGS.items()},
                **_block(
                    assumptions=[
                        f"默认器件 = {lph.DEFAULT_DEVICE}"
                        "（商用 32.768 kHz 音叉晶振去壳裸音叉）："
                        "f0/Q 有公开实测锚点（Wang 2020 Table 1）"
                    ],
                    disclosure=[
                        "跨器件的 V_2f 绝对值**不可直接比**：每个器件的电压"
                        "含私有标定增益 g（吸收其 TIA/热约束等未标定因素）。"
                        "要比器件本征性能请用 lites_compare 的严格口径，"
                        "或看 tau_acc / theta / SBR_eta 等机理因子。",
                    ],
                    interaction={"can_ask": [
                        "某器件的完整物理链路 → lites_device action=get",
                        "自定义器件 → lites_device action=build overrides={...}",
                    ]})}
        # noqa: unreachable

    if action == "get":
        if not key:
            raise ValueError("action=get 需要 key")
        d = lph.get_device(key)
        fom = lph.thermoelastic_fom(d._mat, d.coating)
        opt = lph.optimal_2f_frequency(d.f0, d.q, d.spot_w_m, d._mat)
        return {"device": {
            "key": key, "name": d.name, "material": d.material,
            "coating": d.coating,
            "f0_Hz": d.f0, "Q": d.q, "bw_3dB_Hz": d.bw_3dB,
            "tau_acc_ms": d.tau_acc * 1e3,
            "geometry": {"tine_w_mm": d.tine_w_m * 1e3,
                         "tine_l_mm": d.tine_l_m * 1e3,
                         "tine_thick_mm": d.tine_thick_m * 1e3,
                         "gap_mm": d.gap_m * 1e3,
                         "electrode_area_mm2": d.electrode_area_m2 * 1e6,
                         "spot_w_mm": d.spot_w_m * 1e3},
            "electrical": {"r_tia_ohm": d.r_tia, "c_total_pF": d.c_total * 1e12},
            "thermal": {"constr": d.constr, "tc_ppm_per_K": d.tc_ppm_per_K},
            "optical": {"path_len_cm": d.path_len_cm, "n_pass": d.n_pass,
                        "mirror_refl": d.mirror_refl,
                        "throughput": d.optical_throughput()},
            "fom": fom,
            "optimal_f_m_Hz": opt["f_m_opt"],
            "calibration": {"species": d.cal_species,
                            "power_mW": d.cal_power_W * 1e3,
                            "eta_abs": d.cal_eta_abs,
                            "meas_f2_mV": d.cal_meas_f2_V * 1e3,
                            "solved_gain_g": d._g,
                            "mod_depth_cm1": d.cal_mod_depth_cm1},
        },
            **_block(disclosure=[
                "g 为**标定反解**值（由单一锚点定标），不是第一性原理绝对量；"
                "它吸收了热约束度、电极几何、TIA 阻抗、压电耦合等未标定因素。"
            ])}

    if action == "build":
        if not overrides:
            raise ValueError("action=build 需要 overrides 字典")
        try:
            d = lph.LitesDevice(**overrides)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "hint": "可用字段见 lites_device action=get 的字段名",
                    **_block()}
        return {"ok": True, "device": {
            "name": d.name, "f0_Hz": d.f0, "Q": d.q,
            "bw_3dB_Hz": d.bw_3dB, "tau_acc_ms": d.tau_acc * 1e3,
            "solved_gain_g": d._g,
        }, **_block(disclosure=[
            "临时器件未写入库；标定增益 g 由 cal_* 字段反解，"
            "若 cal_* 缺失则使用默认值（结果仅供量级参考）。"
        ])}

    raise ValueError(f"未知 action {action!r}；可选 list/get/build/groups")


# ══════════════════════════════════════════════════════════════════════
# 8. 共振跟踪
# ══════════════════════════════════════════════════════════════════════

def lites_resonance(device=lph.DEFAULT_DEVICE, delta_T_K=1.0, assume_f0=None,
                    freq_error_pct=None):
    """共振跟踪与温漂失谐分析。

    这是 LITES 的**头号工程难题**：Q 高则带宽窄（Δf = f0/Q），
    任何原因导致的 f0 漂移都会让灵敏度按 H(f) 掉下去。
    本工具量化"漂多少度、损失多少 dB、要不要做跟踪"。
    """
    d = lph.get_device(device)
    f0_true = lph.f0_drift(d.f0, float(delta_T_K), d.tc_ppm_per_K)
    assumed = d.f0 if assume_f0 is None else float(assume_f0)

    drift = lph.detuning_loss(f0_true, assumed, d.q)
    out = {
        "device": device,
        "f0_nominal_Hz": d.f0, "Q": d.q,
        "bw_3dB_Hz": d.bw_3dB,
        "tc_ppm_per_K": d.tc_ppm_per_K,
        "delta_T_K": float(delta_T_K),
        "f0_true_Hz": f0_true,
        "f0_shift_Hz": f0_true - d.f0,
        "f_m_commanded_Hz": d.f0 / 2.0,
        "f_m_needed_Hz": f0_true / 2.0,
        "loss_db": drift["loss_db"],
        "residual_frac": drift["residual_frac"],
        "groups": {},
    }

    for dT in (0.1, 0.5, 1.0, 2.0, 5.0, 10.0):
        f0t = lph.f0_drift(d.f0, dT, d.tc_ppm_per_K)
        L = lph.detuning_loss(f0t, d.f0, d.q)
        out["groups"][f"{dT}K"] = {"f0_shift_Hz": f0t - d.f0,
                                   "loss_db": L["loss_db"]}

    if freq_error_pct is not None:
        fe = d.f0 * (1.0 + float(freq_error_pct) / 100.0)
        out["explicit_error"] = {
            "error_pct": float(freq_error_pct),
            "loss_db": lph.detuning_loss(fe, d.f0, d.q)["loss_db"],
        }

    # 需要的跟踪精度：把"损失 < 0.5 dB"折算成 f0 允差
    tol = None
    lo, hi = d.f0, d.f0 * 1.05
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if abs(lph.detuning_loss(mid, d.f0, d.q)["loss_db"]) < 0.5:
            lo = mid
        else:
            hi = mid
    tol = lo - d.f0

    out["tracking_requirement"] = {
        "f0_tolerance_for_0.5dB_Hz": tol,
        "f0_tolerance_ppm": tol / d.f0 * 1e6,
        "T_tolerance_K": abs(tol / (d.f0 * d.tc_ppm_per_K * 1e-6))
        if d.tc_ppm_per_K else None,
        "verdict": ("必须做主动共振跟踪（温控或锁频）"
                    if abs(tol / d.f0 * 1e6) < 200 else
                    "被动温控即可满足"),
    }
    out.update(_block([], [], [
        "tc_ppm_per_K 为材料标称值，实际器件的温度系数须实测；"
        "封装应力会使有效 TC 显著偏离材料值。"
    ]))
    return out


# ══════════════════════════════════════════════════════════════════════
# 9. 方案对比
# ══════════════════════════════════════════════════════════════════════

def lites_compare(devices=None, common=None, metrics=("V_delta", "SNR", "MDL")):
    """在多器件/多工况下做统一口径对比，输出对比表。

    ⚠ **两个必须分清的口径，不要混**（这是评审里最常见的错误）：

      【A】各自默认工作点（默认）—— L 与 P 不强制统一，各用各的标定值。
          反映的是"把每个器件按它自己的典型用法摆上去，谁更灵敏"。
          适用于**选型**：我要一个开箱即用、按厂家/论文推荐工况跑的方案。

      【B】严格控制变量 —— 显式传 common={'L_gas_cm':X,'power_mW':Y}。
          所有条目在同一 L、同一 P、同一线强、同一浓度下计算。
          适用于**判定器件本征优劣**：排除功率和光程的干扰。

    **口径 A 下不要读 best_mdl**：因为 L 和 P 不同，MDL 的差异主要来自
    功率/光程差异而非器件事物本身，此时"最优于谁"是无意义的。
    本函数因此只在**口径 B（用户显式统一了 L 和 P）**下才给 best_mdl，
    否则返回 None 并说明原因。

    另有一个更隐蔽的坑（2026-09-18 实测确认）：
    每个器件的电压都含一个**私有标定增益 g**（由它自己的锚点反解，见
    lites_physics._solve_gain），g 把该器件的 TIA 参数、热约束度、电极
    面积等未标定因素**全部吸收**。所以：**跨器件的 V_2f_delta 绝对值不可
    比**，比出来的是各自锚点数字的大小。要判器件优劣，请看
    H_th / H_mech / tau_acc / SBR_eta 这些**进了 g 之外**的机理因子，
    或走口径 B。本函数在 notes 里显式声明这一点。
    """
    if devices is None:
        devices = [lph.DEFAULT_DEVICE]
    common = dict(common or {})
    common.setdefault("line_strength", 1.2e-20)
    common.setdefault("x", 1e-6)
    common.setdefault("sigma_V", 9.16e-6)

    sigma = common.pop("sigma_V")

    # 只有用户**显式**同时给了 L 和 P，才算真正统一了口径。
    strict = ("L_gas_cm" in common) and ("power_mW" in common)

    rows = []
    for key in devices:
        d = lph.get_device(key)
        power = common.get("power_mW", d.cal_power_W * 1e3)
        L = common.get("L_gas_cm", d.path_len_cm)
        x = common["x"]

        f = lites_forward(device=key, power_mW=power, x=x,
                          line_strength=common["line_strength"],
                          L_gas_cm=L)
        s_norm = f["result"]["V_2f_delta_V"] / x
        x_min = sigma / s_norm if s_norm > 0 else float("inf")

        # ── 机理因子：**不含私有标定增益 g**，因此可跨器件比较 ────────
        # 这是本函数里唯一能回答"哪个器件更好"的一组数字。
        # V_2f_delta 含 g、不可比；下面这些因子不含 g、可比。
        _fm = d.f0 / 2.0
        mech = {
            "tau_acc_ms": d.tau_acc * 1e3,
            "H_mech": float(lph.mech_transfer(2.0 * _fm, d.f0, d.q)["mag"]),
            "H_th": float(lph.thermal_transfer(_fm, d.spot_w_m, d._mat)["mag"]),
            "theta": float(d._fom["theta"]),          # 材料热弹品质因子 Θ
            "coating_gain": float(d._fom["coating_gain"]),
            "eta_dev": float(d.cal_eta_abs),          # 器件本底吸收比
        }

        rows.append({
            "key": key, "name": d.name,
            "material": d.material, "coating": d.coating,
            "f0_Hz": d.f0, "Q": d.q, "bw_3dB_Hz": d.bw_3dB,
            "tau_acc_ms": d.tau_acc * 1e3,
            "L_gas_cm": L, "power_mW": power,
            "V_2f_delta_V": f["result"]["V_2f_delta_V"],
            "V_2f_baseline_V": f["result"]["V_2f_baseline_V"],
            "SBR_eta": f["result"]["SBR_eta"],
            "SNR": f["result"]["V_2f_delta_V"] / sigma,
            "MDL_x": x_min, "MDL_ppm": x_min * 1e6,
            # ← 可跨器件比较的机理因子（见 notes 第三条）
            "mech_factors": mech,
        })

    # 只在严格统一口径下才评"最优"，否则会给出误导性结论。
    best = min(rows, key=lambda r: r["MDL_x"]) if (rows and strict) else None

    notes = [
        "所有条目使用同一线强/浓度/噪声口径。",
        ("**严格口径**：L 与 P 已被显式统一，MDL 可比，best_mdl 有效。"
         if strict else
         "**默认口径**：光程与功率按各自器件配置（未强制统一）——"
         "反映的是'各自的默认工作点'。"
         "⚠ 本口径下 **best_mdl 返回 None**，因为 MDL 差异主要来自"
         "功率/光程而非器件本身。要比器件本征性能，请显式传 "
         "common={'L_gas_cm':X,'power_mW':Y} 切换到严格口径。"),
        "⚠ 跨器件的 V_2f_delta **绝对值不可比**：每个器件的电压含一个私有"
        "标定增益 g（吸收其 TIA/热约束/电极面积等未标定因素）。"
        "判器件优劣请看 tau_acc / SBR_eta 等机理因子，或走严格口径。",
    ]
    if not strict:
        notes.append("如需严格控制变量，请显式传入 "
                     "common={'L_gas_cm':X,'power_mW':Y}")

    return {
        "common_conditions": {"line_strength": common["line_strength"],
                              "x": common["x"], "sigma_V": sigma,
                              "strict": strict},
        "rows": rows,
        "best_mdl": best["key"] if best else None,
        "best_mdl_valid": strict,
        "notes": notes,
        **_block([], [] if strict else
                 ["切换到严格口径：common={'L_gas_cm':X,'power_mW':Y}"],
                 ["能耗/体积/成本不在本对比范围内，需另行评估"]),
    }


# ══════════════════════════════════════════════════════════════════════
# 10. 方案体检
# ══════════════════════════════════════════════════════════════════════

def lites_review(device=lph.DEFAULT_DEVICE, power_mW=None, x=None, L_gas_cm=None,
                 f_m=None, mod_depth_cm1=None, line_strength=None,
                 T=296.0, P=1.01325, gamma_L=0.06, sigma_V=None):
    """对一套 LITES 实验方案做**逐项体检**，指出问题而不是给好评。

    检查项依据文献中真实出现过的失效模式：
      1. 调制深度 m 是否接近 2.2（偏离则损失信号）
      2. f_m 是否等于 f0/2，以及是否应下移到热-机械联合最优
      3. Q 与 f0 是否会导致共振跟踪困难（带宽 vs 温漂）
      4. 是否把"基线"误当成零（LITES 最常见的定量误差）
      5. 多通池的功率损失是否吃掉了吸收增益
      6. 噪声是否被 1/f 主导，积分时间是否存在最优
      7. 弱吸收线性假设是否成立
    """
    d = lph.get_device(device)
    findings = []
    assume = []

    if power_mW is None:
        power_mW = d.cal_power_W * 1e3
        assume.append(f"power_mW 取 {power_mW:.2f} mW")
    if x is None:
        x = 1e-6
        assume.append("x 取 1 ppm")
    if L_gas_cm is None:
        L_gas_cm = d.path_len_cm
    if line_strength is None:
        line_strength = 1.2e-20
        assume.append("line_strength 取 1.2e-20")
    if f_m is None:
        f_m = d.f0 / 2.0
    if mod_depth_cm1 is None:
        mod_depth_cm1 = d.cal_mod_depth_cm1
    if sigma_V is None:
        sigma_V = d.noise_floor(100.0)["sigma_total_V"]
        sigma_V_is_user = False
    else:
        sigma_V = float(sigma_V)
        sigma_V_is_user = True

    def add(level, item, detail):
        findings.append({"level": level, "item": item, "detail": detail})

    # 1. 调制深度
    hwhm = d.cal_mod_depth_cm1 / 2.2
    m = mod_depth_cm1 / hwhm
    if 1.8 <= m <= 2.6:
        add("ok", "调制深度", f"m={m:.2f}，接近最优 2.2")
    else:
        add("warn", "调制深度",
            f"m={m:.2f} 偏离最优 2.2；2f 幅值按 F(m)=m²e^(1−m²/2.2²) "
            f"为 {m**2*math.exp(1-(m/2.2)**2):.3f}（最优处为 1.0）")

    # 2. f_m 选择
    opt = lph.optimal_2f_frequency(d.f0, d.q, d.spot_w_m, d._mat)
    if abs(f_m - d.f0 / 2.0) < 1e-6:
        add("info", "调制频率",
            f"f_m 取 f0/2={d.f0/2:.1f} Hz（LITES 惯例，使 2f 落在 f0）。"
            f"热-机械联合最优为 {opt['f_m_opt']:.1f} Hz，"
            f"相对改善 {opt['gain_vs_f0half']:.2f}×。"
            f"{'两者接近，无需下移' if opt['gain_vs_f0half'] < 1.1 else '可考虑下移 f_m'}")

    # 3. 共振跟踪
    tol = lph.detuning_loss(d.f0 * 1.001, d.f0, d.q)["loss_db"]
    if d.bw_3dB < 20:
        add("warn", "共振跟踪",
            f"3dB 带宽仅 {d.bw_3dB:.2f} Hz（Q={d.q:.0f}，f0={d.f0:.0f} Hz）。"
            f"1 K 温漂（TC={d.tc_ppm_per_K:g} ppm/K）即失谐 "
            f"{abs(lph.f0_drift(d.f0,1.0,d.tc_ppm_per_K)-d.f0):.2f} Hz，"
            f"损失 {lph.detuning_loss(lph.f0_drift(d.f0,1.0,d.tc_ppm_per_K), d.f0, d.q)['loss_db']:.2f} dB。"
            f"⇒ 必须做温控或主动锁频。")
    else:
        add("ok", "共振跟踪", f"带宽 {d.bw_3dB:.2f} Hz，被动温控可接受")

    # 4. 基线误用
    f = lites_forward(device=device, power_mW=power_mW, x=x,
                      line_strength=line_strength, L_gas_cm=L_gas_cm,
                      T=T, P=P, gamma_L=gamma_L, f_m=f_m,
                      mod_depth_cm1=mod_depth_cm1)
    sbr = f["result"]["SBR_eta"]
    add("warn", "基线口径",
        f"V_2f 总量 {f['result']['V_2f_V']:.4e} V 中含与浓度无关的残余 AM 本底 "
        f"{f['result']['V_2f_baseline_V']:.4e} V；真正的气体信号只有 "
        f"{f['result']['V_2f_delta_V']:.4e} V（SBR={sbr:.3e}）。"
        f"若把总量当信号会高估浓度约 {1/sbr:.3g} 倍。")

    # 5. 多通池
    if d.n_pass > 1:
        tp = d.optical_throughput()
        add("warn" if tp < 0.2 else "info", "多通池权衡",
            f"{d.n_pass} 次反射、R={d.mirror_refl} ⇒ 总透过率 {tp*100:.3f}%。"
            f"LITES 信号 ∝ 功率，故光程增益被功率损失部分抵消；"
            f"净收益 ≈ {d.n_pass}×{tp:.4f}={d.n_pass*tp:.2f}（相对单程）。"
            f"TDLAS 无此损失（信号 ∝ αL 不 ∝ P），这是关键分野。")

    # 6. 噪声主导项
    #    ⚠️ 必须用**调用方给出的 sigma_V**（若给了），而不是无条件的模型自估值：
    #    否则这个参数就是"声明了却无效"。模型自估只用于判断 1/f vs 白噪声的
    #    相对占比（那需要的是形状而非绝对幅度）。
    nf = d.noise_floor(100.0)
    sigma_src = ("调用方实测" if sigma_V_is_user else
                 "模型自估（**请用实验室实测替换**）")
    add("info", "噪声",
        f"σ={sigma_V*1e6:.3f} μV @100 Hz（来源：{sigma_src}），"
        f"模型分解主导项 {nf['dominant']}。"
        f"1/f 主导时延长积分只在某 τ_opt 前有效（见 lites_mdl）。")
    if not sigma_V_is_user:
        add("warn", "噪声口径未标定",
            "sigma_V 用的是模型自估值，不是实测。MDL / SNR 类结论在"
            "实测噪声回填前**不可作为定稿**。")

    # 7. 线性
    aL = f["conditions"]["alphaL"]
    if aL < 0.05:
        add("ok", "弱吸收线性", f"αL={aL:.3e} ≪ 0.05，线性反演成立")
    else:
        add("warn", "弱吸收线性",
            f"αL={aL:.3e} 已不可忽略，A=1−exp(−αL) 饱和效应显著"
            f"（约 {(1-math.exp(-aL))/aL*100:.1f}% 偏离线性）")

    n_warn = sum(1 for x_ in findings if x_["level"] == "warn")
    return {
        "device": device,
        "verdict": ("存在 %d 项需要注意的问题" % n_warn) if n_warn else "未发现明显问题",
        "warn_count": n_warn,
        "findings": findings,
        **_block(assume, [
            "请补充实测噪声 σ_V 与实测 f0/Q，以便给出定稿结论"
        ], [
            "η_dev 未实测：气体信号绝对量级不确定（信号 ∝ η_dev·αL），"
            "本体检中的 SBR 数值仅供量级参考"
        ]),
    }


# ══════════════════════════════════════════════════════════════════════
# 11. 指南与自检
# ══════════════════════════════════════════════════════════════════════

_GUIDE = {
    "overview": {
        "title": "LITES 是什么",
        "body": (
            "光致热弹光谱（Light-Induced Thermoelastic Spectroscopy）：激光穿过气体后"
            "打到**探测器自身**（石英音叉 / 铌酸锂音叉 / LN-MFP），器件吸收光能→局部"
            "升温→热弹形变→机械共振放大→压电输出→锁相解调出 2f。\n"
            "与 QEPAS 的区别：QEPAS 让音叉**浸在气体里**听声波，LITES 是**非接触**的"
            "（器件不必接触腐蚀性气体）。\n"
            "与 TDLAS 的区别：TDLAS 的探测器只做光电转换，信号源是气体吸收；"
            "LITES 的信号源是**器件对光的吸收**，气体吸收只是把它调制一下。"
        ),
    },
    "signal_chain": {
        "title": "信号链与量纲",
        "body": (
            "V_2f = g · (P·η_abs·T_opt) · |H_th(f_m)| · τ_acc · (ΔT→ε→Q_c) "
            "· |H_mech(2f_m)| / C_total · Θ_coat\n"
            "  η_abs(ν) = η_dev + (1−η_dev)[1−exp(−α_gas·L)]   ← 关键\n"
            "  τ_acc = Q/(π·f0)         能量积累时间（越低频越灵敏）\n"
            "  H_th  = 1/√(1+(ω τ_th)²) 热扩散低通，τ_th = w²/(8D)\n"
            "  H_mech= 1/√(1+Q²(f/f0−f0/f)²)  机械共振\n"
            "  Θ_mat = α_te·d_piezo/k_th      材料热弹品质因子\n"
        ),
    },
    "pitfalls": {
        "title": "七个真实失效模式",
        "body": (
            "1. **把 V_2f 总量当信号**——它含与浓度无关的基线偏置，必须扣。\n"
            "2. **以为加浓度就能改善检测限**——LITES 灵敏度被 η_dev 压制，"
            "加大浓度只线性改善分子、压不掉器件吸收本底。\n"
            "3. **忽略共振温漂**——Q 越高带宽越窄，1 K 就可能失谐。\n"
            "4. **以为多通池与 TDLAS 一样净赚**——LITES 信号 ∝ P，镜面反射吃掉功率。\n"
            "5. **以为提 Q 就能线性降噪**——1/f 主导时 Q 的收益远小于 √Δf。\n"
            "6. **复用 TDLAS 的 σ_τ 口径**——LITES 链里没有'透过率'这个量。\n"
            "7. **把模型当第一性原理**——g 与 η_dev 都是反解/反推量，须实测回填。"
        ),
    },
    "workflow": {
        "title": "推荐使用顺序",
        "body": (
            "① lites_device action=list      选器件\n"
            "② lites_review                  方案体检（先挑错）\n"
            "③ lites_forward                 单点信号量级\n"
            "④ lites_sweep                   扫功率/光程/调制频率选工作点\n"
            "⑤ lites_waveform                出仪器级图\n"
            "⑥ lites_mdl / lites_noise_budget 检测限与噪声归因\n"
            "⑦ lites_resonance               共振跟踪设计\n"
            "⑧ lites_compare                 多方案横评\n"
        ),
    },
    "calibration": {
        "title": "必须实测标定的量（当前为估计值）",
        "body": (
            "· η_dev  器件自身吸收比 —— 由文献 V/P 反推，须用空白基线实测\n"
            "· g      标定增益 —— 单点反解，吸收了热约束度/电极几何/TIA 阻抗\n"
            "· f0, Q  共振频率与品质因数 —— 标称≠真值，个体差异可达数十 %\n"
            "· tc     f0 温度系数 —— 标称≠真值，封装应力会显著改变\n"
            "· σ_V    系统噪声 —— 强烈建议用实测值替换模型自估\n"
            "上述量未标定时，模型的**相对趋势**可信，**绝对值**须谨慎。"
        ),
    },
}


def lites_guide(topic=None):
    """LITES 使用指南：概念、信号链、失效模式、工作流、标定清单。"""
    if topic and topic in _GUIDE:
        return {"topic": topic, **_GUIDE[topic],
                "available_topics": sorted(_GUIDE)}
    return {"topics": {k: v["title"] for k, v in _GUIDE.items()},
            "full": _GUIDE,
            **_block()}


def lites_selftest():
    """运行物理内核自检（29 项），并把每一项的通过/失败原样返回。"""
    with _quiet() as g:
        lines = lph.selftest()
    txt = "\n".join(lines)
    n_pass = txt.count("[PASS]")
    n_fail = txt.count("[FAIL]")
    return {
        "ok": n_fail == 0,
        "n_pass": n_pass, "n_fail": n_fail,
        "log": _sanitize_paths(txt).splitlines(),
        **_block(disclosure=[
            "自检覆盖标度律、标定自洽、量纲、共振、噪声口径；"
            "**不覆盖**与真实器件的绝对偏差（无实测数据可比）。"
        ]),
    }
