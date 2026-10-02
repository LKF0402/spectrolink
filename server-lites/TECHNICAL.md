# SpectroLink · server-lites 技术文档

> 面向专业技术员：说明本 server 的**物理模型、逐级传递链、关键算法、默认参数、已知近似与实现陷阱**。
> 本 server 是 SpectroLink monorepo（https://github.com/LKF0402/tdlas-mcp，GPLv3）的子服务器，
> 物理内核复用 `spectrolink_core`；配套文档：`README.md`（功能与快速开始）、`SKILL.md`（AI 使用规范）、`CHANGELOG.md`（变更记录）。

## 目录

- [1. 架构概述](#1-架构概述)
- [2. 与 TDLAS 的分野（必读）](#2-与-tdlas-的分野必读)
- [3. 物理模型](#3-物理模型)
- [4. 传递链逐级实现](#4-传递链逐级实现)
- [5. 标定与反解](#5-标定与反解)
- [6. 关键算法](#6-关键算法)
- [7. 默认参数表](#7-默认参数表)
- [8. 已知近似与局限](#8-已知近似与局限)
- [9. 实现陷阱（踩坑记录）](#9-实现陷阱踩坑记录)
- [10. 保真度台账与行为审计](#10-保真度台账与行为审计)
  - [10.5 未接线的编排层（必须知道的现状）](#105--未接线的编排层必须知道的现状)
- [11. 参考文献](#11-参考文献)

---

## 1. 架构概述

```
tools/lites_hitran.py     HITRAN 取数层（HAPI 1.x 封装，自包含、免 key）
        ↓
lites_physics.py          物理内核（材料/器件模型、传递链、噪声、标定反解）
        ↓
tools/lites_tools.py      仪器口径层（12 个工具、中文绘图、契约块组装）
        ↓
tools/lites_mcp.py        MCP 服务器（JSON-RPC stdio/HTTP、契约注入、schema 校验）
        ↓
tools/_gen_schema.py      JSON Schema 生成器（幂等 + 自校验，schema 的唯一真源）
tools/lites_fidelity.py   保真度台账 + 离线审计（CI 门禁）
tools/_rpc_test.py        端到端 JSON-RPC 回归（含负向用例）
```

**设计纪律**：三层严格分离。取数层不依赖 MCP；物理内核不依赖 MCP 协议与绘图；MCP 层只做参数编排、契约注入与结果封装。

**契约块的注入位置**：`assumptions` / `next_required_actions` / `disclosure_pending` 由 **MCP 层**的 `_wrap()` + `_ensure_contract()` 统一补全，工具实现只需在 `_block()` 里给内容。这样"工具忘记写契约"不可能发生。

---

## 2. 与 TDLAS 的分野（必读）

> 这是全文档最重要的一节。带 TDLAS 直觉读 LITES 输出会得出**系统性错误**的结论。

### 2.1 光-热转换的分母完全不同

| | TDLAS | LITES |
|---|---|---|
| 信号源 | 气体吸收 $\alpha_{gas}L$ | **器件自身吸收** $\eta_{dev}$ |
| 气体吸收的作用 | 直接产生信号 | **减去**到达器件的功率 |
| 探测器 | 光电二极管 | 压电（器件即换能器） |

$$\eta_{abs}(\nu) = \eta_{dev} + (1-\eta_{dev})\big[1 - e^{-\alpha_{gas}(\nu)L_{gas}}\big]$$

- 信号的**浓度依赖**来自 $\Delta\eta_{abs} = \eta_{abs}(\text{线上}) - \eta_{abs}(\text{线外})$
- **本底**是 $\eta_{dev}$ 的绝对值
- 弱吸收下信背比：

$$\mathrm{SBR} \approx \frac{\Delta\eta_{abs}}{\eta_{dev}} \approx \frac{(1-\eta_{dev})\,\alpha_{gas}L_{gas}}{\eta_{dev}}$$

**关键推论**：提高浓度只线性改善**分子**，压不掉**分母** $\eta_{dev}$。这直接解释了文献现象——同一 LN-MFP 器件，PAS 检测限 49 ppb(CH₄) 而 LITES 仅 22 ppm(CH₄)，差 450×，与 $\eta_{dev}/(1-\eta_{dev})$ 的量级一致。

因此：**选低 $\eta_{dev}$ 器件 + 选对波长**比"选强吸收线"重要得多。$\eta_{dev}$ 是波长的强函数（LiNbO₃ 在 2.5–4 μm 有声子吸收带，2.87 μm 处叠加 OH 基频，3.3 μm 落在带肩），**本项目把它列为全链路最大不确定度**。

### 2.2 标定轴是能量积累时间，不是频率

文献结论："降低谐振频率 $f_0$ 有利于增加能量积累时间"。

$$\tau_{acc} = \frac{Q}{\pi f_0}$$

受迫阻尼振子的包络建立时间 = 群延迟。于是：

| | TDLAS/QEPAS | LITES |
|---|---|---|
| 目标 $f$ | 高（抑制 1/f 噪声） | **低**（延长能量积累） |
| 提高 $Q$ | 改善（线性） | 改善，但见 §2.4 |

> ⚠ **早期版本的错误**：初版把"Q 值"直接当增益（$V \propto Q$），导致同一器件跨波段反解出的 $g$ 跨 80×。现改为 $\tau_{acc} = Q/(\pi f_0)$，并显式引入材料热弹品质因数 $\Theta$ 与涂层增益——这三者都**不随波长变**，于是"同器件跨波段 $g$ 一致"才成为**可检验的真判据**。

### 2.3 热扩散低通把最优 2f 拖到 f0/2 以下

$$\tau_{th} = \frac{w^2}{8D},\qquad H_{th}(f) = \frac{1}{\sqrt{1+(\omega\tau_{th})^2}},\qquad f_{cut}=\frac{1}{2\pi\tau_{th}}$$

机械共振要求 $f_m \approx f_0/2$（使 $2f_m$ 落在共振峰），但热扩散是**低通**，$f_m$ 越高热波越被压制。

**净效果：最优 $f_m$ 低于 $f_0/2$** —— 与 QEPAS 的做法**相反**。

> 因此**不要**套用 QEPAS 的 $f_m = f_0/2$，必须用 `lites_sweep(var="f_m")` 实测扫描找最优。`optimal_2f_frequency()` 给出理论参考值，但实测扫描优先。

### 2.4 MPC 在 LITES 里是负收益

$$\text{throughput} = \prod_i R^i \approx R^{n_{pass}}$$

银镜 $R=0.98$、259 次反射 → 总透过率仅 $0.98^{259} \approx 0.5\%$。LITES **功率敏感**（信号 $\propto P$），所以多通池是"吸收增益 vs 功率损失"的权衡，**不像 TDLAS 那样净赚**。

`LitesDevice.optical_throughput()` 已把这一衰减显式建模进传递链。

### 2.5 提高 Q 的收益是次线性的

LITES 工作在 kHz 段（默认器件 $f_0 \approx 32.8$ kHz，自研 QTF 可低至 ~9.5 kHz），远低于 TDLAS 的 30 kHz+，因此 **1/f 噪声主导**。提高 $Q$ 虽延长 $\tau_{acc}$，但同时收窄带宽、放大 1/f 段贡献。**Q 翻倍 ≠ LOD 翻倍改善**——必须看 `lites_noise_budget` 找真瓶颈。

---

## 3. 物理模型

### 3.1 材料热弹品质因数

$$\Theta = \frac{\alpha_{te}\cdot d_{piezo}}{k_{th}}$$

`thermoelastic_fom(mat, coating)` 计算基体与涂层的合成值：

| 材料 | $\alpha_{te}$ | 相对增益 |
|---|---|---|
| LiNbO₃ vs 石英 | 13.6× | $\Theta$ 合计 **45.1×** |

（拆分：$\alpha_{te}$ 13.6× × $d_{piezo}$ 10.9× / $k_{th}$ 3.3×）

### 3.2 热学链

```python
D   = k_th / (rho * cp)                     # 热扩散率
tau_th = w²/(8D)                            # 热时间常数
H_th(f) = 1/sqrt(1 + (2π f tau_th)²)        # 热扩散低通
f_cut  = 1/(2π tau_th)                      # 截止频率
```

### 3.3 机械链（SDOF）

$$H_{mech}(f) = \frac{1}{\sqrt{1+Q^2(f/f_0 - f_0/f)^2}}$$

在 $f=2f_m$ 处取值。3 dB 带宽 $\Delta f = f_0/Q$。

### 3.4 共振跟踪

$$f_0(T) = f_0^{nom}\big[1 + tc\cdot\Delta T\big]$$

温度系数 $tc$：石英 ≈ −30 ppm/K，LiNbO₃ ≈ **−80 ppm/K**。

失谐损失（`detuning_loss`）：把 $f_0^{actual}$ 代入 $H_{mech}$ 与假设值比较，给出电压损失比。$\Delta T = 1$ K 已能造成可测失谐。

### 3.5 热弹应变与电荷

```python
dT   = temp_rise_from_heat(q_dep, f_m, w, L_heat, mat)
eps  = thermal_expansion_strain(dT, alpha_te, constr)   # constr ∈ [0,1] 热约束度
qc   = charge_from_strain(eps, area, mat, thickness)
```

`constr`（热约束度，默认 0.5）描述器件被夹持的程度——完全自由膨胀不产生应力，完全约束产生最大应力。真实值取决于封装方式，属**未标定项**。

---

## 4. 传递链逐级实现

`LitesDevice._chain_v()` 是**唯一机理链**——标定、预测、伪信号、探测限全部复用它（避免"标定一套、预测另一套"的经典漂移）。

$$V_{2f} = g\cdot\underbrace{(P\,\eta_{abs}\,T_{opt})}_{\text{热沉积}}\cdot\underbrace{H_{th}(f_m)}_{\text{热扩散}}\cdot\underbrace{\tau_{acc}}_{\text{能量积累}}\cdot\underbrace{\Theta_{mat}\cdot\Theta_{coat}}_{\text{材料/涂层}}\cdot\underbrace{H_{mech}(2f_m)}_{\text{机械共振}}\cdot\underbrace{\frac{Q_c}{C_{total}}}_{\text{电荷→电压}}$$

逐项：

| 环节 | 实现 | 说明 |
|---|---|---|
| 1. 功率 | $P$ (W) | 激光到达器件的光功率 |
| 2. 器件吸收 | $\times\eta_{abs}$ | **热源**；由 $\eta_{dev}$ + 气体吸收共同决定 |
| 3. 光通量 | $\times R^{n_{pass}}$ | MPC 反射损耗（§2.4） |
| 4. 热低通 | $\times H_{th}(f_m)$ | 热扩散跟不上高 $f_m$ |
| 5. 能量积累 | $\times\tau_{acc}=Q/(\pi f_0)$ | §2.2 的标定轴 |
| 6. 材料/涂层 | $\times\Theta_{mat}\Theta_{coat}$ | §3.1，不随波长变 |
| 7. 机械共振 | $\times H_{mech}(2f_m)$ | §3.3 |
| 8. 温度→应变 | $\Delta T\to\varepsilon$ | §3.5 |
| 9. 应变→电荷 | $\varepsilon\to Q_c$ | 压电效应 |
| 10. 电荷→电压 | $/C_{total}$ | TIA 输入电容积分 |
| 11. 标定增益 | $\times g$ | §5，由实测锚点反解 |

**调制深度因子**（在 `predict_2f_voltage` 中乘入，不在 `_chain_v` 里，因为它是"测量条件"而非"器件属性"）：

```python
F_raw(m) = m² · exp(1 − m²/2.2²)      # 峰值在 m = 2.2 处 = 4.84（不是 1）
F(m)     = F_raw(m) / 4.84            # 归一化，使 m 取标定值时 F = 1
```

> ⚠️ **历史缺陷**：早期版本算了 `F_m` 但**从未乘进** `v_on`/`v_off`，导致改 `mod_depth_cm1` 对输出毫无影响。这是被**行为审计**（§10）抓出来的一类"声明了却无效"缺陷。现已修复，且 `m`/`F_m`/`F_m_raw`/`V_2f_at_m_opt` 全部随返回暴露。

---

## 5. 标定与反解

### 5.1 为什么需要标定

机理链给了**正确的函数形式与标度律**（对 $\eta_{abs}$、$P$、$H_{th}(f_m)$、$H_{mech}$、$Q$ 的依赖），但绝对量级受 `constr`、真实电极面积、TIA 输入阻抗、压电耦合效率等**未标定因素**共同支配。

### 5.2 一点锚定

`_solve_gain()` 由实测锚点反解增益 $g$：

$$g = \frac{V_{meas}}{\text{chain}\big(P_{cal},\, \eta_{abs}^{cal}\big)}\Big|_{f_m = f_0/2}$$

保留完整标度律，仅用一点实测锚定量级。

### 5.3 ★ 锚点口径：必须是 η_dev，不是 α_gas

**这是本项目改造的直接起因**：

- 初版把 `cal_alpha_cm1`（**气体**吸收系数）当热源输入 → 同一器件的三个波段反解出跨 **80×** 的 $g$
- 把"真实的波长相关器件吸收"伪装成了拟合常数——**看起来模型对上了，实际是把物理错误吸收进了标定常数**
- 改为 `cal_eta_abs`（**器件自身**吸收比）口径后，跨波段 $g$ 一致 → 消除

### 5.4 可检验判据

> **同一器件在不同波段、各自给出正确的 $P$ 与 $\eta_{abs}$ 后，反解出的 $g$ 应当一致。**

若跨幅远超量测误差，说明**锚点元数据（尤其 $\eta_{abs}$）写错了**——而不是"模型本来就这样"。这条判据已写入 `selftest()`。

---

## 6. 关键算法

### 6.1 有效器件吸收比

```python
def effective_eta_abs(self, alpha_gas_cm1, L_gas_cm):
    a = 1.0 - exp(-max(alpha_gas_cm1, 0.0) * max(L_gas_cm, 0.0))
    return self.cal_eta_abs + (1.0 - self.cal_eta_abs) * a
```

线上：$a$ 大 → $\eta_{abs}$ 大 → 信号强。线外：$a\to0$ → $\eta_{abs}\to\eta_{dev}$ → 本底。

### 6.2 最优 2f 频率

`optimal_2f_frequency(f0, q, w, mat)`：在 $f_m$ 网格上最大化

$$H_{th}(f_m)\cdot H_{mech}(2f_m)$$

返回理论最优 $f_m$ 与对应值。**实测扫描优先**（§2.3）。

### 6.3 调制深度峰形

见 §4 末。`lites_sweep(var="mod_depth_cm1")` 可直接扫出峰位，验证 $m_{opt}\approx2.2$。

### 6.4 伪信号

`spurious_2f(power_W, eta_spurious)`：器件除气体吸收外还有**非选择性吸收**（表面污染、涂层老化、窗片吸收）产生的 2f 背景。它与浓度无关，是**系统性偏置**，只能扣除不能靠平均消掉。

- `eta_spurious=None` → 模型按 $\eta_{dev}$ 的某个比例估计
- 显式给值 → 用于模拟"器件老化后本底抬升"

### 6.5 检测限

`mdl(power_W, sigma_V, n_sigma, ...)`：由 $\sigma_V$ 反推最小可检测浓度。

$$x_{MDL} = n_\sigma\cdot\frac{\sigma_V}{S(x=1)}$$

`lites_mdl` 工具额外做**文献量级比对**（`compare_literature=True`），把结果与已知 LITES 检测限对比，防止量级错误被当成"新发现"。

### 6.6 噪声预算

`noise_floor(bw_Hz, resp_V_per_C, c_in_F, v_rms_1f)`：

| 分量 | 特征 |
|---|---|
| 热噪声（TIA） | 白，$\propto\sqrt{\Delta f}$ |
| 散粒噪声 | 白，$\propto\sqrt{P}$ |
| **1/f（前放 + 器件）** | 粉红，**kHz 段主导** |
| ADC 量化 | 白，由位数与量程决定 |

`lites_noise_budget` 逐项分解并给贡献占比。**注意**：`resp_V_per_C` 曾因未传递给 `noise_floor` 而失效（行为审计抓出，已修）。

### 6.7 浓度反演

`lites_invert(v_2f_measured_V, ...)`：

- `use_delta=True` + `v_2f_baseline_V` → 用 $\Delta V = V_{on}-V_{off}$，扣掉 $\eta_{dev}$ 本底
- `use_delta=False` → 直接从 $V_{2f}$ 反推，**本底已被包含**，须显式说明

灵敏度 $k$（= 单位摩尔分数的归一化 2f 峰高）必须来自**同一传递链**，不可与解析模型混用。

### 6.7b 结果校验（`lites_review`）

多维度检查，包括（节选）：

1. 器件 key 有效性
2. $\eta_{dev}$ 是否为默认值（未标定 → warn）
3. 工作点是否在机械共振峰附近（$2f_m$ vs $f_0$ 失谐）
4. 热扩散是否已把信号压到噪声量级
5. SBR 是否过低（$\eta_{dev}$ 主导 → warn）
6. **噪声口径**：`sigma_V` 是否为用户给定；未给定则使用模型自估，**须披露**

> `sigma_V` 参数曾被解析但**从未使用**（发现 6 恒用模型自估）。行为审计抓出后修复，现带 `sigma_V_is_user` 标志。

### 6.8 器件对比

`lites_compare(devices, metrics)`：对多个器件跑同一工况，比较 `V_delta`（扣除本底的信号电压）、`SNR`、`MDL`。

`lites_sweep` 支持 `log_scale`，因为 $\eta_{dev}$、$P$、$x$ 常跨数量级。

### 6.9 波形出图

`_plot_waveform()`：六子图（3×2 竖版）：(a) DC 透射包络（真实比例 exp(−αL)）；(b) 载波细节（AC 耦合，包络 = R₂f 幅值）；(c) **正交解调幅值 R₂f=√(X²+Y²)**（与相位无关，X/Y/X′ 保留于返回字段）；(d) 多浓度 R₂f 谱对比（单标度，禁双重计数）；(e) 标定曲线（R₂f 峰高 vs 浓度）；(f) **Allan 方差**（白 + 1/f + 漂移，**全整数 τ 网格 1…N/2，τ_opt 精确到 1 s**）。
正交解调：`_quad_demod_profile()` 逐扫描点构造调制窗 → cos/sin(2ωt+φ_r) 混频 → 整周期平均 → φ*=atan2(Y,X) 旋转；**R₂f=√(X²+Y²) 为主输出口径**（工程锁相输出幅值，单峰无负瓣）。

**中文字体**由 `_mpl_cjk()` 自动探测，优先级：

```python
_CJK_FONTS = ("Microsoft YaHei", "SimHei", "Microsoft JhengHei", "DengXian",
              "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC",
              "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "Sarasa Gothic SC",
              "PingFang SC", "Hiragino Sans GB", "Heiti SC")
```

找不到任何中文字体时会退回 DejaVu Sans（豆腐块）——**不会报错**，故出图后应目视确认。

---

## 7. 默认参数表

### 7.1 器件（`LitesDevice` 构造器默认）

> 下表是 **`LitesDevice` 构造器默认值**（LN-MFP 时代的遗留默认），**不是当前默认器件**；
> 当前唯一内置器件为 `qtf-commercial-decapped`（见 §7.4），其参数在 `lites_physics.DEVICE_LIBRARY` 中显式给出。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `material` | `linbo3` | `quartz` \| `linbo3` |
| `coating` | `none` | `none` \| `pdms` \| `gold` \| `graphene` \| `perovskite` |
| `f0` | 10485.0 Hz | **机械共振频率（须实测标定）** |
| `q` | 1621.0 | **品质因数（须实测标定）** |
| `tine_w_m` / `tine_l_m` / `tine_thick_m` | 1.7 / 11.5 / 0.5 mm | 叉齿几何 |
| `gap_m` | 1.0 mm | 叉齿间隙 |
| `electrode_area_m2` | 2.0e-5 m² | 有效电极面积 |
| `spot_w_m` | 0.3 mm | 激光有效加热宽度（**决定 $\tau_{th}$**） |
| `heat_len_m` | 0.5 mm | 有效传热深度 |
| `eta_piezo` | 1.0 | 压电/几何转换修正（**标定**） |
| `r_tia` | 1e7 V/A | 跨阻增益 |
| `c_total` | 20 pF | 总输入电容（器件 + TIA） |
| `constr` | 0.5 | **热约束度** ∈ [0,1]，封装相关，未标定 |
| `tc_ppm_per_K` | −80.0 | $f_0$ 温度系数（LiNbO₃） |
| `path_len_cm` | 2.5 | 气体吸收光程（决定 $\alpha L$） |
| `n_pass` / `mirror_refl` | 1 / 1.0 | MPC 反射次数 / 单次反射率 |

### 7.2 标定锚点

| 参数 | 默认值 | 说明 |
|---|---|---|
| `cal_power_W` | 10.5e-3 | 锚点时激光功率 |
| `cal_eta_abs` | 1.0e-3 | **器件自身吸收比**（不是气体吸收系数！见 §5.3） |
| `cal_meas_f2_V` | 4.4e-3 | 实测 2f 峰值电压 |
| `cal_mod_depth_cm1` | 0.68 | 锚点时调制深度（$m$ 归一化的基准） |
| `cal_species` | `""` | 锚点物种（仅报告用） |

### 7.3 工况

| 参数 | 默认值 | 说明 |
|---|---|---|
| `T` / `P` | 296 K / 1.01325 atm | 温度 / 气压 |
| `gamma_L` | 0.06 cm⁻¹ | 洛伦兹半宽（HWHM） |
| `f_m` | `None` → 取标定链 $f_0/2$ | **建议显式扫描**（§2.3） |
| `mod_depth_cm1` | `None` → 取 `cal_mod_depth_cm1` | 改它**会**改变输出（§4） |
| `f0_shift_ppm` | 0.0 | 人为引入失谐，用于灵敏度分析 |
| `eta_spurious` | `None` | 伪信号强度，None → 模型估计 |
| `bandwidth_Hz` | 100.0 | 噪声带宽（锁相等效） |
| `resp_V_per_C` | `None` → 1e12 V/C | 电荷灵敏放大器响应（**须传递**，§6.6） |

### 7.4 内置器件库（已裁剪为单默认器件）

**★ 唯一内置器件 = `qtf-commercial-decapped`**（商用 32.768 kHz 音叉晶振去壳裸音叉），**仅作演示占位**。
f0 与 Q 取常压空气公开实测锚点（Wang 2020 表 1 "STANDARD"），**是数量级参考、不是文献锚定结论**；
真实器件参数（datasheet / 实测 / 标定）一律经 `lites_device` 用户交互获取。常量定义在
`lites_physics.DEVICE_LIBRARY` / `DEFAULT_DEVICE`，由 `tools/lites_tools.py` 与
`tools/_gen_schema.py` 的 schema 描述**共同引用同一来源**，不存在第二处硬编码。

| key | 说明 | $f_0$ / $Q$ / $\tau_{acc}$ |
|---|---|---|
| **`qtf-commercial-decapped`** ★ | **默认（演示占位）**。商用音叉晶振去壳裸音叉 | 32757.4 Hz / 8630 / **83.9 ms** |

**它不是最优，只是最合理起点** —— $\tau_{acc}$ 仅 83.9 ms，LITES 的正统优化方向是降 $f_0$、拉长能量积累时间。

**★ 跨器件电压不可比（重要）**：2f 电压含一个**私有标定增益 $g$**，由 `_solve_gain()` 用该器件自己的锚点反解得到，因此 $g$ 吸收了该器件自身的 $C_{total}$、$R_{tia}$、`constr`、电极面积等未标定因素。后果：不同器件的 $V_{2f}$ 比值**只反映各自锚点数字的大小，不反映器件优劣**。
- **正确做法**：要比器件本征性能，读 $\tau_{acc}$ / $\Theta$ / $H_{th}$ / $H_{mech}$ / `SBR_eta` 这类**不含 $g$** 的机理因子；多器件对比用 `lites_compare` 的**严格口径**（显式传 `common={'L_gas_cm':X,'power_mW':Y}`）。

---

## 8. 已知近似与局限

1. **$\eta_{dev}$ 未实机标定**（**最大不确定度**）：波长的强函数。未标定时所有定量结论都应视为量级估计
2. **热约束度 `constr` 为常数**：真实封装下不同模态约束度不同，且可能随温度变
3. **热学用一维有效宽度模型**：$\tau_{th}=w^2/8D$ 假设热量在被加热宽度内均匀沉积、一维扩散；未建模三维热扩散与器件边缘效应
4. **SDOF 机械模型**：只用单自由度谐振子；真实音叉/悬臂有高次模态与耦合
5. **压电转换线性化**：$Q_c$ 与应变线性，未建模高压电场的非线性与去极化
6. **TIA 理想化**：用 $C_{total}$ 积分近似，未建模运放有限 GBW、输入偏置电流、压摆率
7. **$f_0$ 温度系数为典型值**：−80 ppm/K（LiNbO₃）/ −30 ppm/K（石英）；实机须标定
8. **$\tau_{acc}=Q/(\pi f_0)$ 为换算量**（约 19.7% 量级）：由文献"降 $f_0$ 增益能量积累时间"结论换算，**非独立实测**
9. **未建模项**（共 6 项，随结果披露）：自展宽、线混合、Dicke 窄化、热滞后与老化（$f_0$ 慢漂移）、任意阶谐波（3f/4f）与 WMS 完整傅里叶展开、调制深度自动寻优。另有 **1 项需显式开启**：寄生吸收（`eta_spurious`）
10. **1/f 噪声系数未逐器件标定**：定性趋势可靠（kHz 段 1/f 主导），绝对量级需实测
11. **电荷→电压的 $C_{total}$ 用固定值**：未建模电缆电容随长度变化、器件电容随温度变化

---

## 9. 实现陷阱（踩坑记录）

> 本节记录**实际犯过的错误**，技术员修改代码时务必留意。

| # | 陷阱 | 症状 | 正确做法 |
|---|---|---|---|
| 1 | **把气体吸收系数当热源输入标定** | 同器件跨波段反解 $g$ 跨 **80×**，物理错误被吸收进标定常数 | 锚点必须给**器件自身** $\eta_{dev}$（§5.3） |
| 2 | **把 Q 直接当增益（$V\propto Q$）** | 同一器件不同 $f_0$ 下增益失真 | 用 $\tau_{acc}=Q/(\pi f_0)$，并显式引入 $\Theta$ 与涂层增益 |
| 3 | **调制深度算了但没乘进传递链** | 改 `mod_depth_cm1` 输出**逐位不变** | `F(m)` 必须乘进 $v_{on}/v_{off}$；行为审计会抓 |
| 4 | **峰形因子归一化基准搞错** | docstring 声称 $F(2.2)=1$，实际 $F_{raw}(2.2)=4.84$ | 归一化除 **4.84**（= $2.2^2$），不是除 1 |
| 5 | **`sigma_V` 解析了却不用** | `lites_review` 恒用模型自估，用户传值被静默忽略 | 带 `sigma_V_is_user` 标志并使用用户值 |
| 6 | **`resp_V_per_C` 未传给 `noise_floor`** | 噪声预算对响应率不敏感，参数形同虚设 | 显式传递并回显在 `inputs` |
| 7 | **schema 声明了签名里没有的参数** | 传 `x` 给 `lites_mdl` → `TypeError` | 生成器 schema 与签名必须一致，`_gen_schema` 自校验 |
| 8 | **`_quiet()` 丢 `@contextlib.contextmanager`** | `with _quiet():` 抛 `AttributeError: __enter__` | 装饰器是必需品，勿在拼接中丢失 |
| 9 | **`_SCHEMA_BY_NAME` 在拼接中丢失** | `tools/call` 抛 `NameError`，但 `tools/list` 正常 | 由生成器 FOOTER 输出，勿手删 |
| 10 | **手写嵌套 JSON Schema** | 连续 6 次括号 `SyntaxError`，人工修补越修越乱 | 一律用 `_gen_schema.py` 生成，勿手改 |
| 11 | **生成器不幂等** | 每次运行 `lites_mcp.py` 空行增加，md5 每次都变 | `splice()` 锚定在分隔线 + `strip("\n")`，已验证 3 次运行哈希相同 |
| 12 | **`/tmp` 在 Windows 上解析为当前盘根目录** | 测试脚本写到不存在目录 | 测试脚本写在仓库内 `tools/` |
| 13 | **按 kwargs 名匹配做参数可达性审计** | `T`/`P`/`x`/`gamma_L`/`line_strength` 被**按位置**消费，误报 8–11 个"死参数" | 改用**行为审计**：扰动两个值，输出逐位相同才标 |
| 14 | **matplotlib 中文豆腐块** | 图上中文全是方块，但**不报错** | `_mpl_cjk()` 自动探测 + 出图后目视确认 |
| 15 | **多通池按 TDLAS 惯性推荐** | 建议长光程池，实际信号大幅下降 | LITES 信号 $\propto P$，$R^{n_{pass}}$ 已在链中 |
| 16 | **把跨器件的 $V_{2f}$ 直接相比** | 得到 27.3× 之类的**假象**，实际只反映各自锚点大小 | 每个器件含**私有 $g$**，不可比（§7.4）。用 `lites_compare` 严格口径或读 $\tau_{acc}$/$\Theta$（§7.4 末） |
| 17 | **默认器件硬编码在多处** | 改默认时漏改 → schema 描述与函数签名不一致 | 单源 `lites_physics.DEFAULT_DEVICE`，工具层与生成器共同引用 |
| 18 | **批量改名脚本破坏测试负例** | 把 `tdlas_simulate`（未知工具）改成 `lites_forward`（真实工具），负例静默变合法调用、**失去覆盖**而测试仍通过 | 负例工具名加断言钉住；改名前先查是否为他例依赖 |
| 19 | **校准分组把不可比的器件放一起** | `g/中位数` 跨幅 45× 的"发现"，其实是分组错误导致的伪像 | 分组前确认**锚点条件**（L / P / 物种）可对齐；不可对齐的另立组并注明 |
| 20 | **返回值里出现 `NaN`** | `lites_forward` 不传 `mod_depth_cm1` 时返回 `"m": NaN`。**Python 的 json 默认接受并输出裸 `NaN`**，所以自检与 RPC 测试**全都照过**——但 RFC 8259 不允许，严格 MCP 客户端会直接抛错 | 用 `None` 表达"未计算"，并加 `m_note` 说明原因；`_rpc_test.py` 新增 `_find_nonfinite()` 递归守卫（**已验证能抓到该回归**） |

---

## 10. 保真度台账与行为审计

### 10.1 为什么需要

本项目历史上**两次踩同一类坑**——`inputSchema` 声明了参数、工具层却从未把它交给物理内核，于是调用方传了值、拿到的是默认值算出的结果，**全程零提示**。

根因不是疏忽，而是**缺一个单一真源**："物理效应 / 参数 / 证据"分散在代码、文档、测试三处，人一改就漂。

### 10.2 可执行台账

`tools/lites_fidelity.py` 的 `EFFECTS` 表（**26 项**）。每项声明：

| 字段 | 含义 |
|---|---|
| `evidence` | 在哪个源码文件里有对应实现（须为**真实存在的字符串字面量**） |
| `status` | `on` 默认生效 / `opt` 需显式开启 / `off` 未实现 |
| `params` | 控制它的参数 |
| `limit` | 已知缺口 |

### 10.3 三项离线审计

| 审计 | 问什么 | 手段 |
|---|---|---|
| `audit_effects()` | 表里声称的符号真的在源码里吗？（防"表漂了"） | 在 `lites_physics.py` / `tools/lites_tools.py` / `tools/lites_mcp.py` 中检索 `evidence` 字面量 |
| `audit_parameters()` | 有没有"schema 声明了却从未生效"的死参数？ | **行为审计**：对每个参数扰动两个值，输出逐位相同则标记 |
| `missing_effects()` | 哪些效应**没**建模（必须披露）？ | 筛 `status == "off"` |

### 10.4 ★ 为什么是行为审计而不是 kwargs 匹配

初版用"截获真正进入引擎的 kwargs，与 schema 求差"。结果对 `lites_forward` 报出 8–11 个假死参数。

**根因**：`T`/`P`/`x`/`gamma_L`/`line_strength` 在 `lites_tools` 中被**按位置**消费（作为 `alpha_eff`/`power_W` 的实参），所以它们的**名字**从来不出现在内部 kwargs 里——**参数确实生效了，只是改名了**。

**正确判据**：*"如果我改变它，输出会变吗？"* —— 这是行为问题，不是命名问题。

改用行为审计后，一次就跑出 **4 个真实缺陷**（§9 的 #3–#6）。

---

### 10.5 ★ 未接线的编排层（必须知道的现状）

`lites_mcp.py` 里保留了 TDLAS 时代的**契约编排层**，但 LITES 工具链路**从未调用**它们 ——
它们是"定义了但无引用"的孤儿代码（约 217 行）：

| 函数 | 行范围 | 行数 | 提供的能力 |
|---|---|---|---|
| `_interaction_block` | 392–459 | 68 | `severity` 三级 / `conclusion_allowed` / `blocking_reason` / 动作抑制 |
| `_resolve_devices` | 542–575 | 34 | 器件库整机 `setup=` 与分组解析 |
| `_alpha_report_block` | 140–171 | 32 | α 语境自适应播报 |
| `_fringe_report_block` | 174–205 | 32 | etalon 语境自适应播报 |
| `build_clarify_questions` | 692–714 | 23 | 澄清问题库 |
| `_fidelity_digest` | 243–253 | 11 | 保真度精简块（转发台账） |
| `_species_defaults` | 607–614 | 8 | 物种推荐工况 |
| `_DEVICE_TYPES` | 468–474 | 7 | 器件类型表 |
| `_save_devices` | 538–539 | 2 | 设备库落盘 |

**为什么留着**：这些是**能力**而不是垃圾。LITES 侧当前只产出**朴素**契约
（`next_required_actions` / `disclosure_pending` 都是字符串列表，`interaction` 多为 `{}`），
而这些函数实现了明显更强的语义。

**为什么不能就这么留着**：文档若按它们的能力来写，就是在**承诺不存在的功能**。
本项目的 `lites_fidelity.py` 存在的理由正是消灭这一类"声明了却没接上"——
孤儿编排层是同一类问题在**架构层**的残留。

**两种收尾方式（择一）**：

- **(a) 接线**：把这些函数接回 LITES 工具链路，升级契约语义。
  路线：工具层不再自己构造 `_block()`，改由 MCP 层统一调 `_interaction_block(out)`
  并按 `severity` 排序下发；`alpha`/`fringe` 语境按会话态抑制重复。
  → 收益大，工作量中等。
- **(b) 删除**：移除这 217 行，文档永久对齐当前朴素语义。
  → 收益是消除"文档骗人"的风险，代价是放弃已有实现。

> **当前状态**：未接线。README / SKILL.md / docs/VALIDATION.md 已按**实际**语义书写，
> 并显式标注该层未生效（`docs/VALIDATION.md` §5.1）。**下一步应先定 (a) 还是 (b)。**

---

## 11. 参考文献

1. 光致热弹光谱（LITES）原理与器件：见 IMA 文献知识库（kb_id `7498712502774927`），本项目器件锚点参数由此取得
2. HAPI (HITRAN API): https://github.com/hitranonline/hapi
3. HITRAN Database: https://hitran.org
4. Kochanov R V, et al. *HITRAN Application Programming Interface (HAPI)*. JQSRT, 2016. DOI: 10.1016/j.jqsrt.2016.03.005
5. Gordon I E, et al. *The HITRAN2024 molecular spectroscopic database*. JQSRT, 2026. DOI: 10.1016/j.jqsrt.2026.109807
