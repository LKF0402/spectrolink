#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TDLAS 端到端 JSON-RPC 冒烟（离线、确定性，可进 CI）。

为什么需要它：`contract_check.py` 校验的是 schema ↔ 签名、参数透传、DISPATCH 映射，
但**不启动 stdio 子进程**，因此发现不了“请求真的走一遍 JSON-RPC 解包 → 校验 → 派发 →
序列化之后坏掉”这类问题。真实踩过的例子：ndarray 直接入返回体会抛 TypeError，
整次调用失败；Python 的 json 默认输出裸 NaN，自检照过但严格客户端会崩。

覆盖：
  · 正向：initialize / tools/list / ping，以及 3 个**不访问 HITRAN**的轻工具
  · 负向 4 条：未知工具名 / 未声明参数 / 缺必填参数 / 未知方法
  · 严格 JSON 解析（parse_constant 在词法阶段拦截裸 NaN/Infinity）
  · 返回值递归检查 NaN/Infinity

用法：python tools/_rpc_test.py   （退出码 0 = 全部通过）
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "tdlas_mcp.py")
# 用当前解释器，别写死路径；换环境时不会静默用旧解释器。
PY = sys.executable

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "rpc-test", "version": "1"}}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    # 轻工具：不碰 HITRAN、不写用户设备库/会话
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
     "params": {"name": "tdlas_guide", "arguments": {"topic": "m"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
     "params": {"name": "tdlas_device", "arguments": {"action": "list"}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
     "params": {"name": "tdlas_session", "arguments": {"action": "view",
                                                        "session_id": "rpc-smoke"}}},
    # ── 负例：四类都必须被拒绝 ──
    # 未知工具名用**确实不存在**的名字；不要改成真实工具，否则负例退化成合法调用。
    {"jsonrpc": "2.0", "id": 90, "method": "tools/call",
     "params": {"name": "lites_forward", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 91, "method": "tools/call",
     "params": {"name": "tdlas_guide", "arguments": {"bogus_key": 1}}},
    {"jsonrpc": "2.0", "id": 92, "method": "tools/call",
     "params": {"name": "tdlas_invert", "arguments": {"species": "CH4"}}},
    {"jsonrpc": "2.0", "id": 93, "method": "bad/method"},
]

NEGATIVE = {90, 91, 92, 93}
EXPECT = {
    90: ("error", "未知工具"),
    91: ("isError", "未声明"),
    92: ("isError", "缺少必填"),
    93: ("error", "未知方法"),
}
POSITIVE_TOOLS = {4: "tdlas_guide", 5: "tdlas_device", 6: "tdlas_session"}


def _find_nonfinite(obj, path=""):
    """递归找出返回值里的 NaN / ±Infinity（它们不是合法 JSON）。"""
    bad = []
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            bad.append((path, repr(obj)))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            bad += _find_nonfinite(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            bad += _find_nonfinite(v, f"{path}[{i}]")
    return bad


def _reject_constant(value):
    raise ValueError(f"非法 JSON 常量: {value}")


def _strict_loads(text):
    """严格 JSON 解析：裸 NaN/Infinity 在词法阶段直接拒绝。"""
    return json.loads(text, parse_constant=_reject_constant)


def main() -> int:
    inp = "\n".join(json.dumps(r, ensure_ascii=False) for r in REQS) + "\n"
    p = subprocess.run([PY, "-W", "ignore", SCRIPT], input=inp,
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=900)

    lines = [l for l in p.stdout.splitlines() if l.strip()]
    print(f"responses: {len(lines)} / {len(REQS)}")

    byid = {}
    bad_stdout = []
    for l in lines:
        try:
            o = _strict_loads(l)
        except Exception as exc:
            bad_stdout.append((l, repr(exc)))
            continue
        if o.get("id") is not None:
            byid[o["id"]] = o

    ok = True
    if len(lines) != len(REQS):
        print(f"  !! 响应数不符（期望 {len(REQS)}）"); ok = False
    for l, exc in bad_stdout:
        print(f"  !! 非严格 JSON 的 stdout 行（{exc}）: {l[:200]}"); ok = False

    for r in REQS:
        rid = r["id"]
        o = byid.get(rid)
        if o is None:
            print(f"  id={rid:3d}  <无响应>"); ok = False; continue
        kind, msg, txt, parsed = "other", "", "", None
        if "error" in o:
            kind, msg = "error", str(o["error"].get("message", ""))
            print(f"  id={rid:3d}  ERROR {o['error'].get('code')}: {msg[:66]}")
        else:
            res = o["result"]
            if "tools" in res:
                got = len(res["tools"])
                names = {t["name"] for t in res["tools"]}
                print(f"  id={rid:3d}  tools/list -> {got} tools")
                if got != 17:
                    print(f"  !! tools/list 应返回 17 个工具，实得 {got}"); ok = False
                byid["__names__"] = names
                continue
            if "content" in res:
                txt = res["content"][0]["text"]
                kind = "isError" if res.get("isError") else "ok"
                tag = f"[{kind}]"
                print(f"  id={rid:3d}  {tag} {txt[:80]}")
                try:
                    parsed = res.get("structuredContent") or _strict_loads(txt)
                except Exception:
                    parsed = None
            else:
                kind, parsed = "other", res
                print(f"  id={rid:3d}  {json.dumps(res, ensure_ascii=False)[:80]}")

        # —— 断言 ——
        if rid in NEGATIVE:
            want_kind, want_sub = EXPECT[rid]
            if kind != want_kind:
                print(f"  !! id={rid} 期望 {want_kind}，实得 {kind}"); ok = False
            elif want_sub not in (msg if kind == "error" else txt):
                print(f"  !! id={rid} 拒绝信息未含 {want_sub!r}"); ok = False
        elif rid in POSITIVE_TOOLS:
            if kind != "ok":
                print(f"  !! id={rid} 工具 {POSITIVE_TOOLS[rid]} 未调通（{kind}）"); ok = False
            else:
                bad = _find_nonfinite(parsed)
                if bad:
                    print(f"  !! id={rid} 返回含 NaN/Infinity（非法 JSON）: {bad[:3]}"); ok = False

    names = byid.get("__names__") or set()
    stale = sorted(n for n in names if n.startswith("lites"))
    if stale:
        print(f"  !! tools/list 含 LITES 遗留工具名: {stale}"); ok = False
    if len(names) != 17:
        print(f"  !! 工具数应为 17，实得 {len(names)}"); ok = False

    print()
    if ok:
        print(f"全部通过：{len(REQS)} 条请求（3 正向工具 / {len(NEGATIVE)} 负向全部正确拒绝）")
        return 0
    print("存在失败项，见上方 !! 标记")
    return 1


if __name__ == "__main__":
    sys.exit(main())
