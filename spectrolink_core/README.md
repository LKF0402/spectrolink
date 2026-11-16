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
| `calibfree` | 免标定共用内核：`tdlas_shape` / `tdlas_das` / `anchored_ratio` / `lites_anchored`；CSV/NPZ 数据契约与 `GUIDE` |
| `interaction` / `interaction_server` | 动作证据解析、指纹、按需下发；四技术 DISPATCH 统一包装 |
| `validation` | 轻量 `checks[]` 与 `overall` 归并（CRDS/NDIR/FTIR/DOAS 共用） |

## 接口约定

- 纯组分吸收：`hitran.absorption(name, numin, numax, T=296.0, P=1.01325, step=5e-4, wingHW=20.0, iso=None, hitran_units=False) → (nu, alpha, info)`
- 混合气：`hitran.absorption_mixture(gases, numin, numax, T, P, step, wingHW, wn_grid=None) → (nu, alpha_total, per_gas)`，按 `α = Σ xᵢ·αᵢ` 逐点相加，**不用 x·P 当分压**
- 抓取窗外扩量：`hitran.fetch_margin(wingHW=20.0, P=1.01325)` → cm⁻¹（覆盖 ΩWingHW·Γ 的实际翼宽，下限 1.5 cm⁻¹）
- 锁相：`lockin.harmonic_demod_time(S, t, fs, fm, n, ...)` / `lockin.phase_rotate(X, Y, center_idx=None)`
- 免标定：`calibfree.tdlas_shape(x2f, y2f, x2f_bg, y2f_bg, species=..., wn_center_cm1=..., L_cm=...)`（`x=null`）；`calibfree.tdlas_das(i, i0, ...)`；`calibfree.anchored_ratio(...)`；`calibfree.lites_anchored(...)`

> **抓取窗 ≠ 计算窗**：线表按 `[numin - margin, numax + margin]` 抓取，输出网格仍严格等于 `[numin, numax]`。
> 外扩后窗缘偏差压到 0.01% 以内（CH₄ 2968 cm⁻¹ 实测），峰值保持一致。

## 缓存

HITRAN 线表缓存优先级：

1. 环境变量 `SPECTROLINK_DATA_DIR`
2. 用户目录 `~/.spectrolink/Hitran_Data`（默认）
3. 仓库内 `Hitran_Data/`

在线失败自动降级并披露；`table_fingerprint` 给出线表指纹用于 provenance 溯源。

## 铁律

- **不内置仪器**：默认参数仅演示占位，真实器件参数经用户交互（datasheet / 实测 / 标定）获取。
- **不文献锚定**：core 不写死任何"来自某文献"的器件/工况值。
