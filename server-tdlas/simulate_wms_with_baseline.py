# -*- coding: utf-8 -*-
"""
实测基线版 WMS 仿真：用 0 ppm 实测信号做基线，叠加理论吸收。

用法：
    python simulate_wms_with_baseline.py \
        --species CO --wn_center 2183.22 --x 6e-6 --L 2500 \
        --baseline-das zero_das.txt \
        --baseline-wms zero_wms.txt \
        --out sim_6ppm.png

baseline_das: 两列文件 (wavenumber_cm-1, voltage_V) —— 氮气背景不调制的原始信号
baseline_wms: 两列文件 (time_s, voltage_V) —— 氮气背景调制的原始信号（含 RAM）
"""
import os, sys, argparse
import numpy as np

# SpectroLink 路径
sys.path.insert(0, r"D:\software\skills\spectrolink")
import spectrolink_core.hitran as H

# 缓存目录：优先环境变量，其次 workspace 里已有的
from pathlib import Path
import os
_ws = Path(r"C:\Users\16565\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\.sessions\38438958201506050\agents\m_0cwErZhKX6s") / "Hitran_Data"
H._DATA_DIR = Path(os.environ.get("SPECTROLINK_DATA_DIR", str(_ws)))
H._DB_READY = False


def load_two_col(filename):
    """读两列数据文件：跳过注释行，返回 (col1, col2)"""
    data = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                data.append([float(parts[0]), float(parts[1])])
    arr = np.array(data)
    return arr[:, 0], arr[:, 1]


def simulate_wms_with_baseline(
    species="CO",
    wn_center=2183.22,
    T=296.0,
    P=1.0,
    x=6e-6,          # 摩尔分数
    L=2500.0,        # cm
    scan_span=2.0,   # cm^-1
    mod_depth=0.25,  # cm^-1 调制深度
    baseline_das_file=None,
    baseline_wms_file=None,
    fs=100000.0,     # 采样率 Hz
    fm=1000.0,       # 调制频率 Hz
    n_scan_periods=5,  # 扫描周期数
):
    """用实测基线做 WMS 仿真。"""

    # 1. 算理论吸收系数
    numin = wn_center - scan_span/2 - 1.0
    numax = wn_center + scan_span/2 + 1.0
    nu, alpha_pure, _ = H.absorption(species, numin, numax, T=T, P=P, step=0.001, wingHW=30.0)
    alpha = alpha_pure * x
    print(f"理论 α peak = {alpha.max():.3e} cm^-1")

    # 2. 时间轴
    n_per_scan = int(fs / 10)  # 每个扫描周期 fs/10 点
    n_samples = n_per_scan * n_scan_periods
    t = np.arange(n_samples) / fs
    fscan = 10.0  # Hz，扫描频率

    # 3. 瞬时波数 ν(t) = 扫描 + 调制
    # 三角波扫描
    scan_phase = 2 * np.pi * fscan * t
    wn_scan = wn_center + (scan_span/2) * (2/np.pi) * np.arcsin(np.sin(scan_phase))
    # 加正弦调制
    nu_t = wn_scan + mod_depth * np.cos(2 * np.pi * fm * t)

    # 4. 理论透过率 τ_theory(t) = exp(-α(ν(t))·L)
    alpha_t = np.interp(nu_t, nu, alpha)
    tau_theory = np.exp(-alpha_t * L)

    # 5. 叠加实测基线
    if baseline_das_file:
        # 不调制基线：I0(ν) → 插值到 ν(t)
        wn0_das, v0_das = load_two_col(baseline_das_file)
        I0_nu = np.interp(nu_t, wn0_das, v0_das)
        I0_mean = I0_nu.mean()
        # 归一化：让基线均值 = 1
        tau_measured = I0_nu / I0_mean
        print(f"DAS 基线: {len(wn0_das)} points, mean={I0_mean:.3f} V")
    else:
        tau_measured = np.ones_like(t)
        print("无 DAS 基线，用理想 I0=1")

    if baseline_wms_file:
        # 调制基线：I0_mod(t) → 直接乘到信号上
        t0_wms, v0_wms = load_two_col(baseline_wms_file)
        # 插值到当前时间轴
        I0_mod_t = np.interp(t, t0_wms, v0_wms)
        I0_mod_mean = I0_mod_t.mean()
        I0_mod_norm = I0_mod_t / I0_mod_mean
        print(f"WMS 基线: {len(t0_wms)} points, mean={I0_mod_mean:.3f} V")
    else:
        I0_mod_norm = np.ones_like(t)
        print("无 WMS 基线，用理想 I0=1")

    # 6. 最终仿真信号
    v_adc = I0_mod_norm * tau_theory * tau_measured

    # 7. 数字锁相解调（简化）
    # 正交解调：乘以 sin/cos(2πfm t)，低通滤波
    ref_sin = np.sin(2 * np.pi * fm * t)
    ref_cos = np.cos(2 * np.pi * fm * t)

    # 滑动平均窗口 = 一个调制周期
    n_per_mod = int(fs / fm)
    kernel = np.ones(n_per_mod) / n_per_mod

    X1f = np.convolve(v_adc * ref_cos, kernel, mode="same")
    Y1f = np.convolve(v_adc * ref_sin, kernel, mode="same")
    S1f = np.sqrt(X1f**2 + Y1f**2)

    X2f = np.convolve(v_adc * np.cos(4 * np.pi * fm * t), kernel, mode="same")
    Y2f = np.convolve(v_adc * np.sin(4 * np.pi * fm * t), kernel, mode="same")
    S2f = np.sqrt(X2f**2 + Y2f**2)

    return {
        "t": t,
        "nu_t": nu_t,
        "v_adc": v_adc,
        "S1f": S1f,
        "S2f": S2f,
        "tau_theory": tau_theory,
        "alpha": alpha,
        "nu": nu,
        "meta": {
            "species": species,
            "wn_center": wn_center,
            "x": x,
            "L": L,
            "baseline_das": baseline_das_file is not None,
            "baseline_wms": baseline_wms_file is not None,
        }
    }


if __name__ == "__main__":
    # 演示：没有实测基线时跑一下
    r = simulate_wms_with_baseline(
        species="CO",
        wn_center=2183.22,
        x=6e-6,
        L=2500.0,
    )
    print(f"2f peak = {r['S2f'].max():.4f}")
    print("演示完成。有实测基线文件时传 --baseline-das / --baseline-wms")
