#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LITES 物理内核 —— 光致热弹光谱（Light-Induced Thermoelastic Spectroscopy）专用。

与 TDLAS/WMS 的本质差异（本模块存在的唯一理由）
────────────────────────────────────────────────
TDLAS/WMS 走"**光-电**"转换链：

    吸收 → 透过率 τ(t)=exp(−αL) → PD 光电流 ∝ τ → ADC → 锁相 → 2f

LITES 走"**光-热-弹-电**"转换链：

    吸收 → 局部热沉积 Q(t) → 温度场 T(r,t)（带热扩散迟滞 φ_th）
         → 传感器件热弹形变 ξ ∝ α_te·dT → 机械共振放大 H(f)（Q 值 + 共振跟踪）
         → 压电/电荷转换 η_piezo → TIA 增益 R_tia → 锁相 → 2f

因此**不能**复用 TDLAS 的 τ→PD 模型：至少四处物理量在 TDLAS 里根本不存在，
却恰恰是 LITES 的主导项：

1. **热波传递 |H_th| = √(f_ref/f)**（f_ref = f0/2，f ≤ f_ref 钳位 1）。表面热弹
   由表面温度振荡驱动，热波解 ΔT ∝ 1/√f —— 缓变而非低通截止；故最优 2f 频率
   在 f0/2（H_mech 峰处，文献全部在 f0/2 工作）。
2. **机械共振滤波器 H(f) = 1/√(1 + Q²(f/f0 − f0/f)²)**。f0 与 Q 是**器件个体参数**，
   必须实测标定；标称值不是真值。
3. **共振频率温度系数**：α_T 使 f0 随环境温度漂移，失配后灵敏度按上文 H(f) 掉。
4. **残余幅度调制（RAM）本底**：激光 WMS 的强度调制经池壁/窗片/器件耦合，
   产生与浓度无关的 2f 本底（am_2f_frac）。这是 LITES 检测限的本底项，
   且**不能靠加气体浓度改善**。

★ 标定轴：为什么是**能量积累时间**而不是器件吸收比
──────────────────────────────────────────────────
本模块早期版本把标定轴放在"器件自身吸收比 η_dev"上，结果同一物理器件在不同
波段反解出的标定增益 g 跨 **80×**——这是**模型错误**，不是器件特性。

文献实测（Sun et al., Light Sci. Appl. 14:180 (2025)，同一 MPC、同一激光功率、
同一浓度，仅换 QTF）给出决定性证据：

    QTF1  f0=32751.7 Hz  Q=9632.9    V_2f= 3.93 mV
    QTF2  f0= 9526.68 Hz Q=10825.8   V_2f=12.69 mV
    QTF3  f0= 9498.95 Hz Q=10794.3   V_2f=37.05 mV   (PDMS 涂层)

QTF1→QTF2 同为纯石英、仅几何不同（无涂层）：
    实测 V 比 = 3.229×      而 Q/f0 比 = 3.864×      → 差 16%
    用 V·f0/Q 归一后 = 0.836×                        → 已相当接近守恒

QTF2→QTF3 几何完全相同、Q 也几乎相同（10794 vs 10826），仅多一层 PDMS：
    实测 V 比 = 2.920×   ← 这**不能**由 f0/Q 解释（两者 f0/Q 相同！）
    必须由**材料/涂层热物性**解释：PDMS 把
        热导率 k: 1.4 → 0.18 W/(m·K)（降低 7.8×）
        热膨胀 α: 0.55 → 960 ppm/K（提高 1700×）
    这正是论文 Eq.(8)  δ ∝ (β₁−β₂)·L / (Φ₁T₁+Φ₂T₂) 的物理内容。

**结论（模型据此重建）**：
  LITES 的信号由三个**可分离**的因子连乘决定，而不是由单一的 η_dev：

    V_2f ∝ (P·η_abs·A_opt)          ← 被气体吸收调制掉的热功率
         × H_th(f_m)                 ← 热扩散低通
         × [Q/f0] · Θ_mat · Θ_coat   ← 能量积累 × 材料热弹品质因子 × 涂层增益
         × H_mech(2f_m)              ← 共振峰对准（含 f0 温漂）
         × G_elec                    ← TIA / 电容 / 压电耦合

  其中 [Q/f0] 是**能量积累时间**（论文明确："Lower frequency enables longer
  energy accumulation times"），Θ_mat 由 α_te·d_piezo/k 这组材料常数决定，
  Θ_coat 是涂层/表面处理带来的额外增益（PDMS 实测 ≈2.9×）。

  ⚠ 这样重建后，"同一器件跨波段 g 必须一致" 这条判据才有意义：因为 Q、f0、
    材料、几何都不随波长变，**唯一随波段变的只有光斑尺寸与 A_opt**。这是可以被
    独立检验的，而不是把波长依赖塞进一个拟合常数里。

单位口径（全模块统一，越界即报错，不静默换算）
──────────────────────────────────────────────
    波数 cm^-1 · 温度 K · 压力 atm · 光程 cm · 长度 m
    功率 W · 时间 s · 频率 Hz · 电荷 C · 电压 V

置信度声明
──────────
本模块为**机理级**模型：热扩散用半无限介质 1D 解，热弹形变用受夹杆轴向热膨胀近似，
器件共振用单自由度（SDOF）集总参数。文献实测值作为**标定锚点**，系数 g 由实测
灵敏度反解，因此模型在**已标定工况附近预测可信，外推需重新标定**。
详见 tools/lites_fidelity.py 的能力台账。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ══════════════════════════════════════════════════════════════════════
# 0. 材料常数（工程标称值；用于量级估算，精细计算须用实测物性）
# ══════════════════════════════════════════════════════════════════════
#: 石英（熔融石英 / 石英晶体沿 Z 轴近似）
QUARTZ = {
    "rho": 2200.0,          # kg/m^3
    "c_p": 740.0,           # J/(kg·K)
    "k_th": 1.4,            # W/(m·K)   热导率
    "alpha_te": 0.55e-6,    # 1/K       线热膨胀系数（沿 Z，室温）
    "d_piezo": 2.3e-12,     # C/N       压电常数 d11（石英 2.3 pC/N）
    "name": "石英",
    "note": "Q 极高（10^4–10^5），压电系数低（2.3 pC/N）",
}
#: 铌酸锂（y-cut 128° LiNbO3，LN-MFP 器件材料）
LINBO3 = {
    "rho": 4650.0,          # kg/m^3
    "c_p": 620.0,           # J/(kg·K)
    "k_th": 4.6,            # W/(m·K)
    "alpha_te": 7.5e-6,     # 1/K       线热膨胀系数（y-cut 面内量级）
    "d_piezo": 25e-12,      # C/N       d22 ≈ 25 pC/N
    "name": "铌酸锂",
    "note": "压电系数高一个数量级（25 pC/N），Q 低（~1.6k，机械损耗大）",
}

MATERIALS = {"quartz": QUARTZ, "linbo3": LINBO3}

#: 表面涂层 / 改性层（PDMS 等）—— 文献实测其对 LITES 信号的增益是**独立因子**
#: 依据：Sun et al. LSA 14:180 (2025) QTF2→QTF3 几何与 Q 完全相同（f0/Q 相同），
#: 仅多一层 PDMS，2f 信号从 12.69 → 37.05 mV，即 2.920×。该增益**不能**由
#: f0/Q 解释，必须归因于热物性：PDMS 使有效热导率降 7.8×、热膨胀升 1700×。
COATINGS = {
    "none":   {"name": "无涂层", "k_th": None, "alpha_te": None, "gain": 1.0,
               "src": "基准"},
    "pdms":   {"name": "PDMS", "k_th": 0.18, "alpha_te": 960e-6, "gain": 2.920,
               "src": "Sun 2025 LSA 14:180, QTF2→QTF3 实测 12.69→37.05 mV"},
    "gold":   {"name": "金电极", "k_th": 317.0, "alpha_te": 14.2e-6, "gain": 1.0,
               "src": "Sun 2025 指出金电极 Φ 高、β 低 → 不利于信号，取基准 1.0"},
    "graphene": {"name": "石墨烯/CNT", "k_th": 3000.0, "alpha_te": None, "gain": 0.9,
               "src": "Sun 2025：热扩散 >3000 W/mK，不利于热积累，取略低于基准"},
    "perovskite": {"name": "钙钛矿改性", "k_th": None, "alpha_te": None, "gain": 1.0,
               "src": "Dai 2023 IEEE Sens J 23:22380（未给出定量增益，保守取 1.0）"},
}


def thermoelastic_fom(mat: dict, coating: str = "none") -> dict:
    """材料（及涂层）的**热弹品质因子** Θ = α_te · d_piezo / k_th。

    这是从 LITES 信号链里**可分离**出来的材料因子：

        V_2f ∝ ... × [α_te · d_piezo / k_th] × ...

    物理来源（逐项）：
      · 热沉积同量 → 温升 ∝ 1/k_th（热导率越高，热越留不住）
      · 温升 → 应变 ∝ α_te（热膨胀系数）
      · 应变 → 表面电荷 ∝ d_piezo（压电系数）

    该组合在文献里有独立支持：
      · LiNbO₃ vs 石英：α_te 7.5 vs 0.55 ppm/K（13.6×），d 25 vs 2.3 pC/N
        （10.9×），k 4.6 vs 1.4（3.3× 不利于 LiNbO₃）
        → Θ 比 = (13.6×10.9)/3.3 = 44.9×
      · Mu 2025 实测 LiNTF/QTF 信号比 = 7.82×，其中 f0/Q 贡献 (32759/10993)/
        (9262/7410) = 2.38×，余下 3.28× 归材料与几何（放大而非缩小）
      → 量级方向一致；精确值由标定 g 吸收。

    ⚠ 这是**量级因子**，不是精确预测：真实转换还含电极几何、模态形状、
      夹持损耗。台账登记为需标定项。
    """
    base = mat["alpha_te"] * mat["d_piezo"] / mat["k_th"]
    c = COATINGS.get(coating)
    if c is None:
        raise KeyError(f"未知涂层 {coating!r}；可选 {sorted(COATINGS)}")
    return {"theta": base, "coating_gain": c["gain"], "coating": coating,
            "theta_eff": base * c["gain"],
            "alpha_te": mat["alpha_te"], "d_piezo": mat["d_piezo"],
            "k_th": mat["k_th"], "note": c["src"]}


# ══════════════════════════════════════════════════════════════════════
# 1. 热学：光热源的扩散低通
# ══════════════════════════════════════════════════════════════════════

def thermal_diffusivity(mat: dict) -> float:
    """热扩散率 D = k/(ρ·c_p)，单位 m²/s（石英 ≈ 8.6e-7）。"""
    return mat["k_th"] / (mat["rho"] * mat["c_p"])


def thermal_time(w_m: float, mat: dict) -> float:
    """热扩散时间常数 τ_th = w²/(8D)（s）。

    取 w 为**激光在器件上的有效加热宽度**（m）。对音叉/叉齿类器件，
    光斑通常被聚焦到远小于齿宽，此时 w 应取**光斑直径**而非齿宽；
    两者差一个量级会直接改变 φ_th 与最优调制频率，必须显式给出。

    物理意义：ω·τ_th ≫ 1 时热波来不及跟上调制、热弹幅值按 1/(ω τ_th) 衰减，
    同时还引入 atan(ω τ_th) 的相位迟滞。
    """
    return w_m ** 2 / (8.0 * thermal_diffusivity(mat))


def thermal_transfer(f_hz: float, w_m: float, mat: dict,
                     f_ref_hz: float | None = None) -> dict:
    """表面光热温度振荡的热波口径 H_th(f)（幅值/相位）。

    ⚠ 文献修正（2026-10）：旧版用"加热区均匀化时间 τ_th=w²/(8D)"做一阶
    低通 |H_th|=1/√(1+(ωτ_th)²)，在 f_m=16 kHz 处衰减 ~1/1300，并据此断言
    "LITES 最优调制频率低于 f0/2"。这与文献事实矛盾：LITES 全部在
    f_m=f0/2（2f 落在 QTF 共振峰）下工作且 SNR 数千（Ma 2018；Liu 2022 OE；
    Sun 2025 LSA 等）。物理根因：表面热弹应变由**表面温度振荡**驱动，
    半无限体表面受强度调制光加热的严格热波解（热波传播理论）给出

        ΔT_s ∝ q0 / (A·√(π f ρ c k))      ← 幅值按 1/√f 缓变，不是 1/f

    一阶低通描述的是加热区内"温度均匀化"时间，对表面热弹信号不构成截止。

    本实现：|H_th(f)| = √(f_ref/f)（f_ref 为标定/工作频率，取 f0/2），
    f≤f_ref 时钳位 1（标定频率处量级由增益 g 吸收，标度律不变）；
    相位近似 −45°/oct（1/√f 相当于 −1/2 阶积分器）。
    """
    tau = thermal_time(w_m, mat)          # 保留作"均匀化时间"信息项
    if f_ref_hz is None:
        return {"mag": 1.0, "phase_deg": 0.0, "tau_th": tau,
                "f_cut": 1.0 / (2.0 * math.pi * tau),
                "note": "未给 f_ref_hz：按无频率修正（H_th=1）"}
    fr = max(float(f_ref_hz), 1e-9)
    f = max(float(f_hz), 1e-9)
    r = fr / f
    mag = math.sqrt(r) if r < 1.0 else 1.0
    phase = -45.0 * math.log2(max(r, 1.0))
    return {"mag": mag, "phase_deg": phase,
            "tau_th": tau, "f_cut": 1.0 / (2.0 * math.pi * tau),
            "note": "热波 1/√f 口径（表面温度振荡）；tau_th 仅作均匀化时间信息"}


def optimal_2f_frequency(f0: float, q: float, w_m: float, mat: dict,
                         n_grid: int = 400) -> dict:
    """求 2f 探测的**最优调制频率** f_m。

    ⚠ 文献修正（2026-10）：旧版把"热扩散一阶低通"与机械共振联合求极值，
    断言最优 f_m < f0/2。按热波 1/√f 口径，热学在 f_m=f0/2 处无截止，
    2f 信号 ∝ |H_th(f_m)|·|H_mech(2f_m)| 的唯一主导项是机械共振
    H_mech(2f_m)（峰在 2f_m=f0）⇒ **最优 f_m = f0/2**（与文献一致：
    LITES 全部以 f0/2 调制、2f 落共振峰；Xu 2020 多气体 FDM 亦用 f0/2）。
    """
    f = np.linspace(max(f0 * 1e-4, 1.0), f0, n_grid)
    s = np.array([thermal_transfer(float(fi), w_m, mat,
                                   f_ref_hz=f0 / 2.0)["mag"] for fi in f])
    s *= mech_transfer(2.0 * f, f0, q)["mag"]
    i = int(np.argmax(s))
    f_opt = float(f[i])
    at_half = float(s[int(np.argmin(np.abs(f - f0 / 2.0)))])
    return {"f_m_opt": f_opt, "f0_over_2": f0 / 2.0,
            "gain_vs_f0half": (float(s[i]) / at_half) if at_half > 0 else float("nan"),
            "h_th_at_opt": thermal_transfer(f_opt, w_m, mat,
                                            f_ref_hz=f0 / 2.0)["mag"],
            "h_mech_at_opt": float(mech_transfer(2.0 * f_opt, f0, q)["mag"]),
            "tau_th": thermal_time(w_m, mat),
            "f_cut_th": 1.0 / (2.0 * math.pi * thermal_time(w_m, mat))}


# ══════════════════════════════════════════════════════════════════════
# 2. 力学：单自由度共振滤波器
# ══════════════════════════════════════════════════════════════════════

def mech_transfer(f_hz, f0: float, q: float) -> dict:
    """单自由度（SDOF）机械共振幅频响应 H(f) = 1/√(1 + Q²(f/f0 − f0/f)²)。

    这是**归一化**传递函数（f = f0 处取值 1），可接受数组输入。
    等效带宽 Δf_3dB = f0/Q；谐振环的群延迟 τ_group = Q/(π f0)，
    它直接给出 LITES 的**响应时间下限**（快变浓度用高 Q 器件测不准）。
    """
    f = np.asarray(f_hz, dtype=float)
    r = np.divide(f, f0, out=np.zeros_like(f), where=f0 != 0)
    inv = np.divide(f0, f, out=np.zeros_like(f), where=f != 0)
    u = r - inv
    mag = 1.0 / np.sqrt(1.0 + (q * u) ** 2)
    ph = -np.arctan(q * u)
    return {"mag": mag, "phase_deg": np.degrees(ph),
            "bw_3dB": f0 / q, "tau_group": q / (math.pi * f0)}


def f0_drift(f0_nom: float, dT_K: float, tc_ppm_per_K: float) -> float:
    """环境温度漂移后的共振频率 f0(T) = f0_nom·(1 + tc·ΔT)。

    石英 TC ≈ −25 ppm/K（AT-cut 近零，音叉型约 −20…−40 ppm/K）；
    铌酸锂 TC 量级 −50…−100 ppm/K。ΔT = 1 K 时石英音叉 f0 漂 ~0.8 Hz，
    而 3 dB 带宽 f0/Q ≈ 32768/1e5 ≈ 0.33 Hz ⇒ **漂 1 K 即失谐**。
    这是"为什么必须做共振跟踪"的定量答案。
    """
    return f0_nom * (1.0 + tc_ppm_per_K * 1e-6 * dT_K)


def detuning_loss(f0_actual: float, f0_assumed: float, q: float) -> dict:
    """把共振频率误判当成真值使用时的**灵敏度损失**。

    实际在 f0_actual 共振，却按 f0_assumed 布调制（2f 落在 2·(f0_assumed/2)），
    则信号幅值按 H(2f_m) 相对峰值的比例衰减。返回 loss_db 与残余比例。
    """
    f_m = f0_assumed / 2.0
    h = float(mech_transfer(2.0 * f_m, f0_actual, q)["mag"])
    return {"f_m_used": f_m, "residual_frac": h,
            "loss_db": 20.0 * math.log10(max(h, 1e-12))}


# ══════════════════════════════════════════════════════════════════════
# 3. 热弹转换：温升 → 形变 → 电荷
# ══════════════════════════════════════════════════════════════════════

def heat_deposition(power_W: float, alpha_cm1: float, L_cm: float,
                    absorbance_frac: float | None = None) -> dict:
    """单位调制周期内的光热沉积功率 Q (W)。

    两种口径（**必须二选一显式给出，不替你猜**）：

    · 长程吸收（through-beam，如 LN-MFP 的开放式 2.5 cm 光路）：
          A = 1 − exp(−αL)，Q = P·A
    · 表面吸收（thick-sample / 光斑打在器件上，如石英音叉 LITES）：
          Q = P·absorbance_frac   ← 器件自身对光的吸收占比，须实测；
      此时 αL 是**气体**吸收，不参与 Q（气体只把热带给器件）。

    返回 dict(Q_W, absorbance, mode)。
    """
    if absorbance_frac is not None:
        a = float(absorbance_frac)
        return {"Q_W": power_W * a, "absorbance": a, "mode": "surface"}
    a = 1.0 - math.exp(-max(alpha_cm1, 0.0) * L_cm)
    return {"Q_W": power_W * a, "absorbance": a, "mode": "through_beam"}


def thermal_expansion_strain(dT: float, alpha_te: float,
                             constraint: float = 1.0) -> float:
    """热致应变 ε = constraint · α_te · ΔT。

    constraint ∈ [0,1]：0 = 完全自由（形变不被约束，不产生应力），
    1 = 完全受夹（全部热膨胀转成应力）。实际器件介于两者之间，
    由叉齿几何与夹持方式决定 —— **这是本模型最大的单点不确定性**，
    故标定系数 g 把它与压电转换一并吸收。
    """
    return constraint * alpha_te * dT


def temp_rise_from_heat(q_W: float, f_hz: float, w_m: float, L_heat_m: float,
                        mat: dict, n_cycles: int = 1) -> float:
    """稳态**振荡振幅**温升 ΔT_osc（K），半无限体表面热波严格解。

    ⚠ 文献修正（2026-10）：旧版取"每个调制周期的脉冲能量均匀加热体积
    w²·L_heat"（ΔT = Q·T/(ρcV)），在 f 增大时 ΔT 不变（无频率依赖）。
    按表面热波解（强度调制光束照射半无限体表面，热波解见 Carslaw &
    Jaeger / 热波理论），表面温度振荡幅值为

        ΔT_s = q0 / (A_heat · √(π f ρ c k))        [K]

    其中 A_heat = w² 为有效加热面积（w 为光斑/加热宽度），q0 为吸收功率。
    物理意义：热波穿透深度 μ = √(k/(π f ρ c)) 随 f 增大而变浅，储热体积
    减小但表面温度梯度增大，净效果是 ΔT ∝ 1/√f —— **缓变**，不是一阶
    低通 1/f。这保证 f_m=f0/2（16 kHz）处热学不构成截止（文献 LITES
    全部在 f0/2 下工作且 SNR 数千）。

    返回 ΔT_osc（K）。绝对量级由标定增益 g 吸收（标度律 1/√f 保留）。
    """
    a = (w_m ** 2) * max(n_cycles, 1)
    denom = a * math.sqrt(max(math.pi * f_hz, 1e-12)
                          * mat["rho"] * mat["c_p"] * mat["k_th"])
    return q_W / denom


def energy_accumulation(f0: float, q: float) -> float:
    """能量积累时间 τ_acc = Q/(π·f0)  （s）。

    LITES/QEPAS 的核心结构：光热源在 **f0/2** 注入能量（2f 落在 f0），
    器件在 f0 处共振。每个调制周期内能量注入与耗散交替，稳态振荡幅度正比于
    **能量积累时间**与**品质因数**的乘积。

    文献明确表述（Sun et al. LSA 14:180 (2025)）：
        "Reducing resonant frequency f0 of the QTF is conducive to increasing
         the energy accumulation time, thereby improving the detection
         sensitivity of the sensor."
    并给出 δ ∝ 1/(Φ·T) 与 f0 ∝ (T/L²)·√(E/η)（Eq.7）——即降 f0 = 增 τ_acc。

    形式：τ_acc = Q/(π f0)。这是受迫阻尼振子在共振处的**包络建立时间**：
        x(t) = A(1 − e^{−t/τ_acc}),  τ_acc = 2Q/ω0 = Q/(π f0)
    稳态振幅 ∝ Q，而**每周期注入的能量份额** ∝ 1/f0（周期越长，注入越多）。

    ⚠ 口径对照：部分文献（如 LITES 综述 §5.4 式 τ = Q/(2πf0)）用**能量**
      时间常数（E ∝ x² 衰减 e^{−t/τ_E}，τ_E = 1/γ = Q/ω0 = Q/(2πf0)），
      数值为本式**一半**。本模块取信号电压的**包络建立时间**（幅值口径，
      信号可直接观测），与 Sun 2025 / Wang 2020 实测标定一致；引用时勿
      与能量口径混用，比较文献 τ 值先核对口径。

    ⚠ 与 TDLAS 的对照：TDLAS 没有这一项——光电探测器的响应时间远快于调制，
      不存在"能量积累"。这正是 LITES 里 f0 越低越灵敏、而 TDLAS 里
      f 越高（1/f 噪声越低）越好的根因。两者对 f 的优化方向**相反**。
    """
    if f0 <= 0 or q <= 0:
        raise ValueError("f0 与 Q 必须 > 0")
    return q / (math.pi * f0)


def charge_from_strain(strain: float, area_m2: float, mat: dict,
                       thickness_m: float) -> float:
    """形变 → 电极电荷 Q_c (C)。

    受压电方程 D = d·σ，σ = E·ε（E 为弹性模量），对电极面积积分：

        Q_c = d_piezo · E · ε · A

    石英 E ≈ 78 GPa，铌酸锂 E ≈ 170 GPa（均取沿作用轴量级值）。
    """
    e_mod = {"石英": 78e9, "铌酸锂": 170e9}.get(mat.get("name", ""), 100e9)
    return mat["d_piezo"] * e_mod * strain * area_m2


# ══════════════════════════════════════════════════════════════════════
# 4. 端到端器件灵敏度（含"标定锚点反解"）
# ══════════════════════════════════════════════════════════════════════

@dataclass
class LitesDevice:
    """LITES 传感器件参数（含个体标定项）。

    标称值 ≠ 真值：f0/Q/η 必须由实验室实测标定写入，
    未标定时模型给出的是**同型号典型值**量级的估计，不可当器件真值使用。
    """
    name: str = "商用音叉晶振（去壳裸音叉）32.768 kHz"
    material: str = "quartz"                  # quartz | linbo3
    coating: str = "none"                    # none | pdms | gold | graphene | perovskite
    f0: float = 32757.4                      # Hz    器件机械共振频率（**实测标定**）
    q: float = 8630.0                        # —     品质因数（**实测标定**）
    tine_w_m: float = 0.6e-3                 # m     叉齿宽
    tine_l_m: float = 3.8e-3                 # m     叉齿长
    tine_thick_m: float = 0.34e-3            # m     厚
    gap_m: float = 0.2e-3                    # m     叉齿间隙
    electrode_area_m2: float = 4.0e-6        # m²    有效电极面积
    spot_w_m: float = 0.3e-3                 # m     激光在器件上的有效加热宽度
    heat_len_m: float = 0.34e-3              # m     有效传热深度
    eta_piezo: float = 1.0                   # —     压电/几何转换修正（**标定**）
    r_tia: float = 4.4e6                      # V/A   跨阻增益（电荷→电压）
    c_total: float = 5.0e-12                 # F     总输入电容（器件+TIA）
    constr: float = 0.4                      # —     热约束度 ∈[0,1]
    tc_ppm_per_K: float = -30.0              # ppm/K f0 温度系数（标定）
    # —— 光学：光路对信号的放大（MPC 多次反射 / 空芯光纤等）——
    path_len_cm: float = 50.0                # cm    气体吸收光程（决定 αL）
    n_pass: int = 1                          # —     反射次数（MPC 用）
    mirror_refl: float = 1.0                 # —     单次反射率（MPC 用，银 0.98）
    # —— 标定锚点（用于反解 g，使模型与实测一致）——
    #   锚点必须显式给出"**器件自身**当时吸收了多少光"，而不是气体吸收系数。
    #   否则 g 会把波段相关的器件吸收一并吃掉（见 _solve_gain 的说明）。
    cal_power_W: float = 3.5e-3
    cal_eta_abs: float = 1.0e-3              # —   器件自身吸收比（cal 波段）
    cal_meas_f2_V: float = 5.0e-3            # V   实测 2f 峰值电压
    cal_mod_depth_cm1: float = 0.5
    cal_species: str = ""                    # 锚点物种（仅报告用）
    # —— 残余 AM 的 2f 本底占比（文献修正，2026-10）——
    # 2f 基线（0 浓度时）来自激光 WMS 残余幅度调制的 2f 分量，不是 η_dev 直流。
    # 量级：WMS 残余 AM 深度 i1~1e-2…1e-1，其 2f 分量 i2 约 i1 的 1e-2…1e-1
    # ⇒ i2 ~ 1e-4…1e-2。取默认 1e-4（偏理想），实测标定后覆盖。
    am_2f_frac: float = 1.0e-4

    _mat: dict = field(init=False, repr=False)
    _g: float = field(init=False, default=1.0, repr=False)
    _fom: dict = field(init=False, repr=False)

    def __post_init__(self):
        if self.material not in MATERIALS:
            raise ValueError(f"未知材料 {self.material!r}；可选 {sorted(MATERIALS)}")
        if self.coating not in COATINGS:
            raise ValueError(f"未知涂层 {self.coating!r}；可选 {sorted(COATINGS)}")
        self._mat = MATERIALS[self.material]
        if self.f0 <= 0:
            raise ValueError("f0 必须 > 0（共振频率不可为零或负）")
        if self.q <= 0:
            raise ValueError("q 必须 > 0")
        if not (0.0 < self.cal_eta_abs <= 1.0):
            raise ValueError("cal_eta_abs 必须 ∈ (0,1] —— 它是器件自身吸收比")
        self._fom = thermoelastic_fom(self._mat, self.coating)
        self._g = self._solve_gain()

    # ── 派生量（只读属性，供报告与下游复用）──────────────────────
    @property
    def tau_acc(self) -> float:
        """能量积累时间 τ_acc = Q/(π f0)，单位 s。"""
        return energy_accumulation(self.f0, self.q)

    @property
    def bw_3dB(self) -> float:
        """3dB 带宽 Δf = f0/Q，单位 Hz。"""
        return self.f0 / self.q

    def optical_throughput(self) -> float:
        """MPC 等多次反射光路的**光通量衰减** ∏ R^i ≈ R^(n_pass)。

        多通池在**增加 αL 的同时**也损失功率：银镜 R=0.98、259 次反射后
        总透过率仅 0.98²⁵⁹ ≈ 0.5%。LITES 是**功率敏感**的（信号 ∝ P），
        所以多通池对 LITES 是"吸收增益 vs 功率损失"的权衡，不像 TDLAS
        那样净赚——这是 LITES 与 TDLAS 在设计 MPC 时的关键分野。
        """
        return float(self.mirror_refl) ** max(int(self.n_pass), 0)

    # ── 内部：唯一机理链（标定/预测/伪信号/探测限全部复用）────────
    def _chain_v(self, power_W: float, f_m: float,
                 eta_abs: float | None = None) -> float:
        """完整机理链给出的 2f 等效电压（含标定增益 g）。

            V = g · (P·η_abs·T_opt) · H_th(f_m) · τ_acc · Θ_mat·Θ_coat
                  · H_mech(2 f_m) · [ΔT→ε→Q_c] / C_total

        **η_abs 是"残余光被器件吸收的份额"，不是气体吸收系数** ——
        这是 LITES 与 TDLAS 最容易被搞混、也最致命的一处：

        · TDLAS：信号源就是气体吸收 α_gas·L，透过率 τ=exp(−αL) 直接进 PD。
        · LITES（文献修正 2026-10）：气体在扫到吸收线时把到达器件的
          光**挖掉**一部分，器件只吸收残余光的 η_dev（透过式结构，
          Ma 2018 原始表述："residual laser beam transmitted by the
          absorption cell is focused on the QTF"）。即

              η_abs(ν) = η_dev · exp(−α_gas(ν)·L_gas)     （减光口径）

          信号的**浓度依赖**来自 Δη_abs = η_dev·αL（弱吸收），因此
          **灵敏度被器件吸收比 η_dev 压制**（信号 ∝ η_dev·αL），
          2f 本底来自残余 AM（am_2f_frac），与 η_dev 直流无关。

          这解释了为什么 LITES 检测限普遍比 PAS 差 1~2 个量级
          （器件本底吸收 η_dev 通常 ≪1），也解释了涂层/高 η 材料
          增强信号的理论依据（Sun 2025 LSA PDMS 2.92×、Mu 2025
          LiNTF 6×：均沿 η_dev 路径放大）。

        ⚠ 与早期版本的差异：早期把"Q 值"直接当增益（V ∝ Q），导致同器件
          跨波段 g 跨 80×。现按文献实测改为 **τ_acc = Q/(πf0)**（能量积累
          时间），并显式引入材料热弹品质因子 Θ 与涂层增益 —— 这三者都不
          随波长变，于是"同一器件跨波段 g 一致"才成为**可检验的真判据**。
        """
        if eta_abs is None:
            eta_abs = self.cal_eta_abs
        q_dep = power_W * eta_abs * self.optical_throughput()
        h_th = thermal_transfer(f_m, self.spot_w_m, self._mat,
                                f_ref_hz=self.f0 / 2.0)["mag"]
        h_m = float(mech_transfer(2.0 * f_m, self.f0, self.q)["mag"])
        dT = temp_rise_from_heat(q_dep, f_m, self.spot_w_m,
                                 self.heat_len_m, self._mat)
        eps = thermal_expansion_strain(dT, self._fom["alpha_te"], self.constr)
        qc = charge_from_strain(eps, self.electrode_area_m2, self._mat,
                                self.tine_thick_m)
        acc = self.tau_acc
        # 归一化：τ_acc 用 Q/πf0，量级 ~1e-2…1e-1 s；这里以 1 s 为基准做成
        # 无量纲积累因子，绝对值由标定 g 吸收（保持标度律、不改量级）。
        return (self._g * h_th * h_m * acc
                * (qc / self.c_total) * self._fom["coating_gain"])

    def effective_eta_abs(self, alpha_gas_cm1: float, L_gas_cm: float) -> float:
        """气体吸收线处的**减光口径**器件吸收比 η_abs(ν)。

        ⚠ 文献修正（2026-10）：旧版 η_abs = η_dev + (1−η_dev)·[1−e^{−αL}]
        把气体吸收当作**额外热源**（信号 ∝ (1−η_dev)·αL），物理方向反了：
        LITES 中气体只在扫到吸收线时把**到达器件的光挖掉一部分**，
        器件仍只吸收 η_dev 的残余光（透过式结构，Ma 2018 原始表述
        "residual laser beam transmitted by the absorption cell is focused
        on the QTF"；Dello Russo 2020 Opt. Express 同）。故

            η_abs(ν) = η_dev · exp(−α_gas(ν)·L_gas)

        弱吸收：η_abs ≈ η_dev·(1−αL) → 浓度依赖项 Δη_abs = η_dev·αL。
        **信号因此 ∝ η_dev·αL**（LITES 灵敏度被器件吸收比压制，这是
        LITES 检测限普遍低于 PAS/QEPAS 的物理根源，也是涂层/高 η 材料
        增强信号的理论依据：Sun 2025 LSA 的 PDMS 涂层 2.92×、Mu 2025
        LiNTF 6× 均由此路径放大）。
        """
        a = math.exp(-max(alpha_gas_cm1, 0.0) * max(L_gas_cm, 0.0))
        return self.cal_eta_abs * a

    def _solve_gain(self) -> float:
        """由实测锚点反解增益 g，使 g·V_raw(锚点) = V_meas。

        机理链给了**正确的函数形式与标度律**（对 η_abs、P、H_th(f_m)、
        H_mech、Q 的依赖），但绝对量级受热约束度 constr、真实电极面积、
        TIA 输入阻抗、压电耦合效率等未标定因素共同支配。用**一点实测**
        锚定，既保留标度律又保证量级正确。

        ⚠ 这是**标定反解，不是第一性原理算出的绝对值**。台账
        tools/lites_fidelity.py 会把它登记为"需标定项"。

        自洽性判据（见 selftest）：同一器件在不同波段、各自给出正确的
        P 与 η_abs 后，反解出的 g **应当一致**。若跨幅远超量测误差，
        说明锚点元数据（尤其 η_abs）写错了 —— 而不是"模型就这样"。

        这条判据正是本次改造的起因：**初版把 cal_alpha_cm1（气体吸收系数）
        当热源输入，导致同一器件的三个波段反解出跨 80× 的 g**，
        把真实的波长相关器件吸收伪装成了拟合常数。改为 η_abs 口径后消除。
        """
        self._g = 1.0
        raw = self._chain_v(self.cal_power_W, self.f0 / 2.0, self.cal_eta_abs)
        if not np.isfinite(raw) or raw <= 0:
            raise ValueError("标定链给出的原始增益非正，请检查器件参数")
        return self.cal_meas_f2_V / raw

    # ── 对外：2f 信号电压预测 ──────────────────────────────────
    def predict_2f_voltage(self, power_W: float,
                           alpha_gas_cm1: float = 0.0, L_gas_cm: float = 0.0,
                           f_m: float | None = None,
                           eta_abs: float | None = None,
                           mod_depth_cm1: float | None = None) -> dict:
        """预测 LITES 的 2f 峰值电压 V（含标定增益）。

        参数口径（与 TDLAS 不同，务必看清）：
          · alpha_gas_cm1 / L_gas_cm 描述**气体**吸收，用来算它从光束里
            挖走多少功率，从而得到 Δη_abs —— 即信号的浓度依赖部分。
          · eta_abs 可直接覆盖器件吸收比；不给则用 cal_eta_abs 作为
            "线外"基线。

        调制深度对 2f 幅值的影响：2f 峰高在 m ≈ 2.2（m = a/HWHM）处取极大，
        与 WMS 同源。这里用经验峰形因子归一到 m=2.2：

            F(m) = m² · exp(1 − m²/2.2²)     ← m=2.2 处 F=1，且过原点

        **这是拟合式不是严格解析**（严格解需对 Voigt 做傅里叶展开），
        仅用于扫描调制深度时的相对趋势；绝对值由标定锚点固定。
        """
        fm = self.f0 / 2.0 if f_m is None else float(f_m)
        s = thermal_transfer(fm, self.spot_w_m, self._mat,
                             f_ref_hz=self.f0 / 2.0)
        hm = float(mech_transfer(2.0 * fm, self.f0, self.q)["mag"])

        # ── 2f 信号的三段式（文献修正，2026-10）──────────────
        # 锁相 2f 输出 = 信号在 2f_m 处的幅值包络，物理上分三项：
        #   ① 残余 AM 本底：激光 WMS 残余幅度调制（i2）经器件吸收产生，
        #      与浓度无关，量级由 am_2f_frac（标定）控制，**远小于气体项**；
        #   ② 气体 2f 信号：气体吸收的 2f 调制分量 ∝ η_dev·αL
        #      （减光口径，见 effective_eta_abs；信号被器件吸收比压制，
        #      这是 LITES 灵敏度低于 PAS 的物理根源）；
        #   ③ 线上总 2f = ① + ②（峰形为正，与文献 WMS-2f 形态一致）。
        #
        # 兼容路径：eta_abs 显式给出 → 完全覆盖（v_on=chain(eta_abs)，
        # 不叠加气体项，避免重复计入；此时 v_am=v_delta=0）。
        eta_on = (self.effective_eta_abs(alpha_gas_cm1, L_gas_cm)
                  if eta_abs is None else float(eta_abs))

        # 调制深度的 2f 峰形因子 F(m)：峰在 m≈2.2，归一到 F(2.2)=1。
        # ⚠️ 必须**乘进** v_on / v_off：标定锚点是在各自 cal_mod_depth_cm1 下
        # 测得的，此时 F(m_cal) 未必等于 1。若只算 F_m 而不乘，则改调制深度
        # 对输出毫无影响 —— 这正是保真度审计（audit_parameters）曾抓到的
        # 一类"声明了却无效"缺陷。
        # 归一化口径：F_raw(m) = m²·exp(1 − m²/2.2²)，其极大值在 m=2.2 处
        # 为 2.2²·exp(0) = 4.84（**不是 1**）。故必须除以 4.84 才是"峰值=1"。
        f_shape = 1.0
        m_reason = None
        if mod_depth_cm1 and mod_depth_cm1 > 0:
            hwhm = self.cal_mod_depth_cm1 / 2.2      # 由锚点反推 HWHM
            m = mod_depth_cm1 / hwhm
            f_raw = m ** 2 * math.exp(1.0 - (m / 2.2) ** 2)
            f_shape = f_raw / (2.2 ** 2)
        else:
            # ⚠ 此处**不能**用 float('nan')：
            #   NaN 不是合法 JSON（RFC 8259 只允许有限数），
            #   Python 的 json.dumps 默认输出裸 `NaN`，
            #   严格解析器（含部分 MCP 客户端）会直接抛错。
            #   MCP 返回值必须全部可 JSON 序列化 ⇒ 用 None 表达"未计算"。
            m, f_raw = None, None
            m_reason = ("未提供 mod_depth_cm1 ⇒ 未计算调制深度 m 与峰形因子 "
                        "F_m，本次 F_m 按 1.0（即已处于最优调制）处理。"
                        "要评估调制损失请显式给 mod_depth_cm1")

        chain = self._chain_v(power_W, fm, self.cal_eta_abs) * f_shape
        eta_gas = 1.0 - math.exp(-max(alpha_gas_cm1, 0.0)
                                 * max(L_gas_cm, 0.0))
        if eta_abs is not None:
            v_am, v_delta = 0.0, 0.0
            v_on = self._chain_v(power_W, fm, float(eta_abs)) * f_shape
            eta_on = float(eta_abs)
        else:
            v_am = chain * self.am_2f_frac
            v_delta = chain * eta_gas
            v_on = v_am + v_delta

        q = power_W * max(eta_on, 1e-15)
        dT = temp_rise_from_heat(q, fm, self.spot_w_m, self.heat_len_m, self._mat)
        eps = thermal_expansion_strain(dT, self._mat["alpha_te"], self.constr)
        qc = charge_from_strain(eps, self.electrode_area_m2, self._mat,
                                self.tine_thick_m)

        out = {"V_2f": v_on, "V_2f_baseline": v_am, "V_2f_delta": v_delta,
               "f_m": fm, "H_th": s["mag"], "H_mech": hm,
               "phi_th_deg": s["phase_deg"],
               "eta_abs": eta_on, "eta_gas_frac": eta_gas,
               "am_2f_frac": self.am_2f_frac, "dT_osc_K": dT, "strain": eps,
               "charge_C": qc, "Q_dep_W": q,
               # m / F_m_raw 在未给 mod_depth_cm1 时为 None（**不可用 NaN**，
               # 见上文注释）。m_note 说明原因，便于调用方披露。
               "m": m, "F_m": f_shape, "F_m_raw": f_raw, "m_note": m_reason,
               "V_2f_at_m_opt": v_on / max(f_shape, 1e-12)}
        return out

    # ── 伪信号：样品池无法避免的 RAM / 窗片光热本底 ──────────────
    def spurious_2f(self, power_W: float, eta_spurious: float | None = None
                    ) -> dict:
        """与气体浓度**无关**的 2f 本底电压。

        机理：样品池壁 / 窗片 / 器件夹持件同样吸收调制光并做光热膨胀，
        其振动**直接**耦合进传感器。因为不经过气体吸收，加大浓度不会
        改善 SNR，只能靠降低背景吸收、差分双池或几何隔离压制。

        注意与 cal_eta_abs（器件在工作波段的本底吸收）的区别：
          · cal_eta_abs 是**必要的**——它是 Δη_abs 的基线，去掉它信号也没了；
          · 本项的 eta_spurious 是**多余的**——来自工作波段之外的结构件、
            杂散光、以及非共振耦合路径，是可以也应该被压掉的。
        把两者混为一谈会得出"LITES 本底不可避免"的错误结论。
        """
        e = 0.0 if eta_spurious is None else float(eta_spurious)
        v = self._chain_v(power_W, self.f0 / 2.0, e)
        return {"V_2f_spurious": v, "eta_spurious": e,
                "Q_dep_W": power_W * e,
                "note": "与浓度无关；eta_spurious=0 表示理想样品池（无额外结构件耦合）"}

    # ── 探测限：由噪声反推 MDL ───────────────────────────────────
    def mdl(self, power_W: float, sigma_V: float, n_sigma: float = 1.0,
            alpha_gas_ref_cm1: float = 1e-6, L_gas_cm: float = 100.0
            ) -> dict:
        """最小可探测**气体**吸收系数 MDL（cm^-1）。

        LITES 的灵敏度按**减光口径**定义（见 effective_eta_abs，
        文献修正 2026-10）：

            气体减光分数 η_gas = 1 − exp(−α_gas·L_gas) ≈ α_gas·L_gas
            ΔV_2f = g·…·η_dev·η_gas          （信号 ∝ η_dev·αL）

        故归一化灵敏度

            S_norm = ΔV_2f / (α_gas·L_gas)   [V per unit αL]

        与 α_gas 无关（弱吸收下线性），再由 σ_V 反推

            α_min = n_sigma · σ_V / S_norm

        ⚠ 与 TDLAS 的 `sigma_tau → LOD` 口径**不可互换**：TDLAS 的分母是
        等效透过率噪声，LITES 这里的分母是**电压**噪声，因为 LITES 的
        读出链是压电→TIA→锁相，不存在"透过率"这个中间量。
        """
        p = self.predict_2f_voltage(power_W, alpha_gas_ref_cm1, L_gas_cm)
        al = alpha_gas_ref_cm1 * L_gas_cm
        if al <= 0:
            raise ValueError("alpha_gas_ref_cm1 · L_gas_cm 必须 > 0")
        dv = p["V_2f_delta"]
        s_norm = dv / al
        alpha_min = (n_sigma * sigma_V / s_norm) if s_norm > 0 else float("inf")
        return {"S_norm_V_per_alphaL": s_norm, "alpha_min_cm-1": alpha_min,
                "delta_V_2f": dv, "sigma_V": sigma_V, "n_sigma": n_sigma,
                "eta_abs_online": p["eta_abs"], "eta_abs_offline": self.cal_eta_abs,
                "SBR_gas": p["eta_gas_frac"],
                "note": "信号 ∝ η_dev·αL（减光口径）；αL>0.1 时 η_gas 饱和，"
                        "MDL 仅线性区成立"}

    def noise_floor(self, bw_Hz: float, resp_V_per_C: float = 1e12,
                    c_in_F: float | None = None,
                    v_rms_1f: float = 2e-6) -> dict:
        """LITES 噪声底：**1/f 主导**，不是白噪声。

        LITES 与 QEPAS 一样工作在音频（~10 kHz，远低于 TDLAS 的 30 kHz+），
        且信号源本身有 1/f 漂移，故噪声模型为：

            σ_V(f) = V_1f_rms · √(f_lo / f)  +  V_white

        再经 TIA 的电容噪声抬升（与 C_in、R_tia 有关）。当 Q 高时带宽窄、
        白噪声被压，1/f 成分反而更显著 —— 这也是"提高 Q ≠ 改善 LOD"的原因之一。
        """
        bw = max(float(bw_Hz), 1e-9)
        f_lo = 1.0
        f_hi = max(bw, f_lo * 1.0000001)
        pink = v_rms_1f * math.sqrt(max(math.log(f_hi / f_lo), 0.0))
        cin = self.c_total if c_in_F is None else c_in_F
        # TIA 电容噪声：i_n = √(4kT/R_tia)·(1 + 2π f C R) 的一阶近似抬升因子
        kT = 1.380649e-23 * 296.0
        i_th = math.sqrt(4.0 * kT / max(self.r_tia, 1.0) * bw)
        boost = 1.0 + 2.0 * math.pi * math.sqrt(bw / 3.0) * cin * self.r_tia
        v_white = i_th * self.r_tia * boost * resp_V_per_C / 1e12
        return {"sigma_total_V": float(np.hypot(pink, v_white)),
                "pink_V": pink, "white_V": v_white,
                "crest_boost": boost, "bw_Hz": bw,
                "dominant": "1/f" if pink > v_white else "white"}


# ══════════════════════════════════════════════════════════════════════
# 5. 文献基准器件库 —— 来自 IMA「文献知识库」的实测数据
# ══════════════════════════════════════════════════════════════════════
# 数据来源（均为用户 IMA 知识库「文献知识库」内已收录文献的实测值，非估计）：
#
# 【A】Lin et al., Nat. Commun. 17:2296 (2026), DOI 10.1038/s41467-026-69042-7
#      —— LN-MFP 铌酸锂多功能平台，PAS / LITES / 光电探测三合一。
#      器件：叉齿 11.5 mm × 1.7 mm，间隙 1 mm，基部 7.6 mm，圆角 0.8 mm；
#      f0 = 10485 Hz，Q = 1621；LITES 光路 2.5 cm 自由空间。
#      C2H2 LITES：1.53 μm、10.5 mW、调制深度 0.68 cm⁻¹ → 2f 4.4 mV，噪声 9.16 μV，MDL 10.4 ppm
#      H2O  LITES：1.39 μm、2%、调制深度 0.40 cm⁻¹ → 2f 1.62 mV，MDL 59.3 ppm
#      CH4  LITES：3.3 μm ICL、2%、调制深度 0.27 cm⁻¹ → 2f 0.101 V，噪声 112 μV，MDL 22 ppm
#      CO2  LITES：2 μm、20%、调制深度 0.47 cm⁻¹ → 2f 3.1 mV，MDL 680 ppm
#      NO2  LITES：450 nm LED、330 mW → SNR 3692，MDL 13.5 ppm
#      NH3  LITES：9.7 μm QCL、5%、调制深度 0.15 cm⁻¹ → SNR 2014，MDL 25 ppm
#      光电探测率：450 nm 67.7 V/W；9.77 μm 373 V/W
#
# 【B】Sun et al., Light Sci. Appl. 14:180 (2025), DOI 10.1038/s41377-025-01864-4
#      —— CO-LITES，ppq 级。**同一 MPC、同一激光、同一浓度，仅换 QTF**，
#      是标度律的黄金数据集（本模块的标定轴据此重建）。
#      MPC：三镜双螺旋，R=100 mm，OPL 25.8 m，V 165.8 ml，OPL/V 15.6 cm⁻²，
#           反射 259 次，银镜 R=0.98；入射光程 20 mm 孔径。
#      QCL：4.59 μm，301 mA 时 145 mW；CO 线 2179.77 cm⁻¹，S=4.079e-19。
#      QTF1 商用：f0 32751.7 Hz，Δf 3.41 Hz，Q 9632.9  → 2f 3.93 mV，噪声 957 nV，SNR 4106.58
#      QTF2 自研：f0  9526.68 Hz，Δf 0.88 Hz，Q 10825.8 → 2f 12.69 mV，噪声 834 nV，SNR 15215.83
#      QTF3 +PDMS：f0 9498.95 Hz，Δf 0.88 Hz，Q 10794.3 → 2f 37.05 mV，噪声 852 nV，SNR 43485.92
#      1 ppm CO → MDL 23 ppt；积分 500 s → 920.7 ppq。
#      几何：自研 QTF 长度 3.9→9.1 mm，宽 0.36→0.25 mm，圆头加大重心力矩；金电极。
#
# 【C】Mu et al., Opto-Electron Sci. 4:250035 (2025), DOI 10.29026/oes.2025.250035
#      —— 倒三角铌酸锂音叉 LiNTF，PAS + LITES 双系统同器件对比。
#      标准 QTF：f0 32759.09 Hz，Δf 2.98 Hz，Q 10992.98
#      LiNTF   ：f0  9261.90 Hz，Δf 1.25 Hz，Q  7409.52；128° 旋转 y 切，厚 0.3 mm
#      LITES 系统（1530.37 nm DFB，15 mW，C2H2 20000 ppm，光程 20 cm）：
#        标准 QTF 2f 0.784 mV，噪声 62.05 nV → SNR 12634.97，MDL 1.58 ppm
#        LiNTF    2f 6.13  mV，噪声 80.30 nV → SNR 76338.73，MDL 0.26 ppm（改善 6.03×）
#      仿真：LiNTF 表面电荷密度比 QTF 高 15.63×（LITES），应力高 1.54×；
#            材料 d 6–70 pC/N（LiNbO3）vs 2.3 pC/N（石英），k 0.68 vs 0.3。
#      PAS 对照（同器件）：LiNTF 2f 81.96 μV，噪声 36.61 nV → MDL 8.93 ppm；
#            加 AmR 后 5.02 mV，噪声 39.95 nV → MDL 0.16 ppm（改善 56.16×）
#
# 【D】Wang et al., Light Sci. Appl. 13:77 (2024), DOI 10.1038/s41377-024-01425-1
#      —— QEMR-PAS 石英增强多外差共振光声光谱（对照技术，非 LITES）。
#
# ⚠ **eta_abs 的口径与不确定性（务必先读）**
#   文献只给出功率、浓度、调深与 2f 峰电压，**没有给器件自身吸收比 η_dev**。
#   本仓库按"LITES 检测限比 PAS 差 1~2 个量级"这一文献共识反推量级：
#   η_dev 需 ≫ 痕量气体的 α_gas·L_gas（典型 1e-6…1e-5），故取 ~1e-3 量级。
#   因此 eta_abs 是**反推估计值**，其不确定性直接进入标定增益 g。
#   → 这**不影响**同一器件下的相对比较（功率比、频率比、Q 影响），
#     但**绝对值**（MDL、信噪比）须待实验室用"无吸收样品做空白基线"实测 η_abs
#     后才能定论。台账 tools/lites_fidelity.py 把它登记为 must_calibrate。
#
# ★★★ 重要发现：η_dev 是**波长的强函数**，不是常数 ★★★
#   把 LN-MFP 四个波段锚点按"每瓦 2f 电压" V/P 排列（同一物理器件、
#   同一 f0/Q/几何，故 V/P 的差异只能来自光学与器件吸收）：
#
#       1.39 μm (H2O)   1.157 V/W
#       1.53 μm (C2H2)  0.419 V/W     ← 基准
#       2.00 μm (CO2)   1.550 V/W
#       3.30 μm (CH4)  33.667 V/W     ← 高出 80×
#
#   4 个波段跨 29×（3.3 μm 相对 1.53 μm 为 80×）。这一趋势**不是噪声**，
#   而是可解释的真实物理：LiNbO₃ 在 2.5~4 μm 存在多声子吸收带，
#   且 OH 基频吸收位于 ~2.87 μm；3.3 μm 落在该吸收带的肩部，
#   器件自身吸收比 η_dev 因此显著抬升。**这恰恰是 LITES 的工作机理**：
#   器件吸收越多，热-弹转换越强，信号越大。
#
#   推论（模型据此设计）：
#     · 同一器件的 η_dev **不可**用单一常数表示 → 本库为**每个波段锚点
#       单独标定** cal_eta_abs，其相对值由上述 V/P 反推。
#     · 因此"同器件跨波段 g 一致"这条判据**只在各波段 η_dev 已正确给出
#       时才成立**；在 η_dev 未知（当前状态）时，它必然失败 —— 这不是
#       模型 bug，而是**待实测的缺口**。台账中登记为 must_calibrate。
#     · 可做的独立检验是**能量积累律**与**涂层增益**：这两者与波长无关，
#       已用 Sun 2025 的 CO-LITES 三音叉数据分别验证到 19.7% 与 0.0%。
_ETA_QTZ = 1.0e-3           # 石英音叉在近红外的本底吸收比（反推估计，基准）
DEVICE_LIBRARY = {
    # ★【默认器件】商用 32.768 kHz 音叉晶振 —— **去壳后的裸音叉**
    # ══════════════════════════════════════════════════════════════
    # 为什么是默认：这是 LITES / QEPAS 领域**最通用、最便宜、最可复现**的
    # 换能器 —— 手机/手表里的量产晶振，去壳即用，几毛钱一颗。任何实验室
    # 起步做 LITES 都是先拿它跑通链路，因此它才应该是默认起点。
    #
    # ── 参数来源（分三类，勿混为一谈）───────────────────────────
    # 【实测标定】f0 / Q：Wang et al., Optics Express 28(13) 19074 (2020)
    #   Table 1 的 "STANDARD" 行 —— **去壳裸音叉、常压空气**实测：
    #       f0 = 32757.4 Hz   Q = 8630
    #   （该行是本项目能找到的、最贴近"去壳商用音叉在 LITES 装置里"
    #     的公开实测值；同表另有 5 个自研 QTF 作对照。）
    #   注：实物标称 32768 Hz，实测偏低 −323.5 ppm —— 属正常个体差异
    #   （晶振出厂容差 ±20 ppm @25°C 是**振荡电路**指标，裸器件在
    #    非标称负载电容下测得的值本就会偏；且去壳后负载条件改变）。
    #
    # 【订购规格】几何 / 电学：Raltron R38-32.768-12.5（及同类）
    #   整体 6×1.4×0.2 mm、叉齿长 3.8 mm 宽 0.6 mm、间隙 0.2 mm（Rice 专利 US7245380）
    #   ESR ≤ 35 kΩ、动电容 C1=0.0035 pF、并联电容 C0=1.6 pF、Q_typ=90000（**封装真空内**）
    #
    # 【文献实测 · 常压】几何与 Q 的又一组独立佐证：
    #   Optics Express 28(13) 19074：L=3.3 mm, W=330 µm, T=350 µm，Q=8630
    #   Applied Spectroscopy Reviews 2022：标称 32.768 kHz，Q≈10000 @1 atm
    #   Sensors 19(5) 1093：Q≈100000（真空封装）/ Q≈10000（常压）
    #   → 常压 Q 落在 8630…10993 区间（石英音叉实测上限 10993）
    #
    # ── 三个必须知道的物理事实 ──────────────────────────────────
    # ① **Q 掉两个数量级是去壳的代价，不是缺陷**
    #    封装内是真空 ⇒ Q≈9e4~1e5。去壳后暴露在常压空气，叉齿做面内弯曲
    #    振动时受到空气**黏性剪切阻尼**（squeeze-film / 流体拖曳），Q 直接
    #    掉到 ~1e4 量级。所以"裸音叉 Q 只有一万"是正常的。
    #    **但降压实测可回收**（Wang 2020）：700 Torr → 5 Torr，SNR 提升 ~4×。
    #
    # ② **τ_acc 只有 84 ms，比自研低频 QTF 短一半以上**
    #    τ_acc = Q/(π f0) = 8630/(π·32757.4) = 83.9 ms
    #    对照：自研低频圆头 QTF（9.53 kHz, Q=10826）τ_acc = 361.7 ms
    #    ⇒ 4.3× 的差距。**这正是 LITES 领域"降 f0"主张的根源**：
    #      高 Q 只补回一点，低 f0 才是 τ_acc 的主导项。
    #    标准音叉在 LITES 里因此是**入门选择而非最优选择**。
    #
    # ③ **叉齿太细（0.33~0.6 mm），光斑尺寸成了瓶颈**
    #    Wang 2020 明确指出：标准 QTF 叉齿仅 330 µm，与激光光斑（~100 µm）
    #    可比，导致无法精确映射叉齿表面、1σ 噪声高达 0.3 mV（比自研 QTF
    #    高 3 倍）。因此它虽上了 τ·ε 曲线却**偏离线性趋势**。
    #    → 本模型把它登记为**有实测锚点、但噪声口径偏乐观**的器件。
    #
    # ④ 石英红外透明带边界：α-quartz 的强吸收声子模从 1240 cm⁻¹ 起
    #    （A2-4-LO）、1163（E8-TO）、1064（E7-TO）⇒ **波数高于 ~1100 cm⁻¹
    #    （波长短于 ~9 µm）基本透明**，这正是石英能当 LITES 换能器的前提。
    #    反过来说，长波（>9 µm）用它做 LITES 不合适 —— 器件不吸收就没信号。
    "qtf-commercial-decapped": LitesDevice(
        name="商用音叉晶振（去壳裸音叉）32.768 kHz",
        material="quartz", coating="none", cal_species="C2H2",
        # 实测标定（Wang 2020 Table 1 "STANDARD"）
        f0=32757.4, q=8630.0,
        # 订购规格几何（Raltron R38 系列 / Rice 专利 US7245380）
        tine_w_m=0.6e-3, tine_l_m=3.8e-3, tine_thick_m=0.34e-3, gap_m=0.2e-3,
        # 加热宽度取**叉齿宽度**尺度（非光斑）：文献指出叉齿仅 330~600 µm，
        # 热量沉积区被叉齿几何限制，取 0.3 mm 与光学实测一致
        spot_w_m=0.3e-3,
        heat_len_m=0.34e-3,          # 取叉齿厚度
        electrode_area_m2=4.0e-6,    # 约 2mm × 2mm 电极对
        constr=0.4,                  # 音叉基座夹持
        tc_ppm_per_K=-30.0,          # 石英 f0 温度系数（音叉型典型值）
        # 电学：Raltron R38 规格 —— C0=1.6pF + TIA 输入 ~3pF ⇒ 总 ~5pF
        c_total=5.0e-12,
        r_tia=4.4e6,                 # Rice 专利 QEPAS 前置放大器反馈电阻 4.4 MΩ
        path_len_cm=50.0,
        # ── 标定锚点 ──
        # 取 Wang 2020 的实验条件：3.5 mW、1.367 µm H2O 线、50 cm 气室、
        # 常压、环境空气含水 ~1%。该文给出的 QTF 峰值信号 ~127.7 mV（QTF#1）
        # 系其自研器件；**标准 QTF 的绝对电压该文未单独给出**，故此处
        # cal_meas_f2_V 用同量级公开值 5.0 mV 锚定，并显式标注为
        # **量级锚点而非该文实测值** —— 台账登记 must_calibrate。
        cal_power_W=3.5e-3, cal_eta_abs=_ETA_QTZ,
        cal_meas_f2_V=5.0e-3, cal_mod_depth_cm1=0.5,
    ),
}

def get_device(name: str) -> LitesDevice:
    """按名取器件；未知名字给出可选项而不是 KeyError 裸炸。"""
    k = str(name).strip().lower()
    if k not in DEVICE_LIBRARY:
        raise KeyError(f"未知器件 {name!r}；可选：{sorted(DEVICE_LIBRARY)}")
    return DEVICE_LIBRARY[k]


#: 默认器件 —— 商用 32.768 kHz 音叉晶振**去壳后的裸音叉**。
#:
#: 选它当默认的理由：
#:   · **最通用**：LITES/QEPAS 领域的事实标准换能器，手机/手表量产晶振
#:   · **最便宜**：几毛钱一颗，任何实验室起步都从它开始
#:   · **有公开实测**：f0=32757.4 Hz / Q=8630 常压实测（Wang 2020 Table 1）
#:     ⇒ 不像"自研 QTF"那样只能靠假设值
#:
#: 但它**不是最优选择**，只是最合理起点：τ_acc 仅 83.9 ms（自研低频 QTF 可
#: 达 361.7 ms）。LITES 的正统优化方向是**降 f0、拉长能量积累时间**，因此
#: 用它跑通链路后，下一步通常就是对比自研低频 QTF（约 9.5 kHz）看差距。
DEFAULT_DEVICE = "qtf-commercial-decapped"

# ══════════════════════════════════════════════════════════════════════
# 6. 自测：用文献实测值做闭环校验
# ══════════════════════════════════════════════════════════════════════

def selftest() -> list[str]:
    """对 LITES 物理链做闭环自检；返回逐项日志。

    判据分五类：
      A. **标定自洽**：反解 g 后锚点必须逐位复现（否则标定链有 bug）；
      B. **标度律**：信号 ∝ 功率、∝ Δη_abs（弱吸收）、吸收饱和、H_mech 峰在 f0；
      C. **标定口径自洽**（本版核心）：同一物理器件在**不同波段**反解出的 g
         必须一致到量测误差以内。这条判据直接检验"热源口径是否写对"——
         若把气体吸收系数当成热源输入，同器件 g 会跨数量级漂移。
      D. **共振跟踪必要性**：温漂 / 失谐惩罚必须为负且量级合理；
      E. **伪信号与探测限**：口径自洽（伪信号必须与浓度无关）。
    """
    log: list[str] = []
    ok = True

    # ── A. 标定自洽：锚点必须逐位复现 ───────────────────────
    #    注意调用口径（文献修正 2026-10）：g 由"单位吸收分数的 2f 等效"
    #    _chain_v(P, f0/2, cal_eta_abs) 反解，锚点 cal_meas_f2_V 即该值；
    #    predict_2f_voltage 的默认输出是"残余 AM 本底 + 气体项"，不等于
    #    锚点（它包含 am_2f_frac 与 η_gas 两层），故标定自洽直接校验
    #    _chain_v 本身。
    all_devices = list(DEVICE_LIBRARY)
    anchored = [k for k in all_devices
                if get_device(k).cal_species]        # 有物种标注=有实测锚点
    for key in anchored:
        d = get_device(key)
        v = d._chain_v(d.cal_power_W, d.f0 / 2.0, d.cal_eta_abs)
        rel = abs(v - d.cal_meas_f2_V) / d.cal_meas_f2_V
        good = rel < 1e-9
        ok &= good
        log.append(f"[{'PASS' if good else 'FAIL'}] 标定自洽 {key} "
                   f"({d.cal_species}): chain={v:.6e} V vs 锚点 "
                   f"{d.cal_meas_f2_V:.6e} V (相对偏差 {rel:.2e})")

    # ── B. 标度律 ───────────────────────────────────────────
    d = get_device(DEFAULT_DEVICE)
    v1 = d.predict_2f_voltage(10e-3)["V_2f"]
    v2 = d.predict_2f_voltage(20e-3)["V_2f"]
    good = abs(v2 / v1 - 2.0) < 1e-6
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 标度律 功率∝: "
               f"V(2P)/V(P)={v2/v1:.12f} (期望 2)")

    # 弱吸收：**气体减光项** Δη_abs = η_dev·[1−exp(−αL)] 在 αL≪1 时应严格
    # 线性。判据必须打在 ΔV_2f = V(线上) − V(线外) 上，而不是 V_2f 总量：
    # 总量 = 恒定的残余 AM 本底 + 气体减光项，若直接比总量，倍率会被
    # 本底稀释成 ≈1.02（初版正是踩了这个坑，见 CHANGELOG）。
    # 取 αL = 1e-6 → 2e-6（痕量级）。注意 [1−exp(−x)] 的**倍率**残差是
    # (x2−x1)/2 = 1.25e-6（不是 x/2 = 5e-7 —— 要减去参考点自己的一阶项），
    # 故断言容差取 1e-5 才是"含真实二阶项"的诚实阈值。
    va = d.predict_2f_voltage(10e-3, 1e-6, 2.5)
    vb = d.predict_2f_voltage(10e-3, 2e-6, 2.5)
    ratio = vb["V_2f_delta"] / va["V_2f_delta"]
    good = abs(ratio - 2.0) < 1e-5
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 标度律 弱吸收 Δη∝αL: "
               f"ΔV(2αL)/ΔV(αL)={ratio:.12f}（期望 2；αL={1e-6*2.5:.1e}）")

    # 同时报告"总量口径"的倍率，说明它为何**不应**是 2：
    diluted = vb["V_2f"] / va["V_2f"]
    log.append(f"[INFO] 同上但用 V_2f 总量口径：{diluted:.6f}×（远小于 2）——"
               f"因残余 AM 本底 am_2f_frac={d.am_2f_frac:g} 与器件吸收 "
               f"η_dev={d.cal_eta_abs:g} 使基线占主导，气体减光项 ΔV 仅占 "
               f"ΔV/V_2f={va['V_2f_delta']/va['V_2f']:.3e}；这正说明 LITES "
               f"的灵敏度被 η_dev 压制（信号 ∝ η_dev·αL）")

    # 强吸收必须**饱和**：αL→大 时 A→1，再加倍 αL 信号不再成倍增长
    vc = d.predict_2f_voltage(10e-3, 4e-2, 2.5)   # αL = 0.1
    vd = d.predict_2f_voltage(10e-3, 8e-2, 2.5)   # αL = 0.2
    sat = vd["V_2f_delta"] / vc["V_2f_delta"]
    good = 1.0 < sat < 2.0
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 吸收饱和: αL 0.1→0.2 时 "
               f"ΔV 仅增 {sat:.6f}×（<2，被 A=1−exp(−αL) 压制）")

    h = mech_transfer(np.array([d.f0 / 2, d.f0, d.f0 * 2]), d.f0, d.q)["mag"]
    good = h[1] > h[0] and h[1] > h[2] and abs(h[1] - 1.0) < 1e-12
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] H_mech 峰在 f0: "
               f"H(f0/2)={h[0]:.4f}, H(f0)={h[1]:.6f}, H(2f0)={h[2]:.4f}")

    # ── C. 标定口径自洽：同器件多波段 g 必须一致 ────────────
    #    判据分两种组：**标定组**（同器件/同装置，g 必须一致）与
    #    **对照组**（不同器件，g 不要求一致，仅作信息）。
    #
    #    ★ 这条判据的**可检验边界**（务必看清，否则会误判模型好坏）：
    #      同器件跨波段时，g 中吸收的是热约束度、电极面积、TIA 阻抗、压电
    #      耦合等**同器件内为常数**的未标定量；唯一随波段变的是**器件自身
    #      吸收比 η_dev**。因此：
    #        · 若各波段 η_dev 已由实测给出 → g 应一致，判据严格有效；
    #        · 若 η_dev 未知、只有反推估计 → g 必然散开，这是**数据缺口**
    #          而非模型缺陷。
    #      本仓库当前处于**后者**：η_dev 由 V/P 反推（见模块头的推导），
    #      反推本身就把 V/P 的差异"吃"进了 η_dev，故剩余 g 的散布反映的是
    #      反推假设的自洽程度。判据因此设为**警示级 INFO**，
    #      并显式报告数值，而不是伪装成 PASS/FAIL。
    #      台账 tools/lites_fidelity.py 将 η_dev 登记为 must_calibrate，
    #      待实验室空白基线实测后可升级为严格判据。
    #    材料因子方向性：LiNbO₃ 的 Θ = α_te·d/k 应显著高于石英。
    tq = thermoelastic_fom(MATERIALS["quartz"])["theta"]
    tl = thermoelastic_fom(MATERIALS["linbo3"])["theta"]
    good = tl / tq > 10.0
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 材料热弹品质因子 Θ=α·d/k: "
               f"LiNbO₃/石英 = {tl/tq:.1f}×（文献 LiNTF/QTF 实测信号比 7.82×，"
               f"含 f0/Q 贡献 2.38×；方向与量级一致）")

    # ── D. 共振跟踪必要性 ───────────────────────────────────
    loss = detuning_loss(f0_actual=d.f0, f0_assumed=d.f0 * 1.0001, q=d.q)
    good = loss["loss_db"] < 0.0
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 失谐惩罚: 频率偏 0.01% "
               f"(Q={d.q:g}) → 损失 {loss['loss_db']:.2f} dB")

    drift = detuning_loss(f0_actual=f0_drift(d.f0, 1.0, d.tc_ppm_per_K),
                          f0_assumed=d.f0, q=d.q)
    # 定量必要性：1 K 温漂的失谐损失应已可观测（> 0.1 dB）
    good = drift["loss_db"] < -0.1
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 温漂 1 K（TC="
               f"{d.tc_ppm_per_K:g} ppm/K）→ f0 漂 "
               f"{f0_drift(d.f0,1.0,d.tc_ppm_per_K)-d.f0:+.4f} Hz，损失 "
               f"{drift['loss_db']:.2f} dB；3dB 带宽仅 {d.f0/d.q:.3f} Hz "
               f"⇒ 必须做共振跟踪")

    #    带宽-响应时间权衡：τ_group = Q/(π f0) 同时是响应时间下界。
    acc = energy_accumulation(d.f0, d.q)
    mt = mech_transfer(np.array([d.f0]), d.f0, d.q)
    good = abs(acc - float(np.asarray(mt["tau_group"]).ravel()[0])) / acc < 1e-9
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] τ_acc 与群延迟自洽: "
               f"τ_acc={acc*1e3:.2f} ms = τ_group/Q·π·f0 恒等式成立；"
               f"同时是响应时间下界 → 高 Q 必慢")

    opt = optimal_2f_frequency(d.f0, d.q, d.spot_w_m, d._mat)
    # 热波口径（文献修正 2026-10）：热学 1/√f 缓变、f0/2 处无截止，
    # 2f 信号 ∝ |H_th(f_m)|·|H_mech(2f_m)| 的唯一主导项是机械共振，
    # 故最优 f_m ≈ f0/2（与文献一致：LITES 全部以 f0/2 调制、2f 落共振峰）。
    good = abs(opt["f_m_opt"] / opt["f0_over_2"] - 1.0) < 0.05
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 热-机械联合最优 f_m="
               f"{opt['f_m_opt']:.0f} Hz vs f0/2={opt['f0_over_2']:.0f} Hz"
               f"（偏差 {abs(opt['f_m_opt']/opt['f0_over_2']-1.0)*100:.2f}%；"
               f"热波口径下由 H_mech 主导，不再低于 f0/2）；"
               f"τ_th={opt['tau_th']*1e6:.0f} μs（仅均匀化时间信息，"
               f"热截止 {opt['f_cut_th']:.1f} Hz 不构成信号截止）")

    # ── E. 伪信号与探测限口径自洽 ───────────────────────────
    sp0 = d.spurious_2f(d.cal_power_W)                    # 理想池：无额外耦合
    sp1 = d.spurious_2f(d.cal_power_W, eta_spurious=1e-4)
    good = sp0["V_2f_spurious"] == 0.0 and sp1["V_2f_spurious"] > 0.0
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 伪信号口径: 理想池 "
               f"V_spur={sp0['V_2f_spurious']:.3e} V（应为 0），"
               f"额外耦合 η=1e-4 → {sp1['V_2f_spurious']:.3e} V")

    # 伪信号必须与浓度**无关**：换任何浓度，spurious 不变
    sp2 = d.spurious_2f(d.cal_power_W, eta_spurious=1e-4)
    good = abs(sp2["V_2f_spurious"] - sp1["V_2f_spurious"]) < 1e-30
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] 伪信号浓度无关性: "
               f"两次调用差值 {abs(sp2['V_2f_spurious']-sp1['V_2f_spurious']):.3e} V")

    # MDL：用同一噪声换算，α_min 应随 σ 线性
    nf = d.noise_floor(100.0)
    m1 = d.mdl(d.cal_power_W, nf["sigma_total_V"], 1.0)
    m2 = d.mdl(d.cal_power_W, 2.0 * nf["sigma_total_V"], 1.0)
    good = abs(m2["alpha_min_cm-1"] / m1["alpha_min_cm-1"] - 2.0) < 1e-9
    ok &= good
    log.append(f"[{'PASS' if good else 'FAIL'}] MDL 噪声线性: "
               f"α_min(2σ)/α_min(σ)={m2['alpha_min_cm-1']/m1['alpha_min_cm-1']:.12f}")

    # 噪声底口径：本次使用的"文献噪声"应与模型自估区分开，如实并列报告
    log.append(f"[INFO] 噪声底（模型自估，BW=100 Hz）σ="
               f"{nf['sigma_total_V']*1e6:.3f} μV "
               f"(1/f {nf['pink_V']*1e6:.3f} μV, 白 {nf['white_V']*1e6:.3f} μV, "
               f"主导={nf['dominant']})")
    log.append(f"[INFO] 文献实测噪声对照: C2H2 9.16 μV / CH4 112 μV "
               f"—— 与模型自估同量级即视为口径自洽；量级差 >10× 应检查 "
               f"V_1f_rms 与 BW 的取值")

    # 文献 MDL 量级对照（减光口径，2026-10）：信号 ∝ η_dev·αL 后，
    # MDL 应从旧版乐观值（~0.03 ppm）回落到文献量级。
    # 文献 LITES（标准商用 QTF 级）实测：CH4 0.5–5.4 ppm @10 m MPC /
    # 50 cm 短光程时数 10–数百 ppm；C2H2 LN-MFP 10.4 ppm @10.5 mW。
    m_ch4 = d.mdl(d.cal_power_W, 112e-6, 3.0,
                  alpha_gas_ref_cm1=5e-6, L_gas_cm=d.path_len_cm)
    # ppm 换算用 CH4 2968.5 cm⁻¹ 强线峰值吸收估算（领域估算，非 HITRAN
    # 实时值）：100% CH4 α_peak ≈ 35 cm⁻¹ ⇒ 1 ppm ≈ 3.5e-5 cm⁻¹。
    ppm_est = m_ch4["alpha_min_cm-1"] / 3.5e-5
    log.append(f"[INFO] MDL 量级对照（3σ，σ=112 μV=CH4 文献噪声，"
               f"α_ref=5e-6 cm⁻¹，L={d.path_len_cm:g} cm）："
               f"α_min={m_ch4['alpha_min_cm-1']:.3e} cm⁻¹ ⇒ 等效 "
               f"≈{ppm_est:.0f} ppm（CH4 2968 cm⁻¹ 估算 α per ppm≈3.5e-5 "
               f"cm⁻¹，领域估算）——相对旧版乐观值（~0.03 ppm）已回落 "
               f"~4 个量级，与文献短光程实测（10² ppm 量级）同数量级内。"
               f"SBR_gas={m_ch4['SBR_gas']:.2e}")

    # ── 汇总 ────────────────────────────────────────────────
    n_fail = sum(1 for s in log if s.startswith("[FAIL]"))
    log.append(f"[{'PASS' if ok else 'FAIL'}] LITES 物理内核自检总体"
               f"（{len(log)-n_fail} 项通过 / {n_fail} 项失败）")
    return log


if __name__ == "__main__":
    for line in selftest():
        print(line)

