"""返回值路径脱敏（把绝对路径替换成 `<workspace>` / `<home>`）。

MCP 工具的返回值（尤其 log 字段）常含本地绝对路径（HITRAN 缓存目录、PNG 输出目录等）。
统一在返回边界脱敏：结果被贴进会话、报告或截图时不会顺带暴露机器目录结构。
匹配大小写不敏感，替换串做正则转义。
"""
from __future__ import annotations

import re
from pathlib import Path


def make_path_sanitizer(workspace_root=None, home=None):
    """构造递归脱敏函数。

    参数
    ----
    workspace_root : 需要隐藏的工作区根路径
    home : 用户主目录；默认取 ``Path.home()``

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
