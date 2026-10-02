<div align="center">

<h1>SpectroLink</h1>

<p><b>多技术光谱传感仿真 MCP</b><br>
TDLAS-DA/WMS · LITES · NDIR · CRDS · FTIR · DOAS — 自然语言驱动 · 无需 API key</p>

<img src="https://img.shields.io/badge/Python-3.10%2B-3776AB" alt="Python">
<img src="https://img.shields.io/badge/MCP-stdio%20%7C%20HTTP-6B8FD4" alt="MCP">
<img src="https://img.shields.io/badge/HITRAN-HAPI%201.x-4C8C4A" alt="HITRAN">
<img src="https://github.com/LKF0402/tdlas-mcp/actions/workflows/ci.yml/badge.svg" alt="CI">
<img src="https://img.shields.io/badge/release-v0.2.0-blue" alt="Release">
<img src="https://img.shields.io/badge/license-GPLv3-green" alt="License">

</div>

---

## 📖 概述

基于 MCP（Model Context Protocol）的**多技术光谱传感仿真**，已实现 **TDLAS-DA / TDLAS-WMS / LITES / NDIR / CRDS / FTIR / DOAS** 七个技术 server（每技术独立 MCP 服务器、独立加载控制上下文）。以 TDLAS 为例，对实验**全链路**做仪器级建模（而非只算一条理论 2f 曲线）：

```
DAQ 三角波+正弦调制 → 激光调谐(含二次非线性) → HITRAN 气体吸收 → 光电探测 → ADC 量化 → 数字锁相 → 1f / 2f / 2f·1f⁻¹
```

## 🏗️ 架构（monorepo）

| 模块 | 作用 |
|---|---|
| **spectrolink_core** | 共用物理内核：HITRAN 线表/缓存/指纹、Voigt、线强外推、同位素叠加、Allan/LOD 基座、器件库 schema（独立依赖包，`pip install -e ./spectrolink_core`） |
| **server-tdlas** | TDLAS-DA / TDLAS-WMS 独立 MCP 服务器（工具 `t_*`） |
| **server-lites** | LITES 独立 MCP 服务器（工具 `l_*`） |
| **server-ndir** | NDIR（非分散红外）独立 MCP 服务器（工具 `t_ndir_*`） |
| **server-crds** | CRDS（腔衰荡）独立 MCP 服务器（工具 `t_crds_*`） |
| **server-ftir** | FTIR（傅里叶变换红外）独立 MCP 服务器（工具 `t_ftir_*`） |
| **server-doas** | DOAS（差分吸收光谱）独立 MCP 服务器（工具 `t_doas_*`） |

- 共用 = 独立依赖包，**不是代码拷贝**；core 只放物理量级、不放技术特有假设（锁相、QTF 谐振等留在各 server），一处 bug 只修一处。
- **按需启用**：每个技术是独立服务器，配置里启哪个加载哪个，控制上下文占用。
- **不内置仪器**：默认参数仅作演示占位；真实器件参数（datasheet / 实测 / 标定）通过 `t_device` / `l_device` 用户交互获取。
- 技术适配矩阵见 [docs/ADAPTATION_MATRIX.md](./docs/ADAPTATION_MATRIX.md)。

内置 HITRAN 取数与吸收谱计算（HAPI 1.x，**不需要 API key**），由 AI 助手以自然语言驱动仿真。用途：**系统选型、方法验证、排除错误设计**——不替代实测。

## ✨ 核心特性

- **全链路建模**：DAQ 调制 → 激光调谐 → HITRAN 吸收 → PD → ADC → 数字锁相；可选 etalon 条纹、RIN、1/f 漂移、RAM/AM
- **七技术一体**：TDLAS-DA/WMS · LITES · NDIR · CRDS · FTIR · DOAS，独立 server 按需加载、共用 `spectrolink_core` 物理内核
- **混合气多组分**：`mixture` 严格按 `α = Σ xᵢ·α_pureᵢ(T,P)` 逐点相加（**不用 x·P 当分压**），并返回各组分归因
- **AI 交互契约**：返回值携带 `interaction` 与机器可读的 `next_required_actions`——"必须澄清 / 必须披露"由返回值承载
- **保真度台账**：默认生效 11 项 / 需显式开启 6 项 / **未建模 7 项**，未建模项随结果披露
- **可信度分层**：10 项物理校验与交互合规**分别**计分
- **可复现 + 离线门禁**：`seed=0` 逐位可复现；契约自检 147 项与保真度审计均为 CI 硬门禁（不依赖网络）

其他：`return_xy` 透出锁相 X/Y 用于 RAM/AM 诊断；`tdlas_invert(n_repeats>0)` 给测量不确定度（仅统计分量）；`x_list` 多浓度同图。细节见 [TECHNICAL.md](./TECHNICAL.md) 与 [docs/VALIDATION.md](./docs/VALIDATION.md)。

## 📊 效果展示

![WMS demo](docs/assets/wms-ch4-demo.png)

> CH₄ @ 2968.5 cm⁻¹ 的 3×2 输出：驱动电压 → DAS 吸收 → 1f → 2f → 2f/1f（红色为电压折返剔除区）

![交互工作流](docs/assets/interaction-workflow.png)

> 四泳道流程：启动协议 → 参数与澄清（四级优先级 + 设备库 + 结构化追问）→ 仿真执行 → 校验与交付（10 项校验、α/条纹语境播报、未建模效应披露）

<details>
<summary>技术适配矩阵（扩展性）</summary>

17 种光谱技术在本项目四层架构（取数 / 器件 / 信号 / 反演）上的适配判定：🟩 复用 · 🟧 改造 · 🟥 新增

![技术适配矩阵](docs/assets/technique-matrix.png)

</details>

## 🚀 快速上手

```bash
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

接入 MCP 客户端：把 `mcp.config.example.json` 里的路径改为本机路径即可。

> 💡 **一键配置**：复制下面这段话给你的 AI 助手 ——
> "请帮我配置 SpectroLink 的 TDLAS MCP 服务器，本地路径 `<安装路径>`，Python 解释器 `<python.exe 路径>`，入口文件 `server-tdlas/tools/tdlas_mcp.py`；并把本项目 `SKILL.md` 安装为 Skill。"

## ⚠️ Skill 不是可选项

`SKILL.md` 不是文档，而是 **AI 的行为规范**（唯一安装入口）：服务器只能保证 AI「看到」`next_required_actions`，Skill 才规定 AI「照做」——保留默认值必须显式标注、器件参数来源（`source`）必须如实填写、设备命名须含型号/波长。

**渐进式披露架构**：根 `SKILL.md` 只含技术选择矩阵与自动调度协议（L1）；各技术细节（路由表、默认披露、专属坑点）在 `server-<技术>/SKILL.md`（L2），由 AI 按任务自动读取——**用户只需安装根 SKILL 一个技能**，无需按技术分别安装。

安装（任选其一）：放进客户端的 Skill 目录；或让 AI 直接读取该文件作为行为规范。

## 🔧 工具列表

| 工具 | 功能 |
|---|---|
| ⭐ **tdlas_wms_instrument** | **WMS 仪器级仿真首选**：全链路建模，输出标准 3×2 六子图 |
| tdlas_das_instrument | 仪器级 DAS 仿真（DAQ→激光→光路→PD→ADC） |
| tdlas_simulate | 解析模型正向计算：DAS 透过率、1f、2f 峰高 |
| tdlas_das_chain | 三角波 DAS 链路：PD 原始信号 → 基线拟合 → 吸光度 |
| tdlas_review | 结果自动校验（10 项，不绘图）+ 交互契约与保真度声明 |
| tdlas_invert | 免标定浓度反演（2f/1f → 摩尔分数）；`n_repeats>0` 给出不确定度 |
| tdlas_detection_limit | 噪声等效浓度（NEC）与检测限（LOD） |
| tdlas_detection_limit_scan | LOD 随光程 / 参考浓度的二维扫描（选型） |
| tdlas_session | 跨会话工况参数持久化 |
| tdlas_device | 硬件参数库（激光器 / 探测器 / DAQ / 光学） |
| tdlas_guide | AI 交互协议、术语表与保真度台账 |
| tdlas_selftest | 全链路自检 |

> 四个仿真工具（及透传的 `tdlas_review`）共用一对可选项：`mixture`（混合气）与 `x_list`（单物种多浓度扫描）。两者**互斥**，且与单 `x` **二选一**。
>
> `x_list` 时**标准 6 子图本身就按浓度叠加**：②~⑤ 面板（PD / αL / 1f / 2f / 归一化 2f）以 viridis 配色叠放各浓度并标 ppm，纵轴按全部浓度统一（低浓度不会被压平）；另有单用途的 `png_overlay` 对照图。
>
> 四个仿真工具另有 `iso`（同位素）开关：**不传=主同位素**（历史口径，与旧版本结果逐位一致）；`iso="all"`=该分子全部 HITRAN 同位素按丰度叠加——CH4 2968 cm⁻¹ 等**密集谱区**邻近同位素线（如 ¹³CH₄，ν₃ 位移 ±1-2 cm⁻¹）贡献不可忽略，`all` 的峰形/峰位更贴近实测；`iso=<整数>`=指定同位素编号（HAPI 口径，CH4: 1=¹²CH₄、2=¹³CH₄、3=¹²CH₃D、4=¹³CH₃D）。窗口内 0 条线的稀有同位素自动跳过并披露 `iso_skipped`。

### LITES 工具（server-lites）

| 工具 | 功能 |
|---|---|
| lites_forward | 光热正向模型：QTF 谐振 + 热弹机理 → 2f 电压 |
| lites_mdl | 最小可探测浓度（MDL）与噪声预算 |
| lites_device | 器件库（仅内置默认演示器件，真实音叉交互获取） |
| lites_resonance / lites_sweep | 共振跟踪 / 参数扫描 |
| lites_selftest | 物理内核自检（标定自洽 / 标度律 / 饱和 / 失谐） |

### 新技术工具（server-ndir / server-crds / server-ftir / server-doas）

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

## 🌐 远程部署

```bash
python server-tdlas/tools/tdlas_mcp.py --http --host 0.0.0.0 --port 8000 --token <鉴权密钥>
python server-tdlas/tools/remote_link.py   # 公网隧道（cloudflared）
# 其余技术：ndir=8005 / crds=8002 / ftir=8003 / doas=8004（各 tools/<tech>_mcp.py --http 同参）
```

## 📚 文档

| 文档 | 内容 |
|---|---|
| [TECHNICAL.md](./TECHNICAL.md) | 物理原理、算法实现、参数表、已知近似（含 §8 多技术 server 章节） |
| [docs/VALIDATION.md](./docs/VALIDATION.md) | 可信度分层、校验判据口径、已知局限 |
| [docs/ADAPTATION_MATRIX.md](./docs/ADAPTATION_MATRIX.md) | 多技术适配矩阵与接入流程 |
| [SKILL.md](./SKILL.md) | AI 交互规范与工具使用协议 |
| [spectrolink_core/README.md](./spectrolink_core/README.md) | 共用物理内核说明 |
| [server-tdlas/tools/tdlas_fidelity.py](./server-tdlas/tools/tdlas_fidelity.py) | 保真度登记表：单一真源 + 离线审计 |
| [CHANGELOG.md](./CHANGELOG.md) | 版本更新记录 |

## 📝 引用

```
The instrument-level spectral simulations were performed using SpectroLink
(formerly tdlas-mcp, https://github.com/LKF0402/tdlas-mcp, GPLv3).
```

底层数据：HAPI (Kochanov et al., JQSRT 2016, [10.1016/j.jqsrt.2016.03.005](https://doi.org/10.1016/j.jqsrt.2016.03.005)) · HITRAN2024 (Gordon et al., JQSRT 2026, [10.1016/j.jqsrt.2026.109807](https://doi.org/10.1016/j.jqsrt.2026.109807))

## ⚠️ 声明

**学术诚信**：输出为**理论仿真**，仅用于研究参考、方法验证与系统选型。严禁将仿真结果冒充实验测量写入论文或用于产品认证；论文中使用须标注"理论仿真"并按上节致谢。

**版权**：个人独立原创，GPLv3 开源。✅ 个人/学术/教学/二次开发、商业内部研究评估；❌ 闭源出售、去除版权声明后换壳抄袭、把仿真结果当实验数据宣传。衍生作品须同样开源并保留原始版权声明。

**支持作者**：Star、转发或引用，是对个人开发者最直接的支持。

## 📄 许可证

GPLv3 — 详见 [LICENSE](./LICENSE)
