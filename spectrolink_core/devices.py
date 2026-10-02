#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""器件库 schema 占位（spectrolink_core）。

铁律：**只定义结构，不内置任何默认仪器**。真实器件参数一律通过用户交互
获取（datasheet / 实测 / 标定），由各 server 的 `t_*_device` / `l_device`
写入各自持久化文件。本模块为空占位，仅声明跨技术器件字段的通用约束。

后续若需跨技术共用器件字段校验（如激光器调谐率、探测器带宽），在此扩展
schema 定义；不要在此写入具体厂商型号或演示参数。
"""

__all__ = ["DEVICE_FIELD_RULES"]

# 跨技术通用字段规则（只约束类型/量纲，不含任何默认值）
DEVICE_FIELD_RULES = {
    "laser": {
        "eta_VI": "float",      # mA/V
        "dnu_dI": "float",      # cm⁻¹/mA
        "wn_ref": "float",      # cm⁻¹
        "i_th": "float",        # mA
        "eta_IP": "float",      # mW/mA
    },
    "pd": {
        "resp": "float",        # A/W
        "gain": "float",        # V/A
        "bw": "float",          # Hz
    },
    "daq": {
        "fs": "float",          # S/s
        "adc_bits": "int",      # bits
        "v_range": "float",     # V（±）
    },
    "optics": {
        "throughput": "float",  # 0-1
    },
}
