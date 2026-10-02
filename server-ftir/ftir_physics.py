#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FTIR（傅里叶变换红外）物理模型：干涉图 / 切趾 / 分辨率 / 光谱恢复。

原理（教科书级）
────────────────────────────────────────────────────────
迈克尔逊干涉仪测得干涉图 I(x)（x = 光程差），它是光谱的余弦变换：

    I(x) = ∫ T(ν)·cos(2πνx) dν

恢复光谱（离散反变换 + 切趾窗 W(x)）：

    T'(ν) = ∫ I(x)·W(x)·cos(2πνx) dx / ∫ W(x) dx

有限最大光程差 X_max 决定分辨率：Δν ≈ 0.5/X_max [cm⁻¹]（ILS 主瓣口径）。
切趾窗抑制旁瓣但展宽主瓣：boxcar（无窗）→ 强旁瓣；Hamming/Blackman-Harris → 平滑。

单位约定：ν [cm⁻¹]，光程差 x [cm]。

⚠️ 铁律：X_max、切趾、探测器噪声**不内置默认仪器**；演示占位参数
（X_max=2 cm → Δν≈0.25 cm⁻¹）仅保证 selftest 与示例可跑。

依赖：numpy（hapi/HITRAN core 已依赖，本机可用）；HITRAN 不可用时
自动降级为内置高斯演示谱并披露。
"""
from __future__ import annotations

import math

try:
    import numpy as np
    _HAS_NP = True
except Exception:                                  # pragma: no cover
    _HAS_NP = False


def apodization_window(n_x: int, kind: str = "boxcar"):
    """切趾窗 W(x)，x 下标 0..n_x-1。kind: boxcar/hamming/blackman_harris。"""
    if kind == "boxcar":
        return np.ones(n_x)
    if kind == "hamming":
        return 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(n_x) / (n_x - 1))
    if kind == "blackman_harris":
        a0, a1, a2, a3 = 0.35875, 0.48829, 0.14128, 0.01168
        n = np.arange(n_x)
        return (a0 - a1 * np.cos(2 * np.pi * n / (n_x - 1))
                + a2 * np.cos(4 * np.pi * n / (n_x - 1))
                - a3 * np.cos(6 * np.pi * n / (n_x - 1)))
    raise ValueError(f"未知切趾窗：{kind}")


def build_interferogram(t_nu, nu, x_max, n_x=0):
    """透射谱 → 干涉图：I(x_j) = Σ_k T(ν_k)·cos(2π ν_k x_j)·Δν。

    采样间隔按绝对波数奈奎斯特定：Δx = 1/(2·ν_Ny)，ν_Ny = 1.05·ν_max，
    保证载波 cos(2πνx)（ν≈2968 cm⁻¹）无混叠；n_x 由 x_max/Δx 自动决定。
    """
    x = np.linspace(0.0, x_max, n_x) if n_x > 0 else None
    dnu = (nu[-1] - nu[0]) / (len(nu) - 1)
    nu_ny = 1.05 * max(abs(float(nu[0])), abs(float(nu[-1])))
    dx = 1.0 / (2.0 * nu_ny)
    n_auto = int(x_max / dx) + 1
    if x is None or n_auto > n_x:
        x = np.linspace(0.0, x_max, n_auto)
    cos_m = np.cos(2 * np.pi * np.outer(x, nu))          # (n_x, n_nu)
    i_x = cos_m @ t_nu * dnu
    return x, i_x


def recover_spectrum(i_x, x, nu, window="boxcar"):
    """干涉图 → 恢复谱（未归一幅值）。

    幅值说明：离散余弦反演的整体比例依赖 ILS 归一与采样参数。工程 FTIR
    用非吸收区基线标定（见 _normalize_wing）使基线=1，这里返回 raw。
    """
    n_x = len(i_x)
    w = apodization_window(n_x, window)
    dx = (x[-1] - x[0]) / (n_x - 1) if n_x > 1 else 1.0
    cos_m = np.cos(2 * np.pi * np.outer(nu, x))          # (n_nu, n_x)
    num = (cos_m @ (i_x * w)) * dx
    den = w.sum() * dx
    return num / den if den > 0 else num


def _normalize_wing(t, nu, nu0, wing_half):
    """非吸收区基线标定：恢复谱除以翼区中位数（基线→1）。"""
    mask = np.abs(nu - nu0) > wing_half
    base = float(np.median(t[mask])) if mask.any() else 1.0
    return t / base if base != 0 else t


def _gaussian_spectrum(nu, nu0, alpha_pk, gamma_hwhm, L_cm, x):
    """内置解析吸收透射谱：T = exp(-x·α_pk·exp(-((ν-ν0)/γ)²)·L)。"""
    alpha = alpha_pk * np.exp(-((nu - nu0) / gamma_hwhm) ** 2)
    return np.exp(-alpha * L_cm * x)


def simulate(x=1e-5, L_cm=100.0, nu0=2968.41, nu_span=6.0, n_nu=601,
             x_max=2.0, n_x=401, window="boxcar",
             T=296.0, P=1.0, species="CH4", line_source="hitran", iso="all",
             alpha_pk_fallback=13.365, gamma_fallback=0.08,
             noise_frac=0.0, seed=0):
    """FTIR 正演：透射谱 → 干涉图 → 切趾恢复 → 分辨率披露 → 浓度反演。

    line_source: hitran（默认，失败自动降级高斯）/ gaussian。
    反演：对恢复谱做吸光度 −ln(T')，与纯组分 α·L 谱最小二乘 → x。
    """
    import sys
    from pathlib import Path
    _srv = Path(__file__).resolve().parent
    _root = _srv.parent
    for _p in (_root, _srv):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    if not _HAS_NP:
        raise RuntimeError("FTIR 需要 numpy（HITRAN core 已依赖，本机应可用）")

    # 边缘保护带：干涉图截断使恢复谱两端出现伪影（boxcar 亦存在，BH 更甚），
    # 模拟网格比分析区每侧多 pad（≥2×分辨率），恢复后只取分析区。
    dnu_res = 0.5 / x_max
    pad = max(0.3, 2.0 * dnu_res)
    nu_full = np.linspace(nu0 - nu_span / 2 - pad, nu0 + nu_span / 2 + pad, n_nu)
    nu = nu_full
    disclosure = []

    if line_source == "hitran":
        try:
            from spectrolink_core import hitran
            _nu, _alpha, _info = hitran.absorption(species, nu[0], nu[-1], T=T, P=P,
                                                   step=0.002, wingHW=5.0, iso=iso)
            alpha_pure = np.interp(nu, np.asarray(_nu), np.asarray(_alpha))
            src = "hitran"
        except Exception as e:
            disclosure.append(f"HITRAN 不可用（{type(e).__name__}: {str(e)[:120]}）→ 降级高斯演示谱")
            alpha_pure = alpha_pk_fallback * np.exp(-((nu - nu0) / gamma_fallback) ** 2)
            src = "gaussian_fallback"
    else:
        alpha_pure = alpha_pk_fallback * np.exp(-((nu - nu0) / gamma_fallback) ** 2)
        src = "gaussian"

    t_true = np.exp(-alpha_pure * L_cm * x)          # 真实透射谱
    xv, i_x = build_interferogram(t_true, nu, x_max, n_x)
    rng = np.random.default_rng(seed)
    if noise_frac > 0:
        i_x = i_x * (1.0 + rng.normal(0.0, noise_frac, i_x.shape))
    # 增益标定：恢复谱按非吸收区基线归一（翼区中位数→1）
    t_rec_raw = recover_spectrum(i_x, xv, nu, window)
    t_rec = _normalize_wing(t_rec_raw, nu, float(nu0), 0.8)
    # 裁剪边缘保护带 → 分析区（alpha_pure 同步裁剪，保证反演维度一致）
    keep = np.abs(nu - nu0) <= nu_span / 2
    nu, t_true, t_rec, alpha_pure = nu[keep], t_true[keep], t_rec[keep], alpha_pure[keep]

    # 恢复谱主峰 FWHM（沿吸收峰附近的凹陷宽度——用透射谱最小谷测量）
    t_min = float(t_rec.min())
    half = (1.0 + t_min) / 2.0
    below = nu[t_rec <= half]
    fwhm_obs = float(below[-1] - below[0]) if len(below) >= 2 else float("nan")

    # 浓度反演：吸光度谱 −ln(T_rec)，拟合 α_pure·L
    a_obs = -np.log(np.clip(t_rec, 1e-12, 1.0))
    a_pure_L = alpha_pure * L_cm
    denom = float(np.sum(a_pure_L ** 2))
    x_inv = float(np.sum(a_obs * a_pure_L) / denom) if denom > 0 else float("nan")

    return {
        "nu_range": [float(nu[0]), float(nu[-1])], "n_nu": n_nu,
        "x_max_cm": x_max, "n_x": n_x,
        "resolution_cm": round(dnu_res, 6),
        "fwhm_observed_cm": round(fwhm_obs, 6) if fwhm_obs == fwhm_obs else None,
        "x_truth": x, "x_inferred": round(x_inv, 9),
        "x_error_frac": round((x_inv - x) / x if x else 0.0, 9),
        "window": window, "line_source": src,
        "t_rec_min": round(t_min, 9),
        "interferogram": {"x_max": x_max, "n_x": n_x, "noise_frac": noise_frac},
        "disclosure": disclosure,
        "assumptions": {
            "x_max/window": "默认 ai 演示占位（2 cm / boxcar），真实仪器分辨率须用户提供",
            "L_cm": "光程默认演示占位 100 cm，须用户提供",
            "noise_frac": "干涉图相对高斯噪声（探测器/电子学）",
        },
        "source": "default=ai_demo_placeholder; 真实值须 datasheet/calibration/user 交互",
    }


def invert(t_rec_nu, alpha_pure_nu, L_cm):
    """恢复透射谱 → 吸光度谱 → 最小二乘浓度。输入为 numpy 数组。"""
    a_obs = -np.log(np.clip(np.asarray(t_rec_nu), 1e-12, 1.0))
    a_pure_L = np.asarray(alpha_pure_nu) * L_cm
    denom = float(np.sum(a_pure_L ** 2))
    return float(np.sum(a_obs * a_pure_L) / denom) if denom > 0 else float("nan")


def selftest():
    """数值锚点自检（离线，numpy 内置高斯谱）。"""
    fails = []
    if not _HAS_NP:
        return {"ok": False, "fails": ["numpy 不可用"]}
    # 全网格含保护带（模拟边缘截断伪影），分析区 = ν0 ± 3 cm⁻¹
    nu_full = np.linspace(2962.41, 2974.41, 1201)
    keep_an = np.abs(nu_full - 2968.41) <= 3.0

    def _run(t_true_full, x_max):
        xv, i_x = build_interferogram(t_true_full, nu_full, x_max, n_x=0)
        t = recover_spectrum(i_x, xv, nu_full, "boxcar")
        t = _normalize_wing(t, nu_full, 2968.41, 1.5)
        return t[keep_an]

    def _fwhm_robust(t):
        i0 = int(np.argmin(t))
        half = (1.0 + float(t[i0])) / 2.0
        il, ir = i0, i0
        while il > 0 and t[il] < half:
            il -= 1
        while ir < len(t) - 1 and t[ir] < half:
            ir += 1
        if il == i0 or ir == i0:
            return float("nan")
        return float(nu_full[keep_an][ir] - nu_full[keep_an][il])
    # 1) 往返：宽峰 γ=0.08，x_max=8，分析区中心（|ν−ν0|<0.3）误差 < 1.5%
    t_true = _gaussian_spectrum(nu_full, 2968.41, 13.365, 0.08, 100.0, 1e-5)
    t_rec = _run(t_true, 8.0)
    nu_an = nu_full[keep_an]
    t_true_an = t_true[keep_an]
    cent = np.abs(nu_an - 2968.41) < 0.3
    err_cent = float(np.max(np.abs(t_rec[cent] - t_true_an[cent])))
    if err_cent > 0.015:
        fails.append(f"往返中心误差超限 ({err_cent:.4f})")
    # 2) 分辨率缩放：窄峰 γ=0.02（峰深加大便于测量），boxcar，x_max 减半 → FWHM ≈ 2 倍
    t_narrow = _gaussian_spectrum(nu_full, 2968.41, 100.0, 0.02, 100.0, 1e-5)
    f8 = _fwhm_robust(_run(t_narrow, 8.0))
    f4 = _fwhm_robust(_run(t_narrow, 4.0))
    if not (1.4 < f4 / f8 < 3.0):
        fails.append(f"分辨率缩放不符 (f4/f8={f4 / f8:.2f})")
    # 3) 切趾属性：窗函数 DFT 旁瓣水平（教科书标准，与恢复谱欠分辨无关）
    #    boxcar ≈ −13 dB，hamming ≈ −42 dB，blackman_harris ≈ −92 dB，严格递减
    def _sidelobe_db(kind):
        n = 8192
        w = apodization_window(n, kind)
        spec = np.abs(np.fft.rfft(w, n * 4))   # 4x zero-pad：矩形窗 sinc 旁瓣在整数 bin 全零，须过采样
        spec /= spec.max()
        z = int(np.argmin(spec[1:80])) + 1     # 自适应第一零点（各窗主瓣宽度不同）
        side = spec[z + 1:]                    # 只取第一零点右侧旁瓣区（不含 DC 主瓣）
        return 20.0 * np.log10(max(float(side.max()), 1e-12))
    sdb_box = _sidelobe_db("boxcar")
    sdb_ham = _sidelobe_db("hamming")
    sdb_bh = _sidelobe_db("blackman_harris")
    if not (sdb_bh < sdb_ham < sdb_box):
        fails.append("切趾旁瓣序不符 (box={:.1f}, ham={:.1f}, bh={:.1f}) dB".format(sdb_box, sdb_ham, sdb_bh))
    if not (-16.0 < sdb_box < -10.0):
        fails.append("boxcar 旁瓣水平异常 ({:.1f} dB)".format(sdb_box))
    # 4) 反演：宽峰 + x_max=8，x 误差 < 5%
    sim = simulate(x=1e-5, line_source="gaussian", x_max=8.0, n_x=0,
                   alpha_pk_fallback=13.365, gamma_fallback=0.08)
    if abs(sim["x_error_frac"]) > 0.05:
        fails.append("高分辨率反演误差超限")
    return {
        "ok": not fails, "fails": fails,
        "anchors": {"roundtrip_cent_err@8cm": round(err_cent, 6),
                    "fwhm_ratio(4cm/8cm,narrow)": round(f4 / f8, 3),
                    "sidelobe_db_boxcar": round(sdb_box, 2),
                    "sidelobe_db_hamming": round(sdb_ham, 2),
                    "sidelobe_db_bh": round(sdb_bh, 2),
                    "gauss_inv_err": sim["x_error_frac"]},
    }
