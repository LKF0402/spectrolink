#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CRDS（腔衰荡光谱）物理模型：衰荡时间 / ring-down 波形 / 吸收反演。

原理（教科书级）
────────────────────────────────────────────────────────
两高反镜（反射率 R）构成光学腔，腔内气体吸收使光子寿命缩短：

    空腔    τ0    = L / (c·(1-R))                [s]
    有吸收  1/τ   = c·(1-R)/L + c·α(ν)           [1/s]

测量衰减时间 τ(ν) 后反演单程吸收系数：

    α(ν) = 1/(c·τ(ν)) − (1-R)/L                  [m⁻¹]

浓度反演用纯组分吸收谱（HITRAN 或用户谱）：
    α(ν) = x · α_pure(ν)   →   x = α_pk / α_pure_pk

单位约定：L [m]、c = 2.99792458e8 m/s、α 内部统一 [m⁻¹]
（HITRAN 吸收系数为 [cm⁻¹]，×100 换算）。

⚠️ 铁律：镜面反射率 R、腔长 L、探测器参数**不内置默认仪器**；演示占位
参数（R=0.999, L=1 m）仅保证 selftest 与示例可跑，真实值须用户交互提供。
"""
from __future__ import annotations

import math
import random

C = 2.99792458e8          # 真空光速 [m/s]
_CM_TO_M = 100.0          # cm⁻¹ → m⁻¹


def tau_cavity(L_m: float, R: float) -> float:
    """空腔衰荡时间 τ0 = L/(c·(1-R)) [s]。"""
    return L_m / (C * (1.0 - R))


def tau_with_absorption(L_m: float, R: float, alpha_cm: float) -> float:
    """有吸收时衰荡时间：1/τ = c(1-R)/L + c·α。alpha_cm 为单程吸收 [cm⁻¹]。"""
    a_m = alpha_cm * _CM_TO_M
    return 1.0 / (C * (1.0 - R) / L_m + C * a_m)


def alpha_from_tau(tau_s: float, L_m: float, R: float) -> float:
    """衰荡时间 → 单程吸收系数 α [cm⁻¹]。"""
    a_m = 1.0 / (C * tau_s) - (1.0 - R) / L_m
    return a_m / _CM_TO_M


def ring_down(t: list, tau_s: float, i0: float = 1.0,
              noise_frac: float = 0.0, seed: int = 0):
    """生成 ring-down 波形 I(t) = I0·exp(−t/τ) + 高斯噪声（相对 I0）。"""
    rng = random.Random(seed)
    out = []
    for ti in t:
        v = i0 * math.exp(-ti / tau_s)
        if noise_frac > 0:
            v *= 1.0 + rng.gauss(0.0, noise_frac)
        out.append(v)
    return out


def fit_tau(t: list, i: list):
    """对数线性拟合衰荡时间：ln I = ln I0 − t/τ → τ = −1/斜率。

    仅用 I > 0 的点；返回 (tau, i0_fit, n_used, r2)。
    """
    xs, ys = [], []
    for ti, ii in zip(t, i):
        if ii > 0:
            xs.append(ti); ys.append(math.log(ii))
    n = len(xs)
    if n < 2:
        return None
    sx = sum(xs); sy = sum(ys)
    sxx = sum(v * v for v in xs); sxy = sum(a * b for a, b in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-30:
        return None
    slope = (n * sxy - sx * sy) / denom
    inter = (sy - slope * sx) / n
    tau = -1.0 / slope if slope != 0 else float("inf")
    y_mean = sy / n
    ss_tot = sum((v - y_mean) ** 2 for v in ys)
    ss_res = sum((ys[i] - (slope * xs[i] + inter)) ** 2 for i in range(n))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-30 else 1.0
    return {"tau_s": tau, "i0_fit": math.exp(inter), "n_used": n, "r2": r2}


def _gaussian_spectrum(nu, nu0, alpha_pk, gamma_hwhm):
    """内置解析吸收谱（离线验证用）：高斯线形 [cm⁻¹]。"""
    return [alpha_pk * math.exp(-((v - nu0) / gamma_hwhm) ** 2) for v in nu]


def simulate(L_m: float = 1.0, R: float = 0.999, x: float = 1e-5,
             nu0: float = 2968.41, nu_span: float = 2.0, n_nu: int = 201,
             T: float = 296.0, P: float = 1.0, species: str = "CH4",
             line_source: str = "hitran", iso: str = "all",
             alpha_pk_fallback: float = 13.365, gamma_fallback: float = 0.05,
             fit_noise: float = 0.0, seed: int = 0):
    """CRDS 谱扫描正演：τ(ν) 曲线 + 吸收峰处 ring-down 拟合演示。

    line_source:
      · "hitran"   → 用 spectrolink_core HITRAN 纯组分吸收谱（在线线表/缓存）；
                     取谱峰附近 α 峰值。HITRAN 不可用（如离线/504）时**自动降级**
                     为高斯演示谱并在 disclosure 中披露，不谎报为实测谱。
      · "gaussian" → 内置高斯解析谱（离线确定性验证）。

    浓度反演：x_inv = α_pk_measured / α_pure_pk。
    """
    import sys
    from pathlib import Path
    _srv = Path(__file__).resolve().parent
    _root = _srv.parent
    for _p in (_root, _srv):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    nu = [nu0 - nu_span / 2 + nu_span * i / (n_nu - 1) for i in range(n_nu)]
    alpha_pure, src, disclosure = None, line_source, []

    if line_source == "hitran":
        try:
            from spectrolink_core import hitran
            _nu, _alpha, _info = hitran.absorption(species, nu[0], nu[-1], T=T, P=P,
                                                   step=0.002, wingHW=5.0, iso=iso)
            # 插值到本窗口网格（线性）
            alpha_pure = [float(__interp(_nu, _alpha, v)) for v in nu]
            src = "hitran"
        except Exception as e:
            disclosure.append(f"HITRAN 不可用（{type(e).__name__}: {str(e)[:120]}）→ 降级为高斯演示谱，非真实谱")
            line_source = "gaussian"
    if alpha_pure is None:
        alpha_pure = _gaussian_spectrum(nu, nu0, alpha_pk_fallback, gamma_fallback)
        src = "gaussian_fallback"

    a_pk = max(alpha_pure)
    tau = [tau_with_absorption(L_m, R, a * x) for a in alpha_pure]
    tau_pk = min(tau)

    # ring-down 拟合演示（峰处）：2 μs 窗口 × 200 点（fs=100 MHz 量级）
    t = [2e-6 * i / 200 for i in range(201)]
    i_sig = ring_down(t, tau_pk, i0=1.0, noise_frac=fit_noise, seed=seed)
    fit = fit_tau(t, i_sig)
    tau_fit = fit["tau_s"] if fit else float("nan")
    alpha_fit = alpha_from_tau(tau_fit, L_m, R) if fit else float("nan")
    x_inv = alpha_fit / a_pk if a_pk > 1e-30 else float("nan")

    return {
        "nu_range": [round(nu[0], 4), round(nu[-1], 4)], "n_nu": n_nu,
        "tau0_empty": round(tau_cavity(L_m, R), 12),
        "tau_peak": round(tau_pk, 12),
        "tau_minus_tau0_frac": round((tau_pk - tau_cavity(L_m, R)) / tau_cavity(L_m, R), 9),
        "alpha_pure_peak_cm": round(a_pk, 9),
        "x_truth": x, "x_inferred": round(x_inv, 9),
        "x_error_frac": round((x_inv - x) / x if x else 0.0, 9),
        "ringdown_fit": fit,
        "line_source": src,
        "disclosure": disclosure,
        "assumptions": {
            "L_m/R": "默认 ai 演示占位（1 m / R=0.999），真实腔参数须用户提供",
            "T/P/species": "标称热力学状态与组分，用户可覆盖",
            "fit_noise": "ring-down 相对高斯噪声（示波器/探测器）",
        },
        "source": "default=ai_demo_placeholder; 真实值须 datasheet/calibration/user 交互",
    }


def __interp(x, y, xq):
    """线性插值（x 升序）。"""
    import bisect
    if xq <= x[0]:
        return y[0]
    if xq >= x[-1]:
        return y[-1]
    j = bisect.bisect_left(x, xq)
    x1, x2 = x[j - 1], x[j]
    if x2 == x1:
        return y[j]
    return y[j - 1] + (y[j] - y[j - 1]) * (xq - x1) / (x2 - x1)


def invert(tau_meas: float, L_m: float, R: float, alpha_pure_pk: float) -> float:
    """测量 τ → 浓度：α = 1/(cτ)−(1−R)/L，x = α/α_pure_pk。"""
    alpha = alpha_from_tau(tau_meas, L_m, R)
    if alpha_pure_pk <= 0:
        return float("nan")
    return alpha / alpha_pure_pk


def selftest():
    """数值锚点自检（全离线，不依赖网络/HITRAN）。"""
    fails = []
    L, R = 1.0, 0.999
    # 1) 空腔 τ0 = L/(c(1-R))
    tau0 = tau_cavity(L, R)
    if abs(tau0 - L / (C * (1 - R))) > 1e-18:
        fails.append("空腔 τ0 公式不符")
    # 2) 有吸收 τ 变短且公式自洽：tau→α 往返
    alpha_in = 1e-4                      # 1e-4 cm⁻¹
    tau_a = tau_with_absorption(L, R, alpha_in)
    alpha_out = alpha_from_tau(tau_a, L, R)
    if abs(alpha_out - alpha_in) / alpha_in > 1e-6:
        fails.append("τ↔α 往返不一致")
    # 3) ring-down 无噪声拟合：误差 < 0.1%
    t = [2e-6 * i / 200 for i in range(201)]
    tau_true = tau_a
    i_sig = ring_down(t, tau_true)
    fit = fit_tau(t, i_sig)
    if fit is None or abs(fit["tau_s"] - tau_true) / tau_true > 1e-3:
        fails.append("无噪声 ring-down 拟合误差超限")
    # 4) ring-down 1% 噪声：误差 < 3%
    i_n = ring_down(t, tau_true, noise_frac=0.01, seed=2)
    fit_n = fit_tau(t, i_n)
    if fit_n is None or abs(fit_n["tau_s"] - tau_true) / tau_true > 0.03:
        fails.append("噪声 ring-down 拟合误差超限")
    # 5) 高斯谱 simulate：无噪声反演误差 < 1e-6（离线）
    sim = simulate(L_m=L, R=R, x=1e-5, line_source="gaussian",
                   alpha_pk_fallback=13.365, gamma_fallback=0.05)
    if abs(sim["x_error_frac"]) > 1e-6:
        fails.append("高斯谱反演误差超限")
    return {
        "ok": not fails, "fails": fails,
        "anchors": {"tau0@1m_R999": round(tau0, 12),
                    "tau_alpha_roundtrip": round(alpha_out / alpha_in, 9),
                    "ringdown_fit_err": round(abs(fit["tau_s"] - tau_true) / tau_true, 9),
                    "ringdown_noise1pct_err": round(abs(fit_n["tau_s"] - tau_true) / tau_true, 9),
                    "gauss_inv_err": sim["x_error_frac"],
                    "tau_shorten_frac@1e-4cm": round((tau_a - tau0) / tau0, 9)},
    }
