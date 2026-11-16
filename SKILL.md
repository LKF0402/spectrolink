---
name: spectrolink
description: SpectroLink —— 多技术光谱传感仿真 MCP 总入口。触发词：TDLAS、WMS、波长调制、直接吸收、DAS、二次谐波、2f/1f、数字锁相、谐波检测、浓度反演、检测限、LOD、调制系数 m、LITES、光致热弹、石英音叉、QTF、CRDS、腔衰荡、ring-down、NDIR、非分散红外、FTIR、傅里叶变换红外、DOAS、差分吸收、紫外可见宽带光谱。用户要求光谱仿真、气体浓度仿真、检测限计算时必须使用本 Skill。
---

# SpectroLink：多技术光谱传感仿真 MCP（L1 总入口）

## 0. 使用铁律（全局，不可违背）

1. **不内置仪器**：所有技术默认参数仅作演示占位（已在各工具 description 标注），真实器件/工况参数一律经交互获取，来源标记 `datasheet / user / ai / calibration / unspecified`，禁止把推断值标成 datasheet。
2. **输出为理论仿真**，严禁冒充实验数据；写论文数值须附 `provenance.engine_version` 与 `line_table.sha256_16`。
3. **AI 绘图必须自查**：每次交付图片前先 Read 检查（坐标轴、峰值可见性、字体、剔除区），发现问题先修正再交付。

## 1. 技术选择决策矩阵（先选技术 → 再读该技术子 SKILL）

| 任务特征 | 技术 | server 目录 | 工具前缀 |
|---|---|---|---|
| 波长调制/锁相谐波/中红外吸收/快速在线浓度 | TDLAS-DA / WMS | `server-tdlas` | `tdlas_*` |
| 石英音叉/热弹压电探测/2f/MDL | LITES | `server-lites` | `lites_*` |
| 腔衰荡时间测量/超高反射镜/痕量高精度 | CRDS | `server-crds` | `t_crds_*` |
| 宽带光源+滤光双通道/工业 CO2·CH4 | NDIR | `server-ndir` | `t_ndir_*` |
| 宽谱干涉图/多组分同时/离线分析 | FTIR | `server-ftir` | `t_ftir_*` |
| 紫外-可见宽带差分吸收/开放光路 NO2·SO2 | DOAS | `server-doas` | `t_doas_*` |

## 2. 渐进式披露 · 自动调度协议（强制执行）

**本 SKILL 是用户唯一需要安装的入口**；各 `server-*/SKILL.md` 是 AI 自动读取的参考文件，**不是独立安装项**。AI 按任务自动鉴定披露深度：

**调度流程（每次任务自动执行）**：
1. 用 §1 决策矩阵选技术 → 定位 server。
2. **按需自动 Read** `<server>/SKILL.md`：任务需要调用该技术工具、输出定量结论、绘图或披露参数时，必须先 Read 其 L2（含路由表、默认披露、注意事项）。未 Read 前不得调用该技术工具。
3. 按 L2 工具路由表调用；处理返回的 `validation` / `next_required_actions`。

同一会话内已 Read 且文件未改动时复用该 L2，不重复读取；参数仍以工具 schema 为准。

**披露深度分级（自动选择，够用即止）**：
| 深度 | 何时 | 披露内容 |
|---|---|---|
| L1 浅 | 仅技术选型/方案对比/问答 | 决策矩阵一行 + 技术定位 |
| L2 中 | 调用工具/输出定量结果 | Read 目标 server SKILL.md，披露该技术路由与注意事项 |
| L3 深 | 绘图/论文数值/疑难排查 | 在 L2 基础上展开参数表、绘图规范、provenance |

**切换技术**：任务中途改技术时，重新执行调度流程（读新 server 的 L2），旧技术 L2 可弃。

## 3. 通用硬约束（各技术子 SKILL 继承）

- **交互契约**：`validation.overall=fail` 不得下结论先修；`warn` 须在回答披露。
- **参数优先级**：① 用户实测 → ② 器件型号 datasheet（联网核验）→ ③ 标定 → ④ 默认值+显式标注。`clarify.needed=true` 时必须先询问再绘图。
- **绘图**：用户要求绘图时必须传 `save_png=true`；纵轴只按有效数据区确定；图面注明技术名、关键参数与“理论仿真”。
- **自检**：每个 server 提供 `*_selftest`；改代码后按 §3.2 分级回归，不做无差别全量。

## 3.1 免标定（仅 TDLAS / LITES，v1.1.0）

- **TDLAS**：`tdlas_calibfree` 三种模式——`shape`（波形一致性，`x=null`）、`absolute`（需 I0 透射）、`anchored`（单点已知浓度）。浓度走 `absolute` / `anchored`。
- **LITES**：`lites_calibfree` 仅实现 `anchored`（单点参考 + 功率监测 + 共振归一化）。单点锚定后，同器件、同波长可跨浓度输出结果。
- **最小数据清单**：零基线（0% 气/暗）+ 绝对锚点（I0/参考浓度）+ 仪器状态（L/T/P/调制/锁相/采样）；详见 `docs/CALIB_FREE.md`。

## 3.2 执行节奏与验证分级（控制无效返工）

| 改动范围 | 最小验证 | 本次不跑 |
|---|---|---|
| 文档/文案，未动 schema | 不跑代码门禁 | selftest / RPC |
| 单工具函数 | `py_compile` + 1 正例 + 1 边界 | 全量契约 / 其他技术 |
| schema / 协议 / DISPATCH | `contract_check.py` + 对应 `_rpc_test.py` | 其他技术 selftest |
| HITRAN / 缓存 / 物理内核 | 对应 server `--selftest` + 1 组前后基准 | 六技术全量 |
| 发布前 | 全量契约 + 两套 RPC + 受影响 selftest | — |

统一入口：`python verify_changed.py` 按改动文件自动选检查；发布前用 `--full`。

- 同一会话已 Read 且文件未改动，不重复 Read L2 或 schema。
- 一次 profiling、一次修改、一次验证；同一基准不重复跑。
- 信息足够即交付；阻塞问题一次问清，不跨轮反复试探。
- 时间盒：单点修复 10 min，协议/内核 30 min；超时先报阻塞点与已完成部分，不扩大范围。

## 4. 物理内核与数据

- 共用 `spectrolink_core`（HITRAN 线表/吸收谱 + 数字锁相基座 `lockin`），本地缓存 `Hitran_Data/`；首次下载耗时较长，缓存后效率较高。
- 抓取窗比计算窗外扩（`fetch_margin`）：线表按窗边多抓 ΩWingHW·Γ 的翼宽，否则窗外线翼被静默丢弃（窗缘可低 2% 量级）。
- 缓存目录优先级：环境变量 `SPECTROLINK_DATA_DIR`（可用系统路径分隔符给多个目录）> `~/.spectrolink/Hitran_Data` > 仓库内。HAPI 1.x 只激活一个写入目录；其余目录中已存在的线表会在首次命中时按需复制过来，避免“本地有表却联网重抓”。
- 多气体混合：`spectrolink_core.hitran.absorption_mixture()` 自动插值到统一波数网格。
- 横轴口径：TDLAS/CRDS/FTIR 用**波数 cm⁻¹**；DOAS 用**波长 nm**（勿混）。

## 5. 部署（仅本地 stdio）

六个 server 都用 stdio：客户端配置 `command = 本机 python`、`args = [server-<技术>/tools/<技术>_mcp.py]` 即可。
**不提供 HTTP 端口 / 公网隧道 / Bearer 鉴权**——远程形态已整体移除（见 CHANGELOG 第二十三轮）。

自检：`python server-tdlas/tools/tdlas_mcp.py --selftest`（其余技术同名 `--selftest`）。

## 6. 子 SKILL 索引

- `server-tdlas/SKILL.md` — TDLAS-DA/WMS（六子图、设备库、物理约束与注意事项）
- `server-lites/SKILL.md` — LITES（QTF、τ_acc、η_dev）
- `server-crds/SKILL.md` — CRDS（τ(ν)、ring-down、动态范围）
- `server-ndir/SKILL.md` — NDIR（双通道比值、标定）
- `server-ftir/SKILL.md` — FTIR（干涉图、切趾、分辨率）
- `server-doas/SKILL.md` — DOAS（差分吸收、多项式背景）

> 仓库：https://github.com/LKF0402/spectrolink
