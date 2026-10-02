#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力登记表与保真度审计（离线、确定性、可作为契约门禁）。

为什么需要这一层
────────────────
本项目已经踩过两次**同一类**事故：schema 声明了参数、MCP 层却从未把它交给引擎，
于是 AI 传了值、拿到的是默认值算出的结果，**全程零提示**（`edge` 一族、以及
`lites_forward` 的整族 etalon 几何参数）。

根因不是懒惰，而是**缺一个单一真源**：物理效应、参数、证据分散在代码、文档、测试三处，
人一改就漂。本模块把三者收进一张可执行的表：

  · ``EFFECTS``  物理效应登记表 —— 每一项声明「在哪实现 / 是否真的生效 / 有什么已知缺口」
  · ``audit_parameters()`` 参数可达性审计 —— 用假引擎截获真正进入引擎的 kwargs
  · ``audit_effects()``    证据一致性审计 —— 登记表里写的符号/常量是否真的存在于源码
  · ``missing_effects()``  已知缺口清单 —— 供 AI 与用户判断"这次结果可信到什么程度"

设计纪律
────────
1. **不许手工维护"是否实现"**：``audit_effects`` 会去源码里找证据，找不到就报 FAIL。
2. **合法通道白名单必须显式**：设备引用/会话/出图开关不进引擎是**设计如此**，
   白名单之外的一切"声明了却没进引擎"都是缺陷。
3. 这一层不跑仿真、不访问 HITRAN、不启服务器 —— 端到端回归 ``_rpc_test.py`` 同一纪律。

用法：
    python tools/lites_fidelity.py            # 打印审计报告（退出码 0=全通过）
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lites_physics as lph  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════
# 1. 物理效应登记表
# ══════════════════════════════════════════════════════════════════════
# evidence : 必须出现在 lites_physics.py / tools/lites_*.py 源码里的字面量（证明实现真的存在）
# params   : 控制该项的参数名（用于与 schema 交叉核对）；空 = 无参数开关
# status   : "on" 默认生效 / "opt" 需显式开启 / "off" 未实现
# limit    : 已知近似与缺口（会进 AI 的 must_disclose）

EFFECTS = [
    # ── 源层：气体吸收与线型 ──────────────────────────────────────
    dict(id="alpha_from_line_strength", cat="source", status="on",
         title="气体吸收系数 α_gas（线强 × 线型 → αL）",
         evidence=["def effective_eta_abs", "alphaL"],
         params=["line_strength", "L_gas_cm", "gamma_L", "T", "P"],
         limit="用单一 Voigt 近似；未调用 HITRAN 逐线表，故**窗口内的邻近干扰线"
               "与线混合均未计入**。给 line_strength 时需要调用方自己确认该线干净"),
    dict(id="dicke_narrowing", cat="source", status="off",
         title="Dicke 变窄（速度依赖碰撞）",
         evidence=[],
         params=[],
         limit="未建模；低压（≲0.1 atm）时实测线宽会窄于 Voigt 预期，"
               "进而高估 α_peak、低估 SBR"),
    dict(id="line_mixing", cat="source", status="off",
         title="线混合（line mixing）",
         evidence=[],
         params=[],
         limit="未建模；高密度谱区（CH4 ν₃、CO2 4.3μm）的 2f 翼部与实验有偏差"),
    dict(id="self_broadening", cat="source", status="off",
         title="自展宽",
         evidence=[],
         params=[],
         limit="未建模；x ≳ 1e-2 时离线宽被低估"),

    # ── 器件层：η_dev 与光路 ──────────────────────────────────────
    dict(id="device_absorption", cat="device", status="on",
         title="器件自身吸收 η_dev（LITES 的热源，非气体）",
         evidence=["def effective_eta_abs", "eta_abs_offline"],
         params=["eta_spurious"],
         limit="**这是本模型最大的不确定度来源**：η_dev 由文献 V/P 反推得到，"
               "**未经实验室空白基线标定**。它直接决定 V_2f_baseline 的绝对值；"
               "相对量（功率标度、浓度线性、频率响应）不受影响。"
               "换器件/换批次/换镀膜必须重新标定"),
    dict(id="mpc_throughput", cat="device", status="on",
         title="多通池吞吐（R^n 累积镜面反射损失）",
         evidence=["def optical_throughput"],
         params=["n_pass", "mirror_refl"],
         limit="用各向同性 R^n 近似；**未计入**镜面污染随时间的衰减、"
               "高阶模泄漏、以及点阵图案的再注入效率损失。"
               "R=0.98×259 次 → 仅 0.5% 吞吐，这是 MPC-LITES 的主要代价"),
    dict(id="spurious_absorption", cat="device", status="opt",
         title="寄生吸收（窗口污染 / 散射 / 杂散光）",
         evidence=["eta_spurious", "V_2f_spurious_V"],
         params=["eta_spurious"],
         limit="**默认 0（即理想洁净光路）**。真实系统的窗口污染会抬高 η_dev，"
               "既降低 SBR 又让基线漂移被误判为信号。"
               "需显式给 eta_spurious 才生效"),

    # ── 默认器件的专属缺口（2026-09-18 加入，随默认器件变更）────────
    dict(id="decapped_q_air_damping", cat="device", status="off",
         title="去壳音叉的常压空气阻尼（Q 的不可标定个体差异）",
         evidence=[],
         params=[],
         limit="默认器件 `qtf-commercial-decapped` 用的是 **常压实测** Q=8630"
               "（Wang 2020 表 1）。但去壳后 Q 受**空气黏性阻尼**主导，"
               "它随封装壳残余、叉齿朝向、气压、甚至支架气流变化，"
               "**个体差异可达 ±30%**。本模型取单一值 ⇒ 绝对灵敏度"
               "可能偏乐观或偏悲观。降压实测可回收 Q（700→5 Torr 时 SNR ~4×），"
               "**这一项未建模**。若你的实际气压不是 1 atm，Q 必须重测"),
    dict(id="decapped_noise_floor_opt", cat="device", status="off",
         title="去壳音叉的小尺寸噪声惩罚（1σ 噪声偏乐观）",
         evidence=[],
         params=[],
         limit="默认器件叉齿仅 0.33~0.6 mm，**与激光光斑（~100 μm）可比**，"
               "导致无法精确映射叉齿表面、1σ 噪声高达 0.3 mV"
               "（Wang 2020 实测，比自研大叉齿 QTF 高 ~3×）。"
               "本模型的噪声口径**未包含**这个几何惩罚 ⇒ 算出的 SNR 偏高、"
               "MDL 偏低。要保守估计请手动把 sigma_V 放大 3×"),
    dict(id="device_private_gain", cat="device", status="on",
         title="器件私有标定增益 g（跨器件电压不可比）",
         evidence=["def _solve_gain"],
         params=["cal_meas_f2_V", "c_total", "r_tia", "constr",
                 "electrode_area_m2"],
         limit="**每个器件的 2f 电压都含一个私有 g**，由该器件自己的锚点反解，"
               "g 吸收了它自身的 C_total/R_tia/constr/电极面积等未标定因素。"
               "后果：**跨器件的 V_2f 比值只反映锚点数字大小，不反映器件优劣**。"
               "实测自证：单独改 c_total 得 4.000×，但 c_total+r_tia 一起改"
               "后输出只差 2.2×，与直接比两器件的 27.3× 对不上。"
               "要比器件请走 lites_compare 严格口径，或读 tau_acc/Θ/H_th"),

    # ── 热弹转换层 ────────────────────────────────────────────────
    dict(id="heat_deposition", cat="thermo", status="on",
         title="热沉积功率 q = P·η_abs·throughput",
         evidence=["def heat_deposition"],
         params=["power_mW", "L_gas_cm"],
         limit="假设吸收功率**全部**转为热、且沉积长度等于光斑尺度；"
               "未计入荧光/光化学等非热耗散通道（对红外波段通常 <1%）"),
    dict(id="thermal_wave", cat="thermo", status="on",
         title="热波传递 |H_th|=√(f_ref/f)（表面热弹，f_ref=f0/2）",
         evidence=["def thermal_transfer", "def thermal_time"],
         params=["f_m"],
         limit="半无限介质表面热波解；f_ref 处量级由增益 g 吸收。未计入"
               "衬底/电极的额外散热路径与光斑非均匀性；具体器件最优 f_m"
               "建议 lites_sweep 实测确认"),
    dict(id="temp_rise", cat="thermo", status="on",
         title="交变温升 ΔT（点热源 + 热扩散）",
         evidence=["def temp_rise_from_heat"],
         params=["f_m"],
         limit="假设光斑内均匀加热、边界为体材料；未建模表面态与界面热阻"),
    dict(id="thermoelastic", cat="thermo", status="on",
         title="热弹应变 → 电荷（Θ = α_te·d_piezo/k_th）",
         evidence=["def thermoelastic_fom", "def thermal_expansion_strain"],
         params=["material"],
         limit="用**体材料**参数；薄膜/掺杂/晶向会显著改变 d_piezo 与 α_te。"
               "应变-电荷转换用线性压电近似，未含非线性项"),

    # ── 机械谐振层 ────────────────────────────────────────────────
    dict(id="mech_resonance", cat="mech", status="on",
         title="SDOF 机械谐振 H_mech(f)（品质因数放大）",
         evidence=["def mech_transfer"],
         params=["f0_shift_ppm", "f_m"],
         limit="单自由度模型；真实音叉有**一对**近简并模态（面内/面外），"
               "模式耦合会引起分裂与频率牵引，本模型未含"),
    dict(id="energy_accumulation", cat="mech", status="on",
         title="能量积累时间 τ_acc = Q/(π·f0)（本模型的核心校准轴）",
         evidence=["def energy_accumulation", "tau_acc"],
         limit="**受迫振子的包络建立时间**，同时等于群延迟。"
               "用文献 QTF1/QTF2 实测比 3.229× 验证，模型预测 3.864×，"
               "**偏差 19.7%** —— 这一残差来自模态耦合与电极质量差异，未单独建模。"
               "该 20% 量级的偏差是本模型在\"跨器件比较\"时的**真实精度上限**"),
    dict(id="detuning", cat="mech", status="on",
         title="失谐惩罚与温漂（f0(T) = f0·(1+tc·ΔT)）",
         evidence=["def f0_drift", "def detuning_loss"],
         params=["f0_shift_ppm"],
         limit="温度系数取**材料标称值**；封装应力会使有效 TC 显著偏离，"
               "必须用实测扫频标定"),
    dict(id="f0_thermal_history", cat="mech", status="off",
         title="热滞后与老化（f0 的慢漂移）",
         evidence=[],
         params=[],
         limit="未建模；石英音叉在连续工作数小时后 f0 会缓慢下漂，"
               "这是长期稳定性（而非 MDL）的限制因素"),

    # ── 信号链与读出 ──────────────────────────────────────────────
    dict(id="piezo_charge", cat="signal", status="on",
         title="压电电荷读出 → 电压（C_total 决定响应）",
         evidence=["def charge_from_strain", "c_total"],
         params=["electrode_area_m2", "tine_thick_m"],
         limit="平行板电容近似；未含电极边缘场与线缆寄生电容的分布效应"),
    dict(id="elec_gain", cat="signal", status="on",
         title="前置放大/锁相增益与带宽",
         evidence=["_g", "bw_3dB"],
         params=["gain"],
         limit="集总增益常数；未建模 TIA 的输入电容-带宽折衷"
               "（用 lites_noise_budget 的 c_in_F 可做一阶评估）"),
    dict(id="noise_1f", cat="signal", status="on",
         title="噪声预算分解：1/f + 白噪声 + TIA",
         evidence=["def noise_floor", "pink", "white"],
         params=["v_rms_1f", "bandwidth_Hz", "c_in_F"],
         limit="1/f 用单一拐点频率描述；真实系统的 1/f 可能有多段斜率。"
               "**给 v_rms_1f 时用实测值，否则用模型估值** —— 后者仅供量级参考"),
    dict(id="allan", cat="signal", status="on",
         title="Allan 偏差与最优积分时间",
         evidence=['"allan"', "tau_opt_s"],
         params=["integration_s"],
         limit="用 1/f+白噪声的解析模型；真实漂移（热、机械松弛）"
               "会让长积分时间的实测 Allan 偏差**高于**本模型预测"),

    # ── 解调与反演 ────────────────────────────────────────────────
    dict(id="lockin_2f", cat="demod", status="on",
         title="2f 锁相解调（基线与增量分离）",
         evidence=["def predict_2f_voltage", "V_2f_delta_V", "V_2f_baseline_V"],
         params=["f_m", "mod_depth_cm1"],
         limit="**基线故意不置零** —— 这是物理真实，不是 bug。"
               "调用方必须显式决定用 delta 还是总量口径；"
               "用总量口径算线性度会得到系统性错误结果"),
    dict(id="inversion", cat="demod", status="on",
         title="浓度反演（ΔV_2f → x）",
         evidence=["def lites_invert", "linearity_check"],
         params=["use_delta", "v_2f_baseline_V"],
         limit="仅弱吸收（αL ≲ 0.1）成立；返回体含线性度自检，"
               "**若自检不过说明已超出线性区，结论不可用**"),
    dict(id="wms_harmonic_general", cat="demod", status="off",
         title="任意阶谐波（3f/4f）与 WMS 的完整傅里叶展开",
         evidence=[],
         params=[],
         limit="未实现；本模型只做 2f。3f 常用于背景抑制，但 LITES 中"
               "3f 的信噪比劣势更大（热响应在 3f_m 处衰减更多）"),
    dict(id="wavelength_mod_optimization", cat="demod", status="off",
         title="调制深度的自动寻优（2f 峰值 vs m 的最优值）",
         evidence=[],
         params=[],
         limit="未实现自动寻优；mod_depth_cm1 需调用方自行扫描。"
               "受热扩散低通影响，LITES 的最优 m **小于** TDLAS 的经典值 2.2"),
]


# ── 合法通道白名单 ───────────────────────────────────────────────────
# 这些参数**本就不该**进入引擎：它们是 MCP 层的编排/引用/状态，不是物理量。
# 白名单之外出现"声明了却没进引擎"，即为缺陷。
NON_ENGINE_CHANNELS = {
    "device", "key", "action", "overrides",     # 器件库引用：由 get_device 解析
    "species", "var", "values", "log_scale",     # 编排层：扫描/物种覆盖
    "n_points", "base", "metrics", "devices",    # 编排层：扫描/对比控制
    "common", "topic", "out_path", "save_png",   # 编排层：输出与检索
    "seed", "compare_literature",                # 编排层：可复现性/对照开关
}


def _read_sources():
    out = {}
    for rel in ("lites_physics.py", "tools/lites_tools.py", "tools/lites_mcp.py"):
        p = _ROOT / rel
        if p.exists():
            out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def audit_effects():
    """检查登记表里声称的 evidence 是否真的存在于源码（防"表漂了"）。"""
    src = _read_sources()
    blob = "\n".join(src.values())
    problems = []
    for e in EFFECTS:
        if e["status"] == "off":
            if e["evidence"]:
                problems.append(f"{e['id']}: 标为未实现，却给了 evidence {e['evidence']}")
            continue
        if not e["evidence"]:
            problems.append(f"{e['id']}: 标为已实现，却没有 evidence（无法自证）")
            continue
        for token in e["evidence"]:
            if token not in blob:
                problems.append(f"{e['id']}: evidence 未在源码中找到 → {token!r}")
    return problems


def audit_parameters():
    """**行为式**参数可达性审计：逐参数扰动，检查是否真的改变输出。

    为什么不按 kwargs 名匹配
    ────────────────────────
    初版实现（已废弃）在 ``predict_2f_voltage`` 处截获 kwargs，结果对
    ``lites_forward`` 报出 8 个"死参数"。**那是误报**：``T``/``P``/``x``/
    ``gamma_L``/``line_strength`` 在 ``lites_tools`` 里被**位置参数**消费
    （先算成 ``alpha_eff``，再以 ``alpha_gas_cm1`` 传入），名字根本不会
    出现在内层 kwargs 里。按名字匹配只能证明"名字没传下去"，不能证明
    "参数无效"。

    改用行为式判据：对每个声明参数给两个不同值，若输出**逐位相同**
    才是真的死参数。这直接回答"我改了它，结果会不会变"这个真问题。

    返回 [(工具名, [(参数, 说明), ...]), ...]。
    """
    import lites_mcp as M

    # 每个工具一组：基准调用 + 每个参数的探针值对。
    # 探针值必须"物理上合理但明显不同"，否则会被 clamp / 饱和吃掉而误判。
    cases = {
        "lites_forward": (
            dict(device="qtf-commercial-decapped", x=1e-6, line_strength=1.2e-20,
                 L_gas_cm=100.0, T=296.0, P=1.0, gamma_L=0.06,
                 f_m=5000.0, mod_depth_cm1=0.3, f0_shift_ppm=0.0,
                 eta_spurious=0.0, power_mW=10.0),
            {"x": (1e-6, 5e-6), "line_strength": (1.2e-20, 6e-20),
             "L_gas_cm": (100.0, 500.0), "T": (296.0, 400.0),
             "P": (1.0, 0.5), "gamma_L": (0.06, 0.12),
             "f_m": (5000.0, 3000.0), "mod_depth_cm1": (0.3, 1.2),
             "f0_shift_ppm": (0.0, 2000.0), "eta_spurious": (0.0, 5e-4),
             "power_mW": (10.0, 40.0)},
        ),
        "lites_mdl": (
            dict(device="qtf-commercial-decapped", line_strength=1.2e-20,
                 L_gas_cm=100.0, T=296.0, P=1.0, gamma_L=0.06,
                 f_m=5000.0, power_mW=10.0, sigma_V=9.16e-6,
                 n_sigma=1.0, integration_s=10.0),
            {"line_strength": (1.2e-20, 6e-20), "L_gas_cm": (100.0, 500.0),
             "T": (296.0, 400.0), "P": (1.0, 0.5), "gamma_L": (0.06, 0.12),
             "f_m": (5000.0, 3000.0), "power_mW": (10.0, 40.0),
             "sigma_V": (9.16e-6, 4.58e-5), "n_sigma": (1.0, 3.0),
             "integration_s": (10.0, 100.0)},
        ),
        "lites_invert": (
            dict(device="qtf-commercial-decapped", v_2f_measured_V=4.4e-3,
                 line_strength=1.2e-20, L_gas_cm=100.0, T=296.0, P=1.0,
                 gamma_L=0.06, f_m=5000.0, power_mW=10.0, use_delta=True,
                 v_2f_baseline_V=0.0),
            {"v_2f_measured_V": (4.4e-3, 8.8e-3), "line_strength": (1.2e-20, 6e-20),
             "L_gas_cm": (100.0, 500.0), "T": (296.0, 400.0), "P": (1.0, 0.5),
             "gamma_L": (0.06, 0.12), "f_m": (5000.0, 3000.0),
             "power_mW": (10.0, 40.0), "use_delta": (True, False),
             "v_2f_baseline_V": (0.0, 1e-3)},
        ),
        "lites_review": (
            dict(device="qtf-commercial-decapped", x=1e-6, line_strength=1.2e-20,
                 L_gas_cm=100.0, T=296.0, P=1.0, gamma_L=0.06,
                 f_m=5000.0, mod_depth_cm1=0.3, power_mW=10.0, sigma_V=9.16e-6),
            {"x": (1e-6, 5e-6), "line_strength": (1.2e-20, 6e-20),
             "L_gas_cm": (100.0, 500.0), "f_m": (5000.0, 50000.0),
             "power_mW": (10.0, 40.0), "sigma_V": (9.16e-6, 4.58e-5)},
        ),
        "lites_noise_budget": (
            dict(device="qtf-commercial-decapped", bandwidth_Hz=100.0, v_rms_1f=2e-6,
                 c_in_F=1e-11, resp_V_per_C=1e12),
            {"bandwidth_Hz": (100.0, 1000.0), "v_rms_1f": (2e-6, 2e-5),
             "c_in_F": (1e-11, 1e-10), "resp_V_per_C": (1e12, 1e11)},
        ),
        "lites_resonance": (
            dict(device="qtf-commercial-decapped", delta_T_K=1.0, assume_f0=32757.4,
                 freq_error_pct=0.01),
            {"delta_T_K": (1.0, 20.0), "assume_f0": (10485.0, 9000.0),
             "freq_error_pct": (0.01, 0.5)},
        ),
    }

    def _fp(out):
        """把输出压成可比较的指纹（去掉路径/时间等非物理噪声）。"""
        return json.dumps(out, sort_keys=True, ensure_ascii=False,
                          default=str)[:100000]

    results = []
    for tool, (base, probes) in cases.items():
        fn = M.DISPATCH[tool]
        dead = []
        try:
            ref = _fp(fn(**base))
        except Exception as e:
            results.append((tool, [("<整体调用失败>", f"{type(e).__name__}: {e}")]))
            continue
        for pname, (v1, v2) in probes.items():
            outs = []
            err = None
            for v in (v1, v2):
                args = dict(base)
                args[pname] = v
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        outs.append(_fp(fn(**args)))
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
                    break
            if err:
                dead.append((pname, f"探针调用抛异常 → {err}"))
            elif outs[0] == outs[1]:
                dead.append((pname, "两个探针值的输出逐位相同 → 参数未生效"))
        results.append((tool, dead))
    del ref  # 仅用于提前暴露整体失败
    return results


def missing_effects(statuses=("off",)):
    return [e for e in EFFECTS if e["status"] in statuses]


def fidelity_summary():
    """供 MCP 返回给 AI 的结构化保真度报告。"""
    return {
        "implemented": [
            {"id": e["id"], "title": e["title"], "params": e["params"], "limit": e["limit"]}
            for e in EFFECTS if e["status"] == "on"],
        "optional": [
            {"id": e["id"], "title": e["title"], "params": e["params"], "limit": e["limit"]}
            for e in EFFECTS if e["status"] == "opt"],
        "not_implemented": [
            {"id": e["id"], "category": e["cat"], "title": e["title"], "impact": e["limit"]}
            for e in EFFECTS if e["status"] == "off"],
        "disclosure_rule": "对任何定量结论，必须告知：① 本次用了哪些已实现效应；"
                           "② 是否有未实现项会影响该结论（见 not_implemented）；"
                           "③ 不得把点值当作带误差的结果呈现。",
    }


def main():
    bad = 0
    print("=" * 74)
    print("lites-mcp 保真度审计（能力登记表 ↔ 源码证据 ↔ 参数行为可达性）")
    print("=" * 74)

    print("\n=== 1. 登记表证据一致性 ===")
    problems = audit_effects()
    if problems:
        bad += len(problems)
        for p in problems:
            print(f"  FAIL  {p}")
    else:
        print(f"  PASS  {len(EFFECTS)} 项效应的 evidence 全部在源码中找到")

    print("\n=== 2. 参数行为可达性（扰动后输出不变 = 死参数）===")
    for tool, dead in audit_parameters():
        if dead:
            bad += len(dead)
            print(f"  FAIL  {tool}: {len(dead)} 个参数扰动后输出无变化")
            for pname, why in dead:
                print(f"          · {pname}: {why}")
        else:
            print(f"  PASS  {tool}: 全部声明参数扰动均改变输出")

    print("\n=== 3. 已知缺口（必须向用户披露）===")
    offs = missing_effects()
    for e in offs:
        print(f"  [{e['cat']:10s}] {e['title']}")
    print(f"\n  共 {len(offs)} 项未实现；另有 "
          f"{len(missing_effects(('opt',)))} 项需显式开启")
    for e in missing_effects(("opt",)):
        print(f"  [opt/{e['cat']:6s}] {e['title']}  ← 参数 {e['params']}")

    print(f"\n===== 保真度审计：{'全部通过' if not bad else str(bad) + ' 项问题'} =====")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
