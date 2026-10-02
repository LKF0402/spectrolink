#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端 JSON-RPC 回归（离线、确定性，可进 CI）。

为什么需要它：`_gen_schema.py` 只校验**静态**一致性（工具数、schema↔DISPATCH），
`lites_fidelity.py` 只校验**参数**可达性。两者都发现不了"请求真的走一遍
JSON-RPC 解包 → 校验 → 派发 → 序列化之后坏掉"这类问题 —— 例如
`_SCHEMA_BY_NAME` 丢失时 `tools/list` 正常但 `tools/call` 抛 NameError。
本脚本是唯一的**端到端**门禁。

覆盖：
  · 正向 13 条：initialize / tools/list / ping，以及全部 12 个工具各调一次
  · 负向  4 条：未知工具名 / 未声明参数 / 缺必填参数 / 未知方法
    —— 四类都必须被**正确拒绝**，而不是静默返回默认值算出的结果

用法：python tools/_rpc_test.py   （退出码 0 = 全部通过）
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "lites_mcp.py")
# 用当前解释器，别写死路径（写死过一次：换了环境就静默用旧解释器）。
PY = sys.executable

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "rpc-test", "version": "1"}}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
     "params": {"name": "lites_forward",
                "arguments": {"device": "qtf-commercial-decapped", "x": 1e-6,
                              "line_strength": 2.3e-19, "L_gas_cm": 2580.0}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
     "params": {"name": "lites_mdl", "arguments": {"device": "qtf-commercial-decapped"}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
     "params": {"name": "lites_invert", "arguments": {"v_2f_measured_V": 4.4e-3}}},
    {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
     "params": {"name": "lites_guide", "arguments": {"topic": "quickstart"}}},
    {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
     "params": {"name": "lites_sweep", "arguments": {"var": "power_mW",
                                                     "values": [1, 10, 100]}}},
    {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
     "params": {"name": "lites_resonance", "arguments": {"delta_T_K": 2.0}}},
    {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
     "params": {"name": "lites_device", "arguments": {"action": "groups"}}},
    {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
     "params": {"name": "lites_noise_budget", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
     "params": {"name": "lites_compare", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 13, "method": "tools/call",
     "params": {"name": "lites_review", "arguments": {"f_m": 50000.0}}},
    # ── 负例：四类都必须被拒绝 ──
    # ⚠ 别把这里的工具名改成真实存在的工具。曾经被一次批量改名脚本
    #   把 `tdlas_simulate`（真·未知工具）改成 `lites_forward`（真实工具），
    #   于是这条负例退化成一次合法调用、**静默失去覆盖**，而测试照样打印
    #   "含预期的错误响应: 3" —— 少了一条也看不出来。现加断言钉住。
    {"jsonrpc": "2.0", "id": 90, "method": "tools/call",
     "params": {"name": "tdlas_simulate", "arguments": {}}},   # 未知工具名（TDLAS 遗留名）
    {"jsonrpc": "2.0", "id": 91, "method": "tools/call",
     "params": {"name": "lites_forward", "arguments": {"szigma_tau": 1e-4}}},  # 未声明参数
    {"jsonrpc": "2.0", "id": 92, "method": "tools/call",
     "params": {"name": "lites_invert", "arguments": {}}},     # 缺必填参数
    {"jsonrpc": "2.0", "id": 93, "method": "bad/method"},     # 未知方法
]

#: 必须被拒绝的 id
NEGATIVE = {90, 91, 92, 93}
#: 期望的拒绝形式：unknown_tool → JSON-RPC error；其余 → isError 或 error
EXPECT = {
    90: ("error", "未知工具"),
    91: ("isError", "未声明"),
    92: ("isError", "缺少必填"),
    93: ("error", "未知方法"),
}
#: 正向必须调通的 12 个工具（id → 工具名）
POSITIVE_TOOLS = {4: "lites_forward", 5: "lites_mdl", 6: "lites_invert",
                  7: "lites_guide", 8: "lites_sweep", 9: "lites_resonance",
                  10: "lites_device", 11: "lites_noise_budget",
                  12: "lites_compare", 13: "lites_review"}


def _find_nonfinite(obj, path=""):
    """递归找出返回值里的 NaN / ±Infinity（它们**不是合法 JSON**）。

    为什么必须单独查：Python 的 json 模块默认接受并输出裸 `NaN`/`Infinity`，
    所以 **Python 写的测试自然发现不了**；但 RFC 8259 不允许，严格解析器
    会抛错。这类缺陷会静默穿过自检与回归，直到真实 MCP 客户端崩了才暴露。
    """
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
            o = json.loads(l)
        except Exception:
            bad_stdout.append(l)
            continue
        if o.get("id") is not None:
            byid[o["id"]] = o

    ok = True
    if len(lines) != len(REQS):
        print(f"  !! 响应数不符（期望 {len(REQS)}）"); ok = False
    for l in bad_stdout:
        print(f"  !! 非 JSON 的 stdout 行（会污染协议流）: {l[:200]}"); ok = False

    for r in REQS:
        rid = r["id"]
        o = byid.get(rid)
        if o is None:
            print(f"  id={rid:3d}  <无响应>"); ok = False; continue
        if "error" in o:
            kind, msg = "error", str(o["error"].get("message", ""))
            print(f"  id={rid:3d}  ERROR {o['error'].get('code')}: {msg[:66]}")
        else:
            res = o["result"]
            if "tools" in res:
                got = len(res["tools"])
                names = {t["name"] for t in res["tools"]}
                print(f"  id={rid:3d}  tools/list -> {got} tools")
                if got != 12:
                    print(f"  !! tools/list 应返回 12 个工具，实得 {got}"); ok = False
                sys.stdout.flush()
                byid["__names__"] = names
                continue
            elif "content" in res:
                txt = res["content"][0]["text"]
                kind = "isError" if res.get("isError") else "ok"
                tag = f"[{kind}]"
                print(f"  id={rid:3d}  {tag} {txt[:80]}")
                try:
                    parsed = res.get("structuredContent") or json.loads(txt)
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
                # ── NaN / Infinity 泄漏检查（静默缺陷，必须钉住）────────
                # NaN 不是合法 JSON（RFC 8259 只允许有限数）。Python 的
                # json.dumps 默认吐裸 `NaN`，**严格解析器会直接抛错**——
                # 而 MCP 客户端恰恰多是严格解析器。曾经 lites_forward 在
                # 不传 mod_depth_cm1 时返回 "m": NaN、"F_m_raw": NaN，
                # 自检与 RPC 测试**全都照过**，因为 Python 自己解析得动。
                bad = _find_nonfinite(parsed)
                if bad:
                    print(f"  !! id={rid} 返回含 NaN/Infinity（非法 JSON）: "
                          f"{bad[:3]}"); ok = False

    # 工具清单里不能出现 TDLAS 遗留名
    names = byid.get("__names__") or set()
    stale = sorted(n for n in names if n.startswith("tdlas"))
    if stale:
        print(f"  !! tools/list 含 TDLAS 遗留工具名: {stale}"); ok = False
    if len(names) != 12:
        print(f"  !! 工具数应为 12，实得 {len(names)}"); ok = False

    print()
    if ok:
        print(f"全部通过：{len(REQS)} 条请求（{len(POSITIVE_TOOLS) + 3} 正向 / "
              f"{len(NEGATIVE)} 负向全部正确拒绝）")
        return 0
    print("存在失败项，见上方 !! 标记")
    return 1


if __name__ == "__main__":
    sys.exit(main())
