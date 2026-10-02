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


# ── 参数校验 / JSON-RPC（与 server-ndir 同骨架）────────────

_SCHEMA = {}
for _t in TOOLS:
    _props = _t["inputSchema"]["properties"]
    _SCHEMA[_t["name"]] = {k: (v.get("type", "any"), v.get("default"))
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
        if want == "array" and not isinstance(v, list):
            return f"参数 {k} 期望 array，收到 {type(v).__name__}"
    return None


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
            print(json.dumps(_sanitize_paths(t_ftir_selftest()), ensure_ascii=False, indent=2))
        except ImportError as exc:
            sys.stderr.write(f"[ftir-mcp] 自检无法运行：{exc}\n")
            raise SystemExit(2)
        return
    if "--http" in sys.argv:
        host = _arg("--host", "127.0.0.1")
        port = int(_arg("--port", "8003"))
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
    """MCP Streamable HTTP：同一套 handle_request 暴露为 URL。"""
    import uuid
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    SESSION_ID = uuid.uuid4().hex

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, Mcp-Session-Id, Accept")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

        def _auth_ok(self):
            if not token:
                return True
            a = self.headers.get("Authorization", "")
            return a == f"Bearer {token}" or a == token

        def _send(self, resp):
            if resp is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self._cors()
                self.end_headers()
                return
            body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            use_sse = "text/event-stream" in self.headers.get("Accept", "")
            self.send_response(200)
            self.send_header("Mcp-Session-Id", SESSION_ID)
            self._cors()
            if use_sse:
                payload = b"data: " + body + b"\n\n"
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def _read_body(self):
            te = (self.headers.get("Transfer-Encoding", "") or "").lower()
            if "chunked" in te:
                buf = b""
                while True:
                    line = self.rfile.readline().strip()
                    if not line:
                        line = self.rfile.readline().strip()
                    try:
                        size = int(line.split(b";")[0], 16)
                    except ValueError:
                        break
                    if size == 0:
                        while True:
                            h = self.rfile.readline()
                            if h in (b"\r\n", b""):
                                break
                        break
                    buf += self.rfile.read(size)
                    self.rfile.readline()
                return buf
            try:
                n = int(self.headers.get("Content-Length", 0))
            except ValueError:
                n = 0
            return self.rfile.read(n) if n > 0 else b""

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            self.send_response(405)
            self.send_header("Allow", "POST")
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if self.path not in ("/mcp", "/"):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not self._auth_ok():
                err = b'{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"unauthorized"}}'
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return
            try:
                req = json.loads(self._read_body() or b"{}")
            except Exception as e:
                self._send({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": f"解析失败：{e}"}})
                return
            self._send(_sanitize_paths(handle_request(req)))

    sys.stderr.write(f"[ftir-mcp] HTTP 模式已启动：http://{host}:{port}/mcp\n")
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
