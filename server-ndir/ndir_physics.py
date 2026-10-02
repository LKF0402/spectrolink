#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NDIR（非分散红外）双通道前向/反演物理模型。

原理（教科书级，非文献锚定）
────────────────────────────────────────────────────────
非分散红外用**宽带光源 + 窄带滤光片**代替光栅/干涉仪，信号通道滤光片
对准目标气体强吸收带，参考通道对准弱吸收区：

    I_s = I0_s · exp(-k_s · L_s · x)      # 信号通道（带内有效吸收系数 k_s）
    I_r = I0_r · exp(-k_r · L_r · x)      # 参考通道（k_r ≈ 0，补偿光源/窗口漂移）

比值 R = I_s/I_r 与浓度单调相关，且**同时消除光源波动与窗片污染**：

    R(x) = R0 · exp(-A·x),   A = k_s·L_s − k_r·L_r,   R0 = I0_s/I0_r
    x    = −ln(R/R0) / A

单位约定
────────────────────────────────────────────────────────
x 摩尔分数（无量纲，1e-6 = 1 ppm）；k [cm⁻¹]（每单位摩尔分数的有效吸收，
工程上由标定获得）；L [cm]；I 为探测器电流/电压任意线性标度。

⚠️ 铁律：k_s/k_r/滤光片中心与半宽/光源谱**不内置默认仪器**。下面给出的
演示占位参数（CO₂ 4.26 μm 常规量级）仅保证 selftest 与示例可跑，真实
器件参数必须由用户交互提供（datasheet / 标定）。

无 HITRAN 依赖：NDIR 的"吸收"是滤光片带通内的**宽带积分有效值**，工程上
用标定曲线刻画，不需要线表。
"""
from __future__ import annotations

import math
import random


def net_absorption(L_s_cm: float, L_r_cm: float, k_s: float, k_r: float) -> float:
    """净吸收-光程积 A = k_s·L_s − k_r·L_r [无量纲]。"""
    return k_s * L_s_cm - k_r * L_r_cm


def forward(x: float, L_s_cm: float = 10.0, L_r_cm: float = 10.0,
            k_s: float = 0.05, k_r: float = 0.001,
            i0_s: float = 1.0, i0_r: float = 1.0,
            noise_frac: float = 0.0, seed: int = 0):
    """单浓度正演：两通道信号、比值、理论反演。

    参数全部可被用户实测值覆盖；未覆盖项计入 assumptions 并由 source 标记披露。
    返回 dict（含观测、反演、披露）。
    """
    rng = random.Random(seed)
    a = net_absorption(L_s_cm, L_r_cm, k_s, k_r)
    i_s = i0_s * math.exp(-k_s * L_s_cm * x)
    i_r = i0_r * math.exp(-k_r * L_r_cm * x)
    if noise_frac > 0:                       # 相对高斯噪声（探测器热噪声等）
        i_s *= 1.0 + rng.gauss(0.0, noise_frac)
        i_r *= 1.0 + rng.gauss(0.0, noise_frac)
    r_obs = i_s / i_r
    r0 = i0_s / i0_r
    x_inv = -math.log(r_obs / r0) / a if abs(a) > 1e-15 else float("nan")
    # 单点检测限披露（一阶误差传播）：σ_x ≈ σ_R / A ≈ noise_frac / A
    x_noise = noise_frac / a if (noise_frac > 0 and abs(a) > 1e-15) else 0.0
    return {
        "I_s": round(i_s, 9), "I_r": round(i_r, 9),
        "R": round(r_obs, 9), "lnR": round(math.log(r_obs), 9),
        "R0": round(r0, 9),
        "x_truth": x, "x_inferred": round(x_inv, 9),
        "x_error_frac": round((x_inv - x) / x if x != 0 else 0.0, 9),
        "x_noise_1sigma": round(x_noise, 9),   # 单点 1σ 浓度检测限 ≈ noise_frac/A
        "A_net": round(a, 9),
        "assumptions": {
            "k_s": "信号通道带内有效吸收系数 [cm⁻¹]，默认 ai 演示占位（CO₂ 4.26 μm 量级），须用户标定",
            "k_r": "参考通道有效吸收系数，默认 ai 演示占位，须用户标定",
            "L_s_cm/L_r_cm": "两通道光程，默认 ai 演示占位，须用户提供",
        },
        "source": "default=ai_demo_placeholder; 真实值须 datasheet/calibration/user 交互",
    }


def calibrate(x_list, L_s_cm: float = 10.0, L_r_cm: float = 10.0,
              k_s: float = 0.05, k_r: float = 0.001,
              i0_s: float = 1.0, i0_r: float = 1.0,
              noise_frac: float = 0.0, seed: int = 0):
    """浓度扫描标定：返回 R(x) 表 + lnR 线性拟合（最小二乘）。

    拟合量：y = ln(R/R0) = −A·x。返回 A_fit 与理论 A 对比（披露自洽性）。
    """
    n = len(x_list)
    xs, ys, rs = [], [], []
    for x in x_list:
        r = forward(x, L_s_cm, L_r_cm, k_s, k_r, i0_s, i0_r, noise_frac, seed)
        xs.append(x); ys.append(r["lnR"] - math.log(r["R0"])); rs.append(r["R"])
    sx = sum(xs); sy = sum(ys); sxx = sum(v * v for v in xs); sxy = sum(a * b for a, b in zip(xs, ys))
    denom = n * sxx - sx * sx
    # y = ln(R/R0) = -A·x，最小二乘斜率 a = -A → A_fit = -a
    a_fit = -(n * sxy - sx * sy) / denom if abs(denom) > 1e-30 else float("nan")
    r0_fit = math.exp(sy / n - a_fit * (sx / n)) * i0_s / i0_r if i0_r else float("nan")
    # R²（对 lnR 线性模型）
    y_mean = sy / n
    ss_tot = sum((v - y_mean) ** 2 for v in ys)
    ss_res = sum((ys[i] - (a_fit * xs[i])) ** 2 for i in range(n))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-30 else 1.0
    return {
        "n": n,
        "table": [{"x": round(xs[i], 9), "R": round(rs[i], 9)} for i in range(n)],
        "fit": {"A_fit": round(a_fit, 9), "R0_fit": round(r0_fit, 9), "r2": round(r2, 9)},
        "A_theory": round(net_absorption(L_s_cm, L_r_cm, k_s, k_r), 9),
        "A_match": round(a_fit / net_absorption(L_s_cm, L_r_cm, k_s, k_r), 9)
                  if abs(net_absorption(L_s_cm, L_r_cm, k_s, k_r)) > 1e-15 else None,
    }


def invert(r_obs: float, r0: float, a: float) -> float:
    """比值 → 浓度（解析反演）。A 取 0 返回 nan（模型不可反演）。"""
    if abs(a) <= 1e-15 or r_obs <= 0 or r0 <= 0:
        return float("nan")
    return -math.log(r_obs / r0) / a


def selftest():
    """数值锚点自检（不依赖网络/HITRAN）。"""
    fails = []
    # 1) x=0 → R=R0
    r0 = forward(0.0)
    if abs(r0["R"] - r0["R0"]) > 1e-9:
        fails.append("x=0 时 R≠R0")
    # 2) 无噪声正演→反演 误差 < 1e-9
    x_t = 5e-6
    f = forward(x_t)
    if abs(f["x_inferred"] - x_t) > 1e-9 * max(1.0, x_t):
        fails.append("无噪声反演误差超限")
    # 3) R 随 x 单调下降
    r1 = forward(0.0)["R"]; r2 = forward(1e-3)["R"]
    if r2 >= r1:
        fails.append("R 未随浓度单调下降")
    # 4) 标定拟合 A 与理论一致
    xs = [i * 1e-4 for i in range(11)]
    cal = calibrate(xs)
    if abs(cal["A_match"] - 1.0) > 1e-6:
        fails.append("标定拟合 A 与理论不一致")
    # 5) 噪声锚点（统计判据）：1% 噪声 + 1% 浓度，|反演绝对误差| < 3σ_x（σ_x≈noise/A）
    fn = forward(0.01, noise_frac=0.01, seed=1)
    sigma_x = fn["x_noise_1sigma"]
    if abs(fn["x_inferred"] - 0.01) > 3 * sigma_x:
        fails.append("噪声下反演误差超过 3σ")
    # 6) 单点检测限披露自洽：σ_x ≈ noise_frac / A
    if abs(sigma_x - 0.01 / 0.49) > 1e-3:
        fails.append("x_noise_1sigma 披露与公式不符")
    return {
        "ok": not fails, "fails": fails,
        "anchors": {"x0_R_minus_R0": round(r0["R"] - r0["R0"], 12),
                    "x_inv_err@5ppm": f["x_error_frac"],
                    "R@1e-3/R@0": round(r2 / r1, 6),
                    "A_match": cal["A_match"],
                    "noise1pct@1pct": {"x_err_sigma": round(abs(fn["x_inferred"] - 0.01) / sigma_x, 3),
                                       "sigma_x": round(sigma_x, 6)},
                    "x_noise_1sigma@1pct": fn["x_noise_1sigma"]},
    }
