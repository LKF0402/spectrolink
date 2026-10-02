# SpectroLink 技术适配矩阵

> 多技术光谱传感仿真 MCP 的统一架构视图。
> **铁律：不内置仪器、不文献锚定、默认参数仅作演示占位；真实器件参数一律通过用户交互获取（datasheet / 实测 / 标定）。**

## 架构

```
SpectroLink (monorepo)
├── spectrolink_core/      # 共用物理内核（纯函数，无技术假设）
├── server-tdlas/          # TDLAS-DA / TDLAS-WMS 独立 MCP 服务器
├── server-lites/          # LITES 独立 MCP 服务器
├── server-ndir/           # NDIR 独立 MCP 服务器
├── server-crds/           # CRDS 独立 MCP 服务器
├── server-ftir/           # FTIR 独立 MCP 服务器
└── server-doas/           # DOAS 独立 MCP 服务器
```

- **共用 = 独立依赖包**（`pip install -e ./spectrolink_core`），不是代码拷贝；core 里一处 bug 只修一处。
- **防串原则**：core 只放物理量级（HITRAN / Voigt / Allan / LOD / 器件库 schema），不放任何技术特有假设（锁相、QTF 谐振、腔衰荡等留在各 server）。
- **按需启用**：每个技术是独立 MCP 服务器，配置里启哪个加载哪个，控制上下文占用。

## 适配矩阵

| 技术 | 状态 | core 复用 | 技术独有物理模块 | MCP 工具面 | 默认参数策略 |
|---|---|---|---|---|---|
| **TDLAS-DA**（直接吸收） | ✅ 已实现 | hitran / stats | L-I 曲线、基线拟合、吸光度 αL | `t_das_*` | 默认参数+标注；仪器经 `t_device` 交互获取 |
| **TDLAS-WMS**（波长调制） | ✅ 已实现 | hitran / stats | 数字锁相、1f/2f/2f·1f⁻¹、调制系数 m、RAM | `t_wms_*` | 同上 |
| **LITES**（光热光谱） | ✅ 已实现 | hitran / stats | QTF 谐振（f0/Q）、热弹机理、τ_acc、MDL | `l_*` | 单默认器件（商用去壳音叉）仅作演示；真实音叉参数交互获取 |
| **NDIR**（非分散红外） | ✅ 已实现 | —（宽带源，无 HITRAN 线表需求） | 宽带光源、滤光片带通、双通道检测、朗伯-比尔 | `t_ndir_forward / calibrate / invert / selftest` | 全部参数交互获取，无默认仪器 |
| **CRDS**（腔衰荡） | ✅ 已实现 | hitran（线强/展宽复用）+ 离线降级 | 腔衰荡时间 τ(ν)、镜面反射率 R、ring-down 拟合、有效光程 | `t_crds_simulate / ringdown / invert / selftest` | 同上 |
| **FTIR**（傅里叶变换红外） | ✅ 已实现 | — | 干涉图、余弦变换、分辨率/切趾函数（boxcar/hamming/blackman_harris）、翼区基线归一、窗旁瓣验证 | `t_ftir_simulate / invert / selftest` | 同上 |
| **DOAS**（差分吸收光谱） | ✅ 已实现 | —（紫外-可见吸收截面） | 差分吸收、慢变背景多项式分离、参考谱联合最小二乘 | `t_doas_forward / calibrate / invert / selftest` | 同上 |

## core 边界（什么进 core，什么不进）

**进 core（物理量级，跨技术通用）**：
- HITRAN 线表获取 / 缓存 / 指纹（`hitran.py`）
- Voigt / 线强温度外推 / 同位素叠加（`hitran.py`）
- Allan 方差 / LOD 基座（`stats.py`）
- 器件库 schema 占位（`devices.py`，**只定义结构，不内置默认仪器**）

**留在各 server（技术特有）**：
- 数字锁相 / 谐波解调（TDLAS-WMS）
- QTF 谐振 / 热弹机理 / 能量积累（LITES）
- 双通道差分检测（NDIR）、腔衰荡拟合（CRDS）、干涉图处理（FTIR）、差分吸收反演（DOAS）等

## 已实现 server 的验证状态（2026-10-02）

| server | 物理自检 | MCP 协议冒烟 | 端口 |
|---|---|---|---|
| server-tdlas | ✅ 契约自检 147 项 + 保真度审计 | ✅ | 8000 |
| server-lites | ✅ 17 项模块自检 | ✅ | 8001(lites) |
| server-ndir | ✅ 5 锚点（forward/calibrate/invert 自洽） | ✅ initialize/list/call/-32601 | 8005 |
| server-crds | ✅ 5 锚点（τ₀=3.335µs@R=0.999/1m、拟合 R²=0.99997） | ✅ | 8002 |
| server-ftir | ✅ 5 锚点（往返误差 0.2%、分辨率缩放 1.75、窗旁瓣 boxcar -13.5/hamming -52.5/BH -93 dB、反演误差 0.05%） | ✅ | 8003 |
| server-doas | ✅ 5 锚点（无噪反演精确、多项式稳健、噪声统计判据、标定 slope=1.0/R²=1.0） | ✅ | 8004 |

## 接入新技术的流程

1. 新建 `server-<tech>/`，复制 `server-tdlas/` 的骨架（MCP 入口 + tools/ + 自检）。
2. 判定哪些物理量级可复用 core：能复用则 `from spectrolink_core import hitran, stats`；技术特有部分写在 server 内。
3. 工具命名 `t_<tech>_*`，与其它技术不冲突。
4. 本矩阵补一行，标注 core 复用项与独有模块。
5. 自检（`selftest`）必须覆盖：数值锚点、边界、披露契约。
