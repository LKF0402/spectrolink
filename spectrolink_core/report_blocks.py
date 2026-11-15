"""与具体技术无关的会话级报告块——tdlas 与 lites 共用的判定策略。

为什么放 core：这些块的**判定规则与给 AI 的措辞**必须全项目一份。此前两个 server
各写一套，改一处漏一处就会出现"同一行为、两种口径"；会话读写在 core 侧以回调注入，
不把任何 server 的存储实现耦合进来。
"""
from __future__ import annotations

import math


def condition_values(out):
    """取值本次**实际生效**的工况参数（T/P/x/L），兼容两种回显形状。

    仪器链（wms/das）给 `conditions` 块；分析链（invert 等）是平铺的 T_K/P_atm/path_cm。
    """
    c = out.get("conditions") or {}
    return {"T": c.get("T_K", out.get("T_K")),
            "P": c.get("P_atm", out.get("P_atm")),
            "x": c.get("x", out.get("x_ref", out.get("x"))),
            "L_cm": c.get("L_cm", out.get("path_cm"))}


def species_defaults(species, profiles, fallback_l_cm):
    """按物种返回推荐浓度 x_typ 与光程 L_cm（缺省回退 1e-3 / fallback_l_cm）。"""
    prof = profiles.get(str(species or "").strip().upper(), {})
    return prof.get("x_typ", 1e-3), prof.get("L_cm", fallback_l_cm)


def validate_device_params(entry, rules):
    """校验一组设备参数；返回错误说明（None = 通过）。"""
    for k, v in entry.items():
        rule = rules.get(k)
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return f"参数 {k}={v!r} 不是数值"
        if not math.isfinite(fv):
            return f"参数 {k}={v!r} 不是有限数值"
        if rule is None:
            continue
        lo, hi, lo_incl, kind = rule
        if kind == "int" and abs(fv - round(fv)) > 1e-9:
            return f"参数 {k}={fv:g} 必须为整数"
        if kind == "nonzero" and fv == 0.0:
            return f"参数 {k} 不能为 0（否则波数不随注入电流变化，无法反算扫描中心）"
        if lo is not None and (fv < lo or (fv == lo and not lo_incl)):
            return f"参数 {k}={fv:g} 必须 {'≥' if lo_incl else '>'} {lo:g}"
        if hi is not None and fv > hi:
            return f"参数 {k}={fv:g} 必须 ≤ {hi:g}"
    return None


def alpha_report_block(alpha_context, species, session_id, load_sessions, save_sessions,
                       ctx_fields):
    """自适应决定是否需在回答中显式播报 α 峰值的计算语境。"""
    if not alpha_context:
        return None
    snapshot = {"species": str(species).upper(),
                **{k: alpha_context.get(k) for k in ctx_fields},
                "window_cm-1": alpha_context.get("window_cm-1")}
    sessions = load_sessions()
    sess = sessions.get(session_id, {"confirmed": {}, "pending": [], "stage": "clarify"})
    prev = sess.get("last_alpha_report")
    reasons = []
    if prev is None:
        reasons.append("本会话首次给出 α 峰值")
    elif prev != snapshot:
        reasons.append("α 计算语境与上次不同")
    needs = bool(reasons)
    if needs:
        sess["last_alpha_report"] = snapshot
        sessions[session_id] = sess
        save_sessions(sessions)
    return {"alpha_peak_context": alpha_context,
            "needs_report": needs,
            "report_reason": "；".join(reasons) if reasons else "语境未变且已播报过，无需重复",
            "report_rule": "needs_report=True 时：给出 α 峰值**必须同时**列出 T(K)、P(atm)、"
                           "网格步长 step(cm⁻¹)、翼截断 wingHW(cm⁻¹)、波数窗口(cm⁻¹)——缺一不可；"
                           "needs_report=False 时数值口径不变，可省略以保持简洁。"}


def fringe_report_block(fringe_meta, session_id, load_sessions, save_sessions):
    """自适应决定是否需播报 etalon 条纹的影响评估（首次 或 语境变化）。"""
    if not (fringe_meta or {}).get("enabled"):
        return {"enabled": False, "needs_report": False,
                "note": "未启用 etalon 条纹模型（默认理想仿真）"}
    fsr = float(fringe_meta["fsr_cm-1"])
    ctr = float(fringe_meta["contrast"])
    snapshot = {"fsr_cm-1": fsr, "contrast": ctr,
                "drift_frac": float(fringe_meta.get("drift_frac") or 0.0)}
    sessions = load_sessions()
    sess = sessions.get(session_id, {"confirmed": {}, "pending": [], "stage": "clarify"})
    prev = sess.get("last_fringe_report")
    reasons = []
    if prev is None:
        reasons.append("本会话首次启用 etalon 条纹")
    elif prev != snapshot:
        reasons.append("etalon 条纹语境与上次不同")
    needs = bool(reasons)
    if needs:
        sess["last_fringe_report"] = snapshot
        sessions[session_id] = sess
        save_sessions(sessions)
    return {"enabled": True, "fsr_cm-1": fsr, "contrast": ctr,
            "fringe_context": fringe_meta,
            "needs_report": needs,
            "report_reason": "；".join(reasons) if reasons else "语境未变且已播报过，无需重复",
            "report_rule": "needs_report=True 时须向用户说明：① 条纹 FSR 与吸收线宽的关系"
                           "（决定是否会在 2f 上伪造吸收峰）；② 确定性条纹会被背景扣除消除、"
                           "只有漂移残留；③ 压不掉条纹时该做的物理措施（窗片楔化 / AR 镀膜 / 扫频平均）。"}
