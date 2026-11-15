#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FTIR 仪器级仿真 MCP 服务器（stdio JSON-RPC 2024-11-05）。

工具面：
  · t_ftir_simulate   透射谱 → 干涉图 → 切趾恢复 → 分辨率披露 → 浓度反演
  · t_ftir_invert     恢复透射谱 → 浓度（最小二乘）
  · t_ftir_selftest   数值锚点自检（离线）

纪律：纯标准库 stdio JSON-RPC；参数默认值均为 ai 演示占位，
真实仪器参数（X_max/切趾）须用户交互提供。

自测：python tools/ftir_mcp.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SRV = Path(__file__).resolve().parent.parent          # server-ftir
_ROOT = _SRV.parent
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ftir_physics as fph  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "ftir", "version": "0.1.0"}}

_HOME = str(Path.home())
_WS_ROOT = str(_ROOT.parent)

from spectrolink_core.mcp_runtime import (                     # noqa: E402
    make_handle_request, schema_index, serve_stdio)
from spectrolink_core.sanitize import make_path_sanitizer      # noqa: E402

_sanitize_paths = make_path_sanitizer(_WS_ROOT, _HOME)


# ── 工具实现 ──────────────────────────────────────────────

def t_ftir_simulate(x=1e-5, L_cm=100.0, nu0=2968.41, nu_span=6.0, n_nu=601,
                    x_max=2.0, n_x=401, window="boxcar",
                    T=296.0, P=1.0, species="CH4", line_source="hitran", iso="all",
                    alpha_pk_fallback=13.365, gamma_fallback=0.08,
                    noise_frac=0.0, seed=0):
    """FTIR 正演。x 摩尔分数；x_max 最大光程差 [cm]（分辨率≈0.5/x_max）；
    window: boxcar/hamming/blackman_harris。
    ⚠️ 默认参数 ai 演示占位，真实仪器参数须用户提供。
    """
    out = fph.simulate(x, L_cm, nu0, nu_span, n_nu, x_max, n_x, window,
                       T, P, species, line_source, iso,
                       alpha_pk_fallback, gamma_fallback, noise_frac, seed)
    out["validation"] = {"overall": "warn",
                         "note": "默认参数为演示占位；line_source 降级时不得当实测谱"}
    return out


def t_ftir_invert(t_rec_nu=None, alpha_pure_nu=None, L_cm=100.0):
    """恢复透射谱 → 浓度（最小二乘）。t_rec_nu/alpha_pure_nu 为等长数组。
    不传数组时给出用法提示（无内置实测谱，需用户提供）。"""
    if t_rec_nu is None or alpha_pure_nu is None:
        return {"usage": "传等长数值数组 t_rec_nu（恢复透射谱）与 alpha_pure_nu（纯组分吸收 cm⁻¹）",
                "x": None}
    import numpy as np
    x = fph.invert(np.asarray(t_rec_nu), np.asarray(alpha_pure_nu), L_cm)
    return {"x": round(x, 9), "x_ppm": round(x * 1e6, 6),
            "formula": "x = argmin ‖−ln(T′) − α_pure·L·x‖²"}


def t_ftir_selftest():
    """数值锚点自检（离线）。"""
    return fph.selftest()


TOOLS = [
    {"name": "t_ftir_simulate",
     "description": "FTIR 正演：透射谱→干涉图→切趾恢复→分辨率披露→浓度反演。window: boxcar/hamming/blackman_harris。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x": {"type": "number", "description": "摩尔分数，1e-6=1ppm", "default": 1e-5},
                         "L_cm": {"type": "number", "default": 100.0},
                         "nu0": {"type": "number", "default": 2968.41},
                         "nu_span": {"type": "number", "default": 6.0},
                         "n_nu": {"type": "integer", "default": 601},
                         "x_max": {"type": "number", "description": "最大光程差 [cm]，分辨率≈0.5/x_max", "default": 2.0},
                         "n_x": {"type": "integer", "default": 401},
                         "window": {"type": "string", "description": "boxcar/hamming/blackman_harris", "default": "boxcar"},
                         "T": {"type": "number", "default": 296.0},
                         "P": {"type": "number", "default": 1.0},
                         "species": {"type": "string", "default": "CH4"},
                         "line_source": {"type": "string", "description": "hitran/gaussian", "default": "hitran"},
                         "iso": {"type": "string", "default": "all"},
                         "alpha_pk_fallback": {"type": "number", "default": 13.365},
                         "gamma_fallback": {"type": "number", "default": 0.08},
                         "noise_frac": {"type": "number", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_ftir_invert",
     "description": "恢复透射谱 → 浓度最小二乘反演（需用户提供实测恢复谱与纯组分谱数组）。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "t_rec_nu": {"type": "array", "items": {"type": "number"},
                                      "description": "恢复透射谱 T′(ν) 数组"},
                         "alpha_pure_nu": {"type": "array", "items": {"type": "number"},
                                           "description": "纯组分吸收 α(ν) [cm⁻¹] 数组"},
                         "L_cm": {"type": "number", "default": 100.0}}}},
    {"name": "t_ftir_selftest",
     "description": "FTIR 数值锚点自检（离线）。",
     "inputSchema": {"type": "object", "properties": {}}},
]

DISPATCH = {t["name"]: globals()[t["name"]] for t in TOOLS}


# ── 参数校验 / JSON-RPC（共用 spectrolink_core.mcp_runtime）────────────

_SCHEMA_BY_NAME = schema_index(TOOLS)

# 严格口径（必填 / 未知键 / 类型）与其余 server 完全一致；返回值路径在此脱敏
handle_request = make_handle_request(SERVER_INFO, TOOLS, DISPATCH,
                                     _SCHEMA_BY_NAME, sanitize=_sanitize_paths)


def main():
    if "--selftest" in sys.argv:
        try:
            print(json.dumps(_sanitize_paths(t_ftir_selftest()), ensure_ascii=False, indent=2))
        except ImportError as exc:
            sys.stderr.write(f"[ftir-mcp] 自检无法运行：{exc}\n")
            raise SystemExit(2)
        return 0
    return serve_stdio(handle_request)


if __name__ == "__main__":
    main()
