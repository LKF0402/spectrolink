"""把交互契约接到各 server 的 DISPATCH 上：一处包装，避免四个 server 复制。

会话状态默认只在进程内保存（重启重置），不依赖 server 目录写权限；如需镜像，
传入 `session_file`，写失败静默降级为“不记账、每次重新下发”。
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

from .interaction import interaction_block
from .jsonio import atomic_write_text


def _save(path, sessions):
    try:
        atomic_write_text(path, json.dumps(sessions, ensure_ascii=False,
                                           sort_keys=True, indent=2))
    except OSError:
        pass


def install_interaction(dispatch, tools, session_file, build_actions,
                        sev_block="block_conclusion", skip=()):
    """包装 `dispatch` 里的工具函数，为每个返回体追加 interaction 两字段。

    `build_actions(out, tool)` 返回动作 dict 列表；`skip` 内的工具（如 selftest）
    不参与契约、也不写会话。包装保留原函数签名（functools.wraps），因此
    schema/自检/调用方看到的仍是原函数。
    """
    path = Path(session_file) if session_file else None
    names = [t["name"] for t in tools if t["name"] not in set(skip)]
    memory = {}                     # 进程内会话：不依赖目录写权限

    def load_sessions():
        return memory

    def save_sessions(sessions):
        snapshot = dict(sessions)   # sessions 可能正是 memory 本身，先快照再清空
        memory.clear()
        memory.update(snapshot)
        if path is not None:
            _save(path, snapshot)

    for name in names:
        fn = dispatch[name]

        @functools.wraps(fn)
        def wrapper(*args, __fn=fn, __name=name, **kwargs):
            out = __fn(*args, **kwargs)
            if isinstance(out, dict):
                block, actions = interaction_block(
                    out, __name, "default", load_sessions, save_sessions,
                    lambda o, __n=__name: build_actions(o, __n), sev_block)
                out["interaction"] = block
                out["next_required_actions"] = actions
            return out

        dispatch[name] = wrapper
