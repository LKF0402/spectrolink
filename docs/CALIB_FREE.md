# 免标定（Calibration-Free）· 新手引导

**一句话**：免标定不是"少交数据"，而是用**零基线 + 一个绝对锚点 + 仪器状态**替掉整条浓度标定曲线。

> 适用范围：**TDLAS / LITES**（v1.1.0）；其他技术按同一契约逐步扩展。

## 30 秒上手

把下面整段贴给 AI 助手（已装 SpectroLink MCP 或本地仓库均可）：

```
用 SpectroLink 的 tdlas_calibfree 帮我做免标定。先跑 mode=guide，
按它给的最小清单告诉我缺哪些数据；我手头有：
- 0% 气背景 CSV：x2f,y2f（同光路、同增益）
- 样品 2f CSV：x2f,y2f
- 光程、温度、气压、CO2 线中心：按本次实验记录填写（示例用 100 cm / 298 K / 1.0 atm / 2349.0 cm-1）
先只做 shape，确认 corr≥0.99 和峰位对齐；有 I0 或已知浓度参考时，再继续出浓度。
```

AI 会先返回 `guide`（三类数据 + 缺项），再按 `shape → absolute / anchored` 逐步推进。你不需要先学 API。

## 先判断：你手头是哪一种？

| 你有的数据 | 推荐模式 | 输出 |
|---|---|---|
| 样品 2f 的 X/Y（+ 可选 0% 背景） | TDLAS `shape` | 波形 corr、m、扫描轴、复增益/相位、峰位差 |
| 样品透射 I + 同光路 0% 气 I0 | TDLAS `absolute` | 绝对浓度 `x=A_peak/(α_pure·L)` |
| 样品 2f 峰 + 已知浓度参考峰 | TDLAS `anchored` | 跨浓度 `x=x_ref·(A/A_ref)` |
| 参考浓度 2f + 功率监测 + f0/Q | LITES `anchored` | 跨浓度 `x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)` |

> 推荐路径：2f 先跑 `shape` 确认波形与扫描轴，再按手头数据走 `absolute`（有 I0）或 `anchored`（有已知浓度参考），一步到位出浓度。

### 免标定 ≠ 全仪器仿真：两条独立路径

| | 全仪器仿真（`tdlas_wms_instrument` 等） | 免标定反演（`*_calibfree`） |
|---|---|---|
| 需要 | DAQ/激光调谐/PD/ADC/锁相全链路参数，或实测基线 | **实测信号 + 零基线 + 一个绝对锚点 + 工况状态** |
| 不需要 | — | 不需要逐级电路增益、TIA、激光电流-波长非线性等“可被锚点吸收”的参数 |
| 用途 | 设计系统、预测波形、评估方案 | 从已有实验数据直接出浓度/形状，替掉浓度标定曲线 |
| 关系 | 可单独用；也可用仿真选参、再用免标定处理实测 | 可单独用；也可反过来用实测锚点校验仿真 |

> 一句话：**用了免标定，就不需要把整条仪器链的每个增益都测出来**；但 L、T、P、扫描轴、调制频率这些“决定 α(ν) 与采样位置”的状态仍必须知道。

## 三类数据（配齐即可开跑）

| 类别 | 作用 | 具体交什么 |
|---|---|---|
| **A 零基线** | 扣窗口、RAM、暗电流、探测器漂移 | 同光路 0% 气/空腔的 X/Y 或 I0；遮光暗信号；**实验前后各一次** |
| **B 绝对锚点** | 把"伏特"换成"αL"或"浓度" | TDLAS：I0 透射，或已知浓度参考；LITES：已知浓度参考 |
| **C 仪器状态** | 让理论 α 与实测同工况 | L、T、P、调制 f/幅度、扫描跨度/波形、采样率、锁相时间常数/相位、探测器带宽、功率监测 |

A/B/C 配齐后，理论线可与实测对齐，`absolute/anchored` 可直接给出浓度。

## TDLAS：三种模式

### `shape`：波形与扫描轴确认

必填：`x2f, y2f`（+ 建议 `x2f_bg, y2f_bg`）、`species`、`wn_center_cm1`、`T`、`P`、`L_cm`。

```json
{"mode":"shape","species":"CO2","wn_center_cm1":2349.0,
 "T":298.0,"P":1.0,"L_cm":100.0,
 "data_path":"sample_2f.csv","background_path":"background_2f.csv"}
```

看三个数：
- `validation.checks[corr_shape] ≥ 0.99`：形状对得上；
- `peak_aligned` 的采样点差 ≤1：扫描轴/线中心没偏；
- `m` 与 `scan_span_cm1`：记录进 `meta.json`，后续 `absolute/anchored` 必须同轴。

`shape` 输出 `x=null`；浓度由 `absolute` / `anchored` 给出。

### `absolute`：有 I0 才做绝对浓度

必填：`i, i0`（同光路、同增益、同 T/P）、`species`、`wn_center_cm1`、`L_cm`。

```json
{"mode":"absolute","species":"CO2","wn_center_cm1":2349.0,
 "T":298.0,"P":1.0,"L_cm":100.0,"data_path":"sample_das.csv","background_path":"zero_das.csv",
 "baseline_windows":[[80,350],[650,900]]}
```

输出 `A_peak`、`alpha_pure_peak_cm-1`、`x`、`x_percent`。
- 在标气证书浓度范围内使用，结果最稳；更高浓度可等 1.2 的高浓度模型。
- 建议先扣暗信号，再做 `I/I0`，数据更干净。

### `anchored`：有已知浓度参考就跨浓度免曲线

必填：`sample_peak, ref_peak, x_ref`（峰高必须在**同 m、同扫描轴、同增益**下取）。

```json
{"mode":"anchored","sample_peak":0.002,"ref_peak":0.001,"x_ref":0.01}
```

输出 `x=x_ref·(A/A_ref)`。适合弱吸收线性区；在同 m、同扫描轴、同增益下取峰高，跨浓度直接出结果。

## LITES：只做单点锚定

```json
{"mode":"anchored","v2f_sample":0.0020,"v2f_ref":0.0010,"x_ref":0.01,
 "power_sample_mW":2.0,"power_ref_mW":1.0,
 "f_m_sample_Hz":16000.0,"f_m_ref_Hz":16000.0,
 "f0_Hz":32000.0,"Q":8000}
```

公式：`x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)`。

> 先跑 `lites_calibfree(mode="guide")`：返回 `lites_specific`（`principle` / `what_cancels` / `recommended` / `anchoring`）与 `try_this`，把物理链路、可消除项与推荐用法讲清楚。

- `P` 可测，`H_th(f_m)` 与 `H_mech(f_m;f0,Q)` 可由共振曲线消掉；
- `η_dev` 与器件私有增益 g（含 C_total/R_tia/电极面积）被 `x_ref` 吸收；单点锚定后，同器件、同波长可跨浓度直接出结果；
- 换器件或换波长时重新锚定，即可保持结果一致、可追溯。

## CSV / NPZ 格式

首行列名，UTF-8；列名大小写不敏感，支持常见别名（如 `x_2f`、`2fx`、`i_det`、`transmission`）。

| 用途 | 最小列 |
|---|---|
| TDLAS shape | 样品表 `x2f,y2f`；背景表 `x2f,y2f`（也接受 `x2f_bg,y2f_bg`） |
| TDLAS absolute | 样品表 `i`；背景表 `i`（也接受 `i0`） |
| LITES anchored | `v2f,v2f_ref,power_mW,f_m_Hz`（参考列缺省时按 `v2f` 读背景表） |

`meta.json` 模板见 [`calib_free_meta_template.json`](./calib_free_meta_template.json)：未知字段填 `null`，不要猜。

> `anchored` 只接三个标量（`sample_peak / ref_peak / x_ref`），不读 `data_path`；峰高要自己从同轴波形取峰值后传入。

## 实验前 / 中 / 后清单

**前**
1. 同光路、同增益、同调制参数，先录 0% 气背景。
2. 遮光录暗信号 ≥10 s。
3. 实测记录 L、T、P；不要用论文默认值。

**中**
4. 每个样品存**原始电压 + sync/ramp**，不要只存解调后的 X/Y。
5. 同时录功率监测通道。
6. 记录锁相时间常数与相位；改相位必须整组重录背景。

**后**
7. 再录一次背景；前后差 >5% 要标记。
8. 填 `meta.json`，未知项写 `null`；原始与处理数据分开存。

## 使用建议

- 0% 气背景与样品**同光路、同增益**录制，可最大限度扣除窗口、RAM 与暗电流。
- 2f 适合做波形与扫描轴确认；要绝对浓度，直接走 `absolute`（有 I0）或 `anchored`（有已知浓度参考）。
- 扫描非线性场景，建议同时录 sync/ramp 或标准具参考，扫描轴更稳。

## 实测锚点（已验证）

以下为标准 CO₂ 标气上的独立验证（具体工况略）：

| 项目 | 结果 |
|---|---|
| 2f 单浓度形状 | 波形 corr **>0.99**，峰位对齐 |
| 多浓度定轴 | corr **>0.99**，跨浓度 corr 均 ≥0.99 |
| 2f 峰值线性 | R² **>0.99** |
| DAS 绝对反演 | 跨浓度线性 R² **>0.99**，响应稳定 |

## 版本前瞻

| 版本 | 范围 | 内容 |
|---|---|---|
| **1.1.0（当前）** | TDLAS / LITES | `shape / absolute / anchored`；共用 `calibfree.py`；本文件与 meta 模板 |
| 1.2（规划） | TDLAS | 4f 定相、高浓度模型、扫描非线性自校正，覆盖更宽工况 |
| 1.3（规划） | LITES | 实测 `η_dev` 接入、QTF 电-声传递链标定、共振在线跟踪 |
| 后续 | 其他技术 | 按同一免标定契约逐步扩展 |

**统一内核**：免标定与 HITRAN 取数、锁相、线型、单位共用同一内核；单一版本、单一 provenance，用户零新增安装。只有出现"外部项目不装 SpectroLink 也要调用""独立发布节奏""多维护者"三条同时成立时，再评估独立发布。

## 工具入口

- `tdlas_calibfree(mode="guide")` → 最小清单；再 `shape / absolute / anchored`
- `lites_calibfree(mode="guide")` → LITES 专属清单；再 `anchored`
- `tdlas_guide` / `lites_guide` 已加入免标定入口，可直接问 AI"我该交什么数据"
