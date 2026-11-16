<div align="center">

<h1>SpectroLink</h1>

<p><b>多技术光谱传感仿真 MCP</b><br>
TDLAS-DA/WMS · LITES · NDIR · CRDS · FTIR · DOAS<br>
7 种技术 · 6 个 server · 45 个工具 · 自然语言驱动 · 本地 stdio · 无需 API key</p>

<a href="https://github.com/LKF0402/spectrolink/releases"><img src="https://img.shields.io/github/v/release/LKF0402/spectrolink?color=6B8FD4&label=release" alt="Release"></a>
<a href="https://github.com/LKF0402/spectrolink/stargazers"><img src="https://img.shields.io/github/stars/LKF0402/spectrolink?color=yellow" alt="Stars"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-GPLv3-green.svg" alt="License"></a>
<a href="https://github.com/LKF0402/spectrolink/actions/workflows/ci.yml"><img src="https://github.com/LKF0402/spectrolink/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<img src="https://img.shields.io/badge/Python-3.10%2B-3776AB" alt="Python">
<img src="https://img.shields.io/badge/MCP-stdio-6B8FD4" alt="MCP">
<img src="https://img.shields.io/badge/HITRAN-2024-4C8C4A" alt="HITRAN">
<img src="https://img.shields.io/badge/techniques-7-9C6BD4" alt="Techniques">
<img src="https://img.shields.io/badge/tools-45-6B8FD4" alt="Tools">
<img src="https://img.shields.io/badge/calibfree-TDLAS%20%2B%20LITES-4C8C4A" alt="Calib-free">
<a href="https://github.com/LKF0402/spectrolink/commits/main"><img src="https://img.shields.io/github/last-commit/LKF0402/spectrolink" alt="Last commit"></a>
<a href="https://github.com/LKF0402/spectrolink/issues"><img src="https://img.shields.io/github/issues/LKF0402/spectrolink" alt="Issues"></a>
<a href="https://github.com/LKF0402/spectrolink/network/members"><img src="https://img.shields.io/github/forks/LKF0402/spectrolink" alt="Forks"></a>
<img src="https://img.shields.io/github/commit-activity/m/LKF0402/spectrolink" alt="Commit activity">
<img src="https://img.shields.io/badge/API%20key-none-4C8C4A" alt="No API key">
<a href="CHANGELOG.md"><img src="https://img.shields.io/badge/changelog-v1.1.0-blue" alt="Changelog"></a>
<img src="https://img.shields.io/badge/docs-TECHNICAL%20%C2%B7%20USAGE-blueviolet" alt="Docs">

</div>

> **概述**：输入气体、波段与工况，系统输出仪器级仿真波形、谱图、检测限与不确定度；全程本地运行，无需 API key。

---

## 🚀 快速开始

**首次使用时，可将以下指令整体提交给 AI 助手**：

```text
请协助完成 SpectroLink 的安装与自检，无需人工修改路径：
1. 将 https://github.com/LKF0402/spectrolink.git 克隆至固定目录，并确认 Python ≥ 3.10。
2. 执行 pip install -r requirements.txt 与 pip install -e ./spectrolink_core。
3. 在 MCP 客户端中仅启用 spectrolink-tdlas：command 使用本机 python 绝对路径，args 使用 server-tdlas/tools/tdlas_mcp.py 的绝对路径。
4. 将仓库根目录 SKILL.md 安装为 Skill。
5. 执行 python server-tdlas/tools/tdlas_mcp.py --selftest。
完成后请报告安装位置、修改的配置文件及最初三条可用指令；若任一步骤失败，请终止并报告具体环节。
```

安装完成后，可直接输入：`绘制 CH4 在 2968.5 cm⁻¹、50 ppm、10 cm 光程下的 WMS 图`。

> 需要完整的七步安装要求（包括客户端配置文件缺失时的处理）？展开下方「完整安装指令」。若 AI 无法执行本地命令，参见「手动安装与自检」。

<details>
<summary>完整安装指令（提交给 AI）</summary>

```text
拟使用 SpectroLink（多技术光谱仿真 MCP，仓库 https://github.com/LKF0402/spectrolink）开展 TDLAS/WMS 光谱仿真。请协助完成全部安装，无需人工修改路径：

1. 确认本机 Python ≥ 3.10；若版本不足，请说明安装方法，不作推测。
2. 选择固定目录执行 git clone https://github.com/LKF0402/spectrolink.git，并记录其绝对路径。
3. 进入该目录，依次执行 pip install -r requirements.txt、pip install -e ./spectrolink_core。
4. 查找当前 MCP 客户端（Claude Desktop / Cursor / Cline / VS Code 之一）的配置文件，写入 spectrolink-tdlas：
   command = 本机 python 的绝对路径；args = [该目录绝对路径 + "/server-tdlas/tools/tdlas_mcp.py"]
   lites / ndir / crds / ftir / doas 五项暂设为 disabled，待需要时启用。
   若无法定位客户端配置文件，请将 mcp.config.example.json 按真实路径配置后说明应放置的位置。
5. 将仓库根目录 SKILL.md 安装为 Skill（按客户端 Skill 目录约定放置；若不确定，请说明目标位置）。该文件为唯一入口，子技术说明由 AI 按需读取，无需分别安装。
6. 执行 python server-tdlas/tools/tdlas_mcp.py --selftest，并反馈结果。
7. 最后报告：安装位置、修改的配置文件、最初三条可直接使用的指令。

若任一步骤失败，请终止并报告具体环节，请勿跳过。
```

</details>

行为规范见 [SKILL.md](./SKILL.md)，更多交互示例见 [USAGE.md](./USAGE.md)。

## 🧪 免标定（v1.1.0 · 仅 TDLAS / LITES）

**免标定并非取消标定，而是以零基线 + 一个锚点 + 仪器状态替代整条浓度标定曲线。**

| 技术 | 模式 | 所需数据 | 输出 |
|---|---|---|---|
| **TDLAS** | `shape` | 2f 的 X/Y（建议加 0% 背景）、L/T/P、线中心 | 波形一致性、复增益/相位、自动确定的 m 与扫描跨度；浓度由 `absolute` / `anchored` 输出 |
| | `absolute` | 同光路 0% 气 I0、L、T/P | `x=A_peak/(α_pure·L)` |
| | `anchored` | 已知浓度参考 + 同 m/同轴 2f | `x=x_ref·(A/A_ref)` |
| **LITES** | `anchored` | 参考浓度 2f、功率监测、f0/Q | `x=x_ref·(V/V_ref)·(P_ref/P)·(R_ref/R)` |

- 操作顺序：**A 零基线**（0% 气/暗，前后各一次）→ **B 锚点**（I0 或已知浓度参考）→ **C 仪器状态**（L/T/P、调制、锁相、采样率）。
- 推荐路径：单路 2f 先以 `shape` 确认波形，再根据现有数据选择 `absolute`（具备 I0）或 `anchored`（具备已知浓度参考）。
- LITES 采用单点锚定 + 功率/共振归一化，稳定性好且易于实施；完整数据清单与 CSV 列名：[docs/CALIB_FREE.md](./docs/CALIB_FREE.md)。

## 📊 效果展示

![WMS demo](docs/assets/wms-ch4-demo.png)

> CH₄ @ 2968.5 cm⁻¹ 的 3×2 输出：驱动电压 → DAS 吸收 → 1f → 2f → 2f/1f（红色为电压折返剔除区）

![交互工作流](docs/assets/interaction-workflow.png)

> 四泳道流程：启动协议 → 参数与澄清（四级优先级 + 设备库 + 结构化追问）→ 仿真执行 → 校验与交付（10 项校验、α/条纹语境播报、保真度台账）

<details>
<summary>技术适配矩阵（扩展性）</summary>

17 种光谱技术在本项目四层架构（取数 / 器件 / 信号 / 反演）上的适配判定：🟩 复用 · 🟧 改造 · 🟥 新增

![技术适配矩阵](docs/assets/technique-matrix.png)

</details>

## ✨ 核心特性

- **全链路建模**：DAQ 调制 → 激光调谐 → HITRAN 吸收 → PD → ADC → 数字锁相；可选 etalon 条纹、RIN、1/f 漂移、RAM/AM
- **七技术一体**：TDLAS-DA/WMS · LITES · NDIR · CRDS · FTIR · DOAS，独立 server 按需加载、共用 `spectrolink_core` 物理内核
- **免标定（1.1.0）**：TDLAS `shape/absolute/anchored` 与 LITES `anchored`；零基线 + 一个锚点 + 仪器状态，替代浓度标定曲线；最小数据清单见 [docs/CALIB_FREE.md](./docs/CALIB_FREE.md)
- **混合气多组分**：`mixture` 严格按 `α = Σ xᵢ·α_pureᵢ(T,P)` 逐点相加（**不用 x·P 当分压**），并返回各组分归因
- **AI 交互契约**：六个技术的仪器/分析工具统一返回 `interaction` 与机器可读 `next_required_actions`；CRDS / NDIR / FTIR / DOAS 的动作只依据各自真实返回字段（浓度域、拟合质量、谱源降级、缺输入等），selftest 不参与记账
- **保真度台账**：默认生效 11 项 / 需显式开启 6 项，结果随附台账；已建模项与适用范围一目了然
- **可信度分层**：10 项物理校验与交互合规**分别**计分
- **可复现 + 离线门禁**：`seed=0` 逐位可复现；契约自检 200 项与保真度审计均为 CI 硬门禁（不依赖网络）

其他：`return_xy` 透出锁相 X/Y 用于 RAM/AM 诊断；`tdlas_invert(n_repeats>0)` 提供测量不确定度（仅统计分量）；`x_list` 支持多浓度同图。细节见 [TECHNICAL.md](./TECHNICAL.md) 与 [docs/VALIDATION.md](./docs/VALIDATION.md)。

## 📖 它是什么

基于 MCP（Model Context Protocol）的**多技术光谱传感仿真**，已实现 **TDLAS-DA / TDLAS-WMS / LITES / NDIR / CRDS / FTIR / DOAS** 七个技术、**六个 MCP server**（每技术独立服务器、独立加载控制上下文）。以 TDLAS 为例，对实验**全链路**做仪器级建模（而非只算一条理论 2f 曲线）：

```
DAQ 三角波+正弦调制 → 激光调谐(含二次非线性) → HITRAN 气体吸收 → 光电探测 → ADC 量化 → 数字锁相 → 1f / 2f / 2f·1f⁻¹
```

<details>
<summary><b>🏗️ 架构（monorepo）</b></summary>

| 模块 | 作用 |
|---|---|
| **spectrolink_core** | 共用内核：HITRAN 线表/缓存/指纹、Voigt、线强外推、同位素叠加、Allan/LOD 基座、器件库 schema；**MCP 协议层（stdio JSON-RPC）、状态文件原子写、会话报告块、交互契约记账与保真度判定也只此一份**（独立依赖包，`pip install -e ./spectrolink_core`） |
| **server-tdlas** | TDLAS-DA / TDLAS-WMS 独立 MCP 服务器（工具 `t_*`） |
| **server-lites** | LITES（光热/石英音叉）独立 MCP 服务器（工具 `lites_*`） |
| **server-ndir** | NDIR（非分散红外）独立 MCP 服务器（工具 `t_ndir_*`） |
| **server-crds** | CRDS（腔衰荡）独立 MCP 服务器（工具 `t_crds_*`） |
| **server-ftir** | FTIR（傅里叶变换红外）独立 MCP 服务器（工具 `t_ftir_*`） |
| **server-doas** | DOAS（差分吸收光谱）独立 MCP 服务器（工具 `t_doas_*`） |

- 共用 = 独立依赖包，**不是代码拷贝**；core 只放物理量级、不放技术特有假设（锁相、QTF 谐振等留在各 server），一处 bug 只修一处。
- **按需启用**：每个技术是独立服务器，配置里启哪个加载哪个，控制上下文占用。
- **不内置仪器**：默认参数仅作演示占位；真实器件参数（datasheet / 实测 / 标定）通过 `tdlas_device` / `lites_device` 用户交互获取。
- 技术适配矩阵见 [docs/ADAPTATION_MATRIX.md](./docs/ADAPTATION_MATRIX.md)。

内置 HITRAN 取数与吸收谱计算（HAPI 1.x，**不需要 API key**），由 AI 助手以自然语言驱动仿真。用途：**系统选型、方法验证、排除错误设计**——不替代实测。

</details>

<details>
<summary><b>🔧 工具列表（7 技术 / 6 server / 45 个工具）</b></summary>

| 工具 | 功能 |
|---|---|
| ⭐ **tdlas_wms_instrument** | **WMS 仪器级仿真首选**：全链路建模，输出标准 3×2 六子图 |
| ⭐ **tdlas_baseline_simulate** | **实测基线仿真**：0 ppm 氮气实测信号当真实 I0（含 RAM、条纹、漂移），叠加理论吸收 |
| tdlas_das_instrument | 仪器级 DAS 仿真（DAQ→激光→光路→PD→ADC） |
| tdlas_simulate | 解析模型正向计算：DAS 透过率、1f、2f 峰高 |
| tdlas_das_chain | 三角波 DAS 链路：PD 原始信号 → 基线拟合 → 吸光度 |
| tdlas_review | 结果自动校验（10 项，不绘图）+ 交互契约与保真度声明 |
| tdlas_invert | 2f/1f 归一化浓度反演（需灵敏度 k 或已知浓度参考，非免标定） |
| ⭐ **tdlas_calibfree** | **免标定**：`shape` / `absolute`（需 I0）/ `anchored`（单点参考）；先 `mode=guide` |
| tdlas_detection_limit | 噪声等效浓度（NEC）与检测限（LOD） |
| tdlas_detection_limit_scan | LOD 随光程 / 参考浓度的二维扫描（选型） |
| tdlas_session | 跨会话工况参数持久化 |
| tdlas_device | 硬件参数库（激光器 / 探测器 / DAQ / 光学） |
| tdlas_guide | AI 交互协议、术语表与保真度台账 |
| tdlas_calibration_curve | 标定曲线：浓度 vs 2f/1f 峰高（线性/非线性拟合） |
| tdlas_allan | Allan 方差：系统稳定性与最优积分时间评估 |
| tdlas_export | 结果导出为 CSV / JSON |
| tdlas_selftest | 全链路自检 |

> 四个仿真工具（及透传的 `tdlas_review`）共用一对可选项：`mixture`（混合气）与 `x_list`（单物种多浓度扫描）。两者**互斥**，且与单 `x` **二选一**。
>
> `x_list` 时**标准 6 子图本身就按浓度叠加**：②~⑤ 面板（PD / αL / 1f / 2f / 归一化 2f）以 viridis 配色叠放各浓度并标 ppm，纵轴按全部浓度统一（低浓度不会被压平）；另有单用途的 `png_overlay` 对照图。
>
> 四个仿真工具另有 `iso`（同位素）开关：**不传=主同位素**（历史口径，与旧版本结果逐位一致）；`iso="all"`=该分子全部 HITRAN 同位素按丰度叠加——CH4 2968 cm⁻¹ 等**密集谱区**邻近同位素线（如 ¹³CH₄，ν₃ 位移 ±1-2 cm⁻¹）贡献不可忽略，`all` 的峰形/峰位更贴近实测；`iso=<整数>`=指定同位素编号（HAPI 口径，CH4: 1=¹²CH₄、2=¹³CH₄、3=¹²CH₃D、4=¹³CH₃D）。窗口内 0 条线的稀有同位素自动跳过并披露 `iso_skipped`。

#### LITES 工具（server-lites）

| 工具 | 功能 |
|---|---|
| lites_forward | 光热正向模型：QTF 谐振 + 热弹机理 → 2f 电压 |
| lites_mdl | 最小可探测浓度（MDL）与噪声预算 |
| lites_device | 器件库（仅内置默认演示器件，真实音叉交互获取） |
| lites_resonance / lites_sweep | 共振跟踪 / 参数扫描 |
| lites_waveform | 合成 2f 波形 + 6 子图（吸收线型 / 机械传递 / 热扩散 / 2f / 扣基线 / 噪声预算） |
| lites_invert | 实测 2f 幅值 → 摩尔分数（含反推自洽性校验） |
| ⭐ **lites_calibfree** | **免标定**：单点已知浓度 + 功率/共振归一化；`mode=guide` 提供数据清单 |
| lites_review | 实验方案评审：LITES 7 类关键风险点逐条检查 |
| lites_compare | 多器件统一口径对比（同线强/浓度/噪声） |
| lites_noise_budget | 噪声预算拆分：1/f / 白噪声 / TIA 各自占比 |
| lites_guide | LITES 交互协议与术语检索（建议作为初始入口） |
| lites_selftest | 物理内核自检（标定自洽 / 标度律 / 饱和 / 失谐） |

#### 新技术工具（server-ndir / server-crds / server-ftir / server-doas）

| 技术 | 工具 | 功能 |
|---|---|---|
| **NDIR** | t_ndir_forward | 双通道 Beer-Lambert 正演（lnR → 解析反演 + 3σ 披露） |
| | t_ndir_calibrate / t_ndir_invert | 浓度标定曲线 / 比值反演 |
| **CRDS** | t_crds_simulate | 腔衰荡仿真（τ₀、ring-down 波形、有效光程；HITRAN 离线降级） |
| | t_crds_ringdown / t_crds_invert | ring-down 拟合 / 浓度反演 |
| **FTIR** | t_ftir_simulate | 干涉图正演（保护带 + 翼区归一 + 切趾 boxcar/hamming/BH + 反演披露） |
| | t_ftir_invert | 恢复谱数组 → 浓度反演 |
| **DOAS** | t_doas_forward | UV-Vis 截面正演（慢变背景多项式分离 + 联合最小二乘） |
| | t_doas_calibrate / t_doas_invert | 标定曲线 / 实测谱反演 |

> NDIR / CRDS / FTIR / DOAS 还各带一个自检工具：`t_ndir_selftest` / `t_crds_selftest` / `t_ftir_selftest` / `t_doas_selftest`，用于改动后一键回归。

</details>

<details>
<summary><b>⚙️ 手动安装与自检</b></summary>

```bash
git clone https://github.com/LKF0402/spectrolink.git
cd spectrolink
pip install -r requirements.txt
pip install -e ./spectrolink_core          # 共用内核

python server-tdlas/tools/tdlas_mcp.py --selftest   # TDLAS 服务器自检（需访问 hitran.org）
python server-tdlas/tools/contract_check.py         # 离线契约自检（CI 硬门禁）
python server-tdlas/tools/tdlas_fidelity.py         # 离线保真度审计（CI 硬门禁）
python server-tdlas/tools/alpha_crossval.py         # α(ν) 独立交叉校验（与 HAPI 互校）
python server-lites/tools/lites_mcp.py --selftest   # LITES 服务器自检
python server-ndir/tools/ndir_mcp.py --selftest     # NDIR 服务器自检（离线）
python server-crds/tools/crds_mcp.py --selftest     # CRDS 服务器自检（HITRAN 失败自动降级）
python server-ftir/tools/ftir_mcp.py --selftest     # FTIR 服务器自检（离线）
python server-doas/tools/doas_mcp.py --selftest     # DOAS 服务器自检（离线）
```

接入 MCP 客户端：把 `mcp.config.example.json` 里的路径改为本机路径即可（手动方式）。

</details>

<details>
<summary><b>⚠️ Skill 不是可选项 · 运行形态（仅本地）</b></summary>

#### ⚠️ Skill 不是可选项

`SKILL.md` 不是文档，而是 **AI 的行为规范**（唯一安装入口）：服务器仅保证 AI 能读取 `next_required_actions`，Skill 才约束 AI 执行后续动作——保留默认值必须显式标注、器件参数来源（`source`）必须如实填写、设备命名须含型号/波长。

**渐进式披露架构**：根 `SKILL.md` 只含技术选择矩阵与自动调度协议（L1）；各技术细节（路由表、默认披露、专属注意事项）在 `server-<技术>/SKILL.md`（L2），由 AI 按任务自动读取——**用户只需安装根 SKILL 一个技能**，无需按技术分别安装。

安装（任选其一）：放置于客户端 Skill 目录；或由 AI 直接读取该文件作为行为规范。

#### 🏃 运行形态：仅本地

本项目**只做本地 MCP**（stdio 传输）：客户端拉起 `python server-<技术>/tools/<技术>_mcp.py`，
用 stdin/stdout 收发 JSON-RPC。不提供 HTTP 端口、公网隧道或 Bearer 鉴权——
那套远程草稿作用有限、维护成本高，已整体移除（见 CHANGELOG 第二十三轮）。

```bash
python server-tdlas/tools/tdlas_mcp.py --selftest   # 本地执行一次自检
```

</details>

<details>
<summary><b>📚 文档</b></summary>

| 文档 | 内容 |
|---|---|
| [TECHNICAL.md](./TECHNICAL.md) | 物理原理、算法实现、参数表、已知近似（含 §8 多技术 server 章节） |
| [docs/VALIDATION.md](./docs/VALIDATION.md) | 可信度分层、校验判据口径、已知局限 |
| [docs/CALIB_FREE.md](./docs/CALIB_FREE.md) | 免标定指南：三类数据、TDLAS/LITES 模式、CSV 列名、检查表 |
| [docs/ADAPTATION_MATRIX.md](./docs/ADAPTATION_MATRIX.md) | 多技术适配矩阵与接入流程 |
| [SKILL.md](./SKILL.md) | AI 交互规范与工具使用协议 |
| [spectrolink_core/README.md](./spectrolink_core/README.md) | 共用物理内核说明 |
| [server-tdlas/tools/tdlas_fidelity.py](./server-tdlas/tools/tdlas_fidelity.py) | 保真度登记表：单一真源 + 离线审计 |
| [CHANGELOG.md](./CHANGELOG.md) | 版本更新记录 |

</details>

## 📝 引用

```
The instrument-level spectral simulations were performed using SpectroLink
(https://github.com/LKF0402/spectrolink, GPLv3; formerly tdlas-mcp).
```

底层数据：HAPI (Kochanov et al., JQSRT 2016, [10.1016/j.jqsrt.2016.03.005](https://doi.org/10.1016/j.jqsrt.2016.03.005)) · HITRAN2024 (Gordon et al., JQSRT 2026, [10.1016/j.jqsrt.2026.109807](https://doi.org/10.1016/j.jqsrt.2026.109807))

## ⚠️ 声明

**学术诚信**：输出为**理论仿真**，仅用于研究参考、方法验证与系统选型。严禁将仿真结果冒充实验测量写入论文或用于产品认证；论文中使用须标注"理论仿真"并按上节致谢。

**版权**：个人独立原创，GPLv3 开源。✅ 个人/学术/教学/二次开发、商业内部研究评估；❌ 闭源出售、去除版权声明后换壳抄袭、把仿真结果当实验数据宣传。衍生作品须同样开源并保留原始版权声明。

**支持作者**：Star、转发或引用，是对个人开发者最直接的支持。

## 📄 许可证

GPLv3 — 详见 [LICENSE](./LICENSE)
