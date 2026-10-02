# server-lites — LITES 光谱仿真 MCP 服务器

> **SpectroLink 子服务器**（monorepo `tdlas-mcp`，物理内核复用 `spectrolink_core`）。
> 独立加载、按需启用；完整项目说明见仓库根 [README.md](../README.md) 与 [SKILL.md](../SKILL.md)。

**LITES（Light-Induced Thermoelastic Spectroscopy，光致热弹光谱）** 器件级仿真：对从光束到锁相输出的完整仪器链路逐级建模。

```
激光功率(含调制) → 器件吸收+气体吸收 → 热沉积 → 热扩散低通 → 温升
    → 热弹应变 → 机械共振放大(Q, f0) → 压电电荷 → TIA → 锁相 2f → 浓度反演
```

## 工具（`l_*`）

| 工具 | 功能 |
|------|------|
| `lites_forward` | 正向仿真：给定器件+工况 → 2f 电压、SBR、各环节传递量 |
| `lites_mdl` | 最小可探测浓度 MDL 与噪声预算 |
| `lites_device` | 器件库（**仅内置演示默认 qtf-commercial-decapped，真实音叉交互获取**） |
| `lites_resonance` / `lites_sweep` | 共振跟踪 / 参数扫描 |
| `lites_waveform` / `lites_invert` | 波形出图（六子图：DC 包络 / 载波 / **R₂f 幅值** / 多浓度对比 / 标定 / **Allan 方差**，τ 全整数网格 1 s 精度）/ 浓度反演 |
| `lites_noise_budget` / `lites_review` / `lites_guide` | 噪声预算 / 结果校验 / AI 交互协议 |
| `lites_selftest` | 全链路自检 |

> 所有工具返回值自动携带 `assumptions` / `next_required_actions` / `disclosure_pending` 契约字段。

## 铁律

- **不内置仪器**：默认器件（商用 32.768 kHz 去壳裸音叉）仅作**演示占位**，f0/Q 为数量级参考、**不是文献锚定结论**；真实器件参数（datasheet / 实测 / 标定）一律经 `lites_device` 用户交互获取。
- **LITES ≠ TDLAS**（关键差异，勿用 TDLAS 直觉解读本服务器输出）：

| 议题 | TDLAS 直觉 | LITES 实际 |
|------|-----------|-----------|
| 信号来源 | 气体吸收 α·L 越强信号越强 | **减光口径**：气体挖光（A≈αL），残余光被 η_dev 吸收 → 信号 ∝ η_dev·αL |
| 标定轴 | 追求高 f（抑制 1/f） | 追求长能量积累时间 τ_acc = Q/(π·f0)：**低 f0、高 Q** |
| 2f 最优频率 | 取 f0/2 | 热波口径 |H_th|=√(f_ref/f)、f_ref=f0/2 ⇒ 最优 f_m≈f0/2 |
| 多反射池 | 增加光程 → 信号增强 | 每次反射损失功率 → 信号下降 |

## 验证

```bash
python tools/lites_mcp.py --selftest    # 离线确定性自检（标定自洽 / 标度律 / 饱和 / 失谐）
python tools/lites_fidelity.py          # 离线保真度审计（能力台账 ↔ 源码证据）
python tools/_rpc_test.py               # 端到端 JSON-RPC 回归（13 正向 + 4 负向）
```

## 文档

| 文档 | 内容 |
|------|------|
| [TECHNICAL.md](./TECHNICAL.md) | LITES 物理原理、传递链推导、参数表、已知近似（并入前独立仓库完整版） |
| [docs/VALIDATION.md](./docs/VALIDATION.md) | 可信度分层、校验判据口径、已知局限 |
| [CHANGELOG.md](./CHANGELOG.md) | 更新历史 |

## 引用

SpectroLink（formerly tdlas-mcp，https://github.com/LKF0402/tdlas-mcp，GPLv3）的 LITES 子服务器。
底层数据：HAPI (Kochanov et al., JQSRT 2016, 10.1016/j.jqsrt.2016.03.005) · HITRAN2024 (Gordon et al., JQSRT 2026, 10.1016/j.jqsrt.2026.109807)。

> ⚠️ 输出为**理论仿真**，仅用于研究参考、方法验证与系统选型，严禁冒充实验数据。
