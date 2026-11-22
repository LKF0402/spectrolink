#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按变更文件选择最小验证集，减少全量回归的往返耗时。

用法：
    python verify_changed.py            # 只检查本次改动涉及的最小子集
    python verify_changed.py --list     # 只列出将执行的检查
    python verify_changed.py --full     # 发布前全量：契约 + 两套 RPC + 两套 selftest

设计原则：检查项由文件路径决定，不靠人工判断；未触及的层不跑。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def _git(*args: str) -> list[str]:
    p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return []
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def changed_files() -> list[str]:
    files = _git("diff", "--name-only", "--diff-filter=ACMRT", "HEAD")
    files += _git("ls-files", "--others", "--exclude-standard")
    return sorted(set(files))


def _command(label: str, argv: list[str]) -> tuple[str, list[str]]:
    return label, [PY, "-X", "utf8", *argv]


def checks_for(files: list[str]) -> list[tuple[str, list[str]]]:
    py = [f for f in files if f.endswith(".py") and (ROOT / f).exists()]
    checks: list[tuple[str, list[str]]] = []
    if py:
        checks.append(_command("py_compile", ["-m", "py_compile", *py]))

    tdlas = [f for f in files if f.startswith("server-tdlas/") and f.endswith(".py")]
    lites = [f for f in files if f.startswith("server-lites/") and f.endswith(".py")]
    core = [f for f in files if f.startswith("spectrolink_core/") and f.endswith(".py")]
    any_server = [f for f in files if f.split("/")[0].startswith("server-") and f.endswith(".py")]

    # 协议契约覆盖六个 server：任一 server 或共用内核改动都要过一遍（离线、秒级）。
    if any_server or core or any(f.endswith("verify_protocol.py") for f in files):
        checks.append(_command("protocol contract", ["verify_protocol.py"]))

    if tdlas or core:
        checks.append(_command("tdlas contract", ["server-tdlas/tools/contract_check.py"]))
    if any(f.endswith("alpha_crossval.py") for f in files):
        checks.append(_command("tdlas alpha", ["server-tdlas/tools/alpha_crossval.py"]))
    if any(f.endswith("tdlas_fidelity.py") for f in files):
        checks.append(_command("tdlas fidelity", ["server-tdlas/tools/tdlas_fidelity.py"]))
    if tdlas:
        checks.append(_command("tdlas rpc", ["server-tdlas/tools/_rpc_test.py"]))
        checks.append(_command("tdlas selftest", ["server-tdlas/tools/tdlas_mcp.py", "--selftest"]))
    if lites or core:
        checks.append(_command("lites rpc", ["server-lites/tools/_rpc_test.py"]))
        checks.append(_command("lites selftest", ["server-lites/tools/lites_mcp.py", "--selftest"]))
    if any(f.endswith("lites_fidelity.py") for f in files):
        checks.append(_command("lites fidelity", ["server-lites/tools/lites_fidelity.py"]))
    if core:
        checks.append(_command("tdlas rpc", ["server-tdlas/tools/_rpc_test.py"]))
        checks.append(_command("tdlas selftest", ["server-tdlas/tools/tdlas_mcp.py", "--selftest"]))

    # 其余技术：只跑自己的离线自检，不牵动 TDLAS/LITES。
    for server, entry in (("server-crds", "crds_mcp.py"), ("server-ndir", "ndir_mcp.py"),
                          ("server-ftir", "ftir_mcp.py"), ("server-doas", "doas_mcp.py")):
        if any(f.startswith(server + "/") and f.endswith(".py") for f in files):
            checks.append(_command(f"{server} selftest",
                                   [f"{server}/tools/{entry}", "--selftest"]))

    # 去重：同一命令只跑一次（core 与 tdlas 可能同时命中）。
    seen, unique = set(), []
    for label, argv in checks:
        key = tuple(argv)
        if key not in seen:
            seen.add(key)
            unique.append((label, argv))
    return unique


def full_checks() -> list[tuple[str, list[str]]]:
    checks = [
        _command("protocol contract", ["verify_protocol.py"]),
        _command("tdlas contract", ["server-tdlas/tools/contract_check.py"]),
        _command("tdlas alpha", ["server-tdlas/tools/alpha_crossval.py"]),
        _command("tdlas fidelity", ["server-tdlas/tools/tdlas_fidelity.py"]),
        _command("tdlas rpc", ["server-tdlas/tools/_rpc_test.py"]),
        _command("tdlas selftest", ["server-tdlas/tools/tdlas_mcp.py", "--selftest"]),
        _command("lites rpc", ["server-lites/tools/_rpc_test.py"]),
        _command("lites selftest", ["server-lites/tools/lites_mcp.py", "--selftest"]),
    ]
    for server, entry in (("server-crds", "crds_mcp.py"), ("server-ndir", "ndir_mcp.py"),
                          ("server-ftir", "ftir_mcp.py"), ("server-doas", "doas_mcp.py")):
        checks.append(_command(f"{server} selftest", [f"{server}/tools/{entry}", "--selftest"]))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="发布前全量检查")
    ap.add_argument("--list", action="store_true", help="只列出检查项，不执行")
    args = ap.parse_args()

    files = changed_files()
    checks = full_checks() if args.full else checks_for(files)

    print(f"[verify] changed files: {len(files)}")
    for f in files:
        print(f"  {f}")
    if not checks:
        print("[verify] 未命中代码检查（文档/配置改动；按协议不跑代码门禁）")
        return 0

    print(f"[verify] checks: {len(checks)}")
    for label, _ in checks:
        print(f"  - {label}")
    if args.list:
        return 0

    t_all = time.perf_counter()
    failed = []
    for label, argv in checks:
        t0 = time.perf_counter()
        print(f"[run] {label} ...", flush=True)
        p = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        dt = time.perf_counter() - t0
        ok = p.returncode == 0
        print(f"[{'ok' if ok else 'fail'}] {label}  {dt:.1f}s", flush=True)
        if not ok:
            failed.append(label)
            tail = (p.stdout + "\n" + p.stderr).strip().splitlines()[-12:]
            for line in tail:
                print(f"    {line}")
    print(f"[verify] {len(checks) - len(failed)}/{len(checks)} passed  {time.perf_counter() - t_all:.1f}s")
    if failed:
        print("[verify] failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
