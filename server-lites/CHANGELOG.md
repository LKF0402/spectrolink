# Changelog

本文件以最简形式记录 LITES 服务器的功能演进。

## [v0.1.0] — LITES 专用服务器
- 物理内核迁移：lites_physics（器件模型 + 唯一机理链），自检 35 项全过
- 标定锚点口径修正（cal_eta_abs）、增益口径修正（τ_acc=Q/πf₀）
- 12 工具仪器口径层；行为扰动审计抓出 4 个真实缺陷
- JSON Schema 生成器（幂等）；MCP 契约注入集中化
- 五层验证全绿（物理 / 口径 / selftest / 保真度 / RPC）

## 第七轮：默认器件改为去壳商用音叉晶振
- 新增默认器件 qtf-commercial-decapped（f₀=32757.4 Hz、Q=8630）
- 默认器件单源引用，消除硬编码漂移
- 抓出跨器件电压不可比（私有标定增益），lites_compare 语义修正
- NaN 泄漏修复（非法 JSON）+ RPC NaN 守卫
- 保真度台账缺口补齐；文档同步

## [上游] tdlas-mcp 的历史演进
上游演进见主仓库 CHANGELOG。
