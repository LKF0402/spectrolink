"""AI 交互契约的共用实现：证据路径解析、动作指纹、按需下发的会话记账。

各技术的「下一步动作清单」由各自的 `build_next_actions(out)` 生成（动作词表随技术不同），
但记账、去重、stage 判定必须是全项目同一套语义——否则同一份返回在两个 server 上
会得到两种 `conclusion_allowed`。会话读写由调用方以回调注入，本模块不碰任何文件。
"""
from __future__ import annotations

import hashlib
import json


def ev_ok(out, path):
    """evidence_fields 路径解析：`a.b` 逐层取值；任一层缺失即 False。"""
    cur = out
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False
    return True


def action_sig(action):
    """动作的"语境指纹"：只取与数值有关的部分，用于判断是否需要重新下发。"""
    payload = {"id": action["id"], "values": action.get("values"),
               "evidence_fields": action.get("evidence_fields")}
    return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                  default=str).encode("utf-8")).hexdigest()[:10]


def interaction_block(out, tool, session_id, load_sessions, save_sessions,
                      build_actions, sev_block):
    """把 build_actions 的结果做成**按需下发**的交互契约块。

    返回 (interaction, next_required_actions)。stage 语义：
      · clarify  —— conclusion_allowed=false：校验 fail / 扫描含暗区 / 反演越界
      · produced —— 结论可给，但本轮仍有**新**的必须披露项未下发
      · verified —— 结论可给，且本会话该说的都已下发过（本轮无新项）
    ⚠ `verified` 只表示"要求已全部下发过"，**不代表模型已照做**（服务器看不到最终措辞）。
    ⚠ `conclusion_allowed` **故意不把"缺参数未确认"算作阻断**：缺省参数是每个新会话的
      默认状态，若据此阻断则该布尔恒为 false、随即失去信息量；缺参数走 must_disclose。
    """
    acts = build_actions(out)
    sessions = load_sessions()
    sess = sessions.get(session_id, {"confirmed": {}, "pending": [], "stage": "clarify"})
    sent = dict(sess.get("interaction_sent") or {})
    fresh, already, changed = [], [], False
    for a in acts:
        # ⚠ 按 **工具+动作** 记账：同一动作 id 若被两个工具共用，只按 id 记会互相抹掉。
        key = f"{tool}:{a['id']}"
        sig = action_sig(a)
        if sent.get(key) == sig:
            already.append(a["id"])
        else:
            fresh.append(a)
            sent[key] = sig
            changed = True
    keep = {f"{tool}:{a['id']}" for a in acts}            # 剪掉已不适用的条目
    pruned = {k: v for k, v in sent.items() if k in keep}
    if pruned != sent:
        changed = True
    if changed:
        sess["interaction_sent"] = pruned
        sessions[session_id] = sess
        try:
            save_sessions(sessions)
        except OSError:
            # 只读安装/目录不可写时降级为"不记账"：动作每次重新下发，但绝不因此让工具调用失败。
            pass

    val = out.get("validation") or {}
    physics_ok = val.get("overall") != "fail"
    blockers = [a for a in acts if a["severity"] == sev_block]
    result_usable = not blockers
    allowed = bool(physics_ok and result_usable)
    has_result = (("results" in out) or ("result" in out) or ("validation" in out)
                  or ev_ok(out, "mole_frac") or ev_ok(out, "result.x"))
    if not allowed:
        stage = "clarify"
    elif has_result and not fresh:
        stage = "verified"
    else:
        stage = "produced"
    reason = None
    if not allowed:
        parts = []
        if not physics_ok:
            fails = [c.get("check") for c in (val.get("checks") or []) if c.get("status") == "fail"]
            parts.append("物理校验未通过（validation.overall=fail）"
                         + (f"：{'、'.join(str(f) for f in fails)}" if fails else ""))
        parts += [a["action"] for a in blockers]
        reason = "；".join(parts) or "结果不可用"
    interaction = {"tool": tool, "stage": stage,
                   "physics_ok": bool(physics_ok), "result_usable": bool(result_usable),
                   "conclusion_allowed": allowed, "blocking_reason": reason,
                   "disclosure_pending": already,
                   "rule": "conclusion_allowed=false（见 blocking_reason）时不得给出定量结论；"
                           "next_required_actions 里 must_disclose 项须在同一回答里说明；"
                           "disclosure_pending 是本会话已下发过的项（不重复发大 payload，仍须覆盖）。"}
    return interaction, fresh
