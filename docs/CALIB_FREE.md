# 免标定

**一句话**：零基线 + 一个绝对锚点 + 工况，替掉整条浓度标定曲线。适用于 TDLAS / LITES。

## 先交三类数据

| 类别 | 作用 | 交什么 |
|---|---|---|
| A 零基线 | 扣窗口、RAM、暗电流、漂移 | 同光路 0% 气/空腔的 X/Y 或 I0；实验前后各一次 |
| B 绝对锚点 | 把电压换成浓度 | TDLAS：I0，或已知浓度参考；LITES：已知浓度参考 |
| C 工况 | 让理论谱对齐实测 | L、T、P、调制频率/幅度、扫描跨度、采样率、锁相参数 |

## TDLAS：三种模式

| 模式 | 你手头有 | 输出 |
|---|---|---|
| `shape` | 样品 2f 的 X/Y（建议加 0% 背景） | 波形 corr、m、扫描轴、增益/相位、峰位差 |
| `absolute` | 同光路 0% 气 I0 + L/T/P | 绝对浓度 `x=A_peak/(α_pure·L)` |
| `anchored` | 已知浓度参考峰 + 同轴样品峰 | 跨浓度 `x=x_ref·(A/A_ref)` |

最小示例：

```json
{"mode":"shape","species":"CO2","wn_center_cm1":2349.0,
 "T":298.0,"P":1.0,"L_cm":100.0,
 "data_path":"sample_2f.csv","background_path":"background_2f.csv"}
```

先看三个数：`corr_shape ≥ 0.99`、峰位对齐、`m` 与 `scan_span_cm1`。浓度由 `absolute` / `anchored` 给出。

## LITES：单点锚定

```json
{"mode":"anchored","v2f_sample":0.002,"v2f_ref":0.001,"x_ref":0.01,
 "power_sample_mW":2.0,"power_ref_mW":1.0,
 "f_m_sample_Hz":16000.0,"f_m_ref_Hz":16000.0,
 "f0_Hz":32000.0,"Q":8000}
```

`x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)`。同器件、同波长可跨浓度直接出结果；换器件或波长重锚一次。

## CSV 最小列

| 用途 | 列 |
|---|---|
| TDLAS shape | 样品 `x2f,y2f`；背景 `x2f,y2f` |
| TDLAS absolute | 样品 `i`；背景 `i` 或 `i0` |
| LITES anchored | `v2f,v2f_ref,power_mW,f_m_Hz` |

列名大小写不敏感；未知字段填 `null`。模板：[calib_free_meta_template.json](./calib_free_meta_template.json)。

## 已验证

| 项目 | 结果 |
|---|---|
| 2f 单浓度形状 | corr **>0.99**，峰位对齐 |
| 跨浓度 2f | corr **>0.99** |
| 2f 峰值线性 | R² **>0.99** |
| DAS 绝对反演 | 跨浓度线性 R² **>0.99** |

## 入口

- `tdlas_calibfree(mode="guide")` → 数据清单 → `shape / absolute / anchored`
- `lites_calibfree(mode="guide")` → 数据清单 → `anchored`
