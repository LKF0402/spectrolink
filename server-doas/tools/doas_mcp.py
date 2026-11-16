#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DOAS 仪器级仿真 MCP 服务器（stdio JSON-RPC 2024-11-05）。

工具面：
  · doas_forward    单浓度正演（宽带源/吸收/差分反演披露）
  · doas_calibrate  浓度扫描标定曲线（线性拟合 + R²）
  · doas_invert     实测谱 → 差分反演浓度（用户传 I/i0/sigma 数组）
  · doas_selftest   数值锚点自检

纪律：纯标准库 stdio JSON-RPC；print 只走协议 stdout；
参考截面/源包络/光程默认均为 ai 演示占位，真实器件参数须用户交互提供。

自测：python tools/doas_mcp.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SRV = Path(__file__).resolve().parent.parent          # server-doas
_ROOT = _SRV.parent
for _p in (_ROOT, _SRV):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import doas_physics as dph  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"protocolVersion": PROTOCOL_VERSION,
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "doas", "version": "1.0.0"}}

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

def doas_forward(x=5e-6, L_cm=50.0, species="NO2", wl_min=400.0, wl_max=500.0,
                   n_wl=401, T=296.0, P=1.0, poly_deg=3, noise_frac=0.0, seed=0):
    """单浓度 DOAS 正演。x 为摩尔分数（1e-6=1ppm）。λ 单位 nm。

    ⚠️ 参考截面/源包络/L 默认是 ai 演示占位（NO₂ 448 nm 量级），
    真实截面须用户提供（HITRAN xsc 或实测），未提供前不可作定量结论。
    """
    out = dph.forward(x, L_cm, species, wl_min, wl_max, n_wl, T, P, poly_deg,
                      noise_frac, seed)
    checks = [
        check("concentration_in_range",
              "pass" if 0 <= out.get("x_inferred", -1) <= 1 else "fail",
              "反演摩尔分数须落在 [0, 1]", out.get("x_inferred")),
        check("optical_depth", "pass" if 0 < out.get("od_peak", -1) <= 2 else "warn",
              "峰光学厚度应 >0 且 ≤2（过强吸收会破坏差分线性）", out.get("od_peak")),
        check("concentration_error",
              "pass" if abs(out.get("x_error_frac", 0)) < 0.05 else "warn",
              "无噪声正演反演误差应 <5%", out.get("x_error_frac")),
    ]
    out["validation"] = validation_block(
        checks, note="默认截面/源为演示占位，未标定前不可作定量结论")
    return out


def doas_calibrate(x_min=0.0, x_max=2e-5, n=11, L_cm=50.0, species="NO2",
                     T=296.0, P=1.0, poly_deg=3, noise_frac=0.0, seed=0):
    """浓度扫描标定：x_min..x_max 等距 n 点 → 反演浓度表 + 线性拟合。"""
    out = dph.calibrate(x_min, x_max, n, L_cm, species, T, P, poly_deg,
                        noise_frac, seed)
    checks = [
        check("fit_r2", "pass" if out.get("r_squared", 0) >= 0.999 else "warn",
              "标定线性拟合 R² 应 ≥0.999", out.get("r_squared")),
        check("slope", "pass" if abs(out.get("slope", 0) - 1) <= 0.02 else "warn",
              "标定斜率应≈1（反演浓度对真值）", out.get("slope")),
        check("max_error", "pass" if out.get("max_abs_err_frac", 1) <= 0.01 else "warn",
              "归一化最大绝对误差应 ≤1% 满量程", out.get("max_abs_err_frac")),
    ]
    out["validation"] = validation_block(
        checks, note="默认截面/源为演示占位；标定斜率仅验证算法，不代表真实器件")
    return out


def doas_invert(I=None, i0=None, sigma=None, L_cm=50.0, poly_deg=3):
    """实测谱 → 差分反演浓度（等长数组 I/i0/sigma；不传数组给用法提示）。"""
    if I is None or i0 is None or sigma is None:
        return {"usage": "传等长数值数组 I（实测光强）、i0（参考光强）、sigma（吸收截面 cm²/molecule）",
                "x": None,
                "validation": validation_block([
                    check("input_present", "fail", "缺 I/i0/sigma，无法反演")])}
    out = dph.invert(I, i0, sigma, L_cm, poly_deg)
    if out.get("x") is None:
        out["validation"] = validation_block([
            check("input_shape", "fail", out.get("usage", "I/i0/sigma 不合法"))])
    else:
        out["validation"] = validation_block([
            check("concentration_in_range",
                  "pass" if 0 <= out["x"] <= 1 else "fail",
                  "反演摩尔分数须落在 [0, 1]", out["x"]),
        ])
    return out


def doas_selftest():
    """数值锚点自检（离线，不依赖网络）。"""
    return dph.selftest()


def _actions(out, tool):
    acts = []

    def add(aid, severity, text, evidence):
        if all(ev_ok(out, p) for p in evidence):
            acts.append({"id": aid, "severity": severity, "action": text,
                         "evidence_fields": evidence})

    if out.get("x") is None and "usage" in out:
        add("input_required", _SEV_BLOCK,
            f"尚未输入可用实测谱：{out['usage']}", ["usage", "x"])

    note = (out.get("validation") or {}).get("note")
    if note:
        add("disclose_validation_note", "must_disclose",
            f"校验提示：{note}", ["validation.note"])

    x = out.get("x_inferred", out.get("x"))
    if isinstance(x, (int, float)) and not 0 <= x <= 1:
        add("concentration_unusable", _SEV_BLOCK,
            f"反演浓度 x={x:.6g} 不在 [0, 1]；检查差分背景阶数、截面与光程是否同源",
            ["x_inferred"] if "x_inferred" in out else ["x"])

    od = out.get("od_peak")
    if isinstance(od, (int, float)) and od > 2:
        add("disclose_strong_absorption", "must_disclose",
            f"峰光学厚度 {od:.3g} >2；强吸收下差分线性近似失真",
            ["od_peak"])

    err = out.get("x_error_frac")
    if isinstance(err, (int, float)) and abs(err) >= 0.05:
        add("disclose_concentration_error", "must_disclose",
            f"反演相对误差 {abs(err):.1%} ≥ 5%，不得当作精确结果",
            ["x_error_frac"])

    if isinstance(out.get("r_squared"), (int, float)) and out["r_squared"] < 0.999:
        add("disclose_calibration_fit", "must_disclose",
            f"标定 R²={out['r_squared']:.3g} < 0.999；线性标定不可直接用于定量",
            ["r_squared"])
    if isinstance(out.get("max_abs_err_frac"), (int, float)) and out["max_abs_err_frac"] > 0.01:
        add("disclose_calibration_error", "must_disclose",
            f"标定归一化最大误差 {out['max_abs_err_frac']:.1%} > 1% 满量程",
            ["max_abs_err_frac"])
    return acts


_SESSION_FILE = None
_SEV_BLOCK = "block_conclusion"


TOOLS = [
    {"name": "doas_forward",
     "description": "DOAS 单浓度正演：宽带源包络→分子吸收→差分反演披露。x 摩尔分数（1e-6=1ppm），λ 单位 nm。默认截面/源为演示占位（NO₂ 448 nm 量级），真实截面须用户提供。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x": {"type": "number", "description": "摩尔分数，1e-6=1ppm", "default": 5e-6},
                         "L_cm": {"type": "number", "default": 50.0},
                         "species": {"type": "string", "enum": ["NO2", "SO2", "O3"], "default": "NO2"},
                         "wl_min": {"type": "number", "description": "波段下限 nm", "default": 400.0},
                         "wl_max": {"type": "number", "default": 500.0},
                         "n_wl": {"type": "integer", "default": 401},
                         "T": {"type": "number", "default": 296.0},
                         "P": {"type": "number", "description": "气压 atm", "default": 1.0},
                         "poly_deg": {"type": "integer", "description": "慢变背景多项式阶数", "default": 3},
                         "noise_frac": {"type": "number", "description": "相对高斯噪声 σ", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "doas_calibrate",
     "description": "DOAS 浓度扫描标定：x_min..x_max 等距 n 点 → 反演浓度表 + 线性拟合（slope/R²/max_abs_err）。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "x_min": {"type": "number", "default": 0.0},
                         "x_max": {"type": "number", "default": 2e-5},
                         "n": {"type": "integer", "default": 11},
                         "L_cm": {"type": "number", "default": 50.0},
                         "species": {"type": "string", "enum": ["NO2", "SO2", "O3"], "default": "NO2"},
                         "T": {"type": "number", "default": 296.0},
                         "P": {"type": "number", "default": 1.0},
                         "poly_deg": {"type": "integer", "default": 3},
                         "noise_frac": {"type": "number", "default": 0.0},
                         "seed": {"type": "integer", "default": 0}}}},
    {"name": "doas_invert",
     "description": "DOAS 实测谱差分反演：c = argmin ‖ln(I0/I)−P(λ)−σ·L·c‖²。传等长数组 I/i0/sigma。",
     "inputSchema": {"type": "object",
                     "properties": {
                         "I": {"type": "array", "items": {"type": "number"}, "description": "实测光强"},
                         "i0": {"type": "array", "items": {"type": "number"}, "description": "参考光强"},
                         "sigma": {"type": "array", "items": {"type": "number"}, "description": "吸收截面 cm²/molecule"},
                         "L_cm": {"type": "number", "default": 50.0},
                         "poly_deg": {"type": "integer", "default": 3}}}},
    {"name": "doas_selftest",
     "description": "DOAS 数值锚点自检（离线）。",
     "inputSchema": {"type": "object", "properties": {}}},
]


# ── MCP 协议层（共用 spectrolink_core.mcp_runtime）────────────────

DISPATCH = {t["name"]: globals()[t["name"]] for t in TOOLS}
install_interaction(DISPATCH, TOOLS, _SESSION_FILE, _actions,
                    sev_block=_SEV_BLOCK, skip={"doas_selftest"})
_SCHEMA_BY_NAME = schema_index(TOOLS)

# 此前是自写的弱口径：无批量/通知、无必填/未知键/类型校验，还能吃位置参数
handle_request = make_handle_request(SERVER_INFO, TOOLS, DISPATCH,
                                     _SCHEMA_BY_NAME, sanitize=_sanitize_paths)


def main():
    if "--selftest" in sys.argv:
        sys.stdout.write(json.dumps(_sanitize_paths(dph.selftest()), ensure_ascii=False) + "\n")
        return 0 if dph.selftest()["ok"] else 2
    return serve_stdio(handle_request)


if __name__ == "__main__":
    sys.exit(main())
