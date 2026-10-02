#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DOAS（差分吸收光谱）物理模型：宽带源 / 参考截面 / 慢变背景分离 / 浓度反演。

原理（教科书级）
────────────────────────────────────────────────────────
DOAS 在 UV-Vis 用宽带光源测分子指纹吸收。透射光强：

    I(λ) = I0(λ) · exp[ −σ(λ)·c·L − ε(λ)·L ]

其中 σ(λ) 为吸收截面（分子快变指纹），ε(λ) 为慢变消光（瑞利 λ⁻⁴、
Mie λ⁻ᵅ、光源包络——用低阶多项式吸收）。差分吸收分离：

    ln(I0/I) = σ(λ)·c·L + P(λ)      →  扣除多项式 P 后余差 D(λ) ≈ σ·c·L
    c = argmin ‖D − σ_ref·L·c‖²     （最小二乘）

单位约定：λ [nm]，σ [cm²/molecule]，L [cm]，
数密度 n = x·P/(k_B·T) [molecule/cm³]，c 为摩尔分数（1e-6 = 1 ppm）。

⚠️ 铁律：参考截面、光程、源包络**不内置默认仪器**；演示截面为高斯带
占位（NO₂ 448 nm 量级），真实截面须用户提供（HITRAN 截面库或实测）。
"""
from __future__ import annotations

import math

try:
    import numpy as np
    _HAS_NP = True
except Exception:                                  # pragma: no cover
    _HAS_NP = False

_KB_ERGS = 1.380649e-16        # erg/K（cgs，配合 cm⁻³ 数密度）
_ATM_DYN = 1.01325e6           # dyn/cm² per atm

# 演示吸收截面（高斯带占位；真实值须用户提供，勿用于定量结论）
_DEMO_SECTIONS = {
    "NO2": {"wl0": 448.0, "bands": [(448.0, 6.5e-19, 8.0), (430.0, 1.9e-19, 6.0),
                                    (465.0, 1.1e-19, 10.0), (410.0, 0.7e-19, 5.0)]},
    "SO2": {"wl0": 300.0, "bands": [(300.0, 2.5e-19, 5.0), (285.0, 1.2e-19, 4.0),
                                    (315.0, 0.8e-19, 6.0)]},
    "O3":  {"wl0": 254.0, "bands": [(254.0, 1.1e-17, 6.0), (300.0, 3.0e-19, 20.0),
                                    (330.0, 4.0e-19, 25.0)]},
}


def demo_section(wl: np.ndarray, species: str = "NO2"):
    """演示吸收截面 σ(λ) [cm²/molecule]（高斯带叠加；ai 演示占位）。"""
    if species not in _DEMO_SECTIONS:
        raise ValueError(f"未知演示物种：{species}（可用 {list(_DEMO_SECTIONS)}）")
    sigma = np.zeros_like(wl, dtype=float)
    for wl0, s0, fwhm in _DEMO_SECTIONS[species]["bands"]:
        gamma = fwhm / (2.0 * math.sqrt(math.log(2.0)))
        sigma += s0 * np.exp(-((wl - wl0) / gamma) ** 2)
    return sigma


def _n_from_x(x: float, T: float, P: float):
    """摩尔分数 → 数密度 [molecule/cm³]：n = x·P/(k_B·T)，P 单位 atm。"""
    return x * (P * _ATM_DYN) / (_KB_ERGS * T)


def forward(x: float = 5e-6, L_cm: float = 50.0, species: str = "NO2",
            wl_min: float = 400.0, wl_max: float = 500.0, n_wl: int = 401,
            T: float = 296.0, P: float = 1.0, poly_deg: int = 3,
            noise_frac: float = 0.0, seed: int = 0):
    """DOAS 正演：I0(慢变源包络) → 吸收 → I(λ)，并做差分反演披露。

    I0 用高斯源包络（中心 wl0、宽度由波段决定），瑞利/Mie 慢变并入多项式。
    """
    if not _HAS_NP:
        raise RuntimeError("DOAS 需要 numpy")
    wl = np.linspace(wl_min, wl_max, n_wl)
    wl0 = _DEMO_SECTIONS[species]["wl0"]
    i0 = np.exp(-((wl - wl0) / (0.35 * (wl_max - wl_min))) ** 2)   # 平滑源包络（慢变）
    # 瑞利散射慢变 + 多项式消光并入：正演里 ln(I0/I) 的多项式部分来自 σ 之外的慢变
    sigma = demo_section(wl, species)
    n = _n_from_x(x, T, P)
    od_pure = sigma * n * L_cm                          # 快变差分吸收
    # 演示慢变背景：多项式可表示型（线性+宽二次，DOAS 前提是背景可被低阶多项式吸收）。
    # 真实瑞利 λ⁻⁴ / Mie / 光源包络为平滑结构，窄窗口内同样可由多项式近似。
    od_slow = 0.02 * (wl - wl_min) / (wl_max - wl_min) + 0.001 * ((wl - wl0) / (0.5 * (wl_max - wl_min))) ** 2
    I = i0 * np.exp(-(od_pure + od_slow))

    rng = np.random.default_rng(seed)
    if noise_frac > 0:
        I = I * (1.0 + rng.normal(0.0, noise_frac, I.shape))

    # 反演：ln(I0/I) − 多项式背景 → 差分吸收 → 与 σ 最小二乘
    x_inv = _invert_core(I, i0, sigma, L_cm, poly_deg)
    return {
        "wl_range": [float(wl[0]), float(wl[-1])], "n_wl": n_wl,
        "species": species, "sigma_peak_cm2": float(sigma.max()),
        "L_cm": L_cm, "n_density_cm3": float(n),
        "x_truth": x, "x_inferred": round(x_inv, 9),
        "x_error_frac": round((x_inv - x) / x if x else 0.0, 9),
        "od_peak": round(float(od_pure.max()), 6),
        "polynomial_background": {"deg": poly_deg,
                                  "role": "吸收瑞利/Mie/光源包络等慢变，差分后不影响反演"},
        "source": "default=ai_demo_placeholder（演示截面/源包络）；真实截面须用户提供（HITRAN xsc 或实测）",
    }


def _invert_core(I: np.ndarray, i0: np.ndarray, sigma: np.ndarray,
                 L_cm: float, poly_deg: int, T: float = 296.0, P: float = 1.0):
    """差分反演核心：ln(I0/I) 联合最小二乘 [多项式背景, σ·L] → c。

    差分拟合（教科书 DOAS）：ln(I0/I) = Σaₖ·λₖ + σ(λ)·L·c，一次求解全部
    系数，避免"先扣背景再拟合"的遗漏变量偏置（σ 平滑包络与多项式空间
    不正交时两阶段法有偏）。解出的 c 为数密度 n [cm⁻³]，按
    n = x·P/(k_B·T) 转回摩尔分数 x。
    """
    y = -np.log(np.clip(I, 1e-300, None) / np.clip(i0, 1e-300, None))
    wl_n = np.linspace(-1.0, 1.0, len(y))
    dm = np.vstack([wl_n ** k for k in range(poly_deg + 1)] + [sigma * L_cm]).T
    # 列归一化：σ·L 列幅度（~1e-17）与多项式列（~1）差 17 个数量级，
    # 裸 lstsq 的 rcond 会把 σ 列判为秩亏丢弃 → 归一后精确分解再恢复。
    norms = np.linalg.norm(dm, axis=0)
    coef_n = np.linalg.lstsq(dm / norms, y, rcond=None)[0]
    coef = coef_n / norms
    n_dens = float(coef[-1])
    x = n_dens * (_KB_ERGS * T) / (P * _ATM_DYN)
    return x


def invert(I, i0, sigma, L_cm: float = 50.0, poly_deg: int = 3):
    """用户实测谱 → 差分反演浓度（等长数组）。"""
    if not _HAS_NP:
        raise RuntimeError("DOAS 需要 numpy")
    I = np.asarray(I, dtype=float)
    i0 = np.asarray(i0, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    if I.shape != i0.shape or I.shape != sigma.shape:
        return {"usage": "I/i0/sigma 必须等长（实测光强/参考光强/吸收截面）", "x": None}
    x = _invert_core(I, i0, sigma, L_cm, poly_deg)
    return {"x": round(x, 9), "x_ppm": round(x * 1e6, 6),
            "formula": "c = argmin ‖ln(I0/I)−P(λ)−σ·L·c‖²"}


def calibrate(x_min: float = 0.0, x_max: float = 2e-5, n: int = 11,
              L_cm: float = 50.0, species: str = "NO2",
              T: float = 296.0, P: float = 1.0, poly_deg: int = 3,
              noise_frac: float = 0.0, seed: int = 0):
    """浓度扫描标定：x_min..x_max 等距 n 点 → 反演浓度表 + 线性拟合（斜率/R²）。"""
    if not _HAS_NP:
        raise RuntimeError("DOAS 需要 numpy")
    wl = np.linspace(400.0, 500.0, 401)
    wl0 = _DEMO_SECTIONS[species]["wl0"]
    i0 = np.exp(-((wl - wl0) / 35.0) ** 2)
    sigma = demo_section(wl, species)
    xs, invs = [], []
    for k in range(n):
        x = x_min + (x_max - x_min) * k / (n - 1)
        n_dens = _n_from_x(x, T, P)
        od = sigma * n_dens * L_cm + 0.02 * (wl - 400.0) / 100.0 + 0.001 * ((wl - wl0) / 50.0) ** 2
        I = i0 * np.exp(-od)
        rng = np.random.default_rng(seed + k)
        if noise_frac > 0:
            I = I * (1.0 + rng.normal(0.0, noise_frac, I.shape))
        xs.append(x)
        invs.append(_invert_core(I, i0, sigma, L_cm, poly_deg))
    xs = np.asarray(xs)
    invs = np.asarray(invs)
    slope, intercept = np.polyfit(xs, invs, 1)
    r2 = 1.0 - float(np.sum((invs - (slope * xs + intercept)) ** 2)) / max(
        float(np.sum((invs - invs.mean()) ** 2)), 1e-300)
    return {"n_points": n, "slope": round(float(slope), 6),
            "intercept": round(float(intercept), 9), "r_squared": round(r2, 6),
            "max_abs_err_frac": round(float(np.max(np.abs(invs - xs) / np.maximum(np.abs(xs), 1e-30))), 6),
            "source": "default=ai_demo_placeholder; 真实截面须用户提供"}


def selftest():
    """数值锚点自检（离线，演示截面）。"""
    fails = []
    if not _HAS_NP:
        return {"ok": False, "fails": ["numpy 不可用"]}
    # 1) x=0 → OD=0，I=I0（无吸收）
    wl = np.linspace(400.0, 500.0, 401)
    wl0 = 448.0
    i0 = np.exp(-((wl - wl0) / 35.0) ** 2)
    sigma = demo_section(wl, "NO2")
    n0 = _n_from_x(0.0, 296.0, 1.0)
    if n0 != 0.0:
        fails.append("x=0 数密度不为 0")
    # 2) 无噪反演：平坦与强慢变背景都应收敛
    for x_t in (2e-6, 5e-6, 1e-5):
        n = _n_from_x(x_t, 296.0, 1.0)
        od = sigma * n * 50.0 + 0.02 * (wl - 400.0) / 100.0 + 0.001 * ((wl - wl0) / 50.0) ** 2
        I = i0 * np.exp(-od)
        x_inv = _invert_core(I, i0, sigma, 50.0, 3)
        if abs(x_inv - x_t) / x_t > 0.01:
            fails.append(f"无噪反演误差超限 x={x_t:.2e} → {x_inv:.3e}")
    # 3) 慢变多项式阶数稳健性：deg 2~6 反演一致
    n = _n_from_x(5e-6, 296.0, 1.0)
    od = sigma * n * 50.0 + 0.02 * (wl - 400.0) / 100.0 + 0.001 * ((wl - wl0) / 50.0) ** 2
    I = i0 * np.exp(-od)
    invs = [_invert_core(I, i0, sigma, 50.0, d) for d in (2, 3, 4, 5, 6)]
    spread = max(invs) - min(invs)
    if spread / 5e-6 > 0.02:
        fails.append(f"多项式阶数不稳健 (spread={spread:.2e})")
    # 4) 1% 光强噪声：统计判据（DOAS 差分吸收 SNR 受 σ 带宽与光程限制）
    #    10 m 光程演示：od_pure~0.08 vs 噪声等效 OD 0.01 → SNR~8
    n = _n_from_x(5e-6, 296.0, 1.0)
    od = sigma * n * 1000.0 + 0.02 * (wl - 400.0) / 100.0 + 0.001 * ((wl - wl0) / 50.0) ** 2
    I = i0 * np.exp(-od)
    xs_noise = []
    for seed in range(12):
        rng = np.random.default_rng(seed)
        In = I * (1.0 + rng.normal(0.0, 0.01, I.shape))
        xs_noise.append(_invert_core(In, i0, sigma, 1000.0, 3))
    xs_noise = np.asarray(xs_noise)
    mean = float(xs_noise.mean())
    std = float(xs_noise.std())
    sem = std / math.sqrt(len(xs_noise))
    if abs(mean - 5e-6) > 3.0 * sem:
        fails.append(f"噪声反演偏置超限 (mean={mean:.2e}, std={std:.2e}, n=12)")
    # 5) 标定曲线：斜率≈1、R²>0.999
    cal = calibrate(0.0, 2e-5, 11, noise_frac=0.0)
    if cal["r_squared"] < 0.999 or abs(cal["slope"] - 1.0) > 0.02:
        fails.append(f"标定曲线异常 (slope={cal['slope']}, R²={cal['r_squared']})")
    return {
        "ok": not fails, "fails": fails,
        "anchors": {"noise_mean_err_frac": round(abs(mean - 5e-6) / 5e-6, 6),
                    "noise_std": round(std, 9),
                    "cal_slope": cal["slope"], "cal_r2": cal["r_squared"]},
    }
