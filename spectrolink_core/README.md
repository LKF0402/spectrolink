# spectrolink_core — SpectroLink 共用物理内核

SpectroLink 多技术 MCP（monorepo）的**共享依赖包**，分发名 `spectrolink-core`：

```bash
pip install -e ./spectrolink_core
```

## 分层原则

core 只放**物理量级**的纯函数（无任何技术假设）；技术口径（锁相 2f/1f、QTF 谐振、腔衰荡拟合、
干涉图切趾等）一律留在各技术 server。一处 bug 只修一处，跨技术复用不复制代码。

## 模块

| 模块 | 内容 |
|------|------|
| `hitran` | HITRAN 线表获取 / 本地缓存 / 指纹、Voigt 谱形、线强外推、同位素叠加、离线降级；抓取窗自动外扩（`fetch_margin`） |
| `lockin` | 数字锁相基座：`harmonic_demod_time`（多级低通 + 谐波解调）、`phase_rotate`（正交相位校正） |
| `stats` | Allan / LOD 基座等统计工具 |
| `devices` | 器件库字段规则 `DEVICE_FIELD_RULES`：只约束类型/量纲，**零默认仪器** |

## 接口约定

- 纯组分吸收：`hitran.absorption(name, numin, numax, T=296.0, P=1.01325, step=5e-4, wingHW=20.0, iso=None, hitran_units=False) → (nu, alpha, info)`
- 混合气：`hitran.absorption_mixture(gases, numin, numax, T, P, step, wingHW, wn_grid=None) → (nu, alpha_total, per_gas)`，按 `α = Σ xᵢ·αᵢ` 逐点相加，**不用 x·P 当分压**
- 抓取窗外扩量：`hitran.fetch_margin(wingHW=20.0, P=1.01325)` → cm⁻¹（覆盖 ΩWingHW·Γ 的实际翼宽，下限 1.5 cm⁻¹）
- 锁相：`lockin.harmonic_demod_time(S, t, fs, fm, n, ...)` / `lockin.phase_rotate(X, Y, center_idx=None)`

> **抓取窗 ≠ 计算窗**：线表按 `[numin - margin, numax + margin]` 抓取，输出网格仍严格等于 `[numin, numax]`。
> 只抓窗内线会让窗外谱线的翼部被静默丢弃（CH₄ 2968 cm⁻¹ 窗左缘曾偏低 −2.74%）。

## 缓存

HITRAN 线表缓存优先级：

1. 环境变量 `SPECTROLINK_DATA_DIR`
2. 用户目录 `~/.spectrolink/Hitran_Data`（默认）
3. 仓库内 `Hitran_Data/`

在线失败自动降级并披露；`table_fingerprint` 给出线表指纹用于 provenance 溯源。

## 铁律

- **不内置仪器**：默认参数仅演示占位，真实器件参数经用户交互（datasheet / 实测 / 标定）获取。
- **不文献锚定**：core 不写死任何"来自某文献"的器件/工况值。
