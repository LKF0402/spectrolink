---
name: spectrolink
description: SpectroLink —— 多技术光谱传感仿真 MCP 总入口。触发词：TDLAS、WMS、波长调制、直接吸收、DAS、二次谐波、2f/1f、数字锁相、谐波检测、浓度反演、检测限、LOD、调制系数 m、LITES、光致热弹、石英音叉、QTF、CRDS、腔衰荡、ring-down、NDIR、非分散红外、FTIR、傅里叶变换红外、DOAS、差分吸收、紫外可见宽带光谱。用户要求光谱仿真、气体浓度仿真、检测限计算时必须使用本 Skill。
---

# SpectroLink：多技术光谱传感仿真 MCP（L1 总入口）

## 0. 使用铁律（全局，不可违背）

1. **不内置仪器**：所有技术默认参数仅作演示占位（已在各工具 description 标注），真实器件/工况参数一律经交互获取，来源标记 `datasheet / user / ai / calibration / unspecified`，禁止把推断值标成 datasheet。
2. **输出为理论仿真**，严禁冒充实验数据；写论文数值须附 `provenance.engine_version` 与 `line_table.sha256_16`。
3. **AI 出图必须自查**：每次交付图片前先 Read 检查（坐标轴、峰值可见性、字体、剔除区），发现问题先修再交付。

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
2. **按需自动 Read** `<server>/SKILL.md`：任务需要调该技术工具、给定量结论、出图或披露参数时，必须先 Read 其 L2（含路由表、默认披露、坑点）。未 Read 前不得调该技术工具。
3. 按 L2 工具路由表调用；处理返回的 `validation` / `next_required_actions`。

**披露深度分级（自动选择，够用即止）**：
| 深度 | 何时 | 披露内容 |
|---|---|---|
| L1 浅 | 仅技术选型/方案对比/问答 | 决策矩阵一行 + 技术定位 |
| L2 中 | 调用工具/给定量结果 | Read 目标 server SKILL.md，披露该技术路由+坑点 |
| L3 深 | 出图/论文数值/疑难排查 | 在 L2 基础上展开参数表、绘图规范、provenance |

**切换技术**：任务中途改技术时，重新执行调度流程（读新 server 的 L2），旧技术 L2 可弃。

## 3. 通用硬约束（各技术子 SKILL 继承）

- **交互契约**：`validation.overall=fail` 不得下结论先修；`warn` 须在回答披露。
- **参数优先级**：① 用户实测 → ② 器件型号 datasheet（联网核验）→ ③ 标定 → ④ 默认值+显式标注。`clarify.needed=true` 必须先问再出图。
- **出图**：用户说"画图"必须传 `save_png=true`；纵轴只按有效数据区定；图面注明技术名、关键参数与"理论仿真"。
- **自检**：每个 server 提供 `*_selftest`；改代码后全量回归。

## 4. 物理内核与数据

- 共用 `spectrolink_core`（HITRAN 线表/吸收谱），本地缓存 `Hitran_Data/`；首次下载慢，已缓存后快。
- 横轴口径：TDLAS/CRDS/FTIR 用**波数 cm⁻¹**；DOAS 用**波长 nm**（勿混）。

## 5. 部署（stdio 默认；HTTP 端口表）

| server | 端口 |
|---|---|
| tdlas | 8000 |
| lites | 8001 |
| ndir | 8005 |
| crds | 8002 |
| ftir | 8003 |
| doas | 8004 |

远程 HTTP 均强制 Bearer token；公网隧道用各 server `tools/remote_link.py`。

## 6. 子 SKILL 索引

- `server-tdlas/SKILL.md` — TDLAS-DA/WMS（六子图、设备库、物理坑点）
- `server-lites/SKILL.md` — LITES（QTF、τ_acc、η_dev）
- `server-crds/SKILL.md` — CRDS（τ(ν)、ring-down、动态范围）
- `server-ndir/SKILL.md` — NDIR（双通道比值、标定）
- `server-ftir/SKILL.md` — FTIR（干涉图、切趾、分辨率）
- `server-doas/SKILL.md` — DOAS（差分吸收、多项式背景）

> 仓库：https://github.com/LKF0402/spectrolink
