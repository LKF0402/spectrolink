#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TDLAS 状态层：会话持久化 + 设备库（加载/校验/解析/建议名/溯源）。

从 tdlas_mcp.py 拆出，函数体未改动。本模块不依赖 tdlas_mcp，避免循环导入。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_SRV = _ROOT / "server-tdlas"
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tdlas_sim as ts  # noqa: E402
from spectrolink_core.jsonio import atomic_write_text as _atomic_write_text  # noqa: E402
from spectrolink_core.report_blocks import validate_device_params  # noqa: E402

from tdlas_constants import (          # noqa: E402
    PARAM_ACQ_GUIDE,
    _DEVICE_RULES,
    _DEVICE_SALIENT_KEYS,
    _DEVICE_TYPES,
    _DEVICE_TYPE_CN,
)

_SESSION_FILE = _ROOT / ".tdlas_session.json"
_DEVICE_FILE = _ROOT / ".tdlas_devices.json"


def _load_sessions():
    if _SESSION_FILE.exists():
        try:
            return json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_sessions(sessions):
    _atomic_write_text(_SESSION_FILE, json.dumps(sessions, ensure_ascii=False, indent=2))


def _get_session(session_id="default"):
    return _load_sessions().get(session_id,
                                {"confirmed": {}, "pending": [], "stage": "clarify"})


def _validate_device_entry(entry):
    """校验一组设备参数；返回错误说明（None = 通过）。规则与实现见 core。"""
    return validate_device_params(entry, _DEVICE_RULES)


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
    # ★ 不传 setup 时自动用默认 setup
    if setup is None:
        setup = dev.get("default", {}).get("setup")
    pick = {"laser": laser, "pd": pd, "daq": daq, "optics": optics}
    if setup:
        st = dev.get("setup", {}).get(str(setup))
        if st is None:
            _exist = sorted((dev.get("setup") or {}).keys())
            raise ValueError(
                f"整机配置 {setup!r} 不存在。已有配置：{_exist or '（无）'}。"
                f"如需新建，请告诉用户你需要哪几台设备的**型号或规格书**，"
                f"用 tdlas_device save 建库后再 save_setup 打包（source 必须如实填）。")
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
        if params is None and k == "laser":
            # 允许直接引用内置 demo 预设（SKILL.md §C+ 承诺可用）：只取该类型允许键，
            # source 标 ai —— 演示参数不是真实器件，避免被当成 datasheet。
            _p = (getattr(ts, "PRESET_LASERS", {}) or {}).get(str(name))
            if _p is not None:
                params = {kk: _p[kk] for kk in _DEVICE_TYPES["laser"] if _p.get(kk) is not None}
                params["source"] = "ai"
                params["source_note"] = "内置 demo 预设（非真实器件）"
        if isinstance(params, dict) and isinstance(params.get("params"), dict):
            # 兼容嵌套历史格式 {name, source, params:{...}, note}：
            # 外层只把 provenance 并入参数域，name/note 一律不进（否则被当成非数值参数）
            _outer = {kk: params[kk] for kk in ("source", "source_note", "updated", "fields")
                      if params.get(kk) is not None}
            params = {**params["params"], **_outer}
        if params is None:
            _keys = _DEVICE_SALIENT_KEYS.get(k, [])
            _need = "、".join(
                f"{(PARAM_ACQ_GUIDE.get(kk) or (kk, '-', ''))[0]}({(PARAM_ACQ_GUIDE.get(kk) or (kk, '-', ''))[1]})"
                for kk in _keys)
            _exist = sorted((dev.get(k) or {}).keys())
            raise ValueError(
                f"{_DEVICE_TYPE_CN[k]}设备 {name!r} 不存在。已有：{_exist or '（无）'}。"
                f"若要新建该设备，请向用户索取**型号或规格书**（需：{_need}），"
                f"然后用 tdlas_device save device_type={k} name=... source=datasheet|user|ai。")
        # ★ 先把 provenance 元数据与**参数字段**分开：前者是字符串（source），
        #   若混进参数域会被 _validate_device_entry 当成"非数值参数"而报错。
        _PROV_FIELDS = ("source", "source_note", "fields", "updated")
        entry = {kk: vv for kk, vv in params.items()
                 if vv is not None and kk not in _PROV_FIELDS}
        bad = _validate_device_entry(entry)          # 兜住历史/手改过的非法条目
        if bad:
            raise ValueError(f"已保存的{_DEVICE_TYPE_CN[k]}设备 {name!r} 参数非法：{bad}；"
                             f"请用 tdlas_device save 重新保存修正")
        resolved.update({k: v for k, v in entry.items()
                         if k not in ("source", "source_note", "fields", "updated")})
        # 回显来源：让 AI 能如实说出"这些参数来自哪里"
        _meta_src = {k: params.get(k) for k in ("source", "source_note", "updated")
                     if params.get(k) is not None}
        # 即使该条目没有 source（旧条目），也必须如实报出"来源未记录"——
        # 否则 AI 会默认这些硬件参数是“规格书里的”。空白不等于可信。
        resolved.setdefault("__provenance__", {})[k] = {
            "device": str(name),
            "source": _meta_src.get("source", "unspecified"),
            **({"source_note": _meta_src["source_note"]} if _meta_src.get("source_note") else {}),
            **({"updated": _meta_src["updated"]} if _meta_src.get("updated") else {}),
            **({} if _meta_src.get("source") else
               {"warning": "本条目建立于来源追踪之前，未记录 source；"
                           "建议重存以补上（如规格书则 source=datasheet）"}),
        }
    # ★ 从 setup 取出工况参数
    if setup and st.get("conditions"):
        resolved["__conditions__"] = dict(st["conditions"])
    return resolved


def _name_is_distinctive(name, device_type=None):
    """判断设备/整机名是否**足够显著**。

    规则（任一即可）：① 含型号类信息（字母+数字混合，如 NI_USB-6211、DFB-1653）；
    ② 含长度/波长类信息（如 3373nm、3.3um、1653）；③ 含中文型号词（如 实验室甲、多通池）。
    **拒绝**：纯编号（a1/dev1/test）、单字符、以及"测试/临时/新建/copy"这类通用词。
    返回 (ok, reason)。
    """
    nm = str(name or "").strip()
    if len(nm) < 3:
        return False, f"名字过短（{nm!r}），无法区分"
    low = nm.lower()
    for bad in ("test", "tmp", "temp", "测试", "临时", "新建", "copy", "副本", "demo", "abc"):
        if low == bad or low.startswith(bad + "_") or low.startswith(bad + "-"):
            return False, f"名字含通用词 {bad!r}，无法区分"
    if __import__("re").fullmatch(r"[a-z]?\d{1,3}", low):
        return False, f"名字 {nm!r} 是纯编号，无法区分"
    has_digit = any(c.isdigit() for c in nm)
    has_alpha = any(c.isalpha() for c in nm)
    has_cjk = any("一" <= c <= "鿿" for c in nm)
    if (has_digit and has_alpha) or has_cjk:
        return True, ""
    return False, (f"名字 {nm!r} 不含型号/波长等可区分信息；"
                   f"建议如 'nanoplus_3373nm_SN5712'、'NI_USB-6211'、'多通池_10m'")


def _suggest_setup_name(dev, laser=None, pd=None, daq=None, optics=None):
    """当用户没给合适名字时，**由已有设备名自动拼一个显著名**。

    这是"AI 负责命名、用户只给素材"的具体落地：用户给了四台设备，
    但不一定想得出合适的整机名——那就用设备名的**显著片段**拼出来。
    """
    parts = []
    for k, v in (("laser", laser), ("pd", pd), ("daq", daq), ("optics", optics)):
        if not v:
            continue
        nm = str(v)
        # 取最能区分的一段：优先含数字的词（型号/波长），否则取前 12 字符
        toks = [t for t in __import__("re").split(r"[_\-\s]+", nm) if t]
        pick = next((t for t in toks if any(c.isdigit() for c in t)), None)
        parts.append(pick or nm[:12])
    return "_".join(parts) if parts else ""


def _device_setup_guide(dev, laser=None, pd=None, daq=None, optics=None):
    """告诉 AI：还缺哪些设备、每台需要哪些参数、该向用户问什么。

    这是本项目"用户只上传 AI 要的东西、AI 负责构建与提问"的接口：
    不要只报"设备不存在，请先 save"（用户不知道要给什么），
    而要给出**缺什么 + 每项的中文名/单位 + 去哪里查 + 实在没有怎么办**。
    """
    missing = []
    for k, v in (("laser", laser), ("pd", pd), ("daq", daq), ("optics", optics)):
        if v and v not in (dev.get(k) or {}):
            keys = _DEVICE_SALIENT_KEYS.get(k, [])
            fields = []
            for kk in keys:
                g = PARAM_ACQ_GUIDE.get(kk)
                fields.append({"key": kk, "cn": g[0] if g else kk,
                               "unit": g[1] if g else "-", "why": g[2] if g else ""})
            missing.append({
                "device_type": k, "cn": _DEVICE_TYPE_CN[k], "name_given": str(v),
                "fields_needed": fields,
                "ask_user": (f"请提供{_DEVICE_TYPE_CN[k]} **{v}** 的型号或规格书"
                             f"（需：" + "、".join(f["cn"] + f"({f['unit']})" for f in fields) + "）"),
                "if_no_datasheet": "无规格书时：① 用型号联网检索；"
                                   "② 引导现场标定；③ 保留默认并在结论中标注。",
            })
    avail = {k: sorted((dev.get(k) or {}).keys()) for k in ("laser", "pd", "daq", "optics")}
    return {"missing": missing, "available": avail,
            "ai_instruction": "请按 missing[].ask_user 向用户索取；"
                              "拿到型号/规格书后用 tdlas_device save 建库"
                              "（**source 必须如实填**：规格书=datasheet、AI 推断=ai），"
                              "然后用 save_setup 打包成整机。用户不需要知道参数名。"}


def _device_provenance(setup=None, laser=None, pd=None, daq=None, optics=None):
    """只取设备引用的**来源元数据**（不取参数），供结果回显。

    为什么单独出一个函数：`_resolve_devices` 的返回值会被 setdefault 合并进引擎参数，
    若在里面塞一个 `__provenance__` 键，它会被当成真实参数传给引擎（已踩过这个坑）。
    """
    try:
        raw = _resolve_devices(setup, laser, pd, daq, optics)
        prov = raw.pop("__provenance__", None)
        return prov
    except (KeyError, TypeError, ValueError, OSError):   # 设备库缺项/损坏：来源未知≠崩溃
        return None
