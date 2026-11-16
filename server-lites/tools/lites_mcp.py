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
  · lites_device           器件库（list / get / build）
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
import io
import json
import sys
from pathlib import Path

_SRV = Path(__file__).resolve().parent.parent      # server-lites
_ROOT = _SRV.parent                            # 仓库根（spectrolink_core）
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lites_physics as lph  # noqa: E402
from tools import lites_tools as ltool  # noqa: E402
from spectrolink_core import calibfree as _cf  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "lites", "version": "1.1.0"}}
# 返回值（尤其 tools/call 的 log 字段）可能含本地绝对路径（如 HITRAN 缓存目录、
# PNG 输出目录）。在返回边界统一脱敏：递归把用户目录/工作区绝对路径替换成中性标记。
# 注意：不硬编码任何真实路径字符串（符合 push 前安全扫描规则），改用 Path.home() 动态获取。
_HOME = str(Path.home())
_WS_ROOT = str(_ROOT.parent)

from spectrolink_core.interaction import (                      # noqa: E402
    ev_ok as _ev_ok, interaction_block as _interaction_block_core)
from spectrolink_core.jsonio import atomic_write_text as _atomic_write_text   # noqa: E402
from spectrolink_core.mcp_runtime import (                      # noqa: E402
    make_handle_request, serve_stdio, validate_args)
from spectrolink_core.sanitize import make_path_sanitizer       # noqa: E402

_sanitize_paths = make_path_sanitizer(_WS_ROOT, _HOME)


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


def _save_sessions(sessions):
    _atomic_write_text(_SESSION_FILE, json.dumps(sessions, ensure_ascii=False, indent=2))


# ══════════════════ α 语境的自适应播报 ══════════════════

# ══════════════ AI 交互契约：结构化动作（可校验 / 按需下发） ══════════════
# 为什么要有这一层：项目的"必须澄清 / 必须披露"曾以**散文**形式写在交互指南里，
# 而散文会漂、漂了不会有任何测试发现 —— 三起真实事故（`edge` 一族被参数白名单丢弃、
# `lites_invert` 描述指向 `S2f1f_peak`、`allow_partial_dark` 曾被白名单丢弃）全靠人肉复核
# 才发现。本层把它升级为**机器可读的动作**：
#   ① 每条动作指向返回值里的**具体字段**（evidence_fields），AI 不必自己找数据，也不易漏；
#   ② 三级严重度；"能不能给定量结论"由服务器算出，而不是靠模型自觉；
#   ③ **按需下发**：只下"本会话尚未下发过"的动作。每次返回都重发整张清单等于把散文搬进
#      payload 且反复计费 —— 门控按「工具+动作」在会话里记账；
#   ④ `build_next_actions()` 是**纯函数**，契约测试可直接断言，不必起 MCP。
# 诚实的局限：服务器看不到模型最终的措辞，故本层只保证"要求已下发且不重复骚扰"，
# **不能**保证模型照做。要真正闭环需要模型自报回执（未做：为不可验证的目标增加一次
# 往返不划算；见 docs/VALIDATION.md §8）。
_SEV_BLOCK = "block_conclusion"   # 未满足 → 不得给出定量结论（结果照给，结论受控）
_SEV_DISCLOSE = "must_disclose"   # 结论可给，但必须在同一回答里说明（缺一不可）
_SEV_ADVISORY = "advisory"        # 建议
_SEV_ORDER = {_SEV_BLOCK: 0, _SEV_DISCLOSE: 1, _SEV_ADVISORY: 2}


def build_next_actions(out):
    """从工具返回**推导**出"AI 接下来必须做什么" —— 纯函数，只读 out，不碰会话/不写盘。

    返回按严重度排序的 list[dict]，每条：{id, severity, action, evidence_fields, values, template}。

    ⚠ LITES 的返回没有 TDLAS 的 warnings / normalization / fidelity / clarify 块，
    所以判定只依赖 LITES **实际产出**的字段（validation / result.x / linearity_check /
    assumptions / findings）。历史上这里照抄了 TDLAS 的字段名，导致除 disclose_defaults
    外的分支全是永不触发的死代码。
    """
    acts = []
    val = out.get("validation") or {}
    overall = val.get("overall")

    def add(_id, sev, action, ev, values=None, template=None):
        if not all(_ev_ok(out, p) for p in ev):        # 数据不在 → 不生成（不指向空气）
            return
        acts.append({"id": _id, "severity": sev, "action": action,
                     "evidence_fields": list(ev), "values": values, "template": template})

    # ① 物理校验 fail：前提已破
    if overall == "fail":
        _fails = [c.get("check") for c in (val.get("checks") or []) if c.get("status") == "fail"]
        add("fix_validation_fail", _SEV_BLOCK,
            "先处理 validation 的 fail 项；fail 项不得作为可用结果报出",
            ["validation.checks"], values={"fail_checks": _fails},
            template=f"本次校验未通过：{'、'.join(str(f) for f in _fails)}。")
    # ② 反演结果越界：摩尔分数必须在 (0,1]
    if _ev_ok(out, "result.x"):
        _x = out["result"].get("x")
        if not isinstance(_x, (int, float)) or not (0.0 < float(_x) <= 1.0):
            add("invert_result_unusable", _SEV_BLOCK,
                "反演结果不可用（x 不在 (0,1]）：先排除基线过扣/灵敏度符号/参数不同源，再报数",
                ["result.x"], values={"x": _x})
        if "uncertainty" not in out:
            add("attach_uncertainty", _SEV_DISCLOSE,
                "报出浓度时须说明未附不确定度，或改用多次实测得到统计分量",
                ["result.x"], values={"x": _x})
    # ②b 正演/波形：浓度与弱吸收线性区（与反演同一条判据，覆盖 forward/sweep/waveform）
    if _ev_ok(out, "conditions.x"):
        _xc = out["conditions"].get("x")
        if not isinstance(_xc, (int, float)) or not (0.0 < float(_xc) <= 1.0):
            add("concentration_unusable", _SEV_BLOCK,
                "输入浓度 x 不在 (0,1]：先修正摩尔分数再解释信号",
                ["conditions.x"], values={"x": _xc})
    _alpha_l, _alpha_path = None, None
    for _p in ("linearity_check.alphaL", "conditions.alphaL", "metrics.alphaL"):
        if _ev_ok(out, _p):
            _v = out
            for _part in _p.split("."):
                _v = _v[_part]
            if isinstance(_v, (int, float)):
                _alpha_l, _alpha_path = float(_v), _p
                break
    if _alpha_l is not None and _alpha_l >= 0.05:
        add("disclose_nonlinear", _SEV_DISCLOSE,
            "说明 αL 已出弱吸收线性区（线性反演误差 >2.5%）；定量结论须改用 "
            "lites_forward 迭代或稀释后重测",
            [_alpha_path],
            values={"alphaL": _alpha_l, "threshold": 0.05})

    if _ev_ok(out, "power_law_index"):
        _pl = out.get("power_law_index")
        if isinstance(_pl, (int, float)) and abs(float(_pl) - 1.0) >= 0.10:
            add("disclose_sweep_nonlinear", _SEV_DISCLOSE,
                "sweep 的 log-log 斜率明显偏离 1（次线性/超线性）：不得把该扫描"
                "当作线性标定曲线，先确认是否进入饱和区或功率损失",
                ["power_law_index"], values={"power_law_index": _pl})
    # ③ review 的 warn 项：方案体检发现的问题必须逐条转述
    _warn = [f for f in (out.get("findings") or [])
             if isinstance(f, dict) and f.get("level") == "warn"]
    if _warn:
        add("disclose_review_warnings", _SEV_DISCLOSE,
            "逐条说明 review 的 warn 项（优化前先解决失效模式，不要只报 ok 项）",
            ["findings"], values={"items": [f.get("item") for f in _warn][:6],
                                  "count": len(_warn)})
    # ④ 默认值披露：assumptions 是完整句子，逐项转述（不能只报个数）
    _as = list(out.get("assumptions") or [])
    if _as:
        add("disclose_defaults", _SEV_DISCLOSE,
            "向用户说明哪些参数用了默认值（工况/器件均须点名），并指出改为实测值的途径",
            ["assumptions"],
            values={"count": len(_as), "items": _as[:6]},
            template=f"本次有 {len(_as)} 项参数用了默认值，前 6 项：{'；'.join(map(str, _as[:6]))}")
    return sorted(acts, key=lambda a: _SEV_ORDER.get(a["severity"], 9))


def _interaction_block(out, tool, session_id="default"):
    """按需下发交互契约块（记账/去重/stage 语义见 core，本处注入本技术的动作清单）。

    实现层 `_block(next_actions=...)` 给出的动作（dict）也并入清单：否则 `_wrap`
    用 core 返回的 fresh 覆盖 `next_required_actions` 时会把实现层的提示静默丢掉。
    """
    def _actions(o):
        impl = [a for a in (o.get("next_required_actions") or []) if isinstance(a, dict)]
        return build_next_actions(o) + impl

    return _interaction_block_core(out, tool, session_id, _load_sessions, _save_sessions,
                                   _actions, _SEV_BLOCK)


def _get_session(session_id="default"):
    return _load_sessions().get(session_id,
                                {"confirmed": {}, "pending": [], "stage": "clarify"})


# 技术知识：随工具返回，供 AI 向用户解释真实实验要点（而非只给数字）
# LITES 不需要「波段选择 / 激光可达性」：它不建模激光调谐，波长只通过
# `lites_forward(wn_cm1=...)` 影响 QTF 器件吸收率，线强由调用方显式给出。
# 因此这里不再保留 TDLAS 式的物种推荐表、激光可达性表与散文交互协议；
# 真正对外的话术以本文件 `build_next_actions`（机器可读动作）与 server-lites/SKILL.md 为准。


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


# 需要下发交互契约的工具（仪器/分析链）；guide / device / selftest 不写会话、不下发动作。
_INTERACTION_TOOLS = {
    "lites_forward", "lites_sweep", "lites_waveform", "lites_invert",
    "lites_mdl", "lites_noise_budget", "lites_resonance", "lites_compare", "lites_review",
    "lites_calibfree",
}


def _wrap(fn, tool_name):
    """把实现层函数包成 MCP 工具：补契约 + 收 stdout + 异常转可读文本。"""
    def _call(**kwargs):
        with _quiet() as g:
            out = fn(**kwargs)
        out = _ensure_contract(out, tool_name)
        if tool_name in _INTERACTION_TOOLS:
            out["interaction"], out["next_required_actions"] = _interaction_block(out, tool_name)
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
t_calibfree = _wrap(ltool.lites_calibfree, "lites_calibfree")
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

    try:
        cf_lines = list(_cf.selftest())
        log += ["=== calibfree.selftest ==="] + cf_lines
        if any(x.startswith("[FAIL]") for x in cf_lines):
            ok = False
    except Exception as e:
        ok = False
        log.append(f"[FAIL] calibfree.selftest 抛异常：{type(e).__name__}: {e}")

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
    "lites_calibfree": t_calibfree,
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
                "description": "器件键名，如 qtf-commercial-decapped / qtf-commercial-decapped（默认）/用 lites_device(action='list') 查全部",
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
            "wn_cm1": {
                "type": "number",
                "description": "目标波数 cm⁻¹；给出即启用 QTF 全波段吸收率模型（η_dev 按波长缩放，基准=器件标定波长）",
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
            "gas": {
                "type": "string",
                "description": "HITRAN 分子式（如 CH4 / H2O）；给出则用真实多线剖面替代单线，此时必须同时给 wn_center",
            },
            "wn_center": {
                "type": "number",
                "description": "真实波段中心波数 cm⁻¹（gas 模式必填）",
            },
            "scan_span_cm": {
                "type": "number",
                "description": "慢扫半宽 cm⁻¹，默认 3.0",
            },
            "iso": {
                "type": "string",
                "description": "HITRAN 同位素选择，默认 \"all\"",
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
    "description": "【器件库】查/建器件。内置器件均来自文献实测锚点（f0、Q、V_2f、噪声、几何）。action='list' 列全部；'get' 取单个详情；'build' 由参数现场构造一个虚拟器件做假设性推演。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "build"],
                "description": "list / get / build",
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
    "name": "lites_calibfree",
    "description": "【LITES 免标定】guide 返回最小数据清单；anchored 用单点已知浓度 + 功率监测 + 共振参数做跨浓度免标定曲线：x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)。同器件同波长跨浓度，换器件/波长重锚一次。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["guide", "anchored"],
                "description": "guide / anchored；默认 guide",
            },
            "data_path": {
                "type": "string",
                "description": "CSV/NPZ 路径；列名 v2f,v2f_ref,power_mW,f_m_Hz",
            },
            "v2f_sample": {
                "type": "number",
                "description": "样品 2f 电压 V（波形请先取峰值）",
            },
            "v2f_ref": {
                "type": "number",
                "description": "已知浓度参考的 2f 电压 V",
            },
            "x_ref": {
                "type": "number",
                "description": "参考摩尔分数",
            },
            "power_sample_mW": {
                "type": "number",
                "description": "样品测量时的入射光功率 mW",
            },
            "power_ref_mW": {
                "type": "number",
                "description": "参考测量时的入射光功率 mW",
            },
            "f_m_sample_Hz": {
                "type": "number",
                "description": "样品测量的调制频率 Hz",
            },
            "f_m_ref_Hz": {
                "type": "number",
                "description": "参考测量的调制频率 Hz",
            },
            "f0_Hz": {
                "type": "number",
                "description": "音叉共振频率 Hz；与 Q 一起给才做共振归一化",
            },
            "Q": {
                "type": "number",
                "description": "音叉品质因数；与 f0_Hz 一起给",
            },
            "v2f_baseline_sample": {
                "type": "number",
                "description": "样品 0% 气基线 V（可选）",
            },
            "v2f_baseline_ref": {
                "type": "number",
                "description": "参考 0% 气基线 V（可选）",
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
    """兼容旧引用：转调共用协议层的严格校验（必填 / 未知键 / 类型）。

    同时是 `tools/_gen_schema.py` 的拼接终点（splice 以 `def _validate_args` 行定位），
    删掉会让重新生成 schema 直接失败——保留，勿当成死代码清理。
    """
    return validate_args(_SCHEMA_BY_NAME, name, args)


# ───────────────────────── JSON-RPC ─────────────────────────

# 协议语义只由 spectrolink_core.mcp_runtime 定义：批量 / 通知 / 必填 / 未知键 /
# 类型 / 工具边界异常，六个 server 完全同一口径。
handle_request = make_handle_request(SERVER_INFO, TOOLS, DISPATCH,
                                     _SCHEMA_BY_NAME, sanitize=_sanitize_paths)


def main():
    # Windows 控制台默认 GBK：协议流必须强制 UTF-8，否则中文会破坏 JSON-RPC
    if "--selftest" in sys.argv:
        try:
            print(json.dumps(_sanitize_paths(t_selftest()), ensure_ascii=False, indent=2))
        except ImportError as exc:      # 依赖缺失：给可操作的提示 + 非零退出码（便于 CI 判断）
            sys.stderr.write(f"[lites-mcp] 自检无法运行：{exc}\n")
            raise SystemExit(2)
        return 0
    return serve_stdio(handle_request)


if __name__ == "__main__":
    main()
