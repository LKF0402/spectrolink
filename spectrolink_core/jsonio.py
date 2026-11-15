"""JSON 状态文件的原子写盘——会话/设备库共用一份实现。

为什么必须原子：会话/设备文件是读-改-写，MCP 崩溃或断电时会留下**半截 JSON**
（下次 `_load_*` 直接 JSONDecodeError → 静默丢失全部已确认工况）。`os.replace`
在同一文件系统上是原子的：要么旧内容、要么新内容。

⚠ Windows 实测坑：两个进程同时写同一文件时 `os.replace` 会抛
`PermissionError WinError 5`（目标被另一方短暂占用）。多客户端（IDE + CLI）或
并行测试都会踩到 → 重试几次；仍失败则降级为直接写（放弃原子性，但绝不让一次工具
调用因为"写会话状态"而失败）。临时文件名带 pid，避免两进程互相覆盖。
"""
from __future__ import annotations

import os
import time


def atomic_write_text(path, text, tries=5):
    """先写同目录临时文件，再 os.replace 覆盖；失败重试后降级直接写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    try:                                   # 兜底：直接写，别把工具调用搞崩
        path.write_text(text, encoding="utf-8")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
