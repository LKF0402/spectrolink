"""MCP JSON-RPC 协议层（stdio）——六个 server 共用这一份。

## 为什么集中

改造前每个 server 都自带一套 `handle_request` / `_validate_args` / `_SCHEMA`，
实现并不一致，实际后果是：

- crds / ndir / ftir 只校验类型，**不校验必填与未知键**：传错参数名被静默丢弃，
  工具照常返回"看起来正常"的结果（AI 以为改了、其实没改）；
- doas 更弱：无批量请求、无通知处理、无参数校验，还能吃位置参数；
- tdlas / lites 有严格校验，于是同一份 MCP 协议在六个 server 上是六种行为。

现在协议语义只有一处定义：批量 / 通知 / 必填 / 未知键 / 类型 / 出错边界
全部按 tdlas 的严格口径（它是被契约自检覆盖得最狠的一份）。
"""
from __future__ import annotations

import json
import sys

JSON = dict


def schema_index(tools):
    """工具名 → inputSchema。"""
    return {t["name"]: (t.get("inputSchema") or {}) for t in tools}


def validate_args(schema, name, args):
    """按 inputSchema 做必填 / 未知键 / 类型三项校验。返回错误说明，None = 通过。

    未知键必须拒绝而不是静默丢弃：`edge`/`trim_frac`/`d2nu_dI2` 那类参数一旦漏传，
    返回体仍写着默认分支，用户会拿归因错误的结论去指导真实实验。
    """
    if not isinstance(args, dict):
        return "arguments 必须是 JSON 对象"
    sch = schema.get(name) or {}
    props = sch.get("properties") or {}
    missing = [k for k in (sch.get("required") or []) if k not in args]
    if missing:
        return f"缺少必填参数：{missing}"
    unknown = sorted(k for k in args if k not in props)
    if unknown:
        return (f"存在未声明的参数：{unknown}；本工具允许的键：{sorted(props)}。"
                f"（拼写错误会被拒绝而非静默忽略；确需新参数请提 issue）")
    for k, v in args.items():
        if v is None:
            continue
        want = (props.get(k) or {}).get("type")
        if want == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return f"参数 {k} 期望 number，收到 {type(v).__name__}（{v!r}）"
        if want == "integer" and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or float(v) != int(v)):
            return f"参数 {k} 期望 integer，收到 {v!r}"
        if want == "boolean" and not isinstance(v, bool):
            return f"参数 {k} 期望 boolean，收到 {v!r}"
        if want == "string" and not isinstance(v, str):
            return f"参数 {k} 期望 string，收到 {type(v).__name__}"
        if want == "array" and not isinstance(v, list):
            return f"参数 {k} 期望 array，收到 {type(v).__name__}"
        if want == "object" and not isinstance(v, dict):
            return f"参数 {k} 期望 object，收到 {type(v).__name__}"
    return None


def make_handle_request(server_info, tools, dispatch, schema, sanitize=None):
    """生成该 server 的 `handle_request(req)`。

    参数
    ----
    server_info : initialize 返回的 serverInfo 体
    tools : tools/list 返回的 TOOLS 列表
    dispatch : 工具名 → 可调用对象
    schema : schema_index(TOOLS) 的结果
    sanitize : 可选，对返回文本做路径脱敏
    """

    def _text(obj):
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        return sanitize(s) if sanitize else s

    def handle_request(req):
        """处理 MCP 请求（initialize / tools/list / tools/call）。

        支持 JSON-RPC 2.0 批量请求（顶层数组）；批量内通知（返回 None）被剔除。
        """
        if isinstance(req, list):               # 批量请求：此前会把 list 当 dict 用
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
            return {"jsonrpc": "2.0", "id": req_id, "result": server_info}
        if method in ("notifications/initialized", "initialized"):
            return None                          # 通知无需响应
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            fn = dispatch.get(name)
            if fn is None:
                return {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": f"未知工具：{name}"}}
            bad = validate_args(schema, name, args)
            if bad:
                return {"jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text", "text": f"参数错误：{bad}"}],
                                   "isError": True}}
            try:
                result = fn(**args)
                return {"jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text", "text": _text(result)}]}}
            except Exception as exc:             # 工具边界：必须把异常转成 MCP 错误体
                msg = f"出错：{type(exc).__name__}: {exc}"
                return {"jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text",
                                                "text": sanitize(msg) if sanitize else msg}],
                                   "isError": True}}
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"未知方法：{method}"}}

    return handle_request


def serve_stdio(handle_request, tag="mcp"):
    """把 handle_request 接到 stdin/stdout 的 JSON-RPC 行协议上（唯一传输形态）。"""
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):      # 非文本流 / 已关闭时静默跳过
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            print(json.dumps({"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32700, "message": "JSON 解析失败"}},
                             ensure_ascii=False), flush=True)
            continue
        out = handle_request(req)
        if out is not None:
            print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0
