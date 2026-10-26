# -*- coding: utf-8 -*-
"""spectrolink_core/lockin.py — 正交锁相公共算法。

两个技术共用：
- TDLAS: 时域信号 → 混频 → 低通 → X/Y → 相位旋转 → R
- LITES: 吸收谱 → 局部调制窗 → 整周期平均 → X/Y → 相位旋转 → R

公共部分：X/Y → 最优相位旋转 → R/同相分量。
"""
import numpy as np
import math


def phase_rotate(X, Y, center_idx=None):
    """正交两路 X/Y → 最优相位旋转后的同相分量 + 幅值。

    参数:
        X, Y: np.ndarray，正交解调后的两路（任意长度）
        center_idx: 线中心索引。None 则自动选 |X+Y| 最大的点。

    返回:
        dict:
            R: 幅值 √(X²+Y²)，与参考相位无关（工程锁相输出）
            Xp: 相位旋转后的同相分量（峰中心为正峰、两侧负瓣）
            phi_opt_rad: 最优相位（弧度）
    """
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    R = np.sqrt(X * X + Y * Y)

    if center_idx is None:
        center_idx = int(np.argmax(R))

    phi = math.atan2(Y[center_idx], X[center_idx])
    # 确保中心峰为正
    if X[center_idx] * math.cos(phi) + Y[center_idx] * math.sin(phi) < 0.0:
        phi += math.pi

    Xp = X * math.cos(phi) + Y * math.sin(phi)
    return {"R": R, "Xp": Xp, "phi_opt_rad": phi}


def harmonic_demod_time(S, t, fs, fm, n, n_cycle_avg=1, n_stages=2,
                         lock_kind="boxcar", cutoff_ratio=0.25,
                         zero_phase=False):
    """时域正交锁相（TDLAS 用）。

    与原 tdlas_sim.wms_harmonic_lockin 完全一致，抽到 core 共享。
    """
    w = 2.0 * np.pi * fm
    S = np.asarray(S, dtype=float)
    X = S * np.cos(n * w * t)
    Y = S * np.sin(n * w * t)

    if str(lock_kind).lower() == "butter":
        from scipy.signal import butter as _butter, filtfilt as _ff, lfilter as _lf
        b, a = _butter(int(n_stages), cutoff_ratio * fm / (0.5 * float(fs)), btype="low")
        if zero_phase:
            X, Y = _ff(b, a, X), _ff(b, a, Y)
        else:
            X, Y = _lf(b, a, X), _lf(b, a, Y)
    else:
        # boxcar
        win = max(1, int(round(n_cycle_avg * fs / fm)))
        ker = np.ones(win) / win
        if zero_phase:
            from scipy.signal import filtfilt as _ff
            for _ in range(max(1, int(n_stages))):
                X, Y = _ff(ker, [1.0], X), _ff(ker, [1.0], Y)
        else:
            for _ in range(max(1, int(n_stages))):
                X = np.convolve(X, ker, mode="same")
                Y = np.convolve(Y, ker, mode="same")

    res = phase_rotate(X, Y)
    return res["R"], X, Y
