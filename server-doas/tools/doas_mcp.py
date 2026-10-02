#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DOAS 仪器级仿真 MCP 服务器（stdio JSON-RPC 2024-11-05）。

工具面：
  · t_doas_forward    单浓度正演（宽带源/吸收/差分反演披露）
  · t_doas_calibrate  浓度扫描标定曲线（线性拟合 + R²）
  · t_doas_invert     实测谱 → 差分反演浓度（用户传 I/i0/sigma 数组）
  · t_doas_selftest   数值锚点自检

纪律：纯标准库 stdio JSON-RPC；print 只走协议 stdout；
参考截面/源包络/光程默认均为 ai 演示占位，真实器件参数须用户交互提供。

自测：python tools/doas_mcp.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SRV = Path(__file__).resolve().parent.parent          # server-doas
_ROOT = _SRV.parent
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import doas_physics as dph  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "doas", "version": "0.1.0"}}

_HOME = str(Path.home())
_WS_ROOT = str(_ROOT.parent)


def _sanitize_paths(obj):
    if isinstance(obj, str):
        s = obj
        if _WS_ROOT and _WS_ROOT.lower() in s.lower():
            s = s.replace(_WS_ROOT, "<workspace>")
        if _HOME and _HOME.lower() in s.lower():
            s = s.replace(_HOME, "<home>")
        return s
    if isinstance(obj, list):
        return [_sanitize_paths(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _sanitize_paths(v) for k, v in obj.items()}
    return obj


# ── 工具实现 ──────────────────────────────────────────────

def t_doas_forward(x=5e-6, L_cm=50.0, species="NO2", wl_min=400.0, wl_max=500.0,
                   n_wl=401, T=296.0, P=1.0, poly_deg=3, noise_frac=0.0, seed=0):
    """单浓度 DOAS 正演。x 为摩尔分数（1e-6=1ppm）。λ 单位 nm。

    ⚠️ 参考截面/源包络/L 默认是 ai 演示占位（NO₂ 448 nm 量级），
    真实截面须用户提供（HITRAN xsc 或实测），未提供前不可作定量结论。
    """
    out = dph.forward(x, L_cm, species, wl_min, wl_max, n_wl, T, P, poly_deg,
                      noise_frac, seed)
    out["validation"] = {"overall": "warn",
                         "note": "默认截面/源为演示占位，未标定前不可作定量结论"}
    return out


def t_doas_calibrate(x_min=0.0, x_max=2e-5, n=11, L_cm=50.0, species="NO2",
                     T=296.0, P=1.0, poly_deg=3, noise_frac=0.0, seed=0):
    """浓度扫描标定：x_min..x_max 等距 n 点 → 反演浓度表 + 线性拟合。"""
    return dph.calibrate(x_min, x_max, n, L_cm, species, T, P, poly_deg,
                         noise_frac, seed)


def t_doas_invert(I=None, i0=None, sigma=None, L_cm=50.0, poly_deg=3):
    """实测谱 → 差分反演浓度（等长数组 I/i0/sigma；不传数组给用法提示）。"""
    if I is None or i0 is None or sigma is None:
        return {"usage": "传等长数值数组 I（实测光强）、i0（参考光强）、sigma（吸收截面 cm²/molecule）",
                "x": None}
    return dph.invert(I, i0, sigma, L_cm, poly_deg)


def t_doas_selftest():
    """数值锚点自检（离线，不依赖网络）。"""
    return dph.selftest()


TOOLS = [
    {"name": "t_doas_forward",
     "description": "DOAS 单浓度正演：宽带源包络→分子吸收→差分反演披露。x 摩尔分数（1e-6=1ppm），λ 单位 nm。默认截面/源为演示占位（NO₂ 448 nm 量级），真实截面须用户提供。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x": {"type": "number", "description": "摩尔分数，1e-6=1ppm", "default": 5e-6},
                         "L_cm": {"type": "number", "default": 50.0},
                         "species": {"type": "string", "enum": ["NO2", "SO2", "O3"], "default": "NO2"},
                         "wl_min": {"type": "number", "description": "波段下限 nm", "default": 400.0},
                         "wl_max": {"type": "number", "default": 500.0},
                         "n_wl": {"type": "integer", "default": 401},
                         "T": {"type": "number", "default": 296.0},
                         "P": {"type": "number", "description": "气压 atm", "default": 1.0},
                         "poly_deg": {"type": "integer", "description": "慢变背景多项式阶数", "default": 3},
                         "noise_frac": {"type": "number", "description": "相对高斯噪声 σ", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_doas_calibrate",
     "description": "DOAS 浓度扫描标定：x_min..x_max 等距 n 点 → 反演浓度表 + 线性拟合（slope/R²/max_abs_err）。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x_min": {"type": "number", "default": 0.0},
                         "x_max": {"type": "number", "default": 2e-5},
                         "n": {"type": "integer", "default": 11},
                         "L_cm": {"type": "number", "default": 50.0},
                         "species": {"type": "string", "enum": ["NO2", "SO2", "O3"], "default": "NO2"},
                         "T": {"type": "number", "default": 296.0},
                         "P": {"type": "number", "default": 1.0},
                         "poly_deg": {"type": "integer", "default": 3},
                         "noise_frac": {"type": "number", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_doas_invert",
     "description": "DOAS 实测谱差分反演：c = argmin ‖ln(I0/I)−P(λ)−σ·L·c‖²。传等长数组 I/i0/sigma。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "I": {"type": "array", "items": {"type": "number"}, "description": "实测光强"},
                         "i0": {"type": "array", "items": {"type": "number"}, "description": "参考光强"},
                         "sigma": {"type": "array", "items": {"type": "number"}, "description": "吸收截面 cm²/molecule"},
                         "L_cm": {"type": "number", "default": 50.0},
                         "poly_deg": {"type": "integer", "default": 3}}}},
    {"name": "t_doas_selftest",
     "description": "DOAS 数值锚点自检（离线）。",
     "inputSchema": {"type": "object", "properties": {}}},
]


# ── MCP 协议层 ────────────────────────────────────────────

def handle_request(req):
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}
    if isinstance(params, list):
        args, kwargs = (list(params), {})
    elif isinstance(params, dict):
        args, kwargs = ([], dict(params))
    else:
        args, kwargs = ([], {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": SERVER_INFO}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = kwargs.get("name") or (args[0] if args else "")
        arguments = kwargs.get("arguments") or {}
        fn = {"t_doas_forward": t_doas_forward,
              "t_doas_calibrate": t_doas_calibrate,
              "t_doas_invert": t_doas_invert,
              "t_doas_selftest": t_doas_selftest}.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"未知工具：{name}"}}
        try:
            out = fn(**arguments)
        except TypeError as exc:
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"参数错误：{exc}"}],
                "isError": True}}
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": json.dumps(_sanitize_paths(out), ensure_ascii=False)}]}}
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"未知方法：{method}"}}


def main():
    if "--selftest" in sys.argv:
        sys.stdout.write(json.dumps(_sanitize_paths(dph.selftest()), ensure_ascii=False) + "\n")
        return 0 if dph.selftest()["ok"] else 2
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
