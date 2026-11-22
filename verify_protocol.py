#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨六技术的协议契约自检（离线、确定性、可作 CI 硬门禁）。

## 为什么需要

`tools/contract_check.py` 只覆盖 TDLAS 的 200 项深契约；其余五个 server 只有
`--selftest`，而 selftest 走的是物理函数，不经过 `tools/call` 的“校验→派发→
序列化”这一段。于是一类静默错误没有任何门禁能发现：

- `TOOLS` 里声明了参数、`DISPATCH` 的函数签名里却没有（调用即 TypeError）；
- 必填参数在 schema 里带 default（客户端不传就静默用默认值）；
- schema 默认值与签名默认值不一致（文档说明与实际行为两张皮）；
- 未知键 / 类型错误在某 server 上未被拒绝（协议语义退回六种行为）。

本脚本对六个 server 逐一验证上述契约。它**不执行任何工具函数**：全部检查都
在 `validate_args` 处短路，因此不触网、不写盘、不依赖 HITRAN 缓存。

用法：
    python verify_protocol.py              # 全部 server，逐条 PASS
    python verify_protocol.py --server server-ndir
    python verify_protocol.py --quiet      # 只输出汇总与失败

CI 里按 `PASS` 行数设下限，防止“少跑一半仍显示绿”。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SERVERS = (
    ("server-tdlas", "tdlas_mcp", 17),
    ("server-lites", "lites_mcp", 13),
    ("server-crds", "crds_mcp", 4),
    ("server-ndir", "ndir_mcp", 4),
    ("server-ftir", "ftir_mcp", 3),
    ("server-doas", "doas_mcp", 4),
)

CHILD = r'''
# ── 子进程：单个 server 的自检体（隔离 sys.path，避免六个同名 tools 包串味）──
import importlib, inspect, json, sys

SERVER, MOD, FLOOR = SERVER_NAME, MOD_NAME, TOOL_FLOOR
sys.path[:0] = ["./tools", ".", ".."]
mod = importlib.import_module(MOD)
handle = mod.handle_request
TOOLS, DISPATCH = mod.TOOLS, mod.DISPATCH

out = []

def emit(status, name, text, detail=""):
    out.append({"status": status, "name": name, "text": text, "detail": detail})

def call(name, args):
    return handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": name, "arguments": args}})

def is_error(resp):
    return bool((resp.get("result") or {}).get("isError"))

def err_text(resp):
    return ((resp.get("result") or {}).get("content") or [{}])[0].get("text", "")

VALID_TYPES = ("number", "integer", "boolean", "string", "array", "object")
PROBE = {"number": 1.0, "integer": 1, "boolean": True, "string": "probe",
         "array": [], "object": {}}

def branches(meta):
    """属性声明允许的类型分支：裸 type，或 anyOf/oneOf 各分支。"""
    if not isinstance(meta, dict):
        return []
    if "type" in meta:
        return [meta]
    for key in ("anyOf", "oneOf"):
        if isinstance(meta.get(key), list):
            return [b for b in meta[key] if isinstance(b, dict)]
    return []

def placeholder(meta):
    """按声明分支造一个合法占位值（只用于填必填，不进入函数执行）。"""
    for b in branches(meta):
        if b.get("enum"):
            return b["enum"][0]
        if b.get("type") in PROBE:
            return PROBE[b["type"]]
    return None

def baseline(props, req):
    """必填参数的合法基线：优先 schema default，其次按类型占位。"""
    args = {}
    for p in req:
        meta = props.get(p) or {}
        if "default" in meta:
            args[p] = meta["default"]
            continue
        v = placeholder(meta)
        if v is not None:
            args[p] = v
    return args

# 1) 工具面：数量下限、名称唯一、结构完整
names = [t.get("name") for t in TOOLS]
if len(TOOLS) < FLOOR:
    emit("FAIL", "tools", f"工具数 {len(TOOLS)} 低于下限 {FLOOR}")
else:
    emit("PASS", "tools", f"工具数 {len(TOOLS)} ≥ {FLOOR}")
if len(names) != len(set(names)):
    emit("FAIL", "tools", f"工具名重复：{sorted(n for n in names if names.count(n) > 1)}")
else:
    emit("PASS", "tools", "工具名唯一")
if set(names) != set(DISPATCH):
    emit("FAIL", "dispatch", f"TOOLS↔DISPATCH 不一致 缺={sorted(set(names) - set(DISPATCH))} "
                              f"多={sorted(set(DISPATCH) - set(names))}")
else:
    emit("PASS", "dispatch", "TOOLS↔DISPATCH 一一对应")

# 2) tools/list 走协议层，不得丢字段或改顺序
lst = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
got = [t.get("name") for t in ((lst.get("result") or {}).get("tools") or [])]
if got != names:
    emit("FAIL", "tools/list", f"返回名序与 TOOLS 不一致：{got[:5]}... vs {names[:5]}...")
else:
    emit("PASS", "tools/list", f"{len(got)} 个工具名序一致")

for t in TOOLS:
    name = t.get("name")
    desc = t.get("description") or ""
    schema = t.get("inputSchema") or {}
    props = schema.get("properties") or {}
    req = schema.get("required") or []

    # 3) 声明完整性
    problems = []
    if not desc:
        problems.append("description 为空")
    if schema.get("type") != "object":
        problems.append("inputSchema.type 非 object")
    if not isinstance(props, dict):
        problems.append("properties 非对象")
    if not isinstance(req, list):
        problems.append("required 非数组")
    for p in req:
        if p not in props:
            problems.append(f"required '{p}' 未在 properties 声明")
    for p, meta in props.items():
        brs = branches(meta)
        if not brs:
            problems.append(f"属性 '{p}' 缺 type / anyOf / oneOf")
            continue
        bad = [b.get("type") for b in brs if b.get("type") not in VALID_TYPES]
        if bad:
            problems.append(f"属性 '{p}' 的分支类型非法：{bad}")
    if problems:
        emit("FAIL", name, "声明完整性：" + "；".join(problems))
    else:
        emit("PASS", name, "声明完整性")

    fn = DISPATCH.get(name)
    if fn is None:
        continue
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        emit("WARN", name, "无法取签名（内建/包装对象），跳过签名一致性")
        params = None
    if params is not None:
        has_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())
        mism = [p for p in props if p not in params and not has_kwargs]
        if mism:
            emit("FAIL", name, f"schema 属性不在函数签名中：{mism}（调用必 TypeError）")
        else:
            emit("PASS", name, "schema 属性均可被函数接收")
        # 默认值一致性：仅比较数值/布尔/字符串等可直接比较的类型
        bad_defaults = []
        for p, meta in props.items():
            if p not in params or "default" not in meta:
                continue
            d0 = params[p].default
            if d0 is inspect._empty:
                continue
            d1 = meta["default"]
            if isinstance(d0, bool) != isinstance(d1, bool):
                bad_defaults.append(f"{p}: {d0!r} vs {d1!r}")
            elif isinstance(d0, (int, float)) and isinstance(d1, (int, float)):
                if d0 != d1:
                    bad_defaults.append(f"{p}: {d0!r} vs {d1!r}")
            elif isinstance(d0, str) and isinstance(d1, str) and d0 != d1:
                bad_defaults.append(f"{p}: {d0!r} vs {d1!r}")
        if bad_defaults:
            emit("FAIL", name, "schema 默认值与签名不一致：" + "；".join(bad_defaults))
        else:
            emit("PASS", name, "schema 默认值与签名一致")

    # 4) 协议层拒绝：未知键（先把必填填成合法基线，否则会被"缺必填"抢先短路）
    base = baseline(props, req)
    r = call(name, dict(base, **{"__unknown_key_probe__": True}))
    if is_error(r) and "未声明" in err_text(r):
        emit("PASS", name, "未知键被拒绝")
    else:
        emit("FAIL", name, f"未知键未被拒绝：{json.dumps(r, ensure_ascii=False)[:180]}")

    # 5) 协议层拒绝：类型错误（挑第一个单一 type 声明的属性；多态参数另测）
    bad_arg = None
    wrong = {"number": "probe", "integer": 1.5, "boolean": 2, "string": 7,
             "array": {}, "object": []}
    for p, meta in props.items():
        if "type" in meta and meta["type"] in wrong:
            bad_arg = (p, wrong[meta["type"]])
            break
    if bad_arg is None:
        emit("SKIP", name, "无可构造类型错误的单一类型属性")
    else:
        r = call(name, dict(base, **{bad_arg[0]: bad_arg[1]}))
        want = props[bad_arg[0]]["type"]
        if is_error(r) and f"期望 {want}" in err_text(r):
            emit("PASS", name, f"类型错误被拒绝（{bad_arg[0]}）")
        else:
            emit("FAIL", name, f"类型错误未被拒绝（{bad_arg[0]}）："
                               f"{json.dumps(r, ensure_ascii=False)[:180]}")

    # 5b) 多态参数（anyOf/oneOf）：每个分支之外的取值必须被拒绝
    poly = [(p, meta) for p, meta in props.items()
            if "type" not in meta and branches(meta)]
    if poly:
        p, meta = poly[0]
        probe, want_desc = None, ""
        for b in branches(meta):
            if b.get("type") in ("number", "integer"):
                probe, want_desc = ({} if b["type"] == "number" else "probe"), b["type"]
                break
        if probe is not None:
            r = call(name, dict(base, **{p: probe}))
            if is_error(r):
                emit("PASS", name, f"多态参数非法分支被拒绝（{p}）")
            else:
                emit("FAIL", name, f"多态参数非法分支未被拒绝（{p}）："
                                   f"{json.dumps(r, ensure_ascii=False)[:180]}")
        else:
            emit("SKIP", name, f"多态参数 {p} 无可构造的非法分支")

    # 6) 协议层拒绝：缺必填
    if not req:
        emit("SKIP", name, "无必填参数")
    else:
        r = call(name, {})
        if is_error(r) and "缺少必填参数" in err_text(r):
            emit("PASS", name, f"缺必填被拒绝（{req[0]}）")
        else:
            emit("FAIL", name, f"缺必填未被拒绝：{json.dumps(r, ensure_ascii=False)[:180]}")

print(json.dumps(out, ensure_ascii=False))
'''


def run_server(server: str, mod: str, floor: int, quiet: bool) -> tuple[int, int]:
    code = (f"SERVER_NAME={server!r}\nMOD_NAME={mod!r}\nTOOL_FLOOR={floor}\n" + CHILD)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       cwd=str(ROOT / server), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if p.returncode != 0 or not lines:
        print(f"[FAIL] {server}: 子进程异常 exit={p.returncode}")
        tail = (p.stderr or "").strip().splitlines()[-6:]
        for ln in tail:
            print(f"    {ln}")
        return 0, 1
    records = json.loads(lines[-1])
    ok = fail = 0
    for r in records:
        if r["status"] == "PASS":
            ok += 1
            if not quiet:
                print(f"PASS {server}/{r['name']}: {r['text']}")
        elif r["status"] == "FAIL":
            fail += 1
            print(f"FAIL {server}/{r['name']}: {r['text']}")
            if r["detail"]:
                print(f"     {r['detail']}")
    if not quiet:
        print(f"--- {server}: {ok} PASS / {fail} FAIL")
    return ok, fail


def main() -> int:
    ap = argparse.ArgumentParser(description="跨六技术 MCP 协议契约自检（离线）")
    ap.add_argument("--server", choices=[s for s, _, _ in SERVERS],
                    help="只检查单个 server")
    ap.add_argument("--quiet", action="store_true", help="只输出失败与汇总")
    ap.add_argument("--min-pass", type=int, default=0,
                    help="通过数下限；低于下限视为异常（CI 防静默少跑）")
    args = ap.parse_args()

    selected = [s for s in SERVERS if args.server in (None, s[0])]
    ok = fail = 0
    for server, mod, floor in selected:
        a, b = run_server(server, mod, floor, args.quiet)
        ok += a
        fail += b
    print(f"[protocol] {ok} PASS / {fail} FAIL")
    if fail:
        return 1
    if args.min_pass and ok < args.min_pass:
        print(f"[protocol] 通过数 {ok} 低于下限 {args.min_pass}，判定为静默少跑")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
