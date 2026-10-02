#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LITES 仪器级仿真 MCP 服务器（stdio JSON-RPC 2024-11-05）。

把 lites_physics 的仪器级模型暴露为 AI 可直接调用的工具：

  · lites_forward          单点 2f 正向预测（含基线/气体增量拆分）
  · lites_sweep            单变量参数扫描（自动拟合幂律指数）
  · lites_waveform         合成 2f 波形 + 仪器级 6 子图
  · lites_invert           2f 幅值 → 浓度反演
  · lites_mdl              探测限 MDL + Allan 偏差
  · lites_noise_budget     噪声预算分解（1/f / 白噪声 / TIA）
  · lites_device           器件库（list / get / build / groups）
  · lites_resonance        共振跟踪与温漂分析
  · lites_compare          多器件统一口径对比
  · lites_review           实验方案评审（7 类已知失效模式）
  · lites_guide            交互协议与参数索取指南
  · lites_selftest         全链路自检

⚠️ 与 TDLAS 的关系 ────────────────────────────────────────────────
本服务器**不是** TDLAS 的换皮。LITES 是**减光口径**：气体把光挖掉
（A≈αL），残余光被器件吸收 η_dev → 2f 信号 ∝ η_dev·αL；本底为残余
AM 的 2f 分量（am_2f_frac）。与 TDLAS 的"气体吸收即信号"物理相反。
因此：
  · 校准轴是能量积累时间 τ_acc = Q/(π·f0)，不是 f0 越大越好；
  · 最优 2f 频率 ≈ f0/2（热波口径，H_mech 峰处）；
  · 音频段的 1/f 噪声主导，提高 Q 不能线性改善 LOD。
沿用 TDLAS 的入参名（sigma_tau、2f/1f 峰高口径）会误导使用者。

纪律 ─────────────────────────────────────────────────────────────
纯标准库 stdio JSON-RPC；所有 print 收进 log 字段，绝不污染 stdout。
未给出的参数进 assumptions，模型不确定处进 disclosure_pending。

自测：python tools/lites_mcp.py --selftest
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import re
import sys
import time
from pathlib import Path

_SRV = Path(__file__).resolve().parent.parent      # server-lites
_ROOT = _SRV.parent                            # 仓库根（spectrolink_core）
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lites_physics as lph  # noqa: E402
from tools import lites_tools as ltool  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "lites", "version": "0.1.0"}}
OUT_DIR = _ROOT / "tmp" / "mcp_out"   # 与 server-tdlas 共用仓库根输出目录

# 远端直链隐私：MCP 返回值（尤其 tools/call 的 log 字段）会被序列化发给远端客户端，
# 其中可能含本地绝对路径（如 HITRAN 缓存目录 Hitran_Data、PNG 输出目录 tmp/mcp_out）。
# 在返回边界统一脱敏：递归把用户目录/工作区绝对路径替换成中性标记，避免泄露服务器目录结构。
# 注意：不硬编码任何真实路径字符串（符合 push 前安全扫描规则），改用 Path.home() 动态获取。
_HOME = str(Path.home())
_WS_ROOT = str(_ROOT.parent)


def _sanitize_paths(obj):
    """递归把绝对路径（用户目录/工作区）替换成中性标记，避免远端返回值泄露服务器目录结构。"""
    if isinstance(obj, str):
        s = obj
        if _WS_ROOT and _WS_ROOT.lower() in s.lower():
            s = re.sub(re.escape(_WS_ROOT), "<workspace>", s, flags=re.IGNORECASE)
        if _HOME and _HOME.lower() in s.lower():
            s = re.sub(re.escape(_HOME), "<home>", s, flags=re.IGNORECASE)
        return s
    if isinstance(obj, list):
        return [_sanitize_paths(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _sanitize_paths(v) for k, v in obj.items()}
    return obj

# 对话状态机：跨会话记住用户已确认的工况参数（存 JSON，MCP 重启/换会话仍保留）
# 存仓库根目录隐藏文件（中性命名，不暴露宿主工具/IDE）
_SESSION_FILE = _ROOT / ".lites_session.json"


def _load_sessions():
    if _SESSION_FILE.exists():
        try:
            return json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _atomic_write_text(path, text, tries=5):
    """原子写盘：先写同目录临时文件再 os.replace 覆盖（带重试与降级）。

    为什么：会话/设备文件的读-改-写不是原子操作，MCP 崩溃或断电时会留下**半截 JSON**
    （下次 _load_* 直接 JSONDecodeError → 静默丢失全部已确认工况）。os.replace 在
    同一文件系统上是原子操作，要么旧内容、要么新内容。

    ⚠ Windows 上的坑（实测）：**两个进程同时写同一个文件**时，`os.replace` 会抛
    `PermissionError WinError 5`（目标被另一方短暂占用）。多客户端（IDE + CLI）或
    并行测试都会踩到 → 这里重试几次；仍失败则降级为直接写（放弃原子性，
    但绝不让一次工具调用因为"写会话状态"而失败）。临时文件名带 pid，避免两进程互相覆盖。
    """
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


def _save_sessions(sessions):
    _atomic_write_text(_SESSION_FILE, json.dumps(sessions, ensure_ascii=False, indent=2))


# ══════════════════ α 语境的自适应播报 ══════════════════
# α（吸收系数 / αL）峰值随 T、P、网格步长 step、翼截断 wingHW、波数窗口 变化：
# 裸报一个 α 数值不可复现、不可比较。但每次都报又啰嗦 → 做成"自适应"：
# 仅在 ① 本会话首次给出 α 峰值，或 ② 语境相对上次播报发生变化 时，才要求 AI 播报。
# 记录写入会话态（.lites_session.json），跨 MCP 重启仍有效。
_ALPHA_CTX_FIELDS = ("T_K", "P_atm", "step_cm-1", "wingHW_cm-1")


def _alpha_report_block(alpha_context, species, session_id="default"):
    """自适应决定是否需在回答中显式播报 α 峰值的计算语境。

    规则（任一命中 → needs_report=True）：
      ① 本会话首次给出 α 峰值（无既往播报记录）；
      ② 语境变化：物种 或 (T, P, step, wingHW, 窗口) 与上次已播报的不同。
    返回 None 表示本次结果不含 α 语境（该工具未报 α）。
    """
    if not alpha_context:
        return None
    snapshot = {"species": str(species).upper(),
                **{k: alpha_context.get(k) for k in _ALPHA_CTX_FIELDS},
                "window_cm-1": alpha_context.get("window_cm-1")}
    sessions = _load_sessions()
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
        _save_sessions(sessions)
    return {"alpha_peak_context": alpha_context,
            "needs_report": needs,
            "report_reason": "；".join(reasons) if reasons else "语境未变且已播报过，无需重复",
            "report_rule": "needs_report=True 时：给出 α 峰值**必须同时**列出 T(K)、P(atm)、"
                           "网格步长 step(cm⁻¹)、翼截断 wingHW(cm⁻¹)、波数窗口(cm⁻¹)——缺一不可；"
                           "needs_report=False 时数值口径不变，可省略以保持简洁。"}


def _fringe_report_block(fringe_meta, session_id="default"):
    """自适应决定是否需播报 etalon 条纹的影响评估（首次 或 语境变化）。

    未启用条纹模型时返回固定说明且**不写会话**（默认关 → 不打扰用户）。
    """
    if not (fringe_meta or {}).get("enabled"):
        return {"enabled": False, "needs_report": False,
                "note": "未启用 etalon 条纹模型（默认理想仿真）"}
    fsr = float(fringe_meta["fsr_cm-1"])
    ctr = float(fringe_meta["contrast"])
    snapshot = {"fsr_cm-1": fsr, "contrast": ctr,
                "drift_frac": float(fringe_meta.get("drift_frac") or 0.0)}
    sessions = _load_sessions()
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
        _save_sessions(sessions)
    return {"enabled": True, "fsr_cm-1": fsr, "contrast": ctr,
            "fringe_context": fringe_meta,
            "needs_report": needs,
            "report_reason": "；".join(reasons) if reasons else "语境未变且已播报过，无需重复",
            "report_rule": "needs_report=True 时须向用户说明：① 条纹 FSR 与吸收线宽的关系"
                           "（决定是否会在 2f 上伪造吸收峰）；② 确定性条纹会被背景扣除消除、"
                           "只有漂移残留；③ 压不掉条纹时该做的物理措施（窗片楔化 / AR 镀膜 / 扫频平均）。"}


# ══════════════ AI 交互契约：结构化动作（可校验 / 按需下发） ══════════════
# 为什么要有这一层：项目的"必须澄清 / 必须披露"一直以**散文**形式写在 AI_INTERACTION_GUIDE
# 里，而散文会漂、漂了不会有任何测试发现 —— 三起真实事故（`edge` 一族被参数白名单丢弃、
# `lites_invert` 描述指向 `S2f1f_peak`、`allow_partial_dark` 曾被白名单丢弃）全靠人肉复核
# 才发现。本层把它升级为**机器可读的动作**：
#   ① 每条动作指向返回值里的**具体字段**（evidence_fields），AI 不必自己找数据，也不易漏；
#   ② 三级严重度；"能不能给定量结论"由服务器算出，而不是靠模型自觉；
#   ③ **按需下发**：只下"本会话尚未下发过"的动作。每次返回都重发整张清单等于把散文搬进
#      payload 且反复计费 —— 门控复用 alpha_report / fringe_report 的既有范式；
#   ④ `build_next_actions()` 是**纯函数**，契约测试可直接断言，不必起 MCP。
# 诚实的局限：服务器看不到模型最终的措辞，故本层只保证"要求已下发且不重复骚扰"，
# **不能**保证模型照做。要真正闭环需要模型自报回执（未做：为不可验证的目标增加一次
# 往返不划算；见 docs/VALIDATION.md §8）。
_SEV_BLOCK = "block_conclusion"   # 未满足 → 不得给出定量结论（结果照给，结论受控）
_SEV_DISCLOSE = "must_disclose"   # 结论可给，但必须在同一回答里说明（缺一不可）
_SEV_ADVISORY = "advisory"        # 建议
_SEV_ORDER = {_SEV_BLOCK: 0, _SEV_DISCLOSE: 1, _SEV_ADVISORY: 2}


def _ev_ok(out, path):
    """evidence_fields 路径解析：`a.b` 逐层取值；任一层缺失即 False。

    为什么要它：动作必须只指向**本次返回里真实存在**的字段，否则 AI 按 id 执行时会
    找不到数据（这正是要消灭的那类漂移）。端到端回归 tools/_rpc_test.py 另有一条
    断言兜底：每个 next_required_actions 的 evidence_fields 都必须可解析。
    """
    cur = out
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False
    return True


def _fidelity_digest():
    """随结果下发的**精简**保真度声明（真源仍是 tools/lites_fidelity.py，此处不复制内容）。"""
    full = _fidelity_summary()
    if "unavailable" in full:
        return {"unavailable": full.get("unavailable"),
                "rule": full.get("disclosure_rule")}
    return {"modeled_count": len(full.get("implemented") or []),
            "optional_available": [e.get("id") for e in (full.get("optional") or [])],
            "not_implemented": [e.get("title") for e in (full.get("not_implemented") or [])],
            "rule": full.get("disclosure_rule"),
            "detail": "完整台账见 lites_guide 的 fidelity（含每项的实现位置与缺口说明）"}


def _condition_values(out):
    """取值本次**实际生效**的工况参数（T/P/x/L），兼容两种回显形状。

    仪器链（wms/das）给 `conditions` 块；分析链（invert 等）是平铺的 T_K/P_atm/path_cm。
    `assumptions` 只说"哪些用了默认"，不给数值 —— 缺了本函数，动作就只能要求 AI
    "说明用了默认值"却报不出数值。
    """
    c = out.get("conditions") or {}
    return {"T": c.get("T_K", out.get("T_K")),
            "P": c.get("P_atm", out.get("P_atm")),
            "x": c.get("x", out.get("x_ref", out.get("x"))),
            "L_cm": c.get("L_cm", out.get("path_cm"))}


def build_next_actions(out):
    """从工具返回**推导**出"AI 接下来必须做什么" —— 纯函数，只读 out，不碰会话/不写盘。

    返回按严重度排序的 list[dict]，每条：{id, severity, action, evidence_fields, values, template}。
    两条供契约测试断言的不变量：
      · 每个 evidence_fields 路径都能在**同一次返回**里解析到（否则 AI 找不到数据）；
      · 存在 block_conclusion 动作时，`interaction.conclusion_allowed` 必须为 False。
    """
    acts = []
    val = out.get("validation") or {}
    overall = val.get("overall")
    title = str(out.get("species") or "").upper() or "该物种"

    def add(_id, sev, action, ev, values=None, template=None):
        if not all(_ev_ok(out, p) for p in ev):        # 数据不在 → 不生成（不指向空气）
            return
        acts.append({"id": _id, "severity": sev, "action": action,
                     "evidence_fields": list(ev), "values": values, "template": template})

    # ① 扫描含暗区：不是措辞问题，而是"这个数不可用"，最高优先级
    _dark = [str(w) for w in (out.get("warnings") or []) if "无激光输出" in str(w)]
    if _dark:
        add("partial_dark_no_conclusion", _SEV_BLOCK,
            "说明本次扫描含无光暗区、2f/1f 已被截断，**不得给出定量结论**",
            ["warnings"], template=_dark[0])
    # ② 物理校验 fail：前提已破
    if overall == "fail":
        _fails = [c.get("check") for c in (val.get("checks") or []) if c.get("status") == "fail"]
        add("fix_validation_fail", _SEV_BLOCK,
            "先处理 validation 的 fail 项；fail 项不得作为可用结果报出",
            ["validation.checks"], values={"fail_checks": _fails},
            template=f"本次校验未通过：{'、'.join(str(f) for f in _fails)}。")
    # ③ 反演结果越界：摩尔分数不在 (0,1] → 结果本身不可用
    _st = out.get("mole_frac_status")
    if _st not in (None, "ok"):
        add("invert_result_unusable", _SEV_BLOCK,
            f"反演结果不可用（mole_frac_status={_st}）：先排除 k 不同源 / 出线性区 / 基线未扣，再报数",
            ["mole_frac_status"], values={"status": _st, "peak_2f1f_in": out.get("peak_2f1f_in")})
    # ④ 缺参数 → **必须是 must_disclose 而不是 block**。理由（实测标定）：
    #    `assumptions` 是"没显式传的一切"（默认工况下 35 项，含全部器件参数），
    #    `clarify.questions` 是 36 问的**题库**（`needed` 只在极端情况才为 False）。若据此
    #    阻断，则**即使显式给全 T/P/x/L，conclusion_allowed 也恒为 false** —— 这个布尔
    #    随即失去信息量、客户端会学会忽略它。项目既有口径也正是"保留默认时须在结论中
    #    明确标注"（见 confirm_note）而非拒绝出结论。真正该阻断的只有"这个数本身不可用"
    #    （扫描含暗区 / 校验 fail / 反演越界，见 ①②③）。
    _qb = out.get("clarify") or {}
    if _qb.get("needed"):
        _qs = _qb.get("questions") or out.get("param_requests") or []
        _names = [str(q.get("param")) for q in _qs if isinstance(q, dict)]
        add("clarify_missing", _SEV_DISCLOSE,
            "用原生结构化提问工具向用户提出这些缺省参数；用户明确说'用默认值'才可跳过，"
            "跳过时必须在结论里标注",
            ["clarify.questions"],
            values={"count": len(_names), "top": _names[:6],
                    "priority_hint": "波段 > 浓度/光程 > T/P > 器件 > 噪声；1 次 1–4 题，超 4 题分批"},
            template=f"有 {len(_names)} 项参数缺省，按优先级前 6：{'、'.join(_names[:6])}。")
    # ⑤ 默认值披露：**工况类逐项报**（直接决定数值），器件类只报个数
    #    （35 项全列出来没法读，AI 也会只挑几条说 —— 等于没报）
    _as = list(out.get("assumptions") or [])
    if _as:
        _cond_keys = [k for k in ("T", "P", "x", "L_cm") if k in _as]
        _cv = _condition_values(out)
        _vals = {k: _cv.get(k) for k in _cond_keys if _cv.get(k) is not None}
        _n_hw = len([k for k in _as if k not in _cond_keys])
        add("disclose_defaults", _SEV_DISCLOSE,
            "向用户说明哪些参数用了默认值（工况类须逐项给出数值），并指出改为实测值的途径",
            ["assumptions"],
            values={"condition_defaults": _vals or None,
                    "condition_params": _cond_keys or None,
                    "hardware_default_count": _n_hw},
            template=(f"本次工况参数 {'、'.join(_cond_keys)} 用了默认值"
                      f"（另有 {_n_hw} 项器件/扫描参数为默认）" if _cond_keys else
                      f"本次有 {len(_as)} 项参数用了默认值（均为器件/扫描设置）"))
    # ⑥ 归一化方法
    if _ev_ok(out, "normalization.method"):
        add("disclose_normalization", _SEV_DISCLOSE,
            "说明本次归一化方法（2f/1f 还是退化为 2f/I0），以及是否做了背景扣除",
            ["normalization.method"],
            values={"method": out["normalization"].get("method"),
                    "background_subtracted": out["normalization"].get("background_subtracted"),
                    "offband_leak_1f": out["normalization"].get("offband_leak_1f")})
    # ⑦ α 语境 / ⑧ etalon 条纹 / ⑨ 激光自动重锚：只在"需要播报"时下发
    if (out.get("alpha_report") or {}).get("needs_report"):
        add("report_alpha_context", _SEV_DISCLOSE,
            "给出 α 峰值时必须同时列出 T / P / step / wingHW / 波数窗口（缺一不可）",
            ["alpha_report.alpha_peak_context"],
            values=out["alpha_report"].get("alpha_peak_context"),
            template=out["alpha_report"].get("report_reason"))
    if (out.get("fringe_report") or {}).get("needs_report"):
        add("report_fringe_impact", _SEV_DISCLOSE,
            "说明 etalon 条纹的 FSR/对比度、是否会在 2f 上伪造吸收、以及该采取的物理措施",
            ["fringe_report.fringe_context"], values=out["fringe_report"].get("fringe_context"),
            template=out["fringe_report"].get("report_reason"))
    if out.get("laser_auto_aligned"):
        _li = out["laser_auto_aligned"]
        add("disclose_laser_realign", _SEV_DISCLOSE,
            "说明本次 wn_ref 是**自动重锚**的理想激光器假设（不是用户手上的器件），"
            "并提示提供实测 wn_ref/dν/dI 或用 lites_device 引用真实设备",
            ["laser_auto_aligned"],
            values={"wn_ref_before": _li.get("wn_ref_before"), "wn_ref_auto": _li.get("wn_ref_auto")})
    # ⑩ 保真度缺口：任何定量结论都要说清"哪些没建模"
    _fid = out.get("fidelity") or {}
    if _fid.get("not_implemented"):
        add("disclose_fidelity_gaps", _SEV_DISCLOSE,
            "说明哪些物理效应本次**未建模**（它们可能主导真实误差），并明确点值≠带误差结果",
            ["fidelity.not_implemented"], values={"not_modeled": _fid["not_implemented"]})
    # ⑪ 不确定度：给了浓度就要说清"有没有误差、是什么口径"
    if _ev_ok(out, "mole_frac") and "uncertainty" not in out:
        add("attach_uncertainty", _SEV_DISCLOSE,
            "报出浓度时须说明未附不确定度，或改用 n_repeats>0 得到统计分量",
            ["mole_frac"], values={"mole_frac": out.get("mole_frac"), "n_repeats": 0})
    return sorted(acts, key=lambda a: _SEV_ORDER.get(a["severity"], 9))


def _action_sig(action):
    """动作的"语境指纹"：只取与数值有关的部分，用于判断是否需要重新下发。"""
    payload = {"id": action["id"], "values": action.get("values"),
               "evidence_fields": action.get("evidence_fields")}
    return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                  default=str).encode("utf-8")).hexdigest()[:10]


def _interaction_block(out, tool, session_id="default"):
    """把 build_next_actions 的结果做成**按需下发**的交互契约块。

    返回 (interaction, next_required_actions)。stage 的语义（写死在这里，别再解释成别的）：
      · clarify  —— conclusion_allowed=false：校验 fail / 扫描含暗区 / 反演越界，
                    即"这个数本身不可用"，不得据此给定量结论
      · produced —— 结论可给，但本轮仍有**新**的必须披露项未下发
      · verified —— 结论可给，且本会话该说的都已下发过（本轮无新项）
    ⚠ `verified` 只表示"要求已全部下发过"，**不代表模型已照做**（服务器看不到最终措辞）。
    ⚠ `conclusion_allowed` **故意不把"缺参数未确认"算作阻断**：缺省参数是每个新会话的默认
      状态（默认工况下 assumptions 有 35 项、clarify 题库有 36 问），若据此阻断则该布尔恒为
      false、随即失去信息量。缺参数走 must_disclose（结论可给 + 必须标注），与项目既有口径
      （confirm_note："保留默认时须在结论中明确注明"）一致。
    """
    acts = build_next_actions(out)
    sessions = _load_sessions()
    sess = sessions.get(session_id, {"confirmed": {}, "pending": [], "stage": "clarify"})
    sent = dict(sess.get("interaction_sent") or {})
    fresh, already, changed = [], [], False
    for a in acts:
        # ⚠ 按 **工具+动作** 记账：review 内部会先跑一次 wms，若只按动作 id 记账，
        # 两个工具写同一份 map 会互相抹掉对方的"已下发"记录（实测序列会来回重复下发）。
        key = f"{tool}:{a['id']}"
        sig = _action_sig(a)
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
        _save_sessions(sessions)

    val = out.get("validation") or {}
    physics_ok = val.get("overall") != "fail"
    blockers = [a for a in acts if a["severity"] == _SEV_BLOCK]      # 只剩"这个数不可用"类
    result_usable = not blockers
    allowed = bool(physics_ok and result_usable)
    has_result = ("results" in out) or ("validation" in out) or _ev_ok(out, "mole_frac")
    if not allowed:
        stage = "clarify"
    elif has_result and not fresh:
        stage = "verified"
    else:
        stage = "produced"
    reason = None
    if not allowed:
        _parts = []
        if not physics_ok:
            _fails = [c.get("check") for c in (val.get("checks") or []) if c.get("status") == "fail"]
            _parts.append("物理校验未通过（validation.overall=fail）"
                          + (f"：{'、'.join(str(f) for f in _fails)}" if _fails else ""))
        _parts += [a["action"] for a in blockers]
        reason = "；".join(_parts) or "结果不可用"
    interaction = {"tool": tool, "stage": stage,
                   "physics_ok": bool(physics_ok), "result_usable": bool(result_usable),
                   "conclusion_allowed": allowed, "blocking_reason": reason,
                   "disclosure_pending": already,
                   "rule": "conclusion_allowed=false（见 blocking_reason）时不得给出定量结论；"
                           "next_required_actions 里 must_disclose 项须在同一回答里说明；"
                           "disclosure_pending 是本会话已下发过的项（不重复发大 payload，仍须覆盖）。"}
    return interaction, fresh


# ══════════════════ 设备库（仪器统一管理）══════════════════
# 用户实验仪器基本固定，把激光器/探测器/采集卡/光学元件命名存下来，
# 仿真时用 setup= / laser= / pd= / daq= / optics= 引用，省去每次手填硬件参数。
_DEVICE_FILE = _ROOT / ".lites_devices.json"

# 各类设备允许保存的参数键（对应仿真里的硬件参数）
_DEVICE_TYPES = {
    "laser": ["eta_VI", "dnu_dI", "d2nu_dI2", "wn_ref", "i_ref", "i_th", "eta_IP",
              "am_i0", "am_i2", "am_psi1", "am_psi2"],
    "pd": ["resp", "gain", "bw", "rin"],
    "daq": ["fs", "n_samples", "adc_bits", "v_range"],
    "optics": ["throughput"],
}
_DEVICE_TYPE_CN = {"laser": "激光器", "pd": "探测器", "daq": "采集卡", "optics": "光学元件"}

# 设备参数合法域：(下限, 上限, 是否含下限, 特殊约束)。None = 该端不设限。
# 为什么必须校验：这些键直接进仿真链路 —— bw→噪声带宽（负值让 np.sqrt 出 nan）、
# gain→跨阻（除零/负增益）、adc_bits/v_range→量化（非法值产生虚假分辨率）、
# fs→采样率、throughput→光通量。在"保存"这个最早入口拦下，远比等仿真出 nan 再回溯根因便宜。
_DEVICE_RULES = {
    "eta_VI": (0.0, None, False, None),
    "dnu_dI": (None, None, False, "nonzero"),
    "d2nu_dI2": (None, None, False, None),
    "wn_ref": (0.0, None, False, None),
    "i_ref": (0.0, None, True, None),
    "i_th": (0.0, None, True, None),
    "eta_IP": (0.0, None, False, None),
    "am_i0": (None, None, False, None),
    "am_i2": (None, None, False, None),
    "am_psi1": (None, None, False, None),
    "am_psi2": (None, None, False, None),
    "resp": (0.0, None, False, None),
    "gain": (0.0, None, False, None),
    "bw": (0.0, None, False, None),
    "rin": (0.0, None, True, None),
    "fs": (0.0, None, False, None),
    "n_samples": (1.0, None, True, "int"),
    "adc_bits": (4.0, 32.0, True, "int"),
    "v_range": (0.0, None, False, None),
    "throughput": (0.0, 1.0, False, None),
}


def _validate_device_entry(entry):
    """校验一组设备参数；返回错误说明（None = 通过）。"""
    for k, v in entry.items():
        rule = _DEVICE_RULES.get(k)
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


def _load_devices():
    if _DEVICE_FILE.exists():
        try:
            return json.loads(_DEVICE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_devices(devices):
    _atomic_write_text(_DEVICE_FILE, json.dumps(devices, ensure_ascii=False, indent=2))


def _resolve_devices(setup=None, laser=None, pd=None, daq=None, optics=None):
    """解析设备引用 → 返回要合并进仿真 inst 的硬件参数字典。

    某类设备的选取优先级：显式单设备引用 > setup 整机里的对应项 > 默认设备。
    返回的参数字典在调用方用 setdefault 合并（本次显式给的具体参数仍最优先）。
    """
    dev = _load_devices()
    pick = {"laser": laser, "pd": pd, "daq": daq, "optics": optics}
    if setup:
        st = dev.get("setup", {}).get(str(setup))
        if st is None:
            raise ValueError(f"整机配置 {setup!r} 不存在，请先用 lites_device 保存")
        for k in pick:
            if pick[k] is None and st.get(k):
                pick[k] = st[k]
    dflt = dev.get("default", {})
    for k in pick:
        if pick[k] is None:
            pick[k] = dflt.get(k)
    resolved = {}
    for k in ("laser", "pd", "daq", "optics"):
        name = pick[k]
        if not name:
            continue
        params = dev.get(k, {}).get(str(name))
        if params is None:
            raise ValueError(f"{_DEVICE_TYPE_CN[k]}设备 {name!r} 不存在，请先用 lites_device 保存")
        entry = {kk: vv for kk, vv in params.items() if vv is not None}
        bad = _validate_device_entry(entry)          # 兜住历史/手改过的非法条目
        if bad:
            raise ValueError(f"已保存的{_DEVICE_TYPE_CN[k]}设备 {name!r} 参数非法：{bad}；"
                             f"请用 lites_device save 重新保存修正")
        resolved.update(entry)
    return resolved


def _get_session(session_id="default"):
    return _load_sessions().get(session_id,
                                {"confirmed": {}, "pending": [], "stage": "clarify"})


def _resolve_conditions(T, P, x, L_cm, session_id="default", x_default=1e-3, L_default=50.0):
    """工况参数优先级：本次显式给 > 会话已确认 > 默认。

    会话里存的是 T/P/x/L_cm（与 lites_forward 一致）。返回 (T, P, x, L_cm, assumed)；
    assumed 为「既非本次显式给、也非会话确认、因此用了默认值」的键列表，供返回 assumptions 字段。

    ⚠ 默认值必须与仪器链（_SCENE_DEFAULTS）**同一套**：曾出现分析链 P=1.0 / L_cm=30 而
    仪器链 P=1.01325 / L_cm=50（物种推荐还有 100），同一会话里两条链对"未给光程"给出
    相差 3.3 倍的 L，两个数看起来都"合理"却互相矛盾（见 docs/VALIDATION.md §6）。
    """
    confirmed = _get_session(session_id).get("confirmed", {})
    res, assumed = {}, []
    for k, v, dflt in (("T", T, _SCENE_DEFAULTS["T"]), ("P", P, _SCENE_DEFAULTS["P"]),
                       ("x", x, x_default), ("L_cm", L_cm, L_default)):
        if v is not None:
            res[k] = v
        elif k in confirmed:
            res[k] = confirmed[k]
        else:
            res[k] = dflt
            assumed.append(k)
    return res["T"], res["P"], res["x"], res["L_cm"], assumed


def _species_defaults(species):
    """按物种返回推荐浓度 x_typ 与光程 L_cm（来自 SPECIES_PROFILES，缺省回退 1e-3 / 50 cm）。

    强吸收分子（如 CH4@3.3μm）默认浓度应更低，否则 αL 过大进入饱和区、2f/1f 非线性。
    回退值取 _SCENE_DEFAULTS 的光程，保证与仪器链一致（见 _resolve_conditions 的说明）。
    """
    prof = SPECIES_PROFILES.get(str(species or "").strip().upper(), {})
    return prof.get("x_typ", 1e-3), prof.get("L_cm", _SCENE_DEFAULTS["L_cm"])


# 技术知识：随工具返回，供 AI 向用户解释真实实验要点（而非只给数字）
EDGE_TECH_NOTE = (
    "真实实验中三角波上升沿与下降沿常不重合，成因："
    "① 激光调谐非线性（注入电流→波长响应并非完美线性）；"
    "② 扫描期间激光器热漂移（波长与功率随时间漂移）；"
    "③ 探测器与前置放大器带宽有限 → 上升/下降沿的相位滞后不同；"
    "④ 电流源上升/下降沿的扫频响应差异。"
    "处理建议：先用 edge='both' 对照两段；若重合约，任取一段即可；若不重合，取较干净的一段，"
    "或用 edge='average' 两段平均（随机噪声按 √2 改善，但系统性偏差不会被平均抵消）。"
)

# 参数索取指南：缺省参数的索取优先级 ——
# ① 用户提供的实测标定值 → ② 用户提供的器件型号（由 AI 检索规格书）
# → ③ 引导用户现场测量（如"驱动电压变化 ΔV → 波数变化 Δν"）
# → ④ 保留内置默认值并在返回中明确标注（assumptions）
PARAM_ACQ_GUIDE = {
    "species": ("待测气体", "—", "HITRAN 分子式（CH4 / H2O / CO2 / CO / C2H2 …）"),
    "wn_center": ("目标波数", "cm⁻¹", "要测的吸收线中心；决定激光调谐到哪条线"),
    "scan_span_cm": ("三角波扫描半宽", "cm⁻¹", "扫描覆盖的波数半宽；amp_V = scan_span_cm/(η_VI·|dν/dI|)，不填用默认 1.5"),
    "amp_V": ("三角波幅值", "V", "**通常无需手填**：由 wn_center + scan_span_cm 自动反算；仅需固定电压时覆盖"),
    "offset_V": ("三角波偏置", "V", "**通常无需手填**：由 wn_center 经电压—波数关系自动反算"),
    "freq_Hz": ("三角波频率", "Hz", "扫描速率；与采样率共同决定每周期采样点数"),
    "phase_deg": ("三角波相位", "°", "起始相位（默认中心对称、先上升后下降）"),
    "eta_VI": ("驱动器跨导 η_VI", "mA/V", "电压—电流转换，取决于驱动器电路"),
    "dnu_dI": ("激光器调谐系数 dν/dI", "cm⁻¹/mA", "波数标定核心；给出激光器型号可查规格书"),
    "eta_IP": ("功率斜率效率", "mW/mA", "决定光功率量级，进而决定 PD 电压与 ADC 量程占用"),
    "wn_ref": ("参考波数", "cm⁻¹", "调谐基准点（通常取规格书中心波长）"),
    "i_ref": ("参考电流", "mA", "与参考波数配对的工作点电流"),
    "i_th": ("阈值电流", "mA", "低于此电流无激光输出"),
    "fs": ("采集卡采样率", "Hz", "常见 16-bit DAQ 上限 250 kS/s"),
    "adc_bits": ("ADC 位数", "bit", "决定量化噪声与动态范围（常见 USB DAQ：16-bit）"),
    "v_range": ("ADC 输入量程", "V", "决定满量程与饱和阈值"),
    "resp": ("PD 响应度 R", "A/W", "光电转换效率（InGaAs 典型 0.9 A/W）"),
    "gain": ("PD 跨阻增益 G", "V/A", "决定 PD 输出电压；过高会导致 ADC 饱和"),
    "bw": ("PD 带宽", "Hz", "与噪声带宽、可解调的最高调制频率相关"),
    "rin": ("激光相对强度噪声 RIN", "1/√Hz", "常为 TDLAS 系统的主导噪声源"),
    "throughput": ("光学元件总透过率", "—", "窗片 / 镜片 / 光纤耦合损耗"),
    "mod_freq_Hz": ("正弦调制频率 fm", "Hz", "把信号搬到高频以规避 1/f 噪声与激光 RIN"),
    "mod_amp_V": ("正弦调制幅值", "V", "决定调制系数 m=a/HWHM；m≈2.2 时 2f 峰值最大"),
    "m_opt": ("目标调制系数 m", "—", "2f 灵敏度最优的调制深度/线宽比，经典值 2.2"),
    "lockin_avg": ("锁相平均周期数", "—", "低通平均的调制周期数，保持 1（>1 会模糊线形且不降残留）"),
    "lockin_stages": ("锁相低通级联级数", "—", "矩形窗频响是 sinc，级联 2 级(sinc²)把非吸收区 2f 残留 4.1%→1.6%"),
    "drift_frac": ("1/f 慢漂移幅度", "相对光强", "激光功率慢漂移；DAS 受害、WMS 锁相抑制；默认 0.005"),
    "flicker_frac": ("1/f 粉红噪声幅度", "相对光强", "频域 1/√f 噪声；默认 0.01"),
    "fringe_n": ("etalon 腔折射率", "—", "etalon 条纹：FSR = 1/(2nd)；空气隙 1.0、玻璃≈1.5"),
    "fringe_d_cm": ("etalon 平行面间距", "cm", "etalon 条纹：决定 FSR；10 mm→1.0、5 mm→0.5"),
    "fringe_R": ("etalon 单面反射率", "—", "etalon 条纹：峰-峰对比度≈4R/(1−R)²；未镀膜玻璃 0.04、AR≈0.005"),
}

# ★ 澄清问题模板：把缺省参数转成"带选项的自然语言问句"，供 AI 主动向用户提问。
CLARIFY_QUESTIONS = {
    "x": {"question": "待测气体浓度（摩尔分数）量级是多少？",
          "options": ["痕量 ~1e-6", "低 ~1e-4", "中 ~1e-2", "不确定，帮我推荐"],
          "why": "决定吸收强弱 αL，弱吸收(1e-5~0.1)下 DAS/2f 才线性"},
    "L_cm": {"question": "吸收池光程是多少？",
             "options": ["10 cm", "30 cm", "100 cm", "多通池（几十米）", "不确定"],
             "why": "与浓度共同决定 αL"},
    "T": {"question": "气体温度？",
          "options": ["室温 296 K", "其他（请填数值）"],
          "why": "决定线强与多普勒线宽"},
    "P": {"question": "气体压力？",
          "options": ["常压 1 atm", "减压（请填数值）", "其他"],
          "why": "决定碰撞展宽（Lorentz HWHM）"},
    "mod_freq_Hz": {"question": "正弦调制频率 fm 用多少？",
                    "options": ["默认 30 kHz", "其他（请填）"],
                    "why": "信号搬到 fm 以避开 1/f 噪声"},
    "drift_frac": {"question": "是否加入 1/f 慢漂移噪声？",
                   "options": ["不加（理想仿真）", "加 0.5%", "加 1%", "其他"],
                   "why": "模拟激光功率慢漂移；DAS 受害、WMS 抑制"},
    "flicker_frac": {"question": "是否加入 1/f 粉红噪声？",
                     "options": ["不加（理想仿真）", "加 1%", "加 3%", "其他"],
                     "why": "模拟 1/f 光强噪声"},
}


def build_clarify_questions(species, wn_center, assumed, used_values):
    """把缺省参数转成结构化澄清问题（含选项），供 AI 主动向用户提问。"""
    questions = []
    # 波段澄清（优先问，因为影响后续一切）
    prof = SPECIES_PROFILES.get(str(species).strip().upper(), {})
    if prof.get("bands"):
        q = {"param": "波段", "question": f"{species} 要测哪个波段？",
             "options": [f"{nm}（{wn} cm⁻¹）" for nm, wn in prof["bands"]],
             "why": "不同波段线强/线密度不同", "current": wn_center}
        questions.append(q)
    for k in assumed:
        tpl = CLARIFY_QUESTIONS.get(k)
        if tpl:
            questions.append({"param": k, "question": tpl["question"],
                              "options": tpl["options"], "why": tpl["why"],
                              "current_default": used_values.get(k)})
        else:
            cn, unit, why = PARAM_ACQ_GUIDE.get(k, (k, "—", ""))
            questions.append({"param": k, "中文名": cn, "单位": unit,
                              "question": f"请确认 {cn}（{unit}），当前用默认 {used_values.get(k)}",
                              "options": [], "why": why,
                              "current_default": used_values.get(k)})
    return questions


# ★ 物种推荐工况（自适应）：未给工况参数时，按物种/波段自动推荐，而非死板用默认值。
SPECIES_PROFILES = {
    "CH4": {"bands": [("3.3 μm", 3010.0), ("1.65 μm", 6046.9)],
            "x_typ": 1e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
            "note": "甲烷近红外 6046.9(2ν3 带 R(3)线，较孤立)、中红外 3010(ν3 带强吸收)"},
    "C2H6": {"bands": [("3.4 μm ν7 带", 2964.5), ("1.7 μm", 5920.0)],
             "x_typ": 1e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
             "note": "2964.5 附近 Q 支密集(159 线)，需 L 较小避免 αL 过大"},
    "H2O": {"bands": [("1.39 μm", 7185.6)],
            "x_typ": 0.02, "L_cm": 30.0, "T": 296.0, "P": 1.0,
            "note": "7185.6 为较孤立单线，常用于锁相/谐波标定"},
    "CO": {"bands": [("2.33 μm", 4285.0)],
           "x_typ": 1e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
           "note": "基频 R 支，线孤立、线强表成熟"},
    "CO2": {"bands": [("2.0 μm", 5003.0)],
            "x_typ": 5e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
            "note": "2.0 μm 组合带"},
    "NO": {"bands": [("5.26 μm", 1900.0)],
           "x_typ": 1e-4, "L_cm": 50.0, "T": 296.0, "P": 1.0,
           "note": "基频带"},
}


def adaptive_condition(species, wn_center=None):
    """工况自适应：未给工况参数时，返回该物种的推荐波段/典型浓度/光程 + **该波段的激光可达性**。

    为什么必须带可达性：推荐表横跨 1900–7185 cm⁻¹，而默认激光只是一支 3.36 μm DFB
    （可达 2964.7–2975.3 cm⁻¹）。旧版只报"推荐 7185.6"，AI 照此调用必然报 offset_V 越界，
    用户会以为是自己选错了线。现在每个波段都附 `可达` 与 `laser_params_needed`，
    AI 可以先告诉用户"该波段需要换激光器"，或直接把这组参数传进仿真（也可依赖
    auto_laser=True 的自动重锚）。
    """
    sp = str(species).strip().upper()
    p = SPECIES_PROFILES.get(sp, {})
    dflt = dict(ts.LASER_DEFAULTS)
    bands_detail = []
    for label, wn in p.get("bands", []):
        r = ts.laser_reach(wn, eta_VI=dflt["eta_VI"], dnu_dI=dflt["dnu_dI"], i_ref=dflt["i_ref"],
                           wn_ref=dflt["wn_ref"], scan_span_cm=1.5, i_th=dflt.get("i_th", 30.0))
        item = {"波段": label, "wn_center_cm-1": wn, "默认激光可达": bool(r["reachable"])}
        if not r["reachable"]:
            item["需要"] = f"wn_ref≈{r['wn_ref_needed']:.6g} cm⁻¹ 的激光器（其余参数可沿用默认）"
            item["laser_params_needed"] = {"wn_ref": round(float(r["wn_ref_needed"]), 6)}
            item["说明"] = ("默认激光（wn_ref=%.6g）覆盖不到该波段；调用 lites_forward 时"
                            "auto_laser=True（默认）会自动重锚 wn_ref 并在 warnings 中标注，"
                            "结论中必须向用户说明这不是真实硬件。" % dflt["wn_ref"])
        bands_detail.append(item)
    rec = {"species": sp,
           "推荐波段": p.get("bands", []),
           "波段可达性": bands_detail,
           "推荐浓度 x": p.get("x_typ"),
           "推荐光程 L_cm": p.get("L_cm"),
           "推荐 T": p.get("T"), "推荐 P": p.get("P"),
           "说明": p.get("note", "无内置资料，请提供工况"),
           "默认激光": {k: dflt[k] for k in ("wn_ref", "dnu_dI", "eta_VI", "i_ref")},
           "提示": "推荐波段未必落在默认激光的调谐范围内；给用户推荐前先看『波段可达性』。"}
    return rec


# ★ AI 主动指导协议：本 MCP 面向**实验新手**，AI 必须主动引导而非被动等参数。
# 每次涉及真实器件的仿真，按此顺序与用户交互（用专业术语，但首次出现给白话解释）。
AI_INTERACTION_GUIDE = {
    "role": "你是 TDLAS 实验设计助手，服务对象多为实验新手。职责是**主动指导**，不是被动等参数。"
            "凡信息不足必须主动索取，绝不能默默用默认值出结果。",
    "priority": [
        "① 先要实测标定值（最可靠）；",
        "② 用户给不出值、但能给**器件型号** → AI **联网检索**该型号官方规格书提取参数（见 datasheet_lookup）；",
        "③ 型号也没有 → 引导用户**现场标定**（例：改变驱动电压 ΔV，记录波数变化 Δν，得 dν/dV）；",
        "④ 以上都做不到 → 用内置默认值，但**必须在结论中显式标注**「以下参数用了默认值 X」。",
    ],
    "workflow": [
        "第 1 步｜确认场景：测什么分子、什么波段、什么工况（T/P/浓度量级/光程）。"
        "用户不确定时主动给推荐（CH4 → 3.3 μm 或 1.65 μm；CO → 2.3 μm；CO2 → 2.0 μm）；"
        "**推荐前先看 adaptive_condition 返回的『波段可达性』**——默认激光只覆盖 2964.7–2975.3 cm⁻¹，"
        "其它波段需要另配激光器：要么把该波段的 laser_params_needed 一并告诉用户（让他知道要换器件），"
        "要么依赖 auto_laser=True 的自动重锚（此时必须按 must_disclose⑦ 说明这属理想假设、非真实硬件）。",
        "第 2 步｜分组索取参数，每次只问一组，并说明该参数控制什么物理量（见 PARAM_ACQ_GUIDE 的 why）。",
        "第 3 步｜拿到结果后做**合理性体检**并主动告知：αL 是否在弱吸收区、ADC 是否饱和、"
        "噪声主导来源（散粒/热/RIN）、检测限量级、调制系数 m 是否接近 2.2。",
        "第 4 步｜若返回值中 warnings / param_requests 非空，**先向用户澄清再解读结论**，"
        "不要拿不合理参数直接下结论。",
    ],
    # ★ 正确 SOP（标准操作流程）——只讲怎么做对，不讲"坑"。AI 必须严格按此 SOP 输出结论。
    "sop": [
        {"step": 1, "name": "技术选型 + 选定孤立单线",
         "rule": "先按谱线密度选技术：窗口内线数 ≤10 → WMS（2f 呈标准双峰、免标定、抗 RIN）；"
                 "线数多（密集谱区）→ 2f 会把每根线都放大成独立峰、看似杂乱，此时 DAS 的直接吸收包络更直观，"
                 "不宜用 WMS 展示标准谐波。WMS 定量/展示标准谐波一律选孤立单线，"
                 "示例：H2O 7185.596、CO 4260.06、N2O 1278.45。线数看 n_lines_in_window。",
         "pass": "已按线密度选对技术 + 用户给定/AI 查到孤立线 → 进 step 2"},
        {"step": 2, "name": "确认激光波数轴覆盖目标线",
         "rule": "若自定义链路，确保 wn_ref 与 wn_center 对齐；本工具已自动处理，"
                 "校验：返回的 scan_window_cm-1 必须包含 wn_center。",
         "pass": "scan_window 包含 wn_center → 进 step 3"},
        {"step": 3, "name": "调用 lites_forward 跑链路",
         "rule": "用默认参数即可（fm=30 kHz, fscan=100 Hz, 自动优化 m=2.2, "
                 "2 级级联低通, edge=rising, trim_frac=0.12）。"
                 "图统一为 5 层：驱动电压 → DAS → 1f → 2f → 归一化 2f（自动选方法）。",
         "pass": "返回无错误 + warnings 非空（含工况说明）→ 进 step 4"},
        {"step": 4, "name": "读 normalization.method 并据此解读",
         "rule": "2f/1f 有效时：使用 2f/1f 读数；1f 失效（1f 过零 或 非吸收区泄漏>30%）："
                 "使用 2f/I0（I0=PD 非吸收区光强均值）读数。**严格按 normalization.method 给出的方法写结论，不要混用**。",
         "pass": "已用同一归一化方法贯穿所有波段读数 → 进 step 5"},
        {"step": 5, "name": "三件校验（形态类判据视工况打折）",
         "rule": "① DAS 提取峰与 HITRAN 理论 αL 一致（偏差 <2%）；"
                 "② 2f 峰位 Δν ≈ ±0.7a（孤立单线下应见标准双峰结构）；"
                 "③ 非吸收区残留/峰 < 2%。"
                 "⚠ **默认工况本身通常就有 1–2 条形态类提醒**（如 CH4@2968.5 密集谱区："
                 "αL=0.133 偏大 + 221 条线非孤立），这属正常，不是失败；"
                 "密集谱区 ② 本就不该按孤立线的标准双峰要求。",
         "pass": "三项都通过 → 物理结论可信；任何一项不通过 → 停止解读，回 step 1 排查（形态类先看线密度）"},
        {"step": 6, "name": "自检 + 二次审核（必须）",
         "rule": "每次出图/下结论前，必须用 lites_review（或读取返回的 validation）做自动校验；"
                 "校验 10 项：波数轴对齐、DAS-理论一致、αL 弱吸收、是否孤立线、调制系数 m、"
                 "采样率、ADC 动态范围、归一化方法、噪声、etalon 条纹。overall=fail 时**不得下结论**，"
                 "先修 fail 项；warn 项须在结论中向用户说明。",
         "pass": "validation.overall=pass 或（warn 项已向用户说明）"},
        {"step": 7, "name": "输出结论",
         "rule": "按此顺序：① 工况（物种/波段/T/P/x/L/fm/调制系数）；"
                 "② normalization.method 及 I0；③ 2f（或归一化 2f）峰值与位置；"
                 "④ 噪声分解（shot/thermal/RIN/1f）；⑤ validation 结论（pass/warn/fail）。"
                 "所有用默认值的参数必须显式标注「默认值」。",
         "pass": "结论完整、可复现、附校验结论"},
    ],
    "image_layout": {
        "布局": "3 行 × 2 列，共 6 子图，固定顺序（左→右、上→下），"
                "figsize≈14×10，每子图约 2:1（横长竖短，利于读谱线形、贴合黄金矩形）：",
        "subplots": [
            "① 波长调制 V(t)（三角波+正弦调制，横轴时间）",
            "② PD 原始信号（无调制 DAS 链路，横轴波数，左轴 V）",
            "DAS αL（-ln 提取）+ HITRAN 理论 αL（虚线对照，横轴波数）",
            "③ 一阶谐波 1f（单独，横轴波数）",
            "④ 二阶谐波 2f（单独，横轴波数）",
            "⑤ 归一化 2f（标注方法 2f/1f 或 2f/I0）",
        ],
        "rule": "1f 与 2f **必须分开**（幅值量级不同，不可同图）；"
                "PD 原始信号与 DAS αL 分两个子图；理论 αL 与 DAS αL 同图用虚线区分；"
                "每层标题标注技术名 + 归一化/基线处理方法；剔除区红带标出；"
                "横轴：驱动电压用时间，其余用波数（扫描波数，非瞬时）。",
        "标注要求": "用户只说'给我 XX 气体图'时，一律出这套 6 子图；"
                    "技术名、归一化方法、基线处理（拟合 or 背景扣除）必须在图上显式标注。",
        "线型约定": "实线=实测/有效数据；虚线=理论参考（如 HITRAN 理论 αL）；"
                    "点线=剔除区（三角波转折点，不可信）；每种线型必须在图例里注明含义。",
    },
    "defaults_when_unknown": "所有物理参数未给时按以下顺序索取：① 实测标定值 → "
                             "② 器件型号（AI 自己检索规格书）→ ③ 引导用户现场标定 → ④ 保留内置默认并**显式标注**「默认值 X」。",
    "datasheet_lookup": {
        "何时": "用户提供了器件型号（如 DAQ 型号、DFB 激光器型号、光电探测器型号）时。",
        "动作": "AI **必须**联网检索该型号的官方 datasheet / 规格书提取参数（用 web 搜索 + 打开官方页面），"
                "不要只把型号当标签、也不要凭记忆编数字。",
        "按器件类别要查的参数": {
            "数据采集卡 DAQ": ["采样率上限 fs_max (S/s)", "分辨率 (bit)", "量程 (±V)", "输入噪声/输入阻抗"],
            "激光器驱动 / 电流源": ["V→I 跨导或调谐响应", "电流量程 (mA)", "调制带宽 (kHz)", "输出噪声 (µA/√Hz)"],
            "DFB / 可调谐激光器": ["中心波长 / 波数", "调谐系数 dν/dI (cm⁻¹/mA)", "阈值电流 i_th (mA)",
                              "输出功率 (mW)", "线宽 (MHz)"],
            "光电探测器 PD": ["响应度 resp (A/W)", "带宽 bw (Hz)", "跨阻增益 gain (V/A)",
                          "NEP (W/√Hz)", "饱和功率"],
        },
        "查到后": "把规格书参数填进仿真对应字段，并在 assumptions 里标注「来源：<型号> datasheet」。",
        "查不到或无网络": "退回到优先级 ③（引导现场标定）或 ④（默认值 + 显式标注），**不得编造规格书数值**。",
    },
    "das_vs_wms": {
        "本质": "WMS 通常强于 DAS。DAS 信号在 DC，受害于 1/f 噪声与激光慢漂移；"
                "WMS 把信号搬到 fm（30 kHz）用窄带锁相提取，避开 1/f，"
                "且 2f/1f 归一化抵消光强波动（免标定）。",
        "公平对比前提": "DAS 与 WMS 必须用同一套噪声模型（白噪声 + 1/f 粉红噪声 + 慢漂移）与同源噪声；"
                "DAS 漏加噪声等于作弊，会得出'WMS 反而差'的假象。",
        "正确判据": "看浓度反演稳定性/检测限，而非单周期 σ；2f/1f 不应在非吸收区（2f、1f 都≈0）测噪声。",
        "何时用 DAS": "需要绝对浓度、或谱线密集区想看直观包络时；",
        "何时用 WMS": "痕量检测、抗 1/f 与漂移、在线免标定时。",
        "谱线密度与波形": "孤立单线（n_lines ≤10）→ 2f 呈标准双峰；密集谱区 → 2f 多峰叠加（DAS 包络更直观）。"
                          "这只是'波形形态'问题，不代表 DAS 更强。",
    },
    "edge_definition": "edge 指**驱动电压**方向（daq_triangle 前半=电压上升、后半=电压下降）；"
                       "因 dν/dI<0（真实 DFB 激光：电流↑→波长红移→波数↓），电压上升沿对应波数下降、"
                       "下降沿对应波数上升。工具把所选方向反转为波数递增输出。",
    "pd_baseline_slope": "PD 原始信号含光强斜坡（L-I 曲线），且 dν/dI<0 使'波数递增'对应'光强下降'，"
                        "故默认 edge=rising 的 PD 基线呈**下降沿**——这是激光器真实特性，不是错误。"
                        "如需光强上升沿，用 edge=falling；DAS 吸光度已除以 I0 消除斜坡，不受影响。",
    "das_baseline_method": {
        "仿真做法": "DAS 基线用**理想 I0**（无吸收光强）：I0 = p_laser × throughput × resp × gain，"
                    "直接用 -ln(v_das / I0) 得 αL。因为仿真里 I0 可精确算出，无需拟合。",
        "为何不用非吸收区拟合": "真实实验常用'非吸收区多项式拟合'估 I0，但**密集谱区没有非吸收区**"
                "（如 C2H6 2963-2966 有 159 条线），off 掩码为空 → 拟合退化、基线把吸收也平均进去，"
                "导致 DAS 峰值偏移/为负（已实测：峰值偏 1.4 cm^-1、相关系数仅 0.015）。",
        "真实实验对应": "实测无法直接得 I0，应：① 扫到线翼外取非吸收基线；② 或充纯缓冲气测背景谱扣基线；"
                "③ 或用相邻无非吸收区时做多项式外推。仿真用 I0 是'已知真值的上限'，供验证用。",
        "告知": "解读 DAS 时须向用户说明：本仿真的 DAS 基线用的是理想 I0（非吸收光强），"
                "真实实验需另做背景扣除，DAS 实际精度会低于此理想值。",
    },
    "condition_adaptation": {
        "规则": "工况参数（T/P/x/L_cm）未给时，按物种用 SPECIES_PROFILES 自动推荐（自适应），"
                "不套用全局默认；返回 condition_advice 告知推荐值。"
                "**推荐波段的可达性也在 condition_advice 里**（波段可达性/laser_params_needed），"
                "推荐前先核对，否则用户按推荐选波段会直接撞上激光调谐范围。",
        "主动询问": "出图前必须**主动向用户确认工况**：物种/波段是否正确、浓度量级、光程、"
                    "T/P；用户不确定时给出 condition_advice 的推荐。",
        "弱吸收校验": "推荐工况应使 αL 落在 1e-3 ~ 1e-1（弱吸收线性区）；"
                      "若 αL>0.1 应建议降低 x 或 L_cm，若 <1e-5 应建议增大。",
    },
    "alpha_reporting": {
        "原则": "α（吸收系数 / αL）峰值随 T、P、网格步长 step、翼截断 wingHW、波数窗口 变化——"
                "**裸报一个 α 数值不可复现、不可比较**。故给出 α 峰值时须能同时给出这五项语境。",
        "何时必须报（自适应）": "看返回的 alpha_report.needs_report：True 时必须报"
                                "（本会话首次给出 α 峰值，或语境相对上次发生变化）；"
                                "False 说明语境未变、已播报过，可省略以保持简洁。",
        "报什么": "α 峰值数值 + T(K) + P(atm) + step(cm⁻¹) + wingHW(cm⁻¹) + 窗口(cm⁻¹)，缺一不可；"
                  "具体值见 alpha_report.alpha_peak_context。",
        "注意": "不得为求简洁而省略语境后再对 α 做定量结论；语境不同的两次 α 不可直接比较。",
    },
    "fringe_reporting": {
        "原则": "etalon 干涉条纹是 TDLAS 痕量检测的**头号系统性误差**：两个平行且反射率不可忽略的面"
                "（窗片/透镜/光纤端面）构成 F-P 腔，产生周期 FSR=1/(2nd)、峰-峰对比度≈4R/(1−R)² 的透过率起伏，"
                "其 2f 与吸收 2f 同形。模型**默认关闭**（fringe=False），绝不静默注入系统性误差。",
        "何时问": "用户提到窗片 / 光纤 / 滤光片 / 未镀膜或未楔化窗片时，应主动询问是否建模；"
                  "开启后若未给几何参数，返回的 param_requests 会列出 fringe_n / fringe_d_cm / fringe_R。",
        "汇报内容": "看返回的 fringe_report：needs_report=True（本会话首次启用或条纹语境变化）时，须说明"
                    "FSR 与吸收线宽的关系、确定性条纹可被背景扣除而只有漂移残留、"
                    "以及压不掉条纹时应采取的物理措施（窗片楔化 / AR 镀膜 / 扫频平均）。",
        "禁止": "不得把 etalon 条纹当成可被降噪 / 多次平均消掉的随机噪声——固定腔长的条纹是确定性项。",
    },
    "fidelity_reporting": {
        "原则": "仿真只包含**已建模的效应**；未建模项（自展宽、线混合、暗电流、前放 1/f…）"
                "在当前工况下可能主导真实误差。**点值不等于带误差的结果。**",
        "单一真源": "能力登记表在 tools/lites_fidelity.py（EFFECTS）：每项效应的实现位置、"
                    "是否默认生效、已知缺口写在同一张表里，并由 audit 与源码证据交叉核对。"
                    "本工具返回的 fidelity 块即该表的结构化快照，**以它为准**，勿凭记忆复述。",
        "何时报": "① 用户问「这个结果可信吗 / 误差多大」；② 给出任何定量结论（浓度、LOD、灵敏度）时；"
                  "③ 结论涉及 fidelity.not_implemented 中某项时——例：高浓度（自展宽）、"
                  "密集谱区（线混合）、痕量 LOD（前放 1/f 未建模 ⇒ LOD 偏乐观）。",
        "报什么": "① 本次实际生效的效应（fidelity.implemented）；"
                  "② 会影响该结论的未实现项（fidelity.not_implemented）；"
                  "③ 明确「这是点值，未含系统不确定度」。",
        "禁止": "不得把未实现项说成「已建模」；不得把点值当带误差的结果呈现；"
                "不得用 n_repeats 的统计散布冒充总不确定度（它只含 run-to-run 随机分量）。",
    },
    "clarify_protocol": {
        "触发": "返回的 clarify.needed=True（有缺省参数）时，必须进入澄清流程。",
        "流程": "① 按 clarify.questions 向用户提问；② 收到回答后填入对应参数重跑；"
                "③ 用户明确说'用默认值'才可跳过该项；④ 全部确认后才出图/下结论。",
        "强制": "clarify.instruction 明确要求'先问再出结果'，这是硬约束，不是建议。",
        "多轮": "支持多轮：每次用户补充一个参数，就少问一个（questions 会随 assumed 缩小）。",
        "提问工具": "AI 必须用**原生结构化提问工具**（AskUserQuestion 类，点击式选择框）"
                    "把 clarify.questions 渲染成选择题，**禁止用纯文字列表让用户打字回答**；"
                    "1 次 1–4 题、每题 2–4 个固定选项 + '其他'自由输入；"
                    "超过 4 题时按优先级分批多轮：波段 > 浓度/光程 > T/P > 器件 > 噪声。",
    },
    "noise_and_interaction": {
        "默认": "**默认：RIN 与 1/f（漂移/粉红）关，但散粒/热噪声恒在**——它们是物理固有项"
                "（只取决于光电流与带宽，量级通常 0.01–0.1 mV），无法通过参数关闭；"
                "要让噪声严格为零请设 physical_noise=False（此时为纯理论对照，结果逐位可复现）。"
                "随机种子默认 seed=0 → 默认参数下结果可复现；返回里的 seed_used 即实际所用种子。",
        "询问": "MCP 必须在出图/解读前**主动询问用户**：是否需要加噪声？加哪类？多大？"
                "可选：① RIN 白噪声(rin) ② 1/f 慢漂移(drift_frac) ③ 1/f 粉红(flicker_frac)。"
                "散粒/热噪声为物理固有、量级极小，**恒在**（若用户要求绝对无噪，用 physical_noise=False）。",
        "透明化": "每次返回必须把 noise_breakdown_mV + noise_1f 原样告知用户，"
                  "并明确「本次是否加了噪声、加了哪些、幅度多少」。",
        "多交互": "MCP 服务要**多与用户交互**，而非一次性吐结果：① 先确认工况（物种/波段/T/P/浓度/光程）；"
                  "② 主动问噪声需求；③ 解读前确认归一化方法；④ 主动问是否调噪声/换孤立线。",
    },
    "glossary": {
        "αL": "吸光度（吸收系数×光程），无量纲；≪1 才算弱吸收，DAS/2f 才与浓度成正比",
        "HWHM": "吸收线半高半宽（cm⁻¹），决定最优调制深度",
        "m": "调制系数 = 调制深度 a ÷ HWHM，最优约 2.2",
        "fm": "正弦调制频率（把信号搬到高频，避开低频噪声）",
        "fscan": "三角波扫描频率（扫过整条吸收线）",
        "RIN": "激光相对强度噪声，常为 TDLAS 主导噪声源",
        "2f/1f": "用 1f 谐波归一化 2f，抵消光强波动；弱吸收下正比于浓度（免标定核心）",
        "LOD": "检测限（最小可测浓度）",
        "m 优化": "工具会自动按 m≈2.2 反算正弦调制幅值；如需手动指定可用 mod_amp_V",
    },
}


# ══════════════════════════════════════════════════════════════════════
# 工具层
#
# 本层是**薄封装**：只做三件事 ——
#   1. 把 MCP 的 kwargs 原样透传给 tools/lites_tools.py 的实现；
#   2. 统一补上 assumptions / next_required_actions / disclosure_pending
#      三个协作契约块（缺一不可，客户端与 CI 都依赖它们）；
#   3. 把 stdout 收进 log，保证协议流干净。
#
# 真正的物理在 lites_physics.py，仪器口径在 tools/lites_tools.py。
# 这里**绝不**复制任何公式 —— 历史上 TDLAS 版本就因为在这里抄了一份
# review 的 schema 而漂移过一次。
# ══════════════════════════════════════════════════════════════════════

@contextlib.contextmanager
def _quiet():
    """把第三方库（HAPI / matplotlib）的刷屏收进缓冲区，不污染 stdout 协议流。

    ⚠️ 必须保留 @contextlib.contextmanager —— 丢了它 `with _quiet():`
    会抛 AttributeError: __enter__（已在拼接脚本里栽过一次）。
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def _ensure_contract(out, tool_name):
    """补齐协作契约三块。若实现层已给出则原样保留，不覆盖。

    为什么放在 MCP 层而不是实现层：契约是**对外协议**的一部分，
    任何工具都必须满足。放在边界上做兜底，新增工具时不会漏。
    """
    if not isinstance(out, dict):
        return out
    out.setdefault("assumptions", [])
    out.setdefault("next_required_actions", [])
    out.setdefault("disclosure_pending", [])
    out.setdefault("tool", tool_name)
    return out


def _wrap(fn, tool_name):
    """把实现层函数包成 MCP 工具：补契约 + 收 stdout + 异常转可读文本。"""
    def _call(**kwargs):
        with _quiet() as g:
            out = fn(**kwargs)
        out = _ensure_contract(out, tool_name)
        txt = g.getvalue().strip()
        if txt:
            out["log"] = _sanitize_paths(txt).splitlines()
        return out
    _call.__name__ = tool_name
    _call.__doc__ = fn.__doc__
    return _call


# ── 逐个绑定（显式列出，避免 hasattr 魔法导致 schema 与实现脱节）──

t_forward = _wrap(ltool.lites_forward, "lites_forward")
t_sweep = _wrap(ltool.lites_sweep, "lites_sweep")
t_waveform = _wrap(ltool.lites_waveform, "lites_waveform")
t_invert = _wrap(ltool.lites_invert, "lites_invert")
t_mdl = _wrap(ltool.lites_mdl, "lites_mdl")
t_noise_budget = _wrap(ltool.lites_noise_budget, "lites_noise_budget")
t_device = _wrap(ltool.lites_device, "lites_device")
t_resonance = _wrap(ltool.lites_resonance, "lites_resonance")
t_compare = _wrap(ltool.lites_compare, "lites_compare")
t_review = _wrap(ltool.lites_review, "lites_review")
t_guide = _wrap(ltool.lites_guide, "lites_guide")


def t_selftest():
    """全链路自检：物理内核（lites_physics）+ 仪器口径（lites_tools）双层。

    两层都不通过时才算失败；任一层报错都会把完整日志回传，便于定位。
    注意 lites_physics.selftest() 返回 list[str]（不是上下文管理器，
    也不是 dict），这里显式适配，避免把返回值当 dict 用。
    """
    log = []
    ok = True

    try:
        with _quiet():
            lines_phys = list(lph.selftest())
        log += ["=== lites_physics.selftest ==="] + lines_phys
        bad = [x for x in lines_phys if x.startswith("[FAIL]")]
        if bad:
            ok = False
    except Exception as e:
        ok = False
        log.append(f"[FAIL] lites_physics.selftest 抛异常：{type(e).__name__}: {e}")

    try:
        r = ltool.lites_selftest()
        log += ["=== lites_tools.lites_selftest ==="] + list(r.get("log") or [])
        log.append(f"通过 {r.get('n_pass')} / 失败 {r.get('n_fail')}")
        ok = ok and bool(r.get("ok"))
    except Exception as e:
        ok = False
        log.append(f"[FAIL] lites_tools.lites_selftest 抛异常：{type(e).__name__}: {e}")

    return {"ok": ok, "log": _sanitize_paths(log)}


DISPATCH = {
    "lites_forward": t_forward,
    "lites_sweep": t_sweep,
    "lites_waveform": t_waveform,
    "lites_invert": t_invert,
    "lites_mdl": t_mdl,
    "lites_noise_budget": t_noise_budget,
    "lites_device": t_device,
    "lites_resonance": t_resonance,
    "lites_compare": t_compare,
    "lites_review": t_review,
    "lites_guide": t_guide,
    "lites_selftest": t_selftest,
}


# ══════════════════════════════════════════════════════════════════════
# JSON Schema 定义
#
# 与实现层的签名**必须一致**：MCP 层 _validate_args 会拦未声明的键，
# 若这里漏写一个参数，AI 传了就会被拒（而不是静默丢弃 —— 这是有意的，
# "以为改了、实际没改"比直接报错危险得多）。
#
# ⚠️ 本段由 tools/_gen_schema.py 生成，请勿手工编辑嵌套结构。
#    改 schema 请改生成脚本后重跑，避免括号错配。
# ══════════════════════════════════════════════════════════════════════

_COND_PROPS = {
    "T": {
        "type": "number",
        "description": "气体温度 K，默认 296",
    },
    "P": {
        "type": "number",
        "description": "气体压力 atm，默认 1.01325",
    },
    "gamma_L": {
        "type": "number",
        "description": "洛伦兹半宽 HWHM cm⁻¹，默认 0.06",
    },
    "L_gas_cm": {
        "type": "number",
        "description": "气体吸收光程 cm；缺省 = 器件标称光程（MPC 为 2580）",
    },
    "line_strength": {
        "type": "number",
        "description": "谱线强度 cm⁻¹/(molecule·cm⁻²)；缺省 = 该器件标定的锚定值",
    },
    "f_m": {
        "type": "number",
        "description": "调制频率 Hz；缺省 = f0/2",
    },
    "power_mW": {
        "type": "number",
        "description": "器件处入射光功率 mW；缺省 = 标定值",
    },
}


TOOLS = [{
    "name": "lites_forward",
    "description": "【LITES 单点正向预测】给定工况返回 2f 幅值，并**显式拆分**基线 V_2f_baseline（器件自身吸收产生的 offset）与气体增量 V_2f_delta。做浓度反演时必须用 delta 口径，用总量口径会得到错误的线性度。返回含 SBR_eta = 气体项/器件项，这是 LITES 区别于 TDLAS 的核心指标。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "T": {
                "type": "number",
                "description": "气体温度 K，默认 296",
            },
            "P": {
                "type": "number",
                "description": "气体压力 atm，默认 1.01325",
            },
            "gamma_L": {
                "type": "number",
                "description": "洛伦兹半宽 HWHM cm⁻¹，默认 0.06",
            },
            "L_gas_cm": {
                "type": "number",
                "description": "气体吸收光程 cm；缺省 = 器件标称光程（MPC 为 2580）",
            },
            "line_strength": {
                "type": "number",
                "description": "谱线强度 cm⁻¹/(molecule·cm⁻²)；缺省 = 该器件标定的锚定值",
            },
            "f_m": {
                "type": "number",
                "description": "调制频率 Hz；缺省 = f0/2",
            },
            "power_mW": {
                "type": "number",
                "description": "器件处入射光功率 mW；缺省 = 标定值",
            },
            "device": {
                "type": "string",
                "description": "器件键名（内置默认 qtf-commercial-decapped，用户可自定义器件后传入）；用 lites_device(action='list') 查全部",
            },
            "x": {
                "type": "number",
                "description": "摩尔分数；缺省 = 器件标定的锚定浓度",
            },
            "mod_depth_cm1": {
                "type": "number",
                "description": "波长调制深度 cm⁻¹，默认 0.3",
            },
            "f0_shift_ppm": {
                "type": "number",
                "description": "f0 相对标称值的偏移 ppm（模拟温漂/装配误差）",
            },
            "eta_spurious": {
                "type": "number",
                "description": "寄生吸收（窗口污染/散射）附加的 η；不填=0",
            },
            "species": {
                "type": "string",
                "description": "物种名覆盖，默认取器件所属物种",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_sweep",
    "description": "【单变量扫描】对某一参数扫值并自动拟合幂律指数。可用于验证'信号∝功率''信号∝光程'这类标度律，或找出饱和拐点。log_scale=True 时按对数均匀取点（适合跨 2~3 个数量级的扫描）。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "默认 qtf-commercial-decapped（去壳裸音叉）",
            },
            "var": {
                "type": "string",
                "description": "被扫参数：power_mW / L_gas_cm / x / line_strength / gamma_L / T / f_m / mod_depth_cm1 / f0_shift_ppm",
            },
            "values": {
                "type": "array",
                "items": {
                    "type": "number",
                },
                "description": "显式取值列表；给了就不用 n_points 自动生成",
            },
            "log_scale": {
                "type": "boolean",
                "description": "是否对数取点，默认 true",
            },
            "n_points": {
                "type": "integer",
                "description": "自动取点数量，默认 25",
            },
            "base": {
                "type": "object",
                "description": "其余工况的基准值（透传给 lites_forward）",
            },
        },
        "required": ["var"],
    },
}, {
    "name": "lites_waveform",
    "description": "【合成 2f 波形 + 仪器级出图】沿慢扫三角波逐点计算，生成完整 2f 波形，并输出 6 子图（吸收线型 / 机械传递函数 / 热扩散低通 / 2f 信号 / 扣基线后 / 噪声预算）。注意基线**故意不置零** —— 这是 LITES 的真实特征，扣基线动作由调用方决定。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "T": {
                "type": "number",
                "description": "气体温度 K，默认 296",
            },
            "P": {
                "type": "number",
                "description": "气体压力 atm，默认 1.01325",
            },
            "gamma_L": {
                "type": "number",
                "description": "洛伦兹半宽 HWHM cm⁻¹，默认 0.06",
            },
            "L_gas_cm": {
                "type": "number",
                "description": "气体吸收光程 cm；缺省 = 器件标称光程（MPC 为 2580）",
            },
            "line_strength": {
                "type": "number",
                "description": "谱线强度 cm⁻¹/(molecule·cm⁻²)；缺省 = 该器件标定的锚定值",
            },
            "f_m": {
                "type": "number",
                "description": "调制频率 Hz；缺省 = f0/2",
            },
            "power_mW": {
                "type": "number",
                "description": "器件处入射光功率 mW；缺省 = 标定值",
            },
            "device": {
                "type": "string",
                "description": "默认 qtf-commercial-decapped（去壳裸音叉）",
            },
            "x": {
                "type": "number",
                "description": "摩尔分数；缺省 = 器件标定值",
            },
            "mod_depth_cm1": {
                "type": "number",
                "description": "调制深度 cm⁻¹，默认 0.3",
            },
            "f_scan": {
                "type": "number",
                "description": "慢扫频率 Hz，默认 0.1",
            },
            "n_scan": {
                "type": "integer",
                "description": "扫描采样点数，默认 4000",
            },
            "sigma_V": {
                "type": "number",
                "description": "输出电压噪声 V，默认 9.16e-6",
            },
            "seed": {
                "type": "integer",
                "description": "噪声随机种子",
            },
            "save_png": {
                "type": "boolean",
                "description": "是否出图，默认 true",
            },
            "out_path": {
                "type": "string",
                "description": "PNG 输出路径；缺省 = docs/assets/lites_waveform.png",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_invert",
    "description": "【浓度反演】由实测 2f 幅值反推摩尔分数。use_delta=True（默认）表示传入的已是扣基线后的气体增量；若手持的是含基线的绝对读数，传 use_delta=False 并给出 v_2f_baseline_V。返回含线性度自检：反推值再正演一轮，核对是否回到原幅值。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "T": {
                "type": "number",
                "description": "气体温度 K，默认 296",
            },
            "P": {
                "type": "number",
                "description": "气体压力 atm，默认 1.01325",
            },
            "gamma_L": {
                "type": "number",
                "description": "洛伦兹半宽 HWHM cm⁻¹，默认 0.06",
            },
            "L_gas_cm": {
                "type": "number",
                "description": "气体吸收光程 cm；缺省 = 器件标称光程（MPC 为 2580）",
            },
            "line_strength": {
                "type": "number",
                "description": "谱线强度 cm⁻¹/(molecule·cm⁻²)；缺省 = 该器件标定的锚定值",
            },
            "f_m": {
                "type": "number",
                "description": "调制频率 Hz；缺省 = f0/2",
            },
            "power_mW": {
                "type": "number",
                "description": "器件处入射光功率 mW；缺省 = 标定值",
            },
            "v_2f_measured_V": {
                "type": "number",
                "description": "实测 2f 幅值 V",
            },
            "device": {
                "type": "string",
                "description": "默认 qtf-commercial-decapped（去壳裸音叉）",
            },
            "use_delta": {
                "type": "boolean",
                "description": "true=输入是扣基线后的增量（默认）；false=输入含基线",
            },
            "v_2f_baseline_V": {
                "type": "number",
                "description": "use_delta=False 时必须给出基线值 V",
            },
        },
        "required": ["v_2f_measured_V"],
    },
}, {
    "name": "lites_mdl",
    "description": "【探测限 MDL】由灵敏度 + 噪声算出最小可探测浓度，并给出 Allan 偏差随积分时间的变化。关键提醒：LITES 工作在音频段，1/f 噪声主导，积分时间延长后 MDL 下降会**早于**纯白噪声预期的 √t 规律而饱和。注意：本工具按**单位浓度灵敏度**外推 MDL，不需要传参考浓度 x（弱吸收线性区与 x 无关）。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "T": {
                "type": "number",
                "description": "气体温度 K，默认 296",
            },
            "P": {
                "type": "number",
                "description": "气体压力 atm，默认 1.01325",
            },
            "gamma_L": {
                "type": "number",
                "description": "洛伦兹半宽 HWHM cm⁻¹，默认 0.06",
            },
            "L_gas_cm": {
                "type": "number",
                "description": "气体吸收光程 cm；缺省 = 器件标称光程（MPC 为 2580）",
            },
            "line_strength": {
                "type": "number",
                "description": "谱线强度 cm⁻¹/(molecule·cm⁻²)；缺省 = 该器件标定的锚定值",
            },
            "f_m": {
                "type": "number",
                "description": "调制频率 Hz；缺省 = f0/2",
            },
            "power_mW": {
                "type": "number",
                "description": "器件处入射光功率 mW；缺省 = 标定值",
            },
            "device": {
                "type": "string",
                "description": "默认 qtf-commercial-decapped（去壳裸音叉）",
            },
            "sigma_V": {
                "type": "number",
                "description": "输出电压噪声 V；缺省 = 器件标定值。**强烈建议给实测值**，否则 MDL 只是模型估计",
            },
            "n_sigma": {
                "type": "number",
                "description": "几倍σ作为判据，默认 1.0",
            },
            "integration_s": {
                "type": "number",
                "description": "指定积分时间 s，返回该点的 MDL",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_noise_budget",
    "description": "【噪声预算】把总噪声拆成 1/f、白噪声、TIA 三部分并给出各自占比。用于判断'当前 LOD 是被哪一项卡住的' —— 这是决定下一步该改光学还是改电路的依据。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "默认 qtf-commercial-decapped（去壳裸音叉）",
            },
            "bandwidth_Hz": {
                "type": "number",
                "description": "等效噪声带宽 Hz，默认 100",
            },
            "v_rms_1f": {
                "type": "number",
                "description": "实测 1f 处电压噪声 V_rms；给了就用实测而非模型值",
            },
            "c_in_F": {
                "type": "number",
                "description": "TIA 输入电容 F；给了才做 TIA 噪声项",
            },
            "resp_V_per_C": {
                "type": "number",
                "description": "电荷灵敏放大器响应 V/C",
            },
            "compare_literature": {
                "type": "boolean",
                "description": "是否对照文献锚点的噪声值，默认 true",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_device",
    "description": "【器件库】查/建器件。内置器件均来自文献实测锚点（f0、Q、V_2f、噪声、几何）。action='list' 列全部；'get' 取单个详情；'groups' 看标定分组（同组内可比）；'build' 由参数现场构造一个虚拟器件做假设性推演。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "groups", "build"],
                "description": "list / get / groups / build",
            },
            "key": {
                "type": "string",
                "description": "get/build 时的器件键名（build 时为新建的名字）",
            },
            "overrides": {
                "type": "object",
                "description": "build 时的字段覆盖，如 {material:'quartz', f0:9500, q:10800, coating:'pdms', spot_w_m:3e-4}",
            },
        },
        "required": ["action"],
    },
}, {
    "name": "lites_resonance",
    "description": "【共振跟踪分析】给定温漂或装配误差，算出 f0 偏移、2f 失谐惩罚(dB)、以及'必须主动跟踪还是被动温控够用'的结论。LITES 的 Q 很高（~10⁴），失谐 0.01% 就会明显掉信号。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "默认 qtf-commercial-decapped（去壳裸音叉）",
            },
            "delta_T_K": {
                "type": "number",
                "description": "温升 K，默认 1.0",
            },
            "assume_f0": {
                "type": "number",
                "description": "用实测 f0 覆盖标称值 Hz",
            },
            "freq_error_pct": {
                "type": "number",
                "description": "直接指定相对频率误差 %（与 delta_T_K 二选一）",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_compare",
    "description": "【多器件统一口径对比】强制所有条目用同一线强/浓度/噪声，输出可比的对比表。默认对比 3 个典型器件。注意：光程与功率**按各自默认值**，反映的是'各器件在自己的工作点上'；若要比本征性能，请在 common 里显式把 L_gas_cm 与 power_mW 设为同一值。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "devices": {
                "type": "array",
                "items": {
                    "type": "string",
                },
                "description": "器件键名列表",
            },
            "common": {
                "type": "object",
                "description": "统一工况，可含 line_strength / x / sigma_V / L_gas_cm / power_mW",
            },
            "metrics": {
                "type": "array",
                "items": {
                    "type": "string",
                },
                "description": "要输出的指标名，默认 ['V_delta','SNR','MDL']",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_review",
    "description": "【实验方案评审】按 LITES 的 7 类已知失效模式逐条检查给定方案，返回 verdict + 逐条 finding（含严重度与建议）。7 类失效模式：η_dev 未标定 / 基线漂移误判为信号 / 共振失谐 / 热扩散截止压制 2f / 1/f 噪声主导被误当白噪声 / MPC 吞吐损失被忽略 / 光功率密度超损伤阈值。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "T": {
                "type": "number",
                "description": "气体温度 K，默认 296",
            },
            "P": {
                "type": "number",
                "description": "气体压力 atm，默认 1.01325",
            },
            "gamma_L": {
                "type": "number",
                "description": "洛伦兹半宽 HWHM cm⁻¹，默认 0.06",
            },
            "L_gas_cm": {
                "type": "number",
                "description": "气体吸收光程 cm；缺省 = 器件标称光程（MPC 为 2580）",
            },
            "line_strength": {
                "type": "number",
                "description": "谱线强度 cm⁻¹/(molecule·cm⁻²)；缺省 = 该器件标定的锚定值",
            },
            "f_m": {
                "type": "number",
                "description": "调制频率 Hz；缺省 = f0/2",
            },
            "power_mW": {
                "type": "number",
                "description": "器件处入射光功率 mW；缺省 = 标定值",
            },
            "device": {
                "type": "string",
                "description": "默认 qtf-commercial-decapped（去壳裸音叉）",
            },
            "x": {
                "type": "number",
                "description": "摩尔分数",
            },
            "mod_depth_cm1": {
                "type": "number",
                "description": "调制深度 cm⁻¹",
            },
            "sigma_V": {
                "type": "number",
                "description": "电压噪声 V",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_guide",
    "description": "【使用指南】返回 LITES 的交互协议：参数索取优先级、术语表、参数物理含义、以及新手最常踩的坑。topic 传入关键词可做术语检索。第一次接触 LITES 时建议先调这个。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "关键词，如 quickstart / SBR / tau_acc / Q / MDL / 噪声；留空返回全量",
            },
        },
        "required": [],
    },
}, {
    "name": "lites_selftest",
    "description": "【全链路自检】跑物理内核 + 仪器口径两层的全部自检项，返回通过/失败数与逐条日志。改动模型后必须先跑这个。",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}]


# 工具名 → inputSchema 的索引。_validate_args 依赖它做未知键/必填/类型校验。
# ⚠️ 本段随 schema 一起生成（不要手工挪动），否则重新生成 schema 时会丢失，
#    表现为 tools/call 抛 NameError: _SCHEMA_BY_NAME（已栽过一次）。
_SCHEMA_BY_NAME = {t["name"]: t["inputSchema"] for t in TOOLS}


def _validate_args(name, args):
    """按 inputSchema 做轻量校验（未知键 / 必填 / 类型）。返回错误说明，None = 通过。

    为什么必须拦未知键：此前未声明的键被**静默丢弃**，最惨的一次是 schema 声明了
    `edge`/`trim_frac`/`d2nu_dI2`/`am_*` 而 MCP 层从未透传 → AI 传 edge="falling"
    得到的是 rising 的结果、返回体里还写着 rising，全程零提示。用户会拿着归因错误的
    结论去指导真实实验 —— "以为改了、实际没改"比直接报错危险得多。
    """
    if not isinstance(args, dict):
        return "arguments 必须是 JSON 对象"
    sch = _SCHEMA_BY_NAME.get(name) or {}
    props = sch.get("properties") or {}
    missing = [k for k in (sch.get("required") or []) if k not in args]
    if missing:
        return f"缺少必填参数：{missing}"
    unknown = sorted(k for k in args if k not in props)
    if unknown:
        return (f"存在未声明的参数：{unknown}；本工具允许的键：{sorted(props)}。"
                f"（拼写错误会被拒绝而非静默忽略；确需新参数请提 issue）")
    for k, v in args.items():
        if v is None:
            continue
        want = (props.get(k) or {}).get("type")
        if want == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return f"参数 {k} 期望 number，收到 {type(v).__name__}（{v!r}）"
        if want == "integer" and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or float(v) != int(v)):
            return f"参数 {k} 期望 integer，收到 {v!r}"
        if want == "boolean" and not isinstance(v, bool):
            return f"参数 {k} 期望 boolean，收到 {v!r}"
        if want == "string" and not isinstance(v, str):
            return f"参数 {k} 期望 string，收到 {type(v).__name__}"
    return None


# ───────────────────────── JSON-RPC ─────────────────────────

def handle_request(req):
    """处理 MCP 请求（initialize / tools/list / tools/call）。

    支持 JSON-RPC 2.0 批量请求（顶层数组）；批量内每个请求独立处理，通知（返回 None）被剔除。
    """
    if isinstance(req, list):                     # 批量请求：此前会把 list 当 dict 用 → AttributeError
        if not req:
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600, "message": "空批量请求"}}
        return [r for r in (handle_request(x) for x in req) if r is not None]
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "请求必须是 JSON 对象或其数组"}}

    method = req.get("method", "")
    params = req.get("params") or {}
    req_id = req.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": SERVER_INFO}
    if method in ("notifications/initialized", "initialized"):
        return None                                  # 通知无需响应
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = DISPATCH.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"未知工具：{name}"}}
        bad = _validate_args(name, args)
        if bad:
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"参数错误：{bad}"}],
                               "isError": True}}
        try:
            result = fn(**args)
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [{"type": "text",
                                            "text": json.dumps(result, ensure_ascii=False,
                                                               indent=2)}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [{"type": "text",
                                            "text": f"出错：{type(e).__name__}: {e}"}],
                               "isError": True}}
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"未知方法：{method}"}}


def _arg(name, default=""):
    """读取 `--name value` 形式的命令行参数。"""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _run_http(host, port, token):
    """HTTP 传输（MCP Streamable HTTP）：把同一套 handle_request 暴露为 URL。

    远端 MCP 客户端直接填 http://<host>:<port>/mcp 即可直链，调用全部 12 个工具。
    - POST /mcp  客户端→服务器 JSON-RPC（支持 application/json 或 text/event-stream）
    - GET  /mcp  服务器→客户端推送通道（本工具服务器无主动推送，返回 405）
    - 可选 --token 做 Bearer 鉴权（远程暴露强烈建议）
    """
    import uuid
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    SESSION_ID = uuid.uuid4().hex

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # 协议日志不污染 stdout
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers",
                              "Content-Type, Authorization, Mcp-Session-Id, Accept")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

        def _auth_ok(self):
            if not token:
                return True
            a = self.headers.get("Authorization", "")
            return a == f"Bearer {token}" or a == token

        def _send(self, resp):
            if resp is None:  # 通知：无响应体
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self._cors()
                self.end_headers()
                return
            body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            use_sse = "text/event-stream" in self.headers.get("Accept", "")
            self.send_response(200)
            self.send_header("Mcp-Session-Id", SESSION_ID)
            self._cors()
            if use_sse:
                payload = b"data: " + body + b"\n\n"
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def _read_body(self):
            """可靠读取请求体：同时支持 Content-Length 与 chunked 传输编码。

            cloudflared 等反向代理常发 chunked（无 Content-Length），若只按
            Content-Length 读会漏读，残留字节污染连接复用 → 501 'Unsupported method'。
            """
            te = (self.headers.get("Transfer-Encoding", "") or "").lower()
            if "chunked" in te:
                return self._read_chunked()
            try:
                n = int(self.headers.get("Content-Length", 0))
            except ValueError:
                n = 0
            return self.rfile.read(n) if n > 0 else b""

        def _read_chunked(self):
            buf = b""
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    line = self.rfile.readline().strip()
                try:
                    size = int(line.split(b";")[0], 16)
                except ValueError:
                    break
                if size == 0:
                    while True:
                        h = self.rfile.readline()
                        if h in (b"\r\n", b""):
                            break
                    break
                buf += self.rfile.read(size)
                self.rfile.readline()  # 消费块尾 \r\n
            return buf

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            self.send_response(405)
            self.send_header("Allow", "POST")
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if self.path not in ("/mcp", "/"):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not self._auth_ok():
                err = b'{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"unauthorized"}}'
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return
            try:
                req = json.loads(self._read_body() or b"{}")
            except Exception as e:
                self._send({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": f"解析失败：{e}"}})
                return
            self._send(_sanitize_paths(handle_request(req)))

    sys.stderr.write(f"[lites-mcp] HTTP 模式已启动：http://{host}:{port}/mcp\n")
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


def main():
    # Windows 控制台默认 GBK：协议流必须强制 UTF-8，否则中文会破坏 JSON-RPC
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if "--selftest" in sys.argv:
        try:
            print(json.dumps(_sanitize_paths(t_selftest()), ensure_ascii=False, indent=2))
        except ImportError as exc:      # 依赖缺失：给可操作的提示 + 非零退出码（便于 CI 判断）
            sys.stderr.write(f"[lites-mcp] 自检无法运行：{exc}\n")
            raise SystemExit(2)
        return
    if "--http" in sys.argv:
        host = _arg("--host", "127.0.0.1")
        port = int(_arg("--port", "8000"))
        token = _arg("--token", "")
        if host in ("0.0.0.0", "") and not token:
            sys.stderr.write("[警告] 监听 0.0.0.0 且未设置 --token：任何能访问该端口的客户端都可调用仿真，"
                             "远程暴露请务必加 --token。\n")
        _run_http(host, port, token)
        return
    for line in sys.stdin:                            # stdio 协议循环
        line = line.strip()
        if not line:
            continue
        try:
            resp = _sanitize_paths(handle_request(json.loads(line)))
        except ValueError:                     # JSON 解析失败：不回显 Python 异常文本
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "JSON 解析失败（请检查该行是否为合法 JSON 对象）"}}
        if resp is not None:
            print(json.dumps(resp, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
