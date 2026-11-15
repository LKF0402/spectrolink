"""保真度登记表的通用审计/摘要——tdlas 与 lites 的 fidelity 脚本共用。

各技术只提供自己的 `EFFECTS` 登记表与源码快照；判定逻辑（evidence 必须真在源码里、
未实现项不得带 evidence）只此一份，避免两套口径随时间漂移。
"""
from __future__ import annotations


def audit_effects(effects, sources=None):
    """检查登记表里声称的 evidence 是否真的存在于源码（防"表漂了"）。"""
    blob = "\n".join((sources or {}).values())
    problems = []
    for e in effects:
        if e["status"] == "off":
            if e["evidence"]:
                problems.append(f"{e['id']}: 标为未实现，却给了 evidence {e['evidence']}")
            continue
        if not e["evidence"]:
            problems.append(f"{e['id']}: 标为已实现，却没有 evidence（无法自证）")
            continue
        for token in e["evidence"]:
            if token not in blob:
                problems.append(f"{e['id']}: evidence 未在源码中找到 → {token!r}")
    return problems


def fidelity_summary(effects):
    """供 MCP 返回给 AI 的结构化保真度报告。"""
    return {
        "implemented": [
            {"id": e["id"], "title": e["title"], "params": e["params"], "limit": e["limit"]}
            for e in effects if e["status"] == "on"],
        "optional": [
            {"id": e["id"], "title": e["title"], "params": e["params"], "limit": e["limit"]}
            for e in effects if e["status"] == "opt"],
        "not_implemented": [
            {"id": e["id"], "category": e["cat"], "title": e["title"], "impact": e["limit"]}
            for e in effects if e["status"] == "off"],
        "disclosure_rule": "对任何定量结论，必须告知：① 本次用了哪些已实现效应；"
                           "② 是否有未实现项会影响该结论（见 not_implemented）；"
                           "③ 不得把点值当作带误差的结果呈现。",
    }
