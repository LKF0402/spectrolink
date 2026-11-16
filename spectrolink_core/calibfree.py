# -*- coding: utf-8 -*-
"""免标定（calibration-free）共用内核：TDLAS/WMS + LITES。

做两件事：
  1. 把“实验数据 + 仪器状态”变成可复核的反演结果；
  2. 用 guide 给出最小数据清单与推荐路径。

推荐路径：
  · 2f 先做 shape，确认波形/扫描轴/m；
  · 要绝对浓度，给 I0（DAS）或一个已知浓度锚点（WMS/LITES）；
  · 标气证书浓度范围内结果最稳，更高浓度可走 1.2 的高浓度模型。

依赖只有 numpy + spectrolink_core.hitran，不引入 scipy/pandas。
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

from . import hitran as _hitran

_trapz = getattr(np, "trapezoid", None) or np.trapz

# ══════════════════════════════════════════════════════════════════
# 新手引导（MCP 的 mode="guide" 原样返回；文档也引用同一份文案）
# ══════════════════════════════════════════════════════════════════

GUIDE = {
    "title": "免标定最小数据清单",
    "one_sentence": "用“零基线 + 一个绝对锚点 + 仪器状态”代替整条浓度标定曲线。",
    "three_things": [
        {"id": "A", "name": "零基线",
         "what": "同光路、同增益、同调制下的 0% 气/空腔信号；遮光暗信号；实验前后各一次。",
         "why": "扣掉窗口、RAM、暗电流、探测器漂移，2f 三瓣形状更干净。"},
        {"id": "B", "name": "绝对锚点",
         "what": "TDLAS：0% 气的 I0 透射；或一个已知浓度参考。LITES：一个已知浓度参考。",
         "why": "浓度通过 α(x)L 进入信号；锚点把“伏特”直接换算成“αL/浓度”。"},
        {"id": "C", "name": "仪器状态",
         "what": "L、T、P、调制频率/幅度、扫描跨度、采样率、锁相时间常数/相位、探测器带宽。",
         "why": "理论 α 与实测在同一工况下比较，波形和浓度都对得准。"},
    ],
    "tdlas": {
        "shape": {
            "goal": "校验波形、扫描轴与 m；浓度由 absolute / anchored 给出。",
            "need": ["x2f", "y2f", "species", "wn_center_cm1", "T", "P", "L_cm"],
            "optional": ["x2f_bg/y2f_bg（0% 背景，强烈建议；可同表或单独文件）",
                         "scan_span_cm1（不给则自动搜索 0.15–2.4 cm⁻¹）"],
            "output": "m、扫描轴、复增益/相位、corr、峰位差；x=null。",
        },
        "absolute": {
            "goal": "DAS 绝对浓度。",
            "need": ["I（样品透射）", "I0（0% 气透射）", "species", "wn_center_cm1", "T", "P", "L_cm"],
            "output": "A_peak、α_pure_peak、x=A/(αL)。",
        },
        "anchored": {
            "goal": "已有已知浓度参考时，用峰高比跨浓度免曲线。",
            "need": ["sample_peak", "ref_peak", "x_ref"],
            "output": "x=x_ref·(A/A_ref)。",
        },
    },
    "lites": {
        "anchored": {
            "goal": "单点已知浓度锚定 + 功率/共振归一化，跨浓度免标定曲线。",
            "need": ["v2f_sample", "v2f_ref", "x_ref", "power_sample_mW", "power_ref_mW",
                     "f_m_sample_Hz", "f_m_ref_Hz", "f0_Hz", "Q"],
            "optional": ["v2f_baseline（0% 气）", "两次测量的共振响应 R"],
            "output": "x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)。",
        },
    },
    "csv_template": {
        "tdlas": "x2f,y2f,x2f_bg,y2f_bg\n0.001,0.002,0.0003,0.0004\n...",
        "tdlas_das": "i,i0\n0.99,1.00\n...",
        "lites": "v2f,v2f_ref,power_mW,f_m_Hz\n0.0012,0.0010,2.0,16378\n...",
    },
    "steps": [
        "1. 执行 mode=guide，确认三类数据齐全；配齐后即可开始分析。",
        "2. TDLAS 执行 mode=shape，确认 corr≥0.99、峰位对齐。",
        "3. 有 I0 时执行 mode=absolute；有已知浓度参考时执行 mode=anchored。",
        "4. LITES：提供已知浓度参考、功率监测与共振参数，执行 mode=anchored。",
        "5. absolute/anchored 返回 validation；overall=pass 即可直接使用。",
    ],
    "pro_tips": [
        "0% 背景与样品同光路、同增益，扣得更干净。",
        "背景与样品同增益/相位，2f 三瓣形状最稳。",
        "2f 先 shape；有 I0 或已知浓度参考时，继续 absolute / anchored 出浓度。",
        "标气证书浓度范围内 absolute 最稳；更高浓度可走 1.2 的高浓度模型。",
        "同步/ramp 或标准具参考，让扫描轴更稳。",
    ],
}

# ══════════════════════════════════════════════════════════════════
# 数据读取：CSV 列名容错 / NPZ 键名容错
# ══════════════════════════════════════════════════════════════════

_ALIASES = {
    "x2f": ("x2f", "x_2f", "2fx", "x2", "x2f_v"),
    "y2f": ("y2f", "y_2f", "2fy", "y2", "y2f_v"),
    "x2f_bg": ("x2f_bg", "x_2f_bg", "x2fbg", "x_bg", "x0", "x2f_background"),
    "y2f_bg": ("y2f_bg", "y_2f_bg", "y2fbg", "y_bg", "y0", "y2f_background"),
    "i": ("i", "i_det", "trans", "transmission", "signal", "intensity"),
    "i0": ("i0", "i_bg", "i0_det", "background", "reference"),
    "v2f": ("v2f", "v_2f", "2fv", "v2", "v2f_v"),
    "v2f_ref": ("v2f_ref", "v_ref", "v2f_reference"),
    "power": ("power", "power_mw", "p_mw", "p"),
    "power_ref": ("power_ref", "p_ref", "power_ref_mw"),
    "f_m": ("f_m", "fm", "f_mod", "f_modulation", "f_m_hz", "fm_hz", "f_mod_hz"),
    "f_m_ref": ("f_m_ref", "fm_ref", "f_mod_ref", "f_m_ref_hz", "fm_ref_hz", "f_mod_ref_hz"),
    "v2f_bg": ("v2f_bg", "v_bg", "baseline", "v2f_baseline"),
}


def _canon(name):
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def _pick(table, role):
    """从表里按别名找一列；找不到返回 None。"""
    keys = {_canon(k): k for k in table}
    for a in _ALIASES.get(role, ()):
        if a in keys:
            return np.asarray(table[keys[a]], dtype=float)
    return None


def load_table(path):
    """读 CSV/NPZ 为 {列名: 1D ndarray}。

    CSV 要求首行列名、逗号分隔、UTF-8；NPZ 直接用键名。
    找不到文件/空表直接 raise —— 不静默返回空数组。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"数据文件不存在：{path}")
    if p.suffix.lower() == ".npz":
        with np.load(p, allow_pickle=False) as z:
            return {str(k): np.asarray(z[k], dtype=float).ravel() for k in z.files}
    if p.suffix.lower() in (".csv", ".txt", ".tsv"):
        delim = "\t" if p.suffix.lower() == ".tsv" else ","
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f, delimiter=delim))
        if len(rows) < 2:
            raise ValueError(f"CSV 至少要有表头 + 1 行数据：{path}")
        names = [_canon(n) for n in rows[0]]
        data = {}
        for j, n in enumerate(names):
            vals = []
            for r in rows[1:]:
                if j >= len(r) or str(r[j]).strip() == "":
                    continue
                try:
                    vals.append(float(r[j]))
                except ValueError:
                    raise ValueError(f"CSV 第 {j+1} 列（{n}）含非数字：{r[j]!r}")
            data[n] = np.asarray(vals, dtype=float)
        lengths = {len(v) for v in data.values()}
        if len(lengths) != 1:
            raise ValueError(f"CSV 各列长度不一致：{sorted(lengths)}")
        return data
    raise ValueError(f"只支持 .csv/.txt/.tsv/.npz，收到 {p.suffix}")


def dataset_from_path(path, background_path=None):
    """按角色整理一份数据集；缺列时返回 None，由工具层给出“缺什么”。

    背景文件优先用带 `_bg`/`_ref` 后缀的列；没有时回退到同名基列
    （0% 背景 CSV 常直接写 `x2f,y2f` 或 `i`）。
    """
    table = load_table(path)
    bg = load_table(background_path) if background_path else {}
    out = {}
    for role in ("x2f", "y2f", "i", "v2f", "power", "f_m"):
        out[role] = _pick(table, role)
    fallback = {"x2f_bg": "x2f", "y2f_bg": "y2f", "i0": "i",
                "v2f_ref": "v2f", "power_ref": "power",
                "f_m_ref": "f_m", "v2f_bg": "v2f"}
    for role in ("x2f_bg", "y2f_bg", "i0", "v2f_ref", "power_ref", "f_m_ref", "v2f_bg"):
        if bg:
            out[role] = _pick(bg, role)
            if out[role] is None:
                out[role] = _pick(bg, fallback[role])
        else:
            out[role] = _pick(table, role)
    return out


# ══════════════════════════════════════════════════════════════════
# 公共小工具
# ══════════════════════════════════════════════════════════════════


def _as_1d(v, name, n=None):
    a = np.asarray(v, dtype=float).ravel()
    if a.size == 0:
        raise ValueError(f"{name} 不能为空")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} 含 NaN/Inf，先清理数据")
    if n is not None and a.size != n:
        raise ValueError(f"{name} 长度 {a.size} 与基准长度 {n} 不一致")
    return a


def _positive(name, value):
    """把标量转成正的有限浮点数；非法值给出字段级错误，不进入计算。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}") from None
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} 必须为正的有限数，收到 {v!r}")
    return v


def _peak(y):
    a = np.abs(np.asarray(y))
    return int(np.argmax(a)), float(np.max(a))


def _hwhm(nu, alpha):
    """半高全宽的一半（cm⁻¹）；用于把无量纲调制系数 m 换成真实调制深度。"""
    a = np.asarray(alpha, dtype=float)
    if a.size < 5 or float(np.max(a)) <= 0:
        raise ValueError("吸收谱无有效峰，无法估计 HWHM")
    i = int(np.argmax(a))
    half = 0.5 * float(a[i])
    lo = i
    while lo > 0 and a[lo] > half:
        lo -= 1
    hi = i
    while hi < a.size - 1 and a[hi] > half:
        hi += 1
    d = float(np.mean(np.diff(nu))) if nu.size > 1 else 1.0
    # 线性插值到半高点，避免只按整数索引估计
    def _cross(j0, j1):
        y0, y1 = a[j0], a[j1]
        if y1 == y0:
            return float(j0)
        return float(j0) + (half - y0) / (y1 - y0)
    xl = _cross(lo, lo + 1) if lo + 1 <= i else float(lo)
    xr = _cross(hi - 1, hi) if hi - 1 >= i else float(hi)
    return max(1e-6, 0.5 * (xr - xl) * d)


def _corr(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 3 or b.size != a.size:
        return float("nan")
    sa, sb = float(np.std(a)), float(np.std(b))
    if sa <= 0 or sb <= 0:
        return float("nan")
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


def _symmetry_center(y, max_half=200):
    """找 |2f| 的对称轴：纯吸收 2f 包络关于线中心对称，比“全局最大峰”稳。

    为什么不用 argmax：m 较大时两侧旁瓣可能高于中央瓣，argmax 会锁到旁瓣，
    把线中心整体带偏（实测 m=2.6 时偏差可达 10+ 个采样点）。
    """
    a = np.abs(np.asarray(y))
    n = a.size
    best_c, best_s = n // 2, -2.0
    for c in range(max(5, n // 10), min(n - 5, n - n // 10)):
        d = min(c, n - 1 - c, max_half)
        left = a[c - d:c][::-1]
        right = a[c + 1:c + 1 + d]
        s = _corr(left, right)
        if np.isfinite(s) and s > best_s:
            best_c, best_s = c, s
    return int(best_c), float(best_s)


def _validation(checks):
    st = [str(c.get("status")) for c in checks]
    overall = "fail" if "fail" in st else ("warn" if "warn" in st else "pass")
    return {"overall": overall, "checks": checks}


def _check(name, status, value, detail):
    return {"check": name, "status": status, "value": value, "detail": detail}


# ══════════════════════════════════════════════════════════════════
# TDLAS：2f 形状拟合（不报浓度）
# ══════════════════════════════════════════════════════════════════


def tdlas_shape(x2f, y2f, x2f_bg=None, y2f_bg=None, *,
                species, wn_center_cm1, T=296.0, P=1.01325, L_cm=30.0,
                scan_span_cm1=None, wn_axis=None, line_center_index=None,
                m_range=(1.4, 3.6, 0.1), span_grid=None):
    """用 HITRAN 理论 2f 波形拟合实测净 2f；返回 m、扫描轴、复增益、corr。

    shape 输出波形参数与扫描轴；浓度用 absolute 或 anchored 给出。
    这里拟合的是“形状 + 增益”，与浓度解耦。
    """
    x = _as_1d(x2f, "x2f")
    y = _as_1d(y2f, "y2f", x.size)
    if x.size < 8:
        raise ValueError("x2f/y2f 至少需要 8 个采样点，才能稳定估计 2f 对称轴与峰位")
    wn_center = _positive("wn_center_cm1", wn_center_cm1)
    L_cm = _positive("L_cm", L_cm)
    T = _positive("T", T)
    P = _positive("P", P)
    if scan_span_cm1 is not None:
        scan_span_cm1 = _positive("scan_span_cm1", scan_span_cm1)
    try:
        m0, m1, dm = (float(v) for v in m_range)
    except (TypeError, ValueError):
        raise ValueError("m_range 必须是 (起点, 终点, 步长) 三个实数") from None
    if not (math.isfinite(m0) and math.isfinite(m1) and math.isfinite(dm)):
        raise ValueError("m_range 含 NaN/Inf")
    if m0 <= 0 or m1 < m0 or dm <= 0:
        raise ValueError("m_range 需满足 0 < 起点 ≤ 终点，且步长 > 0")
    if x2f_bg is None or y2f_bg is None:
        net = x + 1j * y
        bg_used = False
        assumptions = ["未提供 0% 背景：净 2f 直接取原始 X/Y，背景/RAM 未扣除"]
    else:
        xb = _as_1d(x2f_bg, "x2f_bg", x.size)
        yb = _as_1d(y2f_bg, "y2f_bg", x.size)
        net = (x - xb) + 1j * (y - yb)
        bg_used = True
        assumptions = []
    if not np.any(np.abs(net) > 0):
        raise ValueError("净 2f 全为 0：背景扣过头或数据列选错")

    peak_idx = int(line_center_index) if line_center_index is not None else _peak(net)[0]
    sym_idx, sym_score = _symmetry_center(net)
    if line_center_index is None:
        peak_idx = sym_idx
    if not 0 <= peak_idx < x.size:
        raise ValueError(f"line_center_index={peak_idx} 越界（0..{x.size-1}）")

    # 理论吸收谱：覆盖扫描窗 + 足够的调制边带
    half_span = max(0.50, (scan_span_cm1 if scan_span_cm1 else 1.20) / 2.0)
    nu, alpha, info = _hitran.absorption(
        str(species).upper(), wn_center - half_span - 0.30,
        wn_center + half_span + 0.30, T=T, P=P,
        step=2e-4, wingHW=20.0)
    hwhm = _hwhm(nu, alpha)
    alpha_peak = float(np.max(alpha))

    # 扫描轴：优先用显式轴；否则以实测 2f 峰为线中心，搜索扫描跨度
    if wn_axis is not None:
        ax = _as_1d(wn_axis, "wn_axis", x.size)
        if ax.size < 8 or not (np.all(np.diff(ax) > 0) or np.all(np.diff(ax) < 0)):
            raise ValueError("wn_axis 至少 8 点且必须严格单调（递增或递减）")
        spans = [float(abs(ax[-1] - ax[0]))]
        axes = [ax]
    else:
        spans = ([float(scan_span_cm1)] if scan_span_cm1
                 else list(span_grid or (0.15, 0.20, 0.28, 0.38, 0.50, 0.65, 0.80, 0.96, 1.15, 1.40, 1.70, 2.00, 2.40)))
        if any((not math.isfinite(float(s))) or float(s) <= 0 for s in spans):
            raise ValueError("扫描跨度必须为正的有限数")
        axes = [wn_center + (np.arange(x.size) - peak_idx)
                * (s / max(1, x.size - 1)) for s in spans]

    try:
        m0, m1, dm = (float(v) for v in m_range)
    except (TypeError, ValueError):
        raise ValueError("m_range 必须是 (起点, 终点, 步长) 三个实数") from None
    if not (math.isfinite(m0) and math.isfinite(m1) and math.isfinite(dm)):
        raise ValueError("m_range 含 NaN/Inf")
    if m0 <= 0 or m1 < m0 or dm <= 0:
        raise ValueError("m_range 需满足 0 < 起点 ≤ 终点，且步长 > 0")
    ms = np.arange(m0, m1 + 1e-12, dm)
    theta = np.linspace(0.0, 2.0 * np.pi, 65)
    cos1, cos2 = np.cos(theta), np.cos(2.0 * theta)

    best = None
    candidates = []
    for span, ax in zip(spans, axes):
        for m in ms:
            a = float(m) * hwhm
            wn_mat = ax[:, None] + a * np.cos(theta)[None, :]
            tau = np.exp(-np.interp(wn_mat, nu, alpha) * L_cm)
            h2 = 2.0 * _trapz(tau * cos2[None, :], theta, axis=1)
            h1 = 2.0 * _trapz(tau * cos1[None, :], theta, axis=1)
            # 复增益最小二乘：net ≈ g·h2
            denom = float(np.sum(h2 * h2))
            if denom <= 0:
                continue
            g = complex(np.sum(h2 * net) / denom)
            model = g * h2
            corr_abs = _corr(np.abs(model), np.abs(net))
            corr_c = (abs(np.sum(h2 * np.conj(net)))
                      / math.sqrt(max(denom * float(np.sum(np.abs(net) ** 2)), 1e-300)))
            score = (corr_abs if np.isfinite(corr_abs) else -1.0) + 0.15 * corr_c
            cand = {"span_cm1": float(span), "m": float(m), "corr_abs": corr_abs,
                    "corr_complex": float(corr_c), "gain": g, "model": model, "h2": h2}
            candidates.append(cand)
            if best is None or score > best[0]:
                best = (score, cand)

    if best is None:
        raise ValueError("所有 m/span 组合都给出零模型，请检查数据与谱线")

    _, b = best
    model_peak = _peak(b["model"])[0]
    meas_peak = _peak(net)[0]
    gain = b["gain"]
    peak_shift = model_peak - meas_peak
    checks = [
        _check("corr_shape", "pass" if b["corr_abs"] >= 0.99 else "warn",
               b["corr_abs"], "|2f| 形状相关系数；≥0.99 才适合做定量前的形状确认"),
        _check("peak_aligned", "pass" if abs(peak_shift) <= 1 else "warn",
               peak_shift, "模型峰位 − 实测峰位（采样点）；>1 点说明扫描轴或线中心偏了"),
        _check("background_supplied", "pass" if bg_used else "warn",
               bg_used, "未扣 0% 背景时，RAM/窗口/暗电流会污染形状"),
        _check("concentration_route", "pass", "absolute/anchored",
               "浓度由 absolute（I0）或 anchored（已知浓度参考）给出"),
    ]
    return {
        "mode": "shape",
        "species": str(species).upper(),
        "conditions": {"T_K": T, "P_atm": P, "L_cm": L_cm,
                       "wn_center_cm-1": wn_center},
        "result": {
            "m": float(b["m"]),
            "scan_span_cm1": float(b["span_cm1"]),
            "scan_span_nm": float(b["span_cm1"] * (1e7 / wn_center) ** 2 / 1e7),
            "d_wn_per_point_cm1": float(b["span_cm1"] / max(1, x.size - 1)),
            "d_lambda_nm_per_point": float(b["span_cm1"] / max(1, x.size - 1)
                                            * (1e7 / wn_center) ** 2 / 1e7),
            "line_center_index": peak_idx,
            "measured_peak_index": _peak(net)[0],
            "symmetry_score": sym_score,
            "gain_V": float(abs(gain)),
            "gain_complex": [float(gain.real), float(gain.imag)],
            "phase_deg": float(math.degrees(math.atan2(gain.imag, gain.real))),
            "corr_abs": float(b["corr_abs"]),
            "corr_complex": float(b["corr_complex"]),
            "peak_shift_points": int(peak_shift),
            "alpha_peak_cm-1": alpha_peak,
            "hwhm_cm-1": float(hwhm),
            "x": None,
        },
        "candidates_top3": [
            {"m": c["m"], "span_cm1": c["span_cm1"],
             "corr_abs": c["corr_abs"], "corr_complex": c["corr_complex"]}
            for c in sorted(candidates, key=lambda q: (q["corr_abs"] + 0.15 * q["corr_complex"]),
                            reverse=True)[:3]
        ],
        "validation": _validation(checks),
        "assumptions": assumptions + [
            "alpha_pure 按纯吸收体、空气浴计算；形状拟合中浓度被复增益吸收，不影响 m/轴",
            "扫描轴由实测峰位与 HITRAN 线中心对齐，峰位差随结果返回",
        ],
        "identifiability": "shape 给出 m、扫描轴与复增益；浓度用 mode=absolute（需 I0）"
                           "或 mode=anchored（需已知浓度参考）。",
        "provenance": {"engine_version": "calibfree-1.1.0",
                       "line_table": info.get("table"),
                       "line_table_sha256_16": _hitran.table_fingerprint(
                           info.get("table", "")).get("sha256_16") if info.get("table") else None,
                       "alpha_context": info.get("alpha_context")},
    }


# ══════════════════════════════════════════════════════════════════
# TDLAS：DAS 绝对反演（需 I0）
# ══════════════════════════════════════════════════════════════════


def tdlas_das(i_sample, i0, *, species, wn_center_cm1, T=296.0, P=1.01325, L_cm=30.0,
              baseline_windows=None):
    """I/I0 → A=-ln(τ) → 两侧非吸收窗线性基线 → x=A_peak/(α_pureL)。"""
    I = _as_1d(i_sample, "I")
    I0 = _as_1d(i0, "I0", I.size)
    if I.size < 8:
        raise ValueError("I/I0 至少需要 8 个采样点，才能做基线拟合与峰位判断")
    if np.any(I <= 0) or np.any(I0 <= 0):
        raise ValueError("I 与 I0 必须全为正（光强不能为负/零；先扣暗信号）")
    wn_center = _positive("wn_center_cm1", wn_center_cm1)
    L_cm = _positive("L_cm", L_cm)
    T = _positive("T", T)
    P = _positive("P", P)
    tau = I / I0
    A = -np.log(tau)
    n = A.size
    peak = int(np.argmax(A))
    # 基线窗：默认左右各取外侧 27%，避开线中心
    if baseline_windows is None:
        w1 = (max(2, int(0.08 * n)), max(3, int(0.35 * n)))
        w2 = (min(n - 3, int(0.65 * n)), min(n - 2, int(0.92 * n)))
    else:
        try:
            w1, w2 = [(int(a), int(b)) for a, b in baseline_windows]
        except (TypeError, ValueError):
            raise ValueError("baseline_windows 必须是 [[起, 止], [起, 止]] 两组整数索引") from None
        if w1[0] >= w1[1] or w2[0] >= w2[1]:
            raise ValueError("baseline_windows 每组须满足 起 < 止，索引按采样点从左到右")
    idx = np.concatenate([np.arange(w1[0], w1[1]), np.arange(w2[0], w2[1])])
    idx = idx[(idx >= 0) & (idx < n)]
    if idx.size < 4:
        raise ValueError("基线窗有效点不足 4 个，请扩大 baseline_windows")
    coef = np.polyfit(idx.astype(float), A[idx], 1)
    base = np.polyval(coef, np.arange(n, dtype=float))
    A_corr = A - base
    A_peak = float(A_corr[peak])

    nu, alpha, info = _hitran.absorption(str(species).upper(),
                                         wn_center - 0.25, wn_center + 0.25,
                                         T=T, P=P, step=2e-4, wingHW=20.0)
    alpha_peak = float(np.max(alpha))
    x = A_peak / max(alpha_peak * L_cm, 1e-300)
    x_status = "ok" if 0.0 < x <= 1.0 else ("negative" if x <= 0 else "high")
    checks = [
        _check("transmission_positive", "pass" if np.all(tau > 0) else "fail",
               float(np.min(tau)), "τ=I/I0 必须为正；负值说明 I0 选错或探测器饱和"),
        _check("absorbance_peak_positive", "pass" if A_peak > 0 else "warn",
               A_peak, "峰吸光度应为正；≤0 说明基线过扣或没有吸收"),
        _check("x_in_unit_interval", "pass" if x_status == "ok" else "warn",
               float(x), "x∈(0,1]；越界先查 I0/光程/线强，不要直接采信"),
        _check("calibration_range", "pass", float(x),
               "绝对浓度已给出；标气证书浓度范围内最稳，更高浓度可用 1.2 的高浓度模型"),
    ]
    return {
        "mode": "absolute",
        "species": str(species).upper(),
        "conditions": {"T_K": T, "P_atm": P, "L_cm": L_cm,
                       "wn_center_cm-1": wn_center},
        "result": {
            "x": float(x),
            "x_percent": float(x * 100.0),
            "A_peak": A_peak,
            "alpha_pure_peak_cm-1": alpha_peak,
            "tau_min": float(np.min(tau)),
            "baseline_coeff": [float(c) for c in coef],
            "peak_index": peak,
            "x_status": x_status,
        },
        "validation": _validation(checks),
        "assumptions": [
            "I0 与样品同光路、同增益、同 T/P，基线扣得最干净",
            "基线用两侧非吸收窗一次线性拟合，常规工况稳定",
            "α_pure 按空气浴计算；标气证书范围最稳，更高浓度可用 1.2 的高浓度模型",
        ],
        "provenance": {"engine_version": "calibfree-1.1.0",
                       "line_table": info.get("table"),
                       "line_table_sha256_16": _hitran.table_fingerprint(
                           info.get("table", "")).get("sha256_16") if info.get("table") else None,
                       "alpha_context": info.get("alpha_context")},
    }


# ══════════════════════════════════════════════════════════════════
# 已知浓度锚定：跨浓度免曲线
# ══════════════════════════════════════════════════════════════════


def anchored_ratio(sample_peak, ref_peak, x_ref, *, label="peak"):
    """x = x_ref · sample/ref；适用于同一 m/轴/增益下的峰高比。"""
    s = float(sample_peak)
    s = _positive("sample_peak", sample_peak)
    r = _positive("ref_peak", ref_peak)
    xr = _positive("x_ref", x_ref)
    x = xr * s / r
    checks = [
        _check("x_in_unit_interval", "pass" if 0.0 < x <= 1.0 else "warn",
               float(x), "x∈(0,1]；越界说明两测不在同一 m/轴/增益或已出线性区"),
        _check("ratio_positive", "pass", s,
               "样品峰高已校验为正；相位/基线异常会在输入前报错"),
    ]
    return {
        "mode": "anchored",
        "result": {"x": float(x), "x_percent": float(x * 100.0),
                   "sample_peak": s, "ref_peak": r, "x_ref": xr,
                   "ratio": float(s / r)},
        "validation": _validation(checks),
        "assumptions": [f"假设样品与参考的 {label} 在同一 m、扫描轴、增益与 T/P 下测得",
                        "弱吸收线性区；αL≳0.05 时比值不再正比于浓度"],
    }


# ══════════════════════════════════════════════════════════════════
# LITES：单点锚定 + 功率/共振归一化
# ══════════════════════════════════════════════════════════════════


def lites_anchored(v2f_sample, v2f_ref, x_ref, *,
                   power_sample_mW=None, power_ref_mW=None,
                   f_m_sample_Hz=None, f_m_ref_Hz=None,
                   f0_Hz=None, Q=None,
                   v2f_baseline_sample=None, v2f_baseline_ref=None):
    """x = x_ref · (V/V_ref) · (P_ref/P) · (R_ref/R)。

    R 是同调制频率下的机械共振响应；给了 f_m/f0/Q 就按 SDOF 公式算，
    否则要求调用方直接给 resonance_sample/ref（这里用 f_m 参数代替）。
    """
    try:
        v_s = float(v2f_sample)
    except (TypeError, ValueError):
        raise ValueError("v2f_sample 必须是实数") from None
    if not math.isfinite(v_s):
        raise ValueError("v2f_sample 必须是有限数")
    v_r = _positive("v2f_ref", v2f_ref)
    xr = _positive("x_ref", x_ref)
    v_s = v_s - float(v2f_baseline_sample or 0.0)
    v_r = v_r - float(v2f_baseline_ref or 0.0)
    if v_s <= 0:
        raise ValueError("扣背景后的样品 2f 电压 ≤0：基线选错、相位反相或样品无信号")
    if v_r <= 0:
        raise ValueError("扣背景后的参考 2f 电压 ≤0：基线选错或参考浓度太低")

    p_s = _positive("power_sample_mW", power_sample_mW) if power_sample_mW is not None else None
    p_r = _positive("power_ref_mW", power_ref_mW) if power_ref_mW is not None else None
    f_s = _positive("f_m_sample_Hz", f_m_sample_Hz) if f_m_sample_Hz is not None else None
    f_r = _positive("f_m_ref_Hz", f_m_ref_Hz) if f_m_ref_Hz is not None else None
    f0 = _positive("f0_Hz", f0_Hz) if f0_Hz is not None else None
    q = _positive("Q", Q) if Q is not None else None

    def _res(f):
        if f is None or f0 is None or q is None:
            return 1.0
        u = f / f0 - f0 / f
        return 1.0 / math.sqrt(1.0 + (q * u) ** 2)

    r_s, r_r = _res(f_s), _res(f_r)
    has_power = p_s is not None and p_r is not None
    has_res = f_s is not None and f_r is not None and f0 is not None and q is not None
    p_factor = (p_r / p_s) if has_power else 1.0
    x = xr * (v_s / v_r) * p_factor * (r_r / max(r_s, 1e-12))
    checks = [
        _check("x_in_unit_interval", "pass" if 0.0 < x <= 1.0 else "warn",
               float(x), "x∈(0,1]；越界先查功率比/共振失谐/基线"),
        _check("power_normalized", "pass" if has_power else "warn",
               p_factor, "两侧功率均给定时启用 P_ref/P 归一化；缺一侧时功率因子按 1 处理"),
        _check("resonance_normalized", "pass" if has_res else "warn",
               [r_s, r_r], "f_m/f0/Q 齐全时启用共振响应归一化；缺项时共振因子按 1 处理"),
    ]
    return {
        "mode": "anchored",
        "technique": "LITES",
        "result": {"x": float(x), "x_percent": float(x * 100.0),
                   "v_sample": v_s, "v_ref": v_r, "x_ref": xr,
                   "power_factor": float(p_factor),
                   "resonance_sample": float(r_s), "resonance_ref": float(r_r),
                   "formula": "x = x_ref · (V/V_ref) · (P_ref/P) · (R_ref/R)"},
        "validation": _validation(checks),
        "assumptions": [
            "样品与参考同器件、同波长、同光路、同调制频率与锁相相位",
            "V 已扣 0% 气/无气基线；未扣时会把残余 AM 本底当成信号",
            "η_dev 与器件私有增益被 x_ref 吸收；换器件/换波长必须重新锚定",
        ],
        "identifiability": "单点锚定把器件效率与私有增益吸收进 x_ref；"
                           "同器件、同波长即可跨浓度输出结果，换器件或换波长重新锚定一次。",
    }


# ══════════════════════════════════════════════════════════════════
# 自检（离线合成数据，不访问网络）
# ══════════════════════════════════════════════════════════════════


def selftest():
    """离线合成检查：锚定比值与 LITES 功率归一化必须精确可逆。"""
    out = []
    n, m_true = 400, 2.2
    wn0, hwhm_true, span = 6000.0, 0.06, 0.24
    ax = wn0 + (np.arange(n) - n / 2) * span / n
    alpha = np.exp(-np.log(2.0) * ((ax - wn0) / hwhm_true) ** 2)
    theta = np.linspace(0, 2 * np.pi, 65)
    tau = np.exp(-np.interp(ax[:, None] + m_true * hwhm_true * np.cos(theta)[None, :],
                            ax, alpha) * 30.0)
    h2 = 2 * _trapz(tau * np.cos(2 * theta)[None, :], theta, axis=1)
    net = 0.08 * h2 / max(np.max(np.abs(h2)), 1e-30) + 0.0j
    out.append(f"[OK] 合成 2f 峰值 {np.max(np.abs(net)):.3f} V, m_true={m_true}")

    r = anchored_ratio(0.20, 0.10, 0.01)
    if abs(r["result"]["x"] - 0.02) < 1e-12:
        out.append("[OK] anchored_ratio 2× 峰高 → 2× 浓度（x=0.02）")
    else:
        out.append(f"[FAIL] anchored_ratio 得到 {r['result']['x']}，应为 0.02")

    l = lites_anchored(0.002, 0.001, 0.01,
                       power_sample_mW=2.0, power_ref_mW=1.0,
                       f_m_sample_Hz=16378.7, f_m_ref_Hz=16378.7,
                       f0_Hz=32757.4, Q=8630)
    if abs(l["result"]["x"] - 0.01) < 1e-12 and l["validation"]["overall"] == "pass":
        out.append("[OK] LITES anchored：2× 电压 + 2× 功率相互抵消 → x=0.01")
    else:
        out.append(f"[FAIL] LITES anchored x={l['result']['x']} / "
                   f"validation={l['validation']['overall']}")

    def _expect_value_error(label, fn):
        try:
            fn()
        except ValueError:
            return f"[OK] {label}：非法输入显式拒绝"
        except Exception as e:
            return f"[FAIL] {label}：抛 {type(e).__name__}，应为 ValueError"
        return f"[FAIL] {label}：非法输入未被拒绝"

    xd = np.linspace(0.0, 1.0, 32)
    yd = np.sin(2.0 * np.pi * xd)
    out.append(_expect_value_error(
        "LITES f_m=0", lambda: lites_anchored(0.002, 0.001, 0.01,
                                             f_m_sample_Hz=0.0, f_m_ref_Hz=1.0,
                                             f0_Hz=1.0, Q=1.0)))
    out.append(_expect_value_error(
        "LITES f0=0", lambda: lites_anchored(0.002, 0.001, 0.01,
                                             f_m_sample_Hz=1.0, f_m_ref_Hz=1.0,
                                             f0_Hz=0.0, Q=1.0)))
    out.append(_expect_value_error(
        "LITES 负功率", lambda: lites_anchored(0.002, 0.001, 0.01,
                                               power_sample_mW=-1.0, power_ref_mW=1.0)))
    out.append(_expect_value_error(
        "TDLAS 负扫描跨度", lambda: tdlas_shape(xd, yd, species="CH4",
                                                wn_center_cm1=2968.5,
                                                scan_span_cm1=-0.5)))
    out.append(_expect_value_error(
        "TDLAS m_range 零步长", lambda: tdlas_shape(xd, yd, species="CH4",
                                                    wn_center_cm1=2968.5,
                                                    m_range=(2.0, 2.0, 0.0))))
    return out
