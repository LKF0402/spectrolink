#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NDIR 仪器级仿真 MCP 服务器（stdio JSON-RPC 2024-11-05）。

工具面：
  · t_ndir_forward     单浓度正演（两通道信号/比值/理论反演）
  · t_ndir_calibrate   浓度扫描标定曲线（lnR 线性拟合 + R²）
  · t_ndir_invert      比值 → 浓度解析反演
  · t_ndir_selftest    数值锚点自检

纪律：纯标准库 stdio JSON-RPC；print 只走协议 stdout；
参数默认值均为 ai 演示占位，真实器件参数须用户交互提供。

自测：python tools/ndir_mcp.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SRV = Path(__file__).resolve().parent.parent          # server-ndir
_ROOT = _SRV.parent
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ndir_physics as nph  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "ndir", "version": "0.1.0"}}

_HOME = str(Path.home())
_WS_ROOT = str(_ROOT.parent)

from spectrolink_core.http_transport import (          # noqa: E402
    make_path_sanitizer, run_mcp_http)



_sanitize_paths = make_path_sanitizer(_WS_ROOT, _HOME)


# ── 工具实现 ──────────────────────────────────────────────

def t_ndir_forward(x=5e-6, L_s_cm=10.0, L_r_cm=10.0, k_s=0.05, k_r=0.001,
                   i0_s=1.0, i0_r=1.0, noise_frac=0.0, seed=0):
    """单浓度 NDIR 正演。x 为摩尔分数（1e-6=1ppm）。

    ⚠️ k_s/k_r/L 默认是 ai 演示占位（CO₂ 4.26 μm 量级），真实值须用户提供。
    """
    out = nph.forward(x, L_s_cm, L_r_cm, k_s, k_r, i0_s, i0_r, noise_frac, seed)
    out["validation"] = {"overall": "warn",
                         "note": "默认参数为演示占位，未标定前不可作定量结论"}
    return out


def t_ndir_calibrate(x_min=0.0, x_max=0.01, n=11, L_s_cm=10.0, L_r_cm=10.0,
                     k_s=0.05, k_r=0.001, i0_s=1.0, i0_r=1.0,
                     noise_frac=0.0, seed=0):
    """浓度扫描标定：x_min..x_max 等距 n 点 → R(x) 表 + lnR 线性拟合。"""
    xs = [x_min + (x_max - x_min) * i / (n - 1) for i in range(n)]
    return nph.calibrate(xs, L_s_cm, L_r_cm, k_s, k_r, i0_s, i0_r, noise_frac, seed)


def t_ndir_invert(R=0.5, R0=1.0, A=0.499):
    """比值 → 浓度：x = −ln(R/R0)/A。A = k_s·L_s − k_r·L_r。"""
    x = nph.invert(R, R0, A)
    return {"x": x, "x_ppm": x * 1e6 if not (isinstance(x, float) and x != x) else None,
            "formula": "x = -ln(R/R0) / (k_s*L_s - k_r*L_r)"}


def t_ndir_selftest():
    """数值锚点自检（离线，不依赖网络）。"""
    return nph.selftest()


TOOLS = [
    {"name": "t_ndir_forward",
     "description": "NDIR 单浓度正演：双通道信号/比值/解析反演。x 为摩尔分数（1e-6=1ppm）。k_s/k_r/L 默认演示占位，真实器件参数须用户提供。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x": {"type": "number", "description": "摩尔分数，1e-6=1ppm", "default": 5e-6},
                         "L_s_cm": {"type": "number", "default": 10.0},
                         "L_r_cm": {"type": "number", "default": 10.0},
                         "k_s": {"type": "number", "description": "信号通道带内有效吸收系数 cm⁻¹", "default": 0.05},
                         "k_r": {"type": "number", "default": 0.001},
                         "i0_s": {"type": "number", "default": 1.0},
                         "i0_r": {"type": "number", "default": 1.0},
                         "noise_frac": {"type": "number", "description": "相对高斯噪声 σ", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_ndir_calibrate",
     "description": "NDIR 浓度扫描标定：x_min..x_max 等距 n 点 → R(x) 表 + lnR 线性拟合（A_fit/R0_fit/R²）。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x_min": {"type": "number", "default": 0.0},
                         "x_max": {"type": "number", "default": 0.01},
                         "n": {"type": "integer", "default": 11},
                         "L_s_cm": {"type": "number", "default": 10.0},
                         "L_r_cm": {"type": "number", "default": 10.0},
                         "k_s": {"type": "number", "default": 0.05},
                         "k_r": {"type": "number", "default": 0.001},
                         "i0_s": {"type": "number", "default": 1.0},
                         "i0_r": {"type": "number", "default": 1.0},
                         "noise_frac": {"type": "number", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_ndir_invert",
     "description": "NDIR 比值 → 浓度解析反演：x = -ln(R/R0)/(k_s·L_s−k_r·L_r)。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "R": {"type": "number", "description": "实测两通道比值", "default": 0.5},
                         "R0": {"type": "number", "default": 1.0},
                         "A": {"type": "number", "description": "净吸收积 k_s·L_s−k_r·L_r", "default": 0.499}}}},
    {"name": "t_ndir_selftest",
     "description": "NDIR 数值锚点自检（离线）。",
     "inputSchema": {"type": "object", "properties": {}}},
]

DISPATCH = {t["name"]: globals()[t["name"]] for t in TOOLS}


# ── 参数校验 ──────────────────────────────────────────────

_SCHEMA = {}
for _t in TOOLS:
    _props = _t["inputSchema"]["properties"]
    _SCHEMA[_t["name"]] = {
        k: (v.get("type", "any"), v.get("default"))
        for k, v in _props.items()}


def _validate_args(name, args):
    for k, (want, _) in _SCHEMA.get(name, {}).items():
        if k not in args:
            continue
        v = args[k]
        if want == "number" and not isinstance(v, (int, float)):
            return f"参数 {k} 期望 number，收到 {type(v).__name__}"
        if want == "integer" and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or float(v) != int(v)):
            return f"参数 {k} 期望 integer，收到 {v!r}"
        if want == "string" and not isinstance(v, str):
            return f"参数 {k} 期望 string，收到 {type(v).__name__}"
    return None


# ── JSON-RPC ──────────────────────────────────────────────

def handle_request(req):
    if isinstance(req, list):
        if not req:
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600, "message": "空批量请求"}}
        return [r for r in (handle_request(x) for x in req) if r is not None]
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "请求必须是 JSON 对象或其数组"}}
    method = req.get("method", "")
    params = req.get("params") or {}
    req_id = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": SERVER_INFO}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = DISPATCH.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"未知工具：{name}"}}
        bad = _validate_args(name, args)
        if bad:
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"参数错误：{bad}"}],
                               "isError": True}}
        try:
            result = fn(**args)
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [{"type": "text",
                                            "text": json.dumps(result, ensure_ascii=False,
                                                               indent=2)}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [{"type": "text",
                                            "text": f"出错：{type(e).__name__}: {e}"}],
                               "isError": True}}
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"未知方法：{method}"}}


def _arg(name, default=""):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if "--selftest" in sys.argv:
        try:
            print(json.dumps(_sanitize_paths(t_ndir_selftest()), ensure_ascii=False, indent=2))
        except ImportError as exc:
            sys.stderr.write(f"[ndir-mcp] 自检无法运行：{exc}\n")
            raise SystemExit(2)
        return
    if "--http" in sys.argv:
        host = _arg("--host", "127.0.0.1")
        port = int(_arg("--port", "8005"))
        token = _arg("--token", "")
        if host in ("0.0.0.0", "") and not token:
            sys.stderr.write("[警告] 监听 0.0.0.0 且未设置 --token：远程暴露请务必加 --token。\n")
        _run_http(host, port, token)
        return
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = _sanitize_paths(handle_request(json.loads(line)))
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "JSON 解析失败"}}
        if resp is not None:
            print(json.dumps(resp, ensure_ascii=False), flush=True)


def _run_http(host, port, token):
    """MCP Streamable HTTP：把同一套 handle_request 暴露为 URL（实现见 spectrolink_core）。"""
    run_mcp_http(handle_request, host, port, token,
                 sanitize=_sanitize_paths, server_name="ndir-mcp")


if __name__ == "__main__":
    main()
