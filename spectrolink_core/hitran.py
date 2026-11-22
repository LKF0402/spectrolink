#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HITRAN 线表取数与吸收谱计算 —— SpectroLink 共用内核（core），供 TDLAS/LITES 等全部技术服务器复用。
HAPI 1.x 精简封装（自包含，不依赖外部仓库）。

只用 HAPI 1.x（`hapi.py`，pip 包名 `hitran-api`）的官方接口：
    hapi.db_begin / hapi.fetch / hapi.absorptionCoefficient_Voigt / hapi.ISO / hapi.moleculeName
**不需要 API key** —— HAPI 1.x 走旧下载接口、不校验 key。
有意**不使用 HAPI2**（其官方 v2 API 需 key，配置麻烦），故本模块完全免 key。

设计纪律（沿用 hitran-mcp 的审计结论）：
  · 窗口安全：线表必须真正覆盖请求窗口**及其翼宽**（窗外 ±fetch_margin 的线其翼
    仍会落进计算窗，只抓窗内线会静默偏低，实测窗左缘 −2.74%），否则按窗口重抓；
  · 空谱显式报错：窗口内 0 条线 / 抓取失败直接 raise，绝不静默返回平谱；
  · 单位：波数 cm^-1、温度 K、压力 atm、线翼半宽 cm^-1。
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import threading
import time
import warnings
from pathlib import Path

import numpy as np

# 缓存目录优先级：环境变量 SPECTROLINK_DATA_DIR（可用 os.pathsep 给多个）>
# 用户目录 ~/.spectrolink/Hitran_Data > 仓库内 Hitran_Data。
# 为什么不是单值：用户可能已有两份缓存（例如 HOME 里是旧窗口、仓库里是新窗口）。
# 只认第一个目录会让“本地明明有表”的窗口去联网重抓，甚至撞上 HITRAN 每日配额。
_DEFAULT_DATA_DIR = Path.home() / ".spectrolink" / "Hitran_Data"
_REPO_DATA_DIR = Path(__file__).resolve().parent.parent / "Hitran_Data"


def _initial_data_dirs():
    env = os.environ.get("SPECTROLINK_DATA_DIR", "")
    dirs = []
    for part in env.split(os.pathsep):
        if part.strip():
            dirs.append(Path(part).expanduser())
    for d in (_DEFAULT_DATA_DIR, _REPO_DATA_DIR):
        if d not in dirs:
            dirs.append(d)
    return dirs


_DATA_DIRS = _initial_data_dirs()
_DATA_DIR = _DATA_DIRS[0]
_DB_READY = False
_SPECIES = None


def _hapi():
    """导入 HAPI 1.x（pip 包名 `hitran-api`，import 名才是 `hapi`）。

    缺依赖时给出可操作的提示，而不是裸 ModuleNotFoundError ——
    常见误用是用别的解释器跑（如 windows 商店占位符 python），报错现场离根因很远。
    """
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            import hapi
    except ImportError as exc:          # 依赖缺失：直接说清装什么、用哪个解释器
        import sys
        raise ImportError(
            "缺少依赖 hitran-api（提供 import hapi）→ 无法从 HITRAN 取线表。"
            f"请先安装：pip install -r requirements.txt（当前解释器：{sys.executable}）"
        ) from exc
    return hapi


def _db_begin_quiet(directory):
    """调用 HAPI db_begin，并吞掉它打印到 stdout 的目录/表清单。

    为什么必须吞：MCP 走 stdio JSON-RPC，stdout 只能是协议行。HAPI 的
    `db_begin` 会 print("Using ...") 并逐表打印，若在 tools/call 期间触发，
    会把整条协议流污染成“非 JSON 行”。
    """
    with contextlib.redirect_stdout(io.StringIO()):
        _hapi().db_begin(str(directory))


def _ensure_db():
    """初始化 HAPI 线表缓存目录（进程内一次）。

    HAPI 1.x 的 `db_begin` 只激活一个 DATABASE_DIR；因此这里选第一个**可写**目录作为
    写入主目录，其余目录仅作为只读缓存来源（见 `_sync_table` 的按需复制）。
    """
    global _DB_READY, _DATA_DIR
    if not _DB_READY:
        _DATA_DIR = Path(_DATA_DIR)  # 兼容字符串传入
        # 尝试建目录，失败就 fallback 到仓库内（兼容旧安装）
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            # 用户目录不可写 → 用仓库内 Hitran_Data
            _DATA_DIR = _REPO_DATA_DIR
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
        if _DATA_DIR not in _DATA_DIRS:
            _DATA_DIRS.insert(0, _DATA_DIR)
        _db_begin_quiet(_DATA_DIR)
        _DB_READY = True


def _table_file(table, directory):
    """某目录下的线表数据文件（HAPI 以 `<table>.data` 落盘）。"""
    return Path(directory) / f"{table}.data"


def _copy_table_to_primary(table):
    """把其它缓存目录中的 `<table>.data` / `.header` 补进 HAPI 当前目录。

    返回 True/False 表示是否有复制；复制失败返回 None。`.data` 与 `.header` 必须
    分别检查：旧缓存可能只有 `.data` 没有 `.header`，而 HAPI 1.x 的 `tableList()`
    依赖 `.header` 建立的索引；只看到 `.data` 就返回会让表永远不可见。
    """
    target = _table_file(table, _DATA_DIR)
    target_hdr = target.parent / f"{table}.header"
    copied = False
    for d in _DATA_DIRS:
        if Path(d) == Path(_DATA_DIR):
            continue
        src = _table_file(table, d)
        if not target.exists() and src.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                copied = True
            except OSError:
                return None
        hdr = Path(d) / f"{table}.header"
        if hdr.exists() and not target_hdr.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(hdr, target_hdr)
                copied = True
            except OSError:
                return None
    return copied


def _sync_table(table):
    """单表同步：复制缺失文件，必要时重建 HAPI 索引。"""
    target = _table_file(table, _DATA_DIR)
    changed = _copy_table_to_primary(table)
    if changed is None:
        return None
    if changed:
        # HAPI 1.x 的 getTableList() 读的是 db_begin 时建立的 LOCAL_TABLE_CACHE；
        # 复制后必须重新 db_begin，否则新表不会进入索引。
        try:
            _db_begin_quiet(_DATA_DIR)
        except (AttributeError, OSError, ValueError, TypeError):
            pass
    return target


def _sync_tables(tables):
    """批量同步多张表，只在最后重建一次 HAPI 索引。

    `_loaded_covering` / `_cached_windows` 会遍历多个候选表；若逐表 `_sync_table`，
    每次复制都触发一次 `db_begin`（本机实测约 1.4 s），20 张表就是 20 多次全量扫描，
    出图会从秒级退化到几十秒。这里把复制与重建索引拆开，索引只建一次。
    """
    changed = False
    for table in tables:
        changed = (_copy_table_to_primary(table) is True) or changed
    if changed:
        try:
            _db_begin_quiet(_DATA_DIR)
        except (AttributeError, OSError, ValueError, TypeError):
            pass


def _table_names():
    """所有缓存目录里的线表名（跨目录，避免只看 HAPI 当前目录）。"""
    names = set()
    for d in _DATA_DIRS:
        try:
            names.update(p.stem for p in Path(d).glob("*.data"))
        except OSError:
            continue
    return names



def _species_index():
    """官方物种索引：分子式 → {M, main_iso, isotopologues}（来自 hapi.ISO，不硬编码）。"""
    global _SPECIES
    if _SPECIES is None:
        idx = {}
        for (M, I), rec in _hapi().ISO.items():
            formula = str(rec[4]).upper()
            e = idx.setdefault(formula, {"M": M, "isotopologues": []})
            e["isotopologues"].append({"I": I, "abundance": float(rec[2]), "name": rec[1]})
        for e in idx.values():
            e["isotopologues"].sort(key=lambda d: -d["abundance"])
            e["main_iso"] = e["isotopologues"][0]["I"]
        _SPECIES = idx
    return _SPECIES


def species(with_isotopologues=False):
    """物种速查：分子式 → M / 主同位素（可选含全部同位素与丰度）。"""
    idx = _species_index()
    if with_isotopologues:
        return idx
    return {f: {"M": e["M"], "main_iso": e["main_iso"]} for f, e in idx.items()}


def resolve(name):
    """分子式 / HITRAN 分子号 → (formula, M)。"""
    idx = _species_index()
    s = str(name).strip().upper()
    if s.isdigit():
        M = int(s)
        return str(_hapi().moleculeName(M)).upper(), M
    if s in idx:
        return s, idx[s]["M"]
    for f in idx:                                   # 容错：忽略括号差异
        if f.replace("(", "").replace(")", "") == s.replace("(", "").replace(")", ""):
            return f, idx[f]["M"]
    raise ValueError(f"[spectrolink] 未知物种 '{name}'（HITRAN 官方表无此分子）")


def _wnum(v):
    """窗口数字 → 表名片段：2172.5 -> 2172p5。"""
    return f"{float(v):g}".replace(".", "p").replace("-", "m")


_FETCH_TRIES = 3
_FETCH_BACKOFF = 1.0            # 秒；重试间隔 1s → 2s（指数退避）

# ── 抓取窗的外扩量 ──────────────────────────────────────────────────
# 为什么必须外扩：HAPI 的 `WavenumberWingHW` 以 **HWHM 倍数** 为单位
# （hapi.py:53709 `OmegaWingF = max(OmegaWing, OmegaWingHW*GammaMax)`），
# 且选线循环（hapi.py:53672）遍历**表内每一条线**、不按输出窗口过滤 ——
# 因此"窗外线"只要在表里，其翼仍经 ν0±ΩWingF 落进计算窗；只抓窗内线，
# 这部分贡献被**静默丢弃**（不报错、不提示）。
# 实测（CH4, 2967.6–2969.2 cm-1, wingHW=20, 296 K/1 atm）：
#   dW=0.0 → 窗左缘 −2.74%、窗右缘 −0.42%、全网格最大 −2.74%、均值 −0.12%
#   dW=1.0 → 全网格最大 −0.01%      （耗时 0.030→0.051 s）
#   dW=1.6 → 全网格最大 −0.00%      （耗时 0.069 s）
#   dW=20  → 参照                   （耗时 0.408 s，8 倍于 dW=1.6 却无进一步收益）
# 故外扩量按物理翼宽 ΩWingHW·Γ 定，扫到饱和点即止；Γ ∝ P（洛伦兹展宽）。
_GAMMA_REF_CM = 0.08            # 1 atm 空气浴下洛伦兹 HWHM 的保守上限（cm-1）
_FETCH_DW_MIN_CM = 1.5          # 下限：保证默认 wingHW=20 时到达实测饱和点


def fetch_margin(wingHW=20.0, P=1.01325):
    """抓取线表相对**计算窗**的单边外扩量（cm-1）。

    覆盖 ΩWingHW·GammaMax 的实际翼宽：Γ ∝ P，故含 P 因子；另设下限 1.5 cm-1，
    保证默认 wingHW=20 时落在实测饱和点（dW≥1.0 已把窗缘偏差压到 0.01% 以内）。
    """
    return max(_FETCH_DW_MIN_CM,
               _GAMMA_REF_CM * float(wingHW) * max(1.0, float(P)))



def _is_transient(e):
    """判断抓取失败是否属"网络/服务端暂时故障"（可重试）而非"该窗口无数据"（重试无用）。

    HITRAN 旧接口偶发 502/超时很常见（首次运行与 CI 必踩），此前一次失败就抛错并
    把四种可能原因并列，用户会误读成"该窗口无 HITRAN 收录"。
    """
    import urllib.error
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError, OSError)):
        return True
    code = getattr(e, "code", None)
    if isinstance(code, int) and code >= 500:
        return True
    msg = str(e).lower()
    # HAPI 把 HTTP 故障统一包成 "Failed to retrieve data for given parameters."，
    # 单看这句话无法区分"服务端 502"与"该窗口无数据"，故另配 _isotope_known() 判别。
    return any(w in msg for w in ("timed out", "timeout", "connection", "temporarily",
                                  "bad gateway", "502", "503", "504", "reset",
                                  "failed to retrieve"))


def _isotope_known(M, I):
    """该分子/同位素是否在 HITRAN 收录范围内（用 HAPI 自带索引，离线判断）。

    用途：把"下载失败"与"该同位素根本不存在"分开。HAPI 的 fetch 把两者都抛成同一句话，
    直接并列成"常见原因：无收录/无网络"会让一次 502 被读成"这个波段 HITRAN 没收"。
    返回 True/False，索引不可用时返回 None。
    """
    try:
        h = _hapi()
        # ⚠ HAPI 的 ISO 以 **(M, I) 元组** 为键（不是嵌套字典）：ISO[(6, 1)] = [id, 'CH4', 丰度, 质量, 'CH4']
        return (int(M), int(I)) in h.ISO
    except (AttributeError, KeyError, TypeError, ValueError, OSError):   # 索引不可用 → None
        return None


def _coverage(table, sync=True):
    """已加载表的覆盖区间 (nu_min, nu_max, n_lines)；未加载返回 None。

    sync=False 用于批量同步后只读索引，避免逐表触发 `db_begin`。
    """
    h = _hapi()
    if sync:
        _sync_table(table)                 # 其它缓存目录有表 → 先同步到 HAPI 当前目录
    try:
        if table not in h.tableList():
            return None
        nu = np.asarray(h.getColumn(table, "nu"), dtype=float)
        return (float(nu.min()), float(nu.max()), int(nu.size)) if nu.size else None
    except (AttributeError, KeyError, TypeError, ValueError, IndexError, OSError):   # 表不可读 → None
        return None


def _cached_windows(formula, M, I, limit=8):
    """本地缓存中该分子/同位素的可用覆盖窗口（按下限排序，最多 limit 段）。

    用途：联网失败时告诉调用方“本地还有什么能用”，避免 AI 盲试窗口。
    """
    prefix = f"{formula}_{M}_{I}_"
    candidates = [t for t in _table_names()
                  if t == f"{formula}_{M}_{I}" or t.startswith(prefix)]
    _sync_tables(candidates)
    wins = []
    for t in candidates:
        cov = _coverage(t, sync=False)
        if cov:
            wins.append((cov[0], cov[1]))
    wins.sort()
    merged = []
    for lo, hi in wins:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged[:limit]


def _fmt_windows(wins):
    return ", ".join(f"{lo:.4g}–{hi:.4g}" for lo, hi in wins)


def _loaded_covering(base, numin, numax):
    """已加载的同分子/同位素表中，覆盖 [numin, numax] 的**最小**一张；无则 None。

    为什么需要：抓取窗带 ±dW 外扩后，计算窗略有变化就会生成一个几乎相同的表名
    （如 CH4_6_1_2965p979_2970p821 与 CH4_6_1_2966_2971），若不复用，用户已有的
    缓存会全部失效、每换一次窗口就重下一整张表。取行数最少的一张以省计算时间。
    """
    h = _hapi()
    try:
        names = _table_names() or set(h.tableList())
    except (AttributeError, OSError, ValueError, TypeError):   # 本地索引还没建起来 → 无表可复用
        names = _table_names()
    candidates = [t for t in sorted(names)
                  if t == base or t.startswith(base + "_")]   # 只认同分子/同位素，避免跨物种误用
    _sync_tables(candidates)                                   # 批量复制，只重建一次索引
    best = None
    for t in candidates:
        cov = _coverage(t, sync=False)
        if not cov or cov[0] > numin or cov[1] < numax:
            continue
        if best is None or cov[2] < best[1][2]:
            best = (t, cov)
    return best


def fetch_table(formula, M, I, numin, numax, force=False):
    """保证拿到真正覆盖 [numin, numax] 的线表；返回 (table, coverage)。

    坑：hapi.fetch 见同名表已存在就跳过下载，于是请求新窗口时仍用旧线表
    → 谱线静默缺失。策略：先查覆盖，未覆盖则用带窗口后缀的表名重抓。
    """
    _ensure_db()
    numin, numax = float(numin), float(numax)
    base = f"{formula}_{M}_{I}"
    wtable = f"{base}_{_wnum(numin)}_{_wnum(numax)}"
    if not force:
        cov = _coverage(wtable)                  # 同窗口缓存优先零下载复用
        if cov is not None:
            return wtable, cov
        cov = _coverage(base)
        if cov and cov[0] <= numin and cov[1] >= numax:
            return base, cov
        best = _loaded_covering(base, numin, numax)   # 复用已加载的更宽表，免重复下载
        if best is not None:
            return best
    last = None
    for attempt in range(_FETCH_TRIES):
        try:
            _hapi().fetch(wtable, M, I, numin, numax)
            last = None
            break
        except Exception as e:
            last = e
            if not _is_transient(e):
                break
            if attempt < _FETCH_TRIES - 1:
                time.sleep(_FETCH_BACKOFF * (2 ** attempt))
    if last is not None:
        # ★ 归因必须分开：网络/服务端故障 ≠ "该窗口没有谱线"。
        #   此前把四种原因并列成一段话，一次 502 会被读成"HITRAN 没收录这条线"，
        #   用户据此换波段甚至得出"该气体无吸收"——这正是本模块开头纪律要避免的静默错误。
        known = _isotope_known(M, I)
        cached = _cached_windows(formula, M, I)
        cache_hint = (f" 本地已缓存可用窗口：{_fmt_windows(cached)}。" if cached
                      else " 本地暂无该分子/同位素的缓存窗口。")
        # 优先用**离线索引**下判断（比关键字更可靠）：同位素确实收录 ⇒ 失败必是服务端/网络问题。
        if known is False:
            raise RuntimeError(
                f"[spectrolink] 抓取 {formula}(M={M}, I={I}) 于 {numin}-{numax} cm-1 失败：{last}。"
                f"该分子/同位素不在 HITRAN 收录范围（已用离线索引核对），请核对物种与同位素编号。"
            ) from last
        if known is True or _is_transient(last):
            raise RuntimeError(
                f"[spectrolink] HITRAN 服务暂时不可用（{type(last).__name__}: {last}），"
                f"已自动重试 {_FETCH_TRIES} 次仍失败。"
                + (f"{formula}(M={M}, I={I}) 是 HITRAN 收录的同位素，"
                   f"失败属网络/服务端故障。" if known else "")
                + cache_hint
                + " **这不代表该窗口无谱线** —— 请稍后重试，或改用上述本地已缓存窗口；"
                  "不要据此判定该气体无吸收。"
            ) from last
        raise RuntimeError(
            f"[spectrolink] 抓取 {formula}(M={M}, I={I}) 于 {numin}-{numax} cm-1 失败：{last}。"
            f"该分子号/同位素不在 HITRAN 收录范围（已用离线索引核对），请核对物种与同位素编号。"
        ) from last
    cov = _coverage(wtable)
    if cov is None:
        raise RuntimeError(f"[spectrolink] 抓取失败：{formula} 在 {numin}-{numax} cm-1 无线表")
    if cov[2] == 0:
        raise RuntimeError(
            f"[spectrolink] 表 {wtable} 在 {numin}-{numax} cm-1 返回 0 条谱线。"
            f"该分子/同位素在此窗口无 HITRAN 收录，严禁当作'无吸收 / 平谱'使用")
    return wtable, cov


def _absorption_uncached(name, numin, numax, T=296.0, P=1.01325, step=5e-4, wingHW=20.0,
                         iso=None, hitran_units=False):
    """纯组分吸收系数 α(ν) —— **无缓存**实现（见下方 absorption 的缓存包装）。

    iso 取值：
      · None   → 主同位素（默认，与历史行为一致）
      · int    → 指定同位素编号 I（如 1=¹²CH₄、2=¹³CH₄）
      · "all"  → 该分子全部 HITRAN 收录同位素按丰度叠加
                 （贴近实测峰形：密集谱区邻近同位素线贡献不可忽略；
                  稀有同位素在窗口内 0 条线时自动跳过，不报错）
    """
    _ensure_db()
    h = _hapi()
    formula, M = resolve(name)
    # 抓取窗 = 计算窗 ± fetch_margin。只扩**线表**，输出网格仍是 (numin, numax)。
    _dW = fetch_margin(wingHW, P)
    gmin, gmax = float(numin) - _dW, float(numax) + _dW
    if iso == "all":
        _idx = _species_index()[formula]
        iso_list = _idx["isotopologues"]                       # 按丰度降序
        main_iso = _idx["main_iso"]
        tables, comps, skipped = [], [], []
        for e in iso_list:
            try:
                tbl, _cov = fetch_table(formula, M, e["I"], gmin, gmax)
            except RuntimeError as ex:
                # all 模式下：主同位素失败 = 真故障（网络/服务端），必须显式报错；
                # 非主（稀有）同位素某窗口无谱线属正常（HITRAN 对空窗口返回 404），
                # 一律跳过并披露，不当作故障、不中断整谱叠加。
                if e["I"] == main_iso:
                    raise
                skipped.append({"iso": e["I"], "name": e.get("name"),
                                "error": str(ex)[:120]})
                continue
            tables.append(tbl)
            comps.append((M, e["I"], e["abundance"]))
        if not tables:
            raise RuntimeError(
                f"[spectrolink] {formula} 全部同位素在 {numin}-{numax} cm-1 均无 HITRAN 谱线")
        nu, coef = h.absorptionCoefficient_Voigt(
            Components=comps,
            SourceTables=tables,
            WavenumberRange=(float(numin), float(numax)),
            WavenumberStep=float(step),
            WavenumberWingHW=float(wingHW),
            HITRAN_units=bool(hitran_units),
            Environment={"T": float(T), "p": float(P), "Diluent": {"air": 1.0}})
        n_lines_table = 0
        n_in = 0
        for tbl in tables:
            _all = np.asarray(h.getColumn(tbl, "nu"), dtype=float)
            n_lines_table += int(_all.size)
            n_in += int(((_all >= numin) & (_all <= numax)).sum())
        info = {"molecule": formula, "M": M, "iso": "all",
                "isotopologues": [{"I": e["I"], "abundance": e["abundance"],
                                   "name": e["name"]} for e in iso_list],
                "n_iso": len(comps), "iso_skipped": skipped,
                "tables": tables,
                "coverage_cm-1": [round(float(numin), 3), round(float(numax), 3)],
                # 抓取窗（线表实际请求范围）与计算窗区别：前者含窗外翼线，后者是输出网格。
                "fetch_window_cm-1": [round(gmin, 3), round(gmax, 3)],
                "n_lines_table": n_lines_table, "n_lines_in_window": n_in,
                "alpha_context": {"T_K": float(T), "P_atm": float(P),
                                  "window_cm-1": [float(numin), float(numax)],
                                  "step_cm-1": float(step), "wingHW_cm-1": float(wingHW),
                                  "diluent": "air"}}
        return np.asarray(nu, dtype=float), np.asarray(coef, dtype=float), info
    I = _species_index()[formula]["main_iso"] if iso is None else int(iso)
    table, cov = fetch_table(formula, M, I, gmin, gmax)
    nu, coef = h.absorptionCoefficient_Voigt(
        Components=[(M, I, 1.0)],
        SourceTables=[table],
        WavenumberRange=(float(numin), float(numax)),
        WavenumberStep=float(step),
        WavenumberWingHW=float(wingHW),
        HITRAN_units=bool(hitran_units),
        Environment={"T": float(T), "p": float(P), "Diluent": {"air": 1.0}})
    nu_all = np.asarray(h.getColumn(table, "nu"), dtype=float)
    n_in = int(((nu_all >= numin) & (nu_all <= numax)).sum())
    info = {"molecule": formula, "M": M, "iso": I, "table": table,
            "coverage_cm-1": [round(cov[0], 3), round(cov[1], 3)],
            # 抓取窗（线表实际请求范围）与计算窗区别：前者含窗外翼线，后者是输出网格。
            "fetch_window_cm-1": [round(gmin, 3), round(gmax, 3)],
            "n_lines_table": cov[2], "n_lines_in_window": n_in,
            # α(ν) 的计算语境：α 峰值随 T/P/网格步长/翼截断/窗口 变化，
            # 报告 α 峰值时须能同时给出这五项，否则数值不可复现、不可比较。
            "alpha_context": {"T_K": float(T), "P_atm": float(P),
                              "window_cm-1": [float(numin), float(numax)],
                              "step_cm-1": float(step), "wingHW_cm-1": float(wingHW),
                              "diluent": "air"}}
    return np.asarray(nu, dtype=float), np.asarray(coef, dtype=float), info


# ── 吸收谱的进程内缓存 ────────────────────────────────────────────────
# 为什么需要：蒙特卡洛类调用（measurement_uncertainty / detection_limit）会对
# **完全相同**的 (species, 窗口, T, P, step, wingHW) 反复调用本函数，而每次
# Voigt 计算实测约 0.6–0.9 s，成为重复仿真的主要开销。
# 缓存键包含全部影响 α 的参数；命中时返回**副本**（数组与 info 都是），
# 防止调用方就地修改污染缓存。α(ν) 是参数的纯函数，故缓存不改变任何数值结果。
#
# ⚠ 并发：同一进程的多线程/多客户端会同时碰这个字典。
#   dict.get 本身是原子的，但"取最老键 + 淘汰 + 写入"不是 —— 两个线程同时走到淘汰
#   会拿到同一个键（KeyError），或让迭代器看到 size 变化（RuntimeError）。
#   故只在**改字典**时加锁（锁内微不足道，真正的 0.6 s 计算在锁外）。
_ALPHA_CACHE = {}
_ALPHA_CACHE_MAX = 64
_ALPHA_CACHE_LOCK = threading.Lock()


#: 线表指纹缓存（表名 → sha256 前缀 + 行数）：每张表只读一次。
_TABLE_FP = {}


def table_fingerprint(table):
    """线表指纹：{表名, sha256(前16), 行数, data 文件名}。

    为什么需要：HITRAN 会定期更新线表，**同名表的内容会变**。
    没有指纹时，论文里的一个数无法被第三方重建（不知道用的是哪一版数据）。
    指纹让"这个数是什么算出来的"可被独立核对。
    """
    key = str(table)
    hit = _TABLE_FP.get(key)
    if hit is not None:
        return dict(hit)
    import hashlib
    from pathlib import Path as _P
    fp = {"table": key, "sha256_16": None, "n_lines": None}
    # HAPI 把表存为 <dir>/<table>.data；对内容取前 16 位指纹
    try:
        cand = list(_DATA_DIR.glob(f"{key}*.data"))
        if cand:
            f = cand[0]
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            fp["sha256_16"] = h.hexdigest()[:16]
            fp["data_file"] = _P(f).name
            fp["n_lines"] = sum(1 for _ in open(f, "rb")) - 1 if f.stat().st_size else 0
    except (OSError, ValueError, TypeError):            # 取指纹失败 → 退回仅表名
        pass
    _TABLE_FP[key] = dict(fp)
    return fp


def alpha_cache_clear():
    """清空吸收谱缓存（改过线表/换物种批次后建议调用）。"""
    with _ALPHA_CACHE_LOCK:
        _ALPHA_CACHE.clear()


def alpha_cache_info():
    with _ALPHA_CACHE_LOCK:
        return {"entries": len(_ALPHA_CACHE), "max": _ALPHA_CACHE_MAX}


def absorption(name, numin, numax, T=296.0, P=1.01325, step=5e-4, wingHW=20.0,
               iso=None, hitran_units=False):
    """纯组分吸收系数 α(ν)（带进程内缓存）。

    返回 (nu, alpha, info)：
      · hitran_units=False → α [cm^-1]（该组分纯气、总压 P、空气浴）
      · hitran_units=True  → σ [cm^2/molecule]
    混合气请自行按 α_i = x_i · α_pure_i 叠加（本函数不代劳，避免口径混淆）。
    """
    key = (str(name).strip().upper(), float(numin), float(numax), float(T), float(P),
           float(step), float(wingHW), iso, bool(hitran_units))
    hit = _ALPHA_CACHE.get(key)
    if hit is not None:
        # info 也必须给副本：它是可变 dict，共享出去迟早被某个调用方加键污染
        return hit[0].copy(), hit[1].copy(), dict(hit[2])
    val = _absorption_uncached(name, numin, numax, T=T, P=P, step=step, wingHW=wingHW,
                               iso=iso, hitran_units=hitran_units)
    with _ALPHA_CACHE_LOCK:
        if len(_ALPHA_CACHE) >= _ALPHA_CACHE_MAX:
            _ALPHA_CACHE.pop(next(iter(_ALPHA_CACHE)), None)   # FIFO 淘汰，避免无界增长
        _ALPHA_CACHE[key] = val
    return val[0].copy(), val[1].copy(), dict(val[2])


def absorption_mixture(gases, numin, numax, T=296.0, P=1.01325, step=5e-4, wingHW=20.0,
                         wn_grid=None):
    """混合气吸收系数 α_total(ν) = Σ x_i · α_pure_i(ν)。

    参数:
        gases: list of (name, mole_fraction)，如 [("CO", 6e-6), ("H2O", 0.015)]
        wn_grid: 可选，统一波数网格。不传则自动取第一个气体的网格。

    返回: (nu, alpha_total, alpha_per_species)
        nu: 统一波数网格
        alpha_total: 总吸收系数 cm^-1
        alpha_per_species: dict {name: alpha_i}，每个都已插值到统一网格
    """
    if wn_grid is None:
        # 第一个气体决定网格
        first_name, first_x = gases[0]
        nu0, alpha0, _ = absorption(first_name, numin, numax, T=T, P=P, step=step, wingHW=wingHW)
        wn_grid = nu0.copy()
        alpha_total = first_x * alpha0
        alpha_per = {first_name: alpha0.copy()}
    else:
        wn_grid = np.asarray(wn_grid, dtype=float)
        alpha_total = np.zeros_like(wn_grid)
        alpha_per = {}

    for name, x in gases[1 if wn_grid is None else 0:]:
        nu_i, alpha_i, _ = absorption(name, numin, numax, T=T, P=P, step=step, wingHW=wingHW)
        # 插值到统一网格
        alpha_interp = np.interp(wn_grid, nu_i, alpha_i)
        alpha_per[name] = alpha_interp
        alpha_total += x * alpha_interp

    # 边界披露：α_pure 一律按 air 浴计算（Diluent={"air":1.0}），
    # 高浓度组分（≥1%）的同种分子碰撞展宽（self-broadening）未计入 ——
    # 对呼气/烟道等痕量场景（x≲1%）可忽略，对纯气标定不可忽略。
    for name, x in gases:
        if float(x) >= 0.01:
            warnings.warn(
                f"[spectrolink] {name} 摩尔分数 {float(x):.1%} ≥ 1%：该组分按 air 浴"
                f"展宽系数计算，未计 self-broadening 与同组分碰撞展宽，峰高/峰宽可能偏差。"
                f"适用边界为痕量场景 x≲1%；高浓度定量请用配气标定或显式提供 Diluent 比。",
                stacklevel=2)

    return wn_grid, alpha_total, alpha_per
