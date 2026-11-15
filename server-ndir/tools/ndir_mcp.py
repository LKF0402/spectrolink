#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NDIR 仪器级仿真 MCP 服务器（stdio JSON-RPC 2024-11-05）。

工具面：
  · t_ndir_forward     单浓度正演（两通道信号/比值/理论反演）
  · t_ndir_calibrate   浓度扫描标定曲线（lnR 线性拟合 + R²）
  · t_ndir_invert      比值 → 浓度解析反演
  · t_ndir_selftest    数值锚点自检

纪律：纯标准库 stdio JSON-RPC；print 只走协议 stdout；
参数默认值均为 ai 演示占位，真实器件参数须用户交互提供。

自测：python tools/ndir_mcp.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SRV = Path(__file__).resolve().parent.parent          # server-ndir
_ROOT = _SRV.parent
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ndir_physics as nph  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "ndir", "version": "1.0.0"}}

_HOME = str(Path.home())
_WS_ROOT = str(_ROOT.parent)

from spectrolink_core.mcp_runtime import (                     # noqa: E402
    make_handle_request, schema_index, serve_stdio)
from spectrolink_core.sanitize import make_path_sanitizer      # noqa: E402
from spectrolink_core.interaction import ev_ok                  # noqa: E402
from spectrolink_core.interaction_server import install_interaction  # noqa: E402
from spectrolink_core.validation import check, validation_block  # noqa: E402

_sanitize_paths = make_path_sanitizer(_WS_ROOT, _HOME)


# ── 工具实现 ──────────────────────────────────────────────

def t_ndir_forward(x=5e-6, L_s_cm=10.0, L_r_cm=10.0, k_s=0.05, k_r=0.001,
                   i0_s=1.0, i0_r=1.0, noise_frac=0.0, seed=0):
    """单浓度 NDIR 正演。x 为摩尔分数（1e-6=1ppm）。

    ⚠️ k_s/k_r/L 默认是 ai 演示占位（CO₂ 4.26 μm 量级），真实值须用户提供。
    """
    out = nph.forward(x, L_s_cm, L_r_cm, k_s, k_r, i0_s, i0_r, noise_frac, seed)
    x_ok = isinstance(out.get("x_inferred"), (int, float)) and 0 <= out["x_inferred"] <= 1
    checks = [
        check("concentration_in_range", "pass" if x_ok else "fail",
              "反演摩尔分数须落在 [0, 1]" if x_ok else "反演摩尔分数越界（<0 或 >1）"),
        check("net_absorption_positive",
              "pass" if out.get("A_net", 0) > 0 else "fail",
              "A_net = k_s·L_s − k_r·L_r 须为正，否则信号/参考通道对比度方向错误",
              out.get("A_net")),
        check("concentration_error", "pass" if abs(out.get("x_error_frac", 0)) < 0.05 else "warn",
              "无噪声正演反演误差应 <5%", out.get("x_error_frac")),
    ]
    out["validation"] = validation_block(
        checks, note="默认参数为演示占位，未标定前不可作定量结论")
    return out


def t_ndir_calibrate(x_min=0.0, x_max=0.01, n=11, L_s_cm=10.0, L_r_cm=10.0,
                     k_s=0.05, k_r=0.001, i0_s=1.0, i0_r=1.0,
                     noise_frac=0.0, seed=0):
    """浓度扫描标定：x_min..x_max 等距 n 点 → R(x) 表 + lnR 线性拟合。"""
    xs = [x_min + (x_max - x_min) * i / (n - 1) for i in range(n)]
    out = nph.calibrate(xs, L_s_cm, L_r_cm, k_s, k_r, i0_s, i0_r, noise_frac, seed)
    fit = out.get("fit") or {}
    a_match = out.get("A_match")
    r0_fit = fit.get("R0_fit")
    r2 = fit.get("r2")
    checks = [
        check("fit_r2", "pass" if isinstance(r2, (int, float)) and r2 >= 0.99 else "warn",
              "lnR 线性拟合 R² 应 ≥0.99", r2),
        check("A_match",
              "pass" if isinstance(a_match, (int, float)) and abs(a_match - 1) <= 0.05 else "warn",
              "拟合 A 与理论 A 的相对偏差应 ≤5%", a_match),
        check("R0_fit",
              "pass" if isinstance(r0_fit, (int, float)) and abs(r0_fit - 1) <= 1e-6 else "warn",
              "无噪声时拟合 R0 应≈1（验证截距/符号）", r0_fit),
    ]
    out["validation"] = validation_block(
        checks, note="k_s/k_r/L 为演示占位；标定拟合质量不代表真实器件精度")
    return out


def t_ndir_invert(R=0.5, R0=1.0, A=0.499):
    """比值 → 浓度：x = −ln(R/R0)/A。A = k_s·L_s − k_r·L_r。"""
    x = nph.invert(R, R0, A)
    checks = [
        check("inputs_positive", "pass" if R > 0 and R0 > 0 and A > 0 else "fail",
              "R、R0 须 >0，A 须 >0（信号通道吸收应强于参考通道）"),
        check("ratio_physical", "pass" if 0 < R / R0 <= 1 else "fail",
              "R/R0 须落在 (0, 1]，否则无正浓度解"),
        check("concentration_in_range",
              "pass" if isinstance(x, float) and 0 <= x <= 1 else "fail",
              "反演摩尔分数须落在 [0, 1]；越界说明 A 或 R0 标定不同源", x),
    ]
    return {"x": x, "x_ppm": x * 1e6 if isinstance(x, float) and x == x else None,
            "formula": "x = -ln(R/R0) / (k_s*L_s - k_r*L_r)",
            "validation": validation_block(checks)}


def t_ndir_selftest():
    """数值锚点自检（离线，不依赖网络）。"""
    return nph.selftest()


def _actions(out, tool):
    acts = []

    def add(aid, severity, text, evidence):
        if all(ev_ok(out, p) for p in evidence):
            acts.append({"id": aid, "severity": severity, "action": text,
                         "evidence_fields": evidence})

    note = (out.get("validation") or {}).get("note")
    if note:
        add("disclose_validation_note", "must_disclose",
            f"校验提示：{note}", ["validation.note"])

    x = out.get("x_inferred", out.get("x"))
    if isinstance(x, (int, float)) and not 0 <= x <= 1:
        add("concentration_unusable", _SEV_BLOCK,
            f"反演浓度 x={x:.6g} 不在 [0, 1]；检查 R/R0 与 A 是否同源、A 是否为正",
            ["x_inferred"] if "x_inferred" in out else ["x"])

    a_net = out.get("A_net")
    if isinstance(a_net, (int, float)) and a_net <= 0:
        add("net_absorption_unusable", _SEV_BLOCK,
            "A_net≤0：信号与参考通道对比度方向错误，比值法无正浓度解", ["A_net"])

    err = out.get("x_error_frac")
    if isinstance(err, (int, float)) and abs(err) >= 0.05:
        add("disclose_concentration_error", "must_disclose",
            f"反演相对误差 {abs(err):.1%} ≥ 5%，不得当作精确标定结果",
            ["x_error_frac"])

    fit = out.get("fit") or {}
    if isinstance(fit.get("r2"), (int, float)) and fit["r2"] < 0.99:
        add("disclose_calibration_fit", "must_disclose",
            f"标定拟合 R²={fit['r2']:.3g} < 0.99；线性标定不可直接用于定量",
            ["fit.r2"])
    if isinstance(out.get("max_abs_err_frac"), (int, float)) and out["max_abs_err_frac"] > 0.05:
        add("disclose_calibration_error", "must_disclose",
            f"标定最大相对误差 {out['max_abs_err_frac']:.1%} > 5%",
            ["max_abs_err_frac"])

    if isinstance(out.get("assumptions"), dict) and out["assumptions"]:
        add("disclose_defaults", "must_disclose",
            "k_s/k_r/L 是演示占位；定量前须用标定或 datasheet 覆盖",
            ["assumptions"])
    return acts


_SESSION_FILE = None            # 进程内会话，避免给只读安装目录添写盘依赖
_SEV_BLOCK = "block_conclusion"


TOOLS = [
    {"name": "t_ndir_forward",
     "description": "NDIR 单浓度正演：双通道信号/比值/解析反演。x 为摩尔分数（1e-6=1ppm）。k_s/k_r/L 默认演示占位，真实器件参数须用户提供。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x": {"type": "number", "description": "摩尔分数，1e-6=1ppm", "default": 5e-6},
                         "L_s_cm": {"type": "number", "default": 10.0},
                         "L_r_cm": {"type": "number", "default": 10.0},
                         "k_s": {"type": "number", "description": "信号通道带内有效吸收系数 cm⁻¹", "default": 0.05},
                         "k_r": {"type": "number", "default": 0.001},
                         "i0_s": {"type": "number", "default": 1.0},
                         "i0_r": {"type": "number", "default": 1.0},
                         "noise_frac": {"type": "number", "description": "相对高斯噪声 σ", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_ndir_calibrate",
     "description": "NDIR 浓度扫描标定：x_min..x_max 等距 n 点 → R(x) 表 + lnR 线性拟合（A_fit/R0_fit/R²）。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x_min": {"type": "number", "default": 0.0},
                         "x_max": {"type": "number", "default": 0.01},
                         "n": {"type": "integer", "default": 11},
                         "L_s_cm": {"type": "number", "default": 10.0},
                         "L_r_cm": {"type": "number", "default": 10.0},
                         "k_s": {"type": "number", "default": 0.05},
                         "k_r": {"type": "number", "default": 0.001},
                         "i0_s": {"type": "number", "default": 1.0},
                         "i0_r": {"type": "number", "default": 1.0},
                         "noise_frac": {"type": "number", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "t_ndir_invert",
     "description": "NDIR 比值 → 浓度解析反演：x = -ln(R/R0)/(k_s·L_s−k_r·L_r)。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "R": {"type": "number", "description": "实测两通道比值", "default": 0.5},
                         "R0": {"type": "number", "default": 1.0},
                         "A": {"type": "number", "description": "净吸收积 k_s·L_s−k_r·L_r", "default": 0.499}}}},
    {"name": "t_ndir_selftest",
     "description": "NDIR 数值锚点自检（离线）。",
     "inputSchema": {"type": "object", "properties": {}}},
]

DISPATCH = {t["name"]: globals()[t["name"]] for t in TOOLS}
install_interaction(DISPATCH, TOOLS, _SESSION_FILE, _actions,
                    sev_block=_SEV_BLOCK, skip={"t_ndir_selftest"})


# ── 参数校验 / JSON-RPC（共用 spectrolink_core.mcp_runtime）─────────────

_SCHEMA_BY_NAME = schema_index(TOOLS)

# 严格口径（必填 / 未知键 / 类型）与其余 server 完全一致；返回值路径在此脱敏
handle_request = make_handle_request(SERVER_INFO, TOOLS, DISPATCH,
                                     _SCHEMA_BY_NAME, sanitize=_sanitize_paths)


def main():
    if "--selftest" in sys.argv:
        try:
            print(json.dumps(_sanitize_paths(t_ndir_selftest()), ensure_ascii=False, indent=2))
        except ImportError as exc:
            sys.stderr.write(f"[ndir-mcp] 自检无法运行：{exc}\n")
            raise SystemExit(2)
        return 0
    return serve_stdio(handle_request)


if __name__ == "__main__":
    main()
