# spectrolink_core — SpectroLink 共用物理内核

SpectroLink 多技术 MCP（monorepo）的**共享依赖包**（`pip install -e ./spectrolink_core`）。

## 分层原则

core 只放**物理量级**的纯函数（无任何技术假设）；技术口径（锁相 2f/1f、QTF 谐振、腔衰荡拟合、
干涉图切趾等）一律留在各技术 server。一处 bug 只修一处，跨技术复用不复制代码。

## 模块

| 模块 | 内容 |
|------|------|
| `hitran` | HITRAN 线表获取 / 本地缓存 / 指纹、Voigt 谱形、线强外推、同位素叠加、离线降级 |
| `stats` | Allan / LOD 基座等统计工具 |
| `devices` | **器件库 schema 占位**：只定义跨技术器件字段的类型/量纲约束，**零默认仪器**（铁律） |

## 接口约定

- 吸收系数：`hitran.absorption(name, numin, numax, T, P, step, wingHW, iso) → (nu, alpha, info)`
  返回纯气体吸收系数（混合气由调用方按 `α = Σ xᵢ·αᵢ` 叠加）。
- 缓存：HITRAN 数据落仓库根 `Hitran_Data/`，跨会话复用；在线失败自动降级并披露。

## 铁律

- **不内置仪器**：默认参数仅演示占位，真实器件参数经用户交互（datasheet / 实测 / 标定）获取。
- **不文献锚定**：core 不写死任何"来自某文献"的器件/工况值。
