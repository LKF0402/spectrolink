# 免标定（Calibration-Free）指南

**核心定义**：以免标定替代整条浓度标定曲线，其依据为**零基线 + 一个绝对锚点 + 仪器状态**，并非减少数据量。

> 适用范围：**TDLAS / LITES**（v1.1.0）；其他技术按同一契约逐步扩展。

## 一、快速开始

已安装 SpectroLink MCP 或已部署本地仓库时，可将以下指令整体提交给 AI 助手：

```text
请使用 SpectroLink 的 tdlas_calibfree 执行免标定分析。先调用 mode=guide，
根据最小数据清单说明缺项；现有数据如下：
- 0% 气背景 CSV：x2f,y2f（同光路、同增益）
- 样品 2f CSV：x2f,y2f
- 光程、温度、气压与 CO2 线中心：按本次实验记录填写（示例为 100 cm / 298 K / 1.0 atm / 2349.0 cm-1）
先执行 shape，确认 corr≥0.99 且峰位对齐；具备 I0 或已知浓度参考后，再进入浓度反演。
```

系统将先返回 `guide`（三类数据与缺项），再按 `shape → absolute / anchored` 逐步推进，无需预先熟悉 API。

## 二、模式选择

| 已有数据 | 推荐模式 | 输出 |
|---|---|---|
| 样品 2f 的 X/Y（可选 0% 背景） | TDLAS `shape` | 波形 corr、m、扫描轴、复增益/相位、峰位差 |
| 样品透射 I 与同光路 0% 气 I0 | TDLAS `absolute` | 绝对浓度 `x=A_peak/(α_pure·L)` |
| 样品 2f 峰与已知浓度参考峰 | TDLAS `anchored` | 跨浓度 `x=x_ref·(A/A_ref)` |
| 参考浓度 2f、功率监测与 f0/Q | LITES `anchored` | 跨浓度 `x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)` |

> 推荐顺序：先以 `shape` 确认波形与扫描轴，再根据现有数据选择 `absolute`（具备 I0）或 `anchored`（具备已知浓度参考），完成浓度反演。

### 免标定与全仪器仿真的关系

| 项目 | 全仪器仿真（`tdlas_wms_instrument` 等） | 免标定反演（`*_calibfree`） |
|---|---|---|
| 所需输入 | DAQ、激光调谐、PD、ADC、锁相全链路参数，或实测基线 | **实测信号 + 零基线 + 一个绝对锚点 + 工况状态** |
| 可省略项 | — | 逐级电路增益、TIA、激光电流-波长非线性等可由锚点吸收的参数 |
| 用途 | 系统设计、波形预测、方案评估 | 由已有实验数据直接输出浓度或波形，替代浓度标定曲线 |
| 关系 | 可独立使用；也可先仿真选参，再用免标定处理实测数据 | 可独立使用；也可用实测锚点校验仿真 |

> **采用免标定后，无需测量整条仪器链的各级增益**；但 L、T、P、扫描轴与调制频率等决定 α(ν) 与采样位置的状态量仍需已知。

## 三、三类数据

| 类别 | 作用 | 需提供的数据 |
|---|---|---|
| **A 零基线** | 扣除窗口、RAM、暗电流与探测器漂移 | 同光路 0% 气/空腔的 X/Y 或 I0；遮光暗信号；**实验前后各一次** |
| **B 绝对锚点** | 将电压标度转换为 αL 或浓度 | TDLAS：I0 透射，或已知浓度参考；LITES：已知浓度参考 |
| **C 仪器状态** | 使理论 α 与实测处于同一工况 | L、T、P、调制频率/幅度、扫描跨度/波形、采样率、锁相时间常数/相位、探测器带宽、功率监测 |

A/B/C 配齐后，理论谱线可与实测对齐，`absolute/anchored` 可直接输出浓度。

## 四、TDLAS 三种模式

### `shape`：波形与扫描轴确认

必填：`x2f, y2f`（建议同时提供 `x2f_bg, y2f_bg`）、`species`、`wn_center_cm1`、`T`、`P`、`L_cm`。

```json
{"mode":"shape","species":"CO2","wn_center_cm1":2349.0,
 "T":298.0,"P":1.0,"L_cm":100.0,
 "data_path":"sample_2f.csv","background_path":"background_2f.csv"}
```

重点检查以下三项：
- `validation.checks[corr_shape] ≥ 0.99`：波形一致；
- `peak_aligned` 的采样点差 ≤1：扫描轴与线中心未偏移；
- `m` 与 `scan_span_cm1`：写入 `meta.json`，后续 `absolute/anchored` 必须保持同轴。

`shape` 输出 `x=null`；浓度由 `absolute` / `anchored` 给出。

### `absolute`：具备 I0 时执行绝对浓度反演

必填：`i, i0`（同光路、同增益、同 T/P）、`species`、`wn_center_cm1`、`L_cm`。

```json
{"mode":"absolute","species":"CO2","wn_center_cm1":2349.0,
 "T":298.0,"P":1.0,"L_cm":100.0,"data_path":"sample_das.csv","background_path":"zero_das.csv",
 "baseline_windows":[[80,350],[650,900]]}
```

输出 `A_peak`、`alpha_pure_peak_cm-1`、`x`、`x_percent`。
- 在标气证书浓度范围内使用时结果最稳定；更高浓度可等待 1.2 的高浓度模型。
- 建议先扣除暗信号，再计算 `I/I0`，以改善数据质量。

### `anchored`：具备已知浓度参考时跨浓度免曲线

必填：`sample_peak, ref_peak, x_ref`（峰高须在**同 m、同扫描轴、同增益**条件下取得）。

```json
{"mode":"anchored","sample_peak":0.002,"ref_peak":0.001,"x_ref":0.01}
```

输出 `x=x_ref·(A/A_ref)`。适用于弱吸收线性区；在同 m、同扫描轴、同增益条件下取峰高，可直接跨浓度输出结果。

## 五、LITES 单点锚定

```json
{"mode":"anchored","v2f_sample":0.0020,"v2f_ref":0.0010,"x_ref":0.01,
 "power_sample_mW":2.0,"power_ref_mW":1.0,
 "f_m_sample_Hz":16000.0,"f_m_ref_Hz":16000.0,
 "f0_Hz":32000.0,"Q":8000}
```

公式：`x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)`。

> 先执行 `lites_calibfree(mode="guide")`：返回 `lites_specific`（`principle` / `what_cancels` / `recommended` / `anchoring`）与 `try_this`，用于说明物理链路、可消除项与推荐用法。

- `P` 可测，`H_th(f_m)` 与 `H_mech(f_m;f0,Q)` 可由共振曲线消除；
- `η_dev` 与器件私有增益 g（含 C_total/R_tia/电极面积）由 `x_ref` 吸收；单点锚定后，同器件、同波长可跨浓度输出结果；
- 更换器件或波长时重新锚定，即可保持结果一致与可追溯。

## 六、CSV / NPZ 格式

首行为列名，编码 UTF-8；列名大小写不敏感，支持常见别名（如 `x_2f`、`2fx`、`i_det`、`transmission`）。

| 用途 | 最小列 |
|---|---|
| TDLAS shape | 样品表 `x2f,y2f`；背景表 `x2f,y2f`（亦接受 `x2f_bg,y2f_bg`） |
| TDLAS absolute | 样品表 `i`；背景表 `i`（亦接受 `i0`） |
| LITES anchored | `v2f,v2f_ref,power_mW,f_m_Hz`（参考列缺省时按 `v2f` 读取背景表） |

`meta.json` 模板见 [`calib_free_meta_template.json`](./calib_free_meta_template.json)：未知字段填 `null`，不要推测。

> `anchored` 仅接收三个标量（`sample_peak / ref_peak / x_ref`），不读取 `data_path`；峰高须由用户从同轴波形取峰值后传入。

## 七、实验前 / 中 / 后清单

**实验前**
1. 在同光路、同增益、同调制参数条件下，先记录 0% 气背景。
2. 遮光记录暗信号 ≥10 s。
3. 实测记录 L、T、P；不得使用论文默认值替代。

**实验中**
4. 每个样品保存**原始电压 + sync/ramp**，不得仅保存解调后的 X/Y。
5. 同步记录功率监测通道。
6. 记录锁相时间常数与相位；若相位变更，须整组重录背景。

**实验后**
7. 再次记录背景；前后差异 >5% 时须标记。
8. 填写 `meta.json`，未知项写 `null`；原始数据与处理数据分开保存。

## 八、使用建议

- 0% 气背景与样品应在**同光路、同增益**条件下录制，以最大限度扣除窗口、RAM 与暗电流。
- 2f 适用于波形与扫描轴确认；绝对浓度采用 `absolute`（具备 I0）或 `anchored`（具备已知浓度参考）。
- 扫描非线性场景建议同步记录 sync/ramp 或标准具参考，以提高扫描轴稳定性。

## 九、实测锚点（已验证）

以下结果来自标准 CO₂ 标气上的独立验证（具体工况略）：

| 项目 | 结果 |
|---|---|
| 2f 单浓度形状 | 波形 corr **>0.99**，峰位对齐 |
| 多浓度定轴 | corr **>0.99**，跨浓度 corr 均 ≥0.99 |
| 2f 峰值线性 | R² **>0.99** |
| DAS 绝对反演 | 跨浓度线性 R² **>0.99**，响应稳定 |

## 十、版本前瞻

| 版本 | 范围 | 内容 |
|---|---|---|
| **1.1.0（当前）** | TDLAS / LITES | `shape / absolute / anchored`；共用 `calibfree.py`；本文件与 meta 模板 |
| 1.2（规划） | TDLAS | 4f 定相、高浓度模型、扫描非线性自校正，覆盖更宽工况 |
| 1.3（规划） | LITES | 实测 `η_dev` 接入、QTF 电-声传递链标定、共振在线跟踪 |
| 后续 | 其他技术 | 按同一免标定契约逐步扩展 |

**统一内核**：免标定与 HITRAN 取数、锁相、线型、单位共用同一内核；单一版本、单一 provenance，用户无需新增安装。仅当“外部项目不安装 SpectroLink 仍需调用”“独立发布节奏”“多维护者”三项同时成立时，再评估独立发布。

## 十一、工具入口

- `tdlas_calibfree(mode="guide")` → 最小数据清单；再执行 `shape / absolute / anchored`
- `lites_calibfree(mode="guide")` → LITES 专用清单；再执行 `anchored`
- `tdlas_guide` / `lites_guide` 已加入免标定入口，可直接询问“需要提交哪些数据”
