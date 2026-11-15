"""MCP Streamable HTTP 传输层（stdio 之外的 URL 入口）。

## 为什么抽到这里

六个 server（tdlas / lites / crds / ndir / ftir / doas）此前各自内联一份
`_run_http`（约 120 行）与 `_sanitize_paths`（约 25 行），实现几乎逐字相同，
只有 server 名与 `handle_request` 的绑定点不同。复制粘贴带来的问题是真实的：
一处修（例如 chunked 读取、CORS 头、SSE 分支）必须改六处，漏一处就是线上故障。
本模块把它们收敛为单一实现，行为与原实现逐条对齐。

## 协议要点（MCP Streamable HTTP）

- `POST /mcp`：客户端 → 服务器 JSON-RPC。响应按 `Accept` 选择
  `application/json` 或 `text/event-stream`（SSE，单事件包）。
- `GET /mcp`：服务器 → 客户端推送通道。本工具服务器无主动推送，返回 405。
- `OPTIONS`：CORS 预检，返回 204。
- `Mcp-Session-Id`：每次进程启动生成一次，随响应回传。
- 可选 Bearer token；监听 `0.0.0.0` 且无 token 时由调用方自行告警。

请求体读取同时支持 `Content-Length` 与 `Transfer-Encoding: chunked`：
cloudflared 等反向代理常发 chunked，只按 Content-Length 读会漏读，
残留字节污染连接复用，表现为 501 'Unsupported method'。
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path


def make_path_sanitizer(workspace_root=None, home=None):
    """构造递归脱敏函数：把绝对路径替换成 `<workspace>` / `<home>`。

    MCP 返回值（尤其 tools/call 的 log 字段）会被序列化发给远端客户端，
    其中可能含本地绝对路径（HITRAN 缓存目录、PNG 输出目录等）。在返回边界统一脱敏，
    避免泄露服务器目录结构。匹配大小写不敏感，且对替换串做正则转义。

    参数
    ----
    workspace_root : 需要隐藏的工作区根路径（通常为仓库根的父目录）
    home : 用户主目录；默认取 `Path.home()`

    返回
    ----
    callable(obj) -> obj：递归处理 str / list / dict，其他类型原样返回。
    """
    ws = str(workspace_root) if workspace_root else ""
    hm = str(home) if home else str(Path.home())
    ws_re = re.compile(re.escape(ws), re.IGNORECASE) if ws else None
    hm_re = re.compile(re.escape(hm), re.IGNORECASE) if hm else None

    def sanitize(obj):
        if isinstance(obj, str):
            s = obj
            if ws_re is not None:
                s = ws_re.sub("<workspace>", s)
            if hm_re is not None:
                s = hm_re.sub("<home>", s)
            return s
        if isinstance(obj, list):
            return [sanitize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        return obj

    return sanitize


def run_mcp_http(handle_request, host, port, token="", sanitize=None,
                 server_name="mcp"):
    """把 `handle_request` 暴露为 MCP Streamable HTTP 端点并阻塞服务。

    参数
    ----
    handle_request : callable(dict | list) -> dict | None
        已有的 JSON-RPC 处理器（各 server 自己的实现）。返回 None 表示通知，无响应体。
    host, port : 监听地址
    token : 可选 Bearer token；空串表示不鉴权
    sanitize : 可选脱敏函数（`make_path_sanitizer` 的返回值）；None 表示不脱敏
    server_name : 仅用于启动日志前缀
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    session_id = uuid.uuid4().hex
    _sanitize = sanitize if callable(sanitize) else (lambda x: x)

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):       # 协议日志不污染 stdout
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
            if resp is None:                # 通知：无响应体
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self._cors()
                self.end_headers()
                return
            body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            use_sse = "text/event-stream" in self.headers.get("Accept", "")
            self.send_response(200)
            self.send_header("Mcp-Session-Id", session_id)
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
            """可靠读取请求体：同时支持 Content-Length 与 chunked 传输编码。"""
            te = (self.headers.get("Transfer-Encoding", "") or "").lower()
            if "chunked" in te:
                return self._read_chunked()
            try:
                n = int(self.headers.get("Content-Length", 0))
            except ValueError:
                n = 0
            return self.rfile.read(n) if n > 0 else b""

        def _read_chunked(self):
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
                self.rfile.readline()       # 消费块尾 \r\n
            return buf

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
            self._send(_sanitize(handle_request(req)))

    sys.stderr.write(f"[{server_name}] HTTP 模式已启动：http://{host}:{port}/mcp\n")
    ThreadingHTTPServer((host, port), _Handler).serve_forever()
