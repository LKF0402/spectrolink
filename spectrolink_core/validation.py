"""轻量校验块：给只有「warn 一句话」的 server 补可判定的 checks。

不替代 TDLA/LITES 的专用校验（它们已有各自的物理判据）；这里只统一
`checks[]` 的结构与 overall 的归并规则，避免四个 server 各写一套。
"""
from __future__ import annotations


def check(name, status, detail, value=None):
    """一条校验记录；status 只取 pass/warn/fail。"""
    if status not in ("pass", "warn", "fail"):
        raise ValueError(f"非法校验状态: {status}")
    item = {"check": name, "status": status, "detail": detail}
    if value is not None:
        item["value"] = value
    return item


def validation_block(checks, note=None):
    """按 fail > warn > pass 归并 overall；空 checks 时保持 warn。"""
    checks = list(checks)
    if any(c["status"] == "fail" for c in checks):
        overall = "fail"
    elif any(c["status"] == "warn" for c in checks):
        overall = "warn"
    elif checks:
        overall = "pass"
    else:
        overall = "warn"
    out = {"overall": overall, "checks": checks}
    if note:
        out["note"] = note
    return out
