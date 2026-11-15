#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CRDS 仪器级仿真 MCP 服务器（stdio JSON-RPC 2024-11-05）。

工具面：
  · t_crds_simulate   谱扫描正演：τ(ν) 曲线 + 吸收峰 ring-down 拟合 + 浓度反演
  · t_crds_ringdown   单点 ring-down 波形生成 + 拟合
  · t_crds_invert     测量 τ → 浓度（解析）
  · t_crds_selftest   数值锚点自检（离线）

纪律：纯标准库 stdio JSON-RPC；参数默认值均为 ai 演示占位，
真实腔参数（R/L）须用户交互提供。

自测：python tools/crds_mcp.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_SRV = Path(__file__).resolve().parent.parent          # server-crds
_ROOT = _SRV.parent
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import crds_physics as cph  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "crds", "version": "0.1.0"}}

_HOME = str(Path.home())
_WS_ROOT = str(_ROOT.parent)

from spectrolink_core.mcp_runtime import (                     # noqa: E402
    make_handle_request, schema_index, serve_stdio)
from spectrolink_core.sanitize import make_path_sanitizer      # noqa: E402

_sanitize_paths = make_path_sanitizer(_WS_ROOT, _HOME)


# ── 工具实现 ──────────────────────────────────────────────


def _mpl_cjk():
    import matplotlib
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False


def _plot_crds(L_m, R, x, nu0, nu_span, n_nu, T, P, species, iso,
               alpha_pk_fallback, gamma_fallback, fit_noise, seed, out_path):
    """CRDS 2×2 横版出图：(a) τ(ν) 衰荡时间谱 (b) α(ν) 单程吸收谱
    (c) 峰位 ring-down + 对数线性拟合 (d) τ 峰缩短 vs 浓度（动态范围）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _mpl_cjk()
    plt.rcParams.update({"font.size": 10.5, "axes.grid": True,
                         "grid.alpha": 0.3, "figure.facecolor": "white",
                         "axes.facecolor": "white"})

    nu = np.linspace(nu0 - nu_span / 2.0, nu0 + nu_span / 2.0, n_nu)
    alpha_pure = None
    try:
        from spectrolink_core import hitran
        _nu, _alpha, _info = hitran.absorption(species, nu[0], nu[-1], T=T, P=P,
                                               step=0.002, wingHW=5.0, iso=iso)
        alpha_pure = np.interp(nu, _nu, _alpha)
        src = "hitran"
    except Exception:      # 刻意宽：HITRAN 无网络/无缓存/无该分子任一失败都走演示谱
        alpha_pure = _gauss(nu, nu0, alpha_pk_fallback, gamma_fallback)
        src = "gaussian_fallback"          # 返回体 src 会显式标注，不冒充真实谱
    a_pk = float(np.max(alpha_pure))
    tau0 = cph.tau_cavity(L_m, R)
    tau = np.array([cph.tau_with_absorption(L_m, R, a * x) for a in alpha_pure])
    tau_pk = float(np.min(tau))

    # ring-down 峰处拟合演示：窗口覆盖 ~3.6×τ0（完整衰减）
    t = np.linspace(0.0, 12e-6, 241)
    i_sig = cph.ring_down(t.tolist(), tau_pk, 1.0, fit_noise, seed)
    fit = cph.fit_tau(t.tolist(), i_sig)
    tau_fit = fit["tau_s"] if fit else float("nan")

    fig, ax = plt.subplots(2, 2, figsize=(11, 9))

    # (a) τ(ν)
    ax[0, 0].plot(nu, tau * 1e6, lw=1.6, color="#d62728")
    ax[0, 0].axhline(tau0 * 1e6, ls="--", c="gray", lw=0.8,
                     label=f"空腔 τ₀={tau0*1e6:.2f} μs")
    ax[0, 0].annotate(f"τ_peak={tau_pk*1e6:.2f} μs（缩短 "
                      f"{(1-tau_pk/tau0)*100:.1f}%）",
                      xy=(nu[np.argmin(tau)], tau_pk * 1e6),
                      xytext=(nu0 - 0.35 * nu_span, tau0 * 1e6 * 0.55),
                      fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=0.6))
    ax[0, 0].set_title("(a) 衰荡时间 τ(ν)")
    ax[0, 0].set_xlabel(r"波数 (cm$^{-1}$)")
    ax[0, 0].set_ylabel("τ (μs)")
    ax[0, 0].legend(fontsize=8.5)

    # (b) α(ν) 单程吸收
    ax[0, 1].plot(nu, alpha_pure * x * (L_m * 100.0), lw=1.6, color="#1f77b4")
    ax[0, 1].annotate(f"αL_peak={a_pk*x*(L_m*100.0):.2e}",
                      xy=(nu[np.argmax(alpha_pure)], a_pk * x * (L_m * 100.0)),
                      xytext=(nu0 + 0.1 * nu_span, a_pk * x * (L_m * 100.0) * 0.55),
                      fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=0.6))
    ax[0, 1].set_title("(b) 单程吸收 α(ν)·L")
    ax[0, 1].set_xlabel(r"波数 (cm$^{-1}$)")
    ax[0, 1].set_ylabel("αL")
    ax[0, 1].ticklabel_format(style="sci", axis="y", scilimits=(0, 0))

    # (c) ring-down + 拟合
    ax[1, 0].plot(t * 1e6, i_sig, lw=1.2, color="#2ca02c", label="ring-down")
    if fit:
        ax[1, 0].plot(t * 1e6, np.exp(-t / tau_fit), lw=1.0, ls="--", color="#d62728",
                      label=f"拟合 τ={tau_fit*1e6:.2f} μs (R²={fit['r2']:.3f})")
    ax[1, 0].set_title("(c) 峰位 ring-down 波形 + 对数线性拟合")
    ax[1, 0].set_xlabel("时间 t (μs)")
    ax[1, 0].set_ylabel("I/I₀")
    ax[1, 0].legend(fontsize=8.5)

    # (d) τ 峰缩短 vs 浓度（动态范围，ppb 刻度）
    # 判据 αL/(1-R) ≲ 0.1：R=0.999, L=1m 时界限 x0 ≈ 0.1·(1-R)/(a_pk·L_cm)
    _L_cm = L_m * 100.0
    _x_lim = 0.1 * (1.0 - R) / (a_pk * _L_cm)  # 摩尔分数
    xs = np.array([0, 10, 20, 50, 75, 100, 200, 500, 1000.0]) * 1e-9
    tp = np.array([cph.tau_with_absorption(L_m, R, a_pk * xq) for xq in xs])
    ax[1, 1].semilogy(xs * 1e9, tp * 1e6, "o-", color="#ff7f0e", lw=1.3)
    ax[1, 1].axhline(tau0 * 1e6, ls="--", c="gray", lw=0.8)
    ax[1, 1].axvline(_x_lim * 1e9, ls=":", c="#d62728", lw=0.8)
    ax[1, 1].annotate(f"可测界限 ≈{_x_lim*1e9:.0f} ppb\n(αL/(1-R)=0.1)",
                      xy=(_x_lim * 1e9, tau0 * 1e6 * 0.30), fontsize=9.5,
                      color="#d62728", ha="center",
                      bbox=dict(fc="white", ec="#d62728", lw=0.5, alpha=0.85))
    ax[1, 1].set_title("(d) τ_peak 动态范围（0–1000 ppb）")
    ax[1, 1].set_xlabel("浓度 (ppb)")
    ax[1, 1].set_ylabel("τ_peak (μs)")

    fig.suptitle(
        f"CRDS 腔衰荡仿真 · {species} {nu0:.3f}±{nu_span/2:.2f} cm-1 "
        f"| L={L_m} m, R={R}, x={x*1e9:.0f} ppb, {src}",
        fontsize=12, wrap=True)
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    from pathlib import Path as _P
    out_path = _P(out_path) if out_path else _P("crds_simulate.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path), dpi=150)
    plt.close(fig)
    return str(out_path)


def _gauss(nu, nu0, a_pk, gamma):
    return a_pk * gamma ** 2 / ((nu - nu0) ** 2 + gamma ** 2)


def t_crds_simulate(L_m=1.0, R=0.999, x=1e-5, nu0=2968.41, nu_span=2.0, n_nu=201,
                    T=296.0, P=1.0, species="CH4", line_source="hitran", iso="all",
                    alpha_pk_fallback=13.365, gamma_fallback=0.05,
                    fit_noise=0.0, seed=0, save_png=False,
                    out_path=None):
    """CRDS 谱扫描正演。line_source: hitran（默认，离线自动降级高斯）/ gaussian。

    ⚠️ L_m/R 默认 ai 演示占位，真实腔参数须用户提供。
    """
    out = cph.simulate(L_m, R, x, nu0, nu_span, n_nu, T, P, species,
                       line_source, iso, alpha_pk_fallback, gamma_fallback,
                       fit_noise, seed)
    if save_png:
        out["png"] = _plot_crds(L_m, R, x, nu0, nu_span, n_nu, T, P,
                                species, iso, alpha_pk_fallback,
                                gamma_fallback, fit_noise, seed, out_path)
    out["validation"] = {"overall": "warn",
                         "note": "默认参数为演示占位；line_source=hitran 但谱源降级时不得当实测谱"}
    return out


def t_crds_ringdown(tau_s=3.333e-6, i0=1.0, t_end=2e-5, n_pts=201,
                    noise_frac=0.0, seed=0):
    """单点 ring-down 波形生成 + 对数线性拟合，返回 τ 估计与 R²。"""
    t = [t_end * i / (n_pts - 1) for i in range(n_pts)]
    i_sig = cph.ring_down(t, tau_s, i0, noise_frac, seed)
    fit = cph.fit_tau(t, i_sig)
    return {"tau_truth": tau_s, "tau_fit": fit["tau_s"] if fit else None,
            "i0_fit": fit["i0_fit"] if fit else None,
            "tau_err_frac": round(abs(fit["tau_s"] - tau_s) / tau_s, 9) if fit else None,
            "r2": fit["r2"] if fit else None, "n_pts": n_pts,
            "formula": "τ = −1/斜率(ln I vs t)；α = 1/(cτ) − (1−R)/L"}


def t_crds_invert(tau_meas=3.2e-6, L_m=1.0, R=0.999, alpha_pure_pk=13.365):
    """测量衰荡时间 → 单程吸收 → 浓度 x = α/α_pure_pk。"""
    alpha = cph.alpha_from_tau(tau_meas, L_m, R)
    x = cph.invert(tau_meas, L_m, R, alpha_pure_pk)
    return {"alpha_cm": round(alpha, 9), "x": round(x, 9), "x_ppm": round(x * 1e6, 6)}


def t_crds_selftest():
    """数值锚点自检（离线）。"""
    return cph.selftest()


TOOLS = [
    {"name": "t_crds_simulate",
     "description": "CRDS 谱扫描正演：τ(ν) 曲线、吸收峰 ring-down 拟合、浓度反演。line_source=hitran 用 HITRAN 纯组分谱（离线自动降级高斯并披露）。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "L_m": {"type": "number", "description": "腔长 [m]，默认演示占位 1.0", "default": 1.0},
                         "R": {"type": "number", "description": "镜面反射率，默认演示占位 0.999", "default": 0.999},
                         "x": {"type": "number", "description": "摩尔分数，1e-6=1ppm", "default": 1e-5},
                         "nu0": {"type": "number", "description": "中心波数 [cm⁻¹]", "default": 2968.41},
                         "nu_span": {"type": "number", "default": 2.0},
                         "n_nu": {"type": "integer", "default": 201},
                         "T": {"type": "number", "default": 296.0},
                         "P": {"type": "number", "description": "总压 [atm]", "default": 1.0},
                         "species": {"type": "string", "default": "CH4"},
                         "line_source": {"type": "string", "description": "hitran/gaussian", "default": "hitran"},
                         "iso": {"type": "string", "description": "同位素：None=主同位素, all=全部按丰度", "default": "all"},
                         "alpha_pk_fallback": {"type": "number", "default": 13.365},
                         "gamma_fallback": {"type": "number", "default": 0.05},
                         "fit_noise": {"type": "number", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_crds_ringdown",
     "description": "单点 ring-down 波形生成 + 对数线性拟合 → τ 估计。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "tau_s": {"type": "number", "default": 3.333e-6},
                         "i0": {"type": "number", "default": 1.0},
                         "t_end": {"type": "number", "default": 2e-5},
                         "n_pts": {"type": "integer", "default": 201},
                         "noise_frac": {"type": "number", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_crds_invert",
     "description": "测量 τ → α = 1/(cτ)−(1−R)/L → 浓度 x = α/α_pure_pk。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "tau_meas": {"type": "number", "default": 3.2e-6},
                         "L_m": {"type": "number", "default": 1.0},
                         "R": {"type": "number", "default": 0.999},
                         "alpha_pure_pk": {"type": "number", "description": "纯组分吸收峰 [cm⁻¹]", "default": 13.365}}}},
    {"name": "t_crds_selftest",
     "description": "CRDS 数值锚点自检（离线）。",
     "inputSchema": {"type": "object", "properties": {}}},
]

DISPATCH = {t["name"]: globals()[t["name"]] for t in TOOLS}


# ── 参数校验 / JSON-RPC（共用 spectrolink_core.mcp_runtime）────────────

_SCHEMA_BY_NAME = schema_index(TOOLS)

# 严格口径（必填 / 未知键 / 类型）与其余 server 完全一致；返回值路径在此脱敏
handle_request = make_handle_request(SERVER_INFO, TOOLS, DISPATCH,
                                     _SCHEMA_BY_NAME, sanitize=_sanitize_paths)


def main():
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if "--selftest" in sys.argv:
        try:
            print(json.dumps(_sanitize_paths(t_crds_selftest()), ensure_ascii=False, indent=2))
        except ImportError as exc:
            sys.stderr.write(f"[crds-mcp] 自检无法运行：{exc}\n")
            raise SystemExit(2)
        return 0
    return serve_stdio(handle_request)


if __name__ == "__main__":
    main()
