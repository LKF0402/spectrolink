---
name: spectrolink-ftir
description: SpectroLink 子服务器 server-ftir（L2 参考，AI 自动读取，非独立安装）。FTIR 傅里叶变换红外光谱仿真。触发词：FTIR、傅里叶变换红外、干涉图、切趾、分辨率、光程差、多组分同时分析、离线光谱。
---

# server-ftir：FTIR 傅里叶变换红外仿真（SpectroLink L2 参考）

> 由总 SKILL 自动调度读取。物理内核 `ftir_physics.py` + spectrolink_core。**不内置仪器，默认演示占位，真实仪器参数须用户提供。**

## 原理速览

FTIR 以**宽带干涉测量**获得全谱（Fellgett 优点——全波段同时测量）：

1. 透射谱 T(ν)（HITRAN/高斯）→ 干涉图 I(δ) = ∫T(ν)cos(2πνδ)dν
2. 截断（有限最大光程差 x_max）→ **切趾窗** → 逆傅里叶恢复 T′(ν)
3. 恢复谱含**仪器线型 ILS**（sinc 展宽 + 窗旁瓣），分辨率 ≈ 0.5/x_max [cm⁻¹]
4. 多组分浓度：最小二乘拟合纯组分谱（需用户提供实测恢复谱 + 纯组分 α(ν) 数组）

## 工具路由

| 任务 | 工具 |
|---|---|
| 正演：透射谱→干涉图→切趾恢复→分辨率披露→浓度反演 | `t_ftir_simulate` |
| 恢复谱 → 浓度最小二乘反演（用户提供数组） | `t_ftir_invert` |
| 数值锚点自检（离线） | `t_ftir_selftest` |

## 关键参数（默认演示占位）

| 参数 | 默认 | 说明 |
|---|---|---|
| `x` | 1e-5 | 摩尔分数（1e-6=1ppm） |
| `x_max` | 2.0 | 最大光程差 [cm]，分辨率≈0.5/x_max |
| `window` | "boxcar" | 切趾窗：boxcar / hamming / blackman_harris |
| `line_source` | "hitran" | hitran / gaussian |

## 物理坑点（必查）

1. **切趾窗 tradeoff**：boxcar 分辨率最好但 sinc 旁瓣振铃（弱线被淹没）；Hamming/Blackman-Harris 抑制旁瓣但主瓣展宽（分辨率变差）。选窗 = 分辨率 vs 动态范围取舍。
2. **分辨率是硬披露项**：恢复谱 ≤0.5/x_max 的窄吸收线会被压矮/展宽，定量必须披露 ILS 效应；线宽接近分辨率时浓度低估。
3. **干涉图截断即旁瓣源**：x_max 不足 → 恢复谱振铃，与真实吸收峰混淆。
4. **多组分反演需要同口径纯组分谱**：`t_ftir_invert` 要求用户传实测恢复谱与纯组分 α(ν) 等长数组，不得编造数组。
5. **横轴波数 cm⁻¹**；恢复谱 T′ 是比例量，反演用 ln 域差分。
6. **数值锚点**：自检含 boxcar 恢复分辨率与单线闭合断言。

## 交互契约

- `validation.overall`：`fail` 不得下结论；`warn`（默认演示占位）须披露。
- `window` 非 boxcar 时披露分辨率损失；`line_source=hitran` 降级时披露。

## 使用声明

输出为理论仿真，严禁冒充实验数据。
