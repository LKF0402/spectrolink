"""SpectroLink TDLAS 的纯数据常量表（引导文案、设备规则、契约块、仪器键名）。

本模块只放字面量数据，不含任何逻辑、不 import 本包内其他模块，
所以任何模块都可以安全导入而不产生循环依赖。
"""

from __future__ import annotations


_ALPHA_CTX_FIELDS = ("T_K", "P_atm", "step_cm-1", "wingHW_cm-1")


_SEV_BLOCK = "block_conclusion"   # 未满足 → 不得给出定量结论（结果照给，结论受控）


_SEV_DISCLOSE = "must_disclose"   # 结论可给，但必须在同一回答里说明（缺一不可）


_SEV_ADVISORY = "advisory"        # 建议


_SEV_ORDER = {_SEV_BLOCK: 0, _SEV_DISCLOSE: 1, _SEV_ADVISORY: 2}


_DEVICE_TYPES = {
    "laser": ["eta_VI", "dnu_dI", "d2nu_dI2", "wn_ref", "i_ref", "i_th", "eta_IP",
              "am_i0", "am_i2", "am_psi1", "am_psi2"],
    "pd": ["resp", "gain", "bw", "rin"],
    "daq": ["fs", "n_samples", "adc_bits", "v_range"],
    "optics": ["throughput"],
}


_DEVICE_TYPE_CN = {"laser": "激光器", "pd": "探测器", "daq": "采集卡", "optics": "光学元件"}


_DEVICE_RULES = {
    "eta_VI": (0.0, None, False, None),
    "dnu_dI": (None, None, False, "nonzero"),
    "d2nu_dI2": (None, None, False, None),
    "wn_ref": (0.0, None, False, None),
    "i_ref": (0.0, None, True, None),
    "i_th": (0.0, None, True, None),
    "eta_IP": (0.0, None, False, None),
    "am_i0": (None, None, False, None),
    "am_i2": (None, None, False, None),
    "am_psi1": (None, None, False, None),
    "am_psi2": (None, None, False, None),
    "resp": (0.0, None, False, None),
    "gain": (0.0, None, False, None),
    "bw": (0.0, None, False, None),
    "rin": (0.0, None, True, None),
    "fs": (0.0, None, False, None),
    "n_samples": (1.0, None, True, "int"),
    "adc_bits": (4.0, 32.0, True, "int"),
    "v_range": (0.0, None, False, None),
    "throughput": (0.0, 1.0, False, None),
}


_DEVICE_SALIENT_KEYS = {
    "laser":  ["dnu_dI", "eta_VI", "wn_ref", "i_ref", "i_th", "eta_IP"],
    "pd":     ["resp", "gain", "bw"],
    "daq":    ["fs", "adc_bits", "v_range"],
    "optics": ["throughput"],
}


EDGE_TECH_NOTE = (
    "真实实验中三角波上升沿与下降沿常不重合，成因："
    "① 激光调谐非线性（注入电流→波长响应并非完美线性）；"
    "② 扫描期间激光器热漂移（波长与功率随时间漂移）；"
    "③ 探测器与前置放大器带宽有限 → 上升/下降沿的相位滞后不同；"
    "④ 电流源上升/下降沿的扫频响应差异。"
    "处理建议：先用 edge='both' 对照两段；若重合约，任取一段即可；若不重合，取较干净的一段，"
    "或用 edge='average' 两段平均（随机噪声按 √2 改善，但系统性偏差不会被平均抵消）。"
)


PARAM_ACQ_GUIDE = {
    "species": ("待测气体", "—", "HITRAN 分子式（CH4 / H2O / CO2 / CO / C2H2 …）"),
    "wn_center": ("目标波数", "cm⁻¹", "要测的吸收线中心；决定激光调谐到哪条线"),
    "scan_span_cm": ("三角波扫描半宽", "cm⁻¹", "扫描覆盖的波数半宽；amp_V = scan_span_cm/(η_VI·|dν/dI|)，不填用默认 1.5"),
    "amp_V": ("三角波幅值", "V", "**通常无需手填**：由 wn_center + scan_span_cm 自动反算；仅需固定电压时覆盖"),
    "offset_V": ("三角波偏置", "V", "**通常无需手填**：由 wn_center 经电压—波数关系自动反算"),
    "freq_Hz": ("三角波频率", "Hz", "扫描速率；与采样率共同决定每周期采样点数"),
    "phase_deg": ("三角波相位", "°", "起始相位（默认中心对称、先上升后下降）"),
    "eta_VI": ("驱动器跨导 η_VI", "mA/V", "电压—电流转换，取决于驱动器电路"),
    "dnu_dI": ("激光器调谐系数 dν/dI", "cm⁻¹/mA", "波数标定核心；给出激光器型号可查规格书"),
    "eta_IP": ("功率斜率效率", "mW/mA", "决定光功率量级，进而决定 PD 电压与 ADC 量程占用"),
    "wn_ref": ("参考波数", "cm⁻¹", "调谐基准点（通常取规格书中心波长）"),
    "i_ref": ("参考电流", "mA", "与参考波数配对的工作点电流"),
    "i_th": ("阈值电流", "mA", "低于此电流无激光输出"),
    "fs": ("采集卡采样率", "Hz", "常见 16-bit DAQ 上限 250 kS/s"),
    "adc_bits": ("ADC 位数", "bit", "决定量化噪声与动态范围（常见 USB DAQ：16-bit）"),
    "v_range": ("ADC 输入量程", "V", "决定满量程与饱和阈值"),
    "resp": ("PD 响应度 R", "A/W", "光电转换效率（InGaAs 典型 0.9 A/W）"),
    "gain": ("PD 跨阻增益 G", "V/A", "决定 PD 输出电压；过高会导致 ADC 饱和"),
    "bw": ("PD 带宽", "Hz", "与噪声带宽、可解调的最高调制频率相关"),
    "rin": ("激光相对强度噪声 RIN", "1/√Hz", "常为 TDLAS 系统的主导噪声源"),
    "throughput": ("光学元件总透过率", "—", "窗片 / 镜片 / 光纤耦合损耗"),
    "mod_freq_Hz": ("正弦调制频率 fm", "Hz", "把信号搬到高频以规避 1/f 噪声与激光 RIN"),
    "mod_amp_V": ("正弦调制幅值", "V", "决定调制系数 m=a/HWHM；m≈2.2 时 2f 峰值最大"),
    "m_opt": ("目标调制系数 m", "—", "2f 灵敏度最优的调制深度/线宽比，经典值 2.2"),
    "lockin_avg": ("锁相平均周期数", "—", "低通平均的调制周期数，保持 1（>1 会模糊线形且不降残留）"),
    "lockin_stages": ("锁相低通级联级数", "—", "矩形窗频响是 sinc，级联 2 级(sinc²)把非吸收区 2f 残留 4.1%→1.6%"),
    "drift_frac": ("1/f 慢漂移幅度", "相对光强", "激光功率慢漂移；DAS 受害、WMS 锁相抑制；默认 0.005"),
    "flicker_frac": ("1/f 粉红噪声幅度", "相对光强", "频域 1/√f 噪声；默认 0.01"),
    "fringe_n": ("etalon 腔折射率", "—", "etalon 条纹：FSR = 1/(2nd)；空气隙 1.0、玻璃≈1.5"),
    "fringe_d_cm": ("etalon 平行面间距", "cm", "etalon 条纹：决定 FSR；10 mm→1.0、5 mm→0.5"),
    "fringe_R": ("etalon 单面反射率", "—", "etalon 条纹：峰-峰对比度≈4R/(1−R)²；未镀膜玻璃 0.04、AR≈0.005"),
}


CLARIFY_QUESTIONS = {
    "x": {"question": "待测气体浓度（摩尔分数）量级是多少？",
          "options": ["痕量 ~1e-6", "低 ~1e-4", "中 ~1e-2", "不确定，帮我推荐"],
          "why": "决定吸收强弱 αL，弱吸收(1e-5~0.1)下 DAS/2f 才线性"},
    "L_cm": {"question": "吸收池光程是多少？",
             "options": ["10 cm", "30 cm", "100 cm", "多通池（几十米）", "不确定"],
             "why": "与浓度共同决定 αL"},
    "T": {"question": "气体温度？",
          "options": ["室温 296 K", "其他（请填数值）"],
          "why": "决定线强与多普勒线宽"},
    "P": {"question": "气体压力？",
          "options": ["常压 1 atm", "减压（请填数值）", "其他"],
          "why": "决定碰撞展宽（Lorentz HWHM）"},
    "mod_freq_Hz": {"question": "正弦调制频率 fm 用多少？",
                    "options": ["默认 30 kHz", "其他（请填）"],
                    "why": "信号搬到 fm 以避开 1/f 噪声"},
    "drift_frac": {"question": "是否加入 1/f 慢漂移噪声？",
                   "options": ["不加（理想仿真）", "加 0.5%", "加 1%", "其他"],
                   "why": "模拟激光功率慢漂移；DAS 受害、WMS 抑制"},
    "flicker_frac": {"question": "是否加入 1/f 粉红噪声？",
                     "options": ["不加（理想仿真）", "加 1%", "加 3%", "其他"],
                     "why": "模拟 1/f 光强噪声"},
}


SPECIES_PROFILES = {
    "CH4": {"bands": [("3.3 μm", 3010.0), ("1.65 μm", 6046.9)],
            "x_typ": 1e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
            "note": "甲烷近红外 6046.9(2ν3 带 R(3)线，较孤立)、中红外 3010(ν3 带强吸收)"},
    "C2H6": {"bands": [("3.4 μm ν7 带", 2964.5), ("1.7 μm", 5920.0)],
             "x_typ": 1e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
             "note": "2964.5 附近 Q 支密集(159 线)，需 L 较小避免 αL 过大"},
    "H2O": {"bands": [("1.39 μm", 7185.6)],
            "x_typ": 0.02, "L_cm": 30.0, "T": 296.0, "P": 1.0,
            "note": "7185.6 为较孤立单线，常用于锁相/谐波标定"},
    "CO": {"bands": [("2.33 μm", 4285.0)],
           "x_typ": 1e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
           "note": "基频 R 支，线孤立、线强表成熟"},
    "CO2": {"bands": [("2.0 μm", 5003.0)],
            "x_typ": 5e-4, "L_cm": 100.0, "T": 296.0, "P": 1.0,
            "note": "2.0 μm 组合带"},
    "NO": {"bands": [("5.26 μm", 1900.0)],
           "x_typ": 1e-4, "L_cm": 50.0, "T": 296.0, "P": 1.0,
           "note": "基频带"},
}


AI_INTERACTION_GUIDE = {
    "role": "你是 TDLAS 实验设计助手，服务对象多为实验新手。职责是**主动指导**，不是被动等参数。"
            "凡信息不足必须主动索取，绝不能默默用默认值出结果。",
    "default_tool": {
        "兜底": "不确定该用哪个工具时，默认走 `tdlas_wms_instrument`（最完整、最接近真实实验）。",
        "快速估算": "用户说『快速算』『理论值』『扫一下参数』→ 用 `tdlas_simulate`（解析版，秒出结果）。",
        "只看 DAS": "用户明确说『DAS』『直接吸收』→ 用 `tdlas_das_instrument`。",
        "不要默认走 simulate": "simulate 不模拟仪器链路（DAQ/PD/锁相），只适合快速估算，不适合出完整实验图。",
    },
    "priority": [
        "① 先要实测标定值（最可靠）；",
        "② 用户给不出值、但能给**器件型号** → AI **联网检索**该型号官方规格书提取参数（见 datasheet_lookup）；",
        "③ 型号也没有 → 引导用户**现场标定**（例：改变驱动电压 ΔV，记录波数变化 Δν，得 dν/dV）；",
        "④ 以上都做不到 → 用内置默认值，但**必须在结论中显式标注**「以下参数用了默认值 X」。",
    ],
    "workflow": [
        "第 1 步｜确认场景：测什么分子、什么波段、什么工况（T/P/浓度量级/光程）。"
        "用户不确定时主动给推荐（CH4 → 3.3 μm 或 1.65 μm；CO → 2.3 μm；CO2 → 2.0 μm）；"
        "**推荐前先看 adaptive_condition 返回的『波段可达性』**——默认激光只覆盖 2964.7–2975.3 cm⁻¹，"
        "其它波段需要另配激光器：要么把该波段的 laser_params_needed 一并告诉用户（让他知道要换器件），"
        "要么依赖 auto_laser=True 的自动重锚（此时必须按 must_disclose⑦ 说明这属理想假设、非真实硬件）。",
        "第 2 步｜分组索取参数，每次只问一组，并说明该参数控制什么物理量（见 PARAM_ACQ_GUIDE 的 why）。",
        "第 3 步｜拿到结果后做**合理性体检**并主动告知：αL 是否在弱吸收区、ADC 是否饱和、"
        "噪声主导来源（散粒/热/RIN）、检测限量级、调制系数 m 是否接近 2.2。",
        "第 4 步｜若返回值中 warnings / param_requests 非空，**先向用户澄清再解读结论**，"
        "不要拿不合理参数直接下结论。",
    ],
    # ★ 正确 SOP（标准操作流程）——只讲怎么做对，不讲"坑"。AI 必须严格按此 SOP 输出结论。
    "sop": [
        {"step": 1, "name": "技术选型 + 选定孤立单线",
         "rule": "先按谱线密度选技术：窗口内线数 ≤10 → WMS（2f 呈标准双峰、免标定、抗 RIN）；"
                 "线数多（密集谱区）→ 2f 会把每根线都放大成独立峰、看似杂乱，此时 DAS 的直接吸收包络更直观，"
                 "不宜用 WMS 展示标准谐波。WMS 定量/展示标准谐波一律选孤立单线，"
                 "示例：H2O 7185.596、CO 4260.06、N2O 1278.45。线数看 n_lines_in_window。",
         "pass": "已按线密度选对技术 + 用户给定/AI 查到孤立线 → 进 step 2"},
        {"step": 2, "name": "确认激光波数轴覆盖目标线",
         "rule": "若自定义链路，确保 wn_ref 与 wn_center 对齐；本工具已自动处理，"
                 "校验：返回的 scan_window_cm-1 必须包含 wn_center。",
         "pass": "scan_window 包含 wn_center → 进 step 3"},
        {"step": 3, "name": "调用 tdlas_wms_instrument 跑链路",
         "rule": "用默认参数即可（fm=30 kHz, fscan=100 Hz, 自动优化 m=2.2, "
                 "2 级级联低通, edge=rising, trim_frac=0.12）。"
                 "图统一为 5 层：驱动电压 → DAS → 1f → 2f → 归一化 2f（自动选方法）。",
         "pass": "返回无错误 + warnings 非空（含工况说明）→ 进 step 4"},
        {"step": 4, "name": "读 normalization.method 并据此解读",
         "rule": "2f/1f 有效时：使用 2f/1f 读数；1f 失效（1f 过零 或 非吸收区泄漏>30%）："
                 "使用 2f/I0（I0=PD 非吸收区光强均值）读数。**严格按 normalization.method 给出的方法写结论，不要混用**。",
         "pass": "已用同一归一化方法贯穿所有波段读数 → 进 step 5"},
        {"step": 5, "name": "三件校验（形态类判据视工况打折）",
         "rule": "① DAS 提取峰与 HITRAN 理论 αL 一致（偏差 <2%）；"
                 "② 2f 峰位 Δν ≈ ±0.7a（孤立单线下应见标准双峰结构）；"
                 "③ 非吸收区残留/峰 < 2%。"
                 "⚠ **默认工况本身通常就有 1–2 条形态类提醒**（如 CH4@2968.5 密集谱区："
                 "αL=0.133 偏大 + 221 条线非孤立），这属正常，不是失败；"
                 "密集谱区 ② 本就不该按孤立线的标准双峰要求。",
         "pass": "三项都通过 → 物理结论可信；任何一项不通过 → 停止解读，回 step 1 排查（形态类先看线密度）"},
        {"step": 6, "name": "自检 + 二次审核（必须）",
         "rule": "每次绘图/下结论前，必须用 tdlas_review（或读取返回的 validation）做自动校验；"
                 "校验 10 项：波数轴对齐、DAS-理论一致、αL 弱吸收、是否孤立线、调制系数 m、"
                 "采样率、ADC 动态范围、归一化方法、噪声、etalon 条纹。overall=fail 时**不得下结论**，"
                 "先修 fail 项；warn 项须在结论中向用户说明。",
         "pass": "validation.overall=pass 或（warn 项已向用户说明）"},
        {"step": 7, "name": "输出结论",
         "rule": "按此顺序：① 工况（物种/波段/T/P/x/L/fm/调制系数）；"
                 "② normalization.method 及 I0；③ 2f（或归一化 2f）峰值与位置；"
                 "④ 噪声分解（shot/thermal/RIN/1f）；⑤ validation 结论（pass/warn/fail）。"
                 "所有用默认值的参数必须显式标注「默认值」。",
         "pass": "结论完整、可复现、附校验结论"},
    ],
    "image_layout": {
        "总则": "图是用户唯一直接看到的产物，**规范性优先于美观**。绘图前先确认：技术名、"
                "归一化/基线方法、线型含义、剔除区——缺一项这张图就不能用于汇报。",
        "何时生成图": "只有显式 save_png=true 才生成图像；用户说'画图/给张图/画 WMS/画 DAS'时，"
                    "**必须传 save_png=true**，否则数据库里只有数值、用户拿不到图。"
                    "绘图后把返回的 png / png_overlay 路径告诉用户。",
        "★ 自适应选图（按用户需求决定出什么图，不要一律给六子图）": {
            "判断依据": "从用户话里取意图 → 选图型 → 选参数。**用户要什么就给什么，别把标准六图当唯一答案。**",
            "意图 → 图型/参数": {
                "默认 / '给我 CH4 的图' / '画 WMS 图'": "标准 6 子图（panels 缺省 all），单浓度",
                "'画多浓度 / 不同浓度对比 / 标定曲线'": "传 x_list=[...] + save_png=true → 主图 ②~⑤ 面板**按 ppm 叠加各浓度**（纵轴按全部浓度统一）+ 附加 png_overlay 单用途对照",
                "'混合气 / 含 X% 甲烷和 Y% CO2'": "传 mixture='CH4:0.01,CO2:0.04' → αL 面板自动叠加各组分曲线，**不新增图**",
                "'只要相位匹配的 X 分量 / 不正交 / 单通道锁相'": "传 return_xy=true，从 wms_raw_xy 取 X1f_c/X2f_c（相位匹配分量）作图；"
                                                        "**说明差异**：正交解调取 √(X²+Y²)（默认），单通道只取 X，后者对相位失配更敏感",
                "'系统选型 / 光程要多少 / 检测限'": "tdlas_detection_limit_scan（1×2：LOD vs 光程、LOD vs 参考浓度）",
                "'只看 2f 曲线' / '只要吸光度'": "panels 子集（f2 / al）；**注意**非 6 面板时引擎改竖排堆叠",
            },
            "无法判断时": "先按标准 6 子图出，并在回答里说明'如需多浓度叠加/混合气分组/只看某分量请告知'——"
                          "**不要沉默地只给一种**。",
            "禁止": "用户明确要混合气却只画单组分；要标定曲线却不出 png_overlay；要 X 分量却给正交幅值而不说明。",
        },
        "四类图（按工具区分，勿混用）": {
            "① WMS 仪器链路图": {
                "工具": "tdlas_wms_instrument",
                "布局": "3 行 × 2 列共 6 面板，figsize≈14×10，每格约 2:1（横长竖短，利于读线形）",
                "面板顺序（左→右、上→下）": [
                    "① 波长调制 V(t)（三角波+正弦调制；横轴 时间(ms)，纵轴 驱动电压(V)）",
                    "② 直接吸收 DAS（无调制链路）",
                    "DAS 吸光度 vs 数据库理论值（同图，理论值为虚线对照）**← 与 ② 同一行右侧**",
                    "③ 一阶谐波 1f（纵轴 1f(V)）",
                    "④ 二阶谐波 2f（纵轴 2f(V)，单列避免与 1f 混读）",
                    "⑤ 归一化 2f（标题含归一化方法；纵轴 a.u.）",
                ],
                "要点": "**注意 ② 与 'DAS 吸光度' 是同一行的两个面板**——② 是 PD 原始信号，"
                        "右格才是 αL 与理论对照；不要把两者当成一个面板描述。",
            },
            "② DAS 仪器链路图": {
                "工具": "tdlas_das_instrument",
                "布局": "5 行 × 1 列竖排，figsize≈9.5×12",
                "面板顺序": ["drive V (V)", "power (mW)", "PD out (mV)",
                             "absorbance（吸光度）", "（第 5 格为链路补充信息）"],
                "备注": "该图轴标签为**英文**（与 WMS 的中文标签不同），描述时按图实际内容陈述，不要臆造中文标题。",
            },
            "③ DAS 时域链路图": {
                "工具": "tdlas_das_chain",
                "布局": "4 行 × 1 列竖排，figsize≈9×10",
                "面板顺序": ["三角波时序", "PD 原始时序", "拟合基线与对照", "absorbance 提取结果"],
                "横轴": "时间 (ms) 为主",
            },
            "④ 检测限扫描图": {
                "工具": "tdlas_detection_limit_scan",
                "布局": "1 行 × 2 列，figsize≈14×6",
                "面板顺序": ["LOD vs 光程 L（横轴 光程 L(cm)）",
                             "LOD vs 参考浓度 x（横轴 参考浓度，弱吸收下应近似平线）"],
                "用途": "系统选型：看加光程能把 LOD 降到多少",
            },
            "⑤ 多浓度同图（主图叠加 + 附加 png_overlay）": {
                "何时": "传 x_list（多浓度）+ save_png=true",
                "主图": "标准 6 子图的 ②~⑤ 面板按 viridis 配色叠加**全部浓度**，图例标 ppm；"
                        "纵轴按全部浓度的有效区统一（低浓度不会被压成平线）；① 驱动电压共用仍单条",
                "附加图": "png_overlay：单用途对照（归一化 2f/1f 一条曲线看线性/饱和），与主图 png 并存",
                "命名": "主图 png + 附加 png_overlay",
            },
        },
        "线型约定（每张图都必须遵守）": "实线=有效数据；虚线=理论参考（如 HITRAN 理论 αL）；"
                          "点线/灰点=剔除区（三角波转折点，不可信）；"
                          "**每种线型必须在图例里注明含义**。",
        "横轴约定": "驱动电压用**时间**；其余一律用**扫描波数**（不含 ±a 调制摆动的瞬时波数）"
                    "——用瞬时波数会把曲线折成'水平条纹'乱麻。",
        "剔除区": "扫描两端按 trim_frac（默认 12%）剔除，图上以红色带标出；"
                  "纵轴范围按有效区确定，避免剔除区伪影压扁曲线。",
        "图外必须同步给出的解读": [
            "本次用的技术（WMS / DAS）与为什么选它（线密度）",
            "归一化方法（2f/1f 或 2f/I0）及是否背景扣除",
            "基线处理方式（理想 I0 / 多项式拟合 / 是否触发回退）",
            "validation.overall 与其 fail/warn 项（图好看不代表数可用）",
        ],
        "禁止": "① 不传 save_png 就说'已生成图像'；② 凭印象描述图上没有的内容；"
                "③ 把 1f 与 2f 画进同一个面板；④ 用理想仿真图暗示实测结果。",
        "完整描述契约": "用户要'图里有什么'时，按面板顺序逐个说明：面板标题 → 横轴量 → 纵轴量 → "
                        "该格的结论（如'2f 呈标准双峰，峰位间隔 Δν≈±0.7a'）。",
    },
    "defaults_when_unknown": "所有物理参数未给时按以下顺序索取：① 实测标定值 → "
                             "② 器件型号（AI 自己检索规格书）→ ③ 引导用户现场标定 → ④ 保留内置默认并**显式标注**「默认值 X」。",
    "datasheet_lookup": {
        "何时": "用户提供了器件型号（如 DAQ 型号、DFB 激光器型号、光电探测器型号）时。",
        "动作": "AI **必须**联网检索该型号的官方 datasheet / 规格书提取参数（用 web 搜索 + 打开官方页面），"
                "不要只把型号当标签、也不要凭记忆编数字。",
        "按器件类别要查的参数": {
            "数据采集卡 DAQ": ["采样率上限 fs_max (S/s)", "分辨率 (bit)", "量程 (±V)", "输入噪声/输入阻抗"],
            "激光器驱动 / 电流源": ["V→I 跨导或调谐响应", "电流量程 (mA)", "调制带宽 (kHz)", "输出噪声 (µA/√Hz)"],
            "DFB / 可调谐激光器": ["中心波长 / 波数", "调谐系数 dν/dI (cm⁻¹/mA)", "阈值电流 i_th (mA)",
                              "输出功率 (mW)", "线宽 (MHz)"],
            "光电探测器 PD": ["响应度 resp (A/W)", "带宽 bw (Hz)", "跨阻增益 gain (V/A)",
                          "NEP (W/√Hz)", "饱和功率"],
        },
        "查到后": "把规格书参数填进仿真对应字段，并在 assumptions 里标注「来源：<型号> datasheet」。",
        "查不到或无网络": "退回到优先级 ③（引导现场标定）或 ④（默认值 + 显式标注），**不得编造规格书数值**。",
    },
    "das_vs_wms": {
        "本质": "WMS 通常强于 DAS。DAS 信号在 DC，受害于 1/f 噪声与激光慢漂移；"
                "WMS 把信号搬到 fm（30 kHz）用窄带锁相提取，避开 1/f，"
                "且 2f/1f 归一化抵消光强波动（免标定）。",
        "公平对比前提": "DAS 与 WMS 必须用同一套噪声模型（白噪声 + 1/f 粉红噪声 + 慢漂移）与同源噪声；"
                "DAS 漏加噪声等于作弊，会得出'WMS 反而差'的假象。",
        "正确判据": "看浓度反演稳定性/检测限，而非单周期 σ；2f/1f 不应在非吸收区（2f、1f 都≈0）测噪声。",
        "何时用 DAS": "需要绝对浓度、或谱线密集区想看直观包络时；",
        "何时用 WMS": "痕量检测、抗 1/f 与漂移、在线免标定时。",
        "谱线密度与波形": "孤立单线（n_lines ≤10）→ 2f 呈标准双峰；密集谱区 → 2f 多峰叠加（DAS 包络更直观）。"
                          "这只是'波形形态'问题，不代表 DAS 更强。",
    },
    "edge_definition": "edge 指**驱动电压**方向（daq_triangle 前半=电压上升、后半=电压下降）；"
                       "因 dν/dI<0（真实 DFB 激光：电流↑→波长红移→波数↓），电压上升沿对应波数下降、"
                       "下降沿对应波数上升。工具把所选方向反转为波数递增输出。",
    "pd_baseline_slope": "PD 原始信号含光强斜坡（L-I 曲线），且 dν/dI<0 使'波数递增'对应'光强下降'，"
                        "故默认 edge=rising 的 PD 基线呈**下降沿**——这是激光器真实特性，不是错误。"
                        "如需光强上升沿，用 edge=falling；DAS 吸光度已除以 I0 消除斜坡，不受影响。",
    "das_baseline_method": {
        "仿真做法": "DAS 基线用**理想 I0**（无吸收光强）：I0 = p_laser × throughput × resp × gain，"
                    "直接用 -ln(v_das / I0) 得 αL。因为仿真里 I0 可精确算出，无需拟合。",
        "为何不用非吸收区拟合": "真实实验常用'非吸收区多项式拟合'估 I0，但**密集谱区没有非吸收区**"
                "（如 C2H6 2963-2966 有 159 条线），off 掩码为空 → 拟合退化、基线把吸收也平均进去，"
                "导致 DAS 峰值偏移/为负（已实测：峰值偏 1.4 cm^-1、相关系数仅 0.015）。",
        "真实实验对应": "实测无法直接得 I0，应：① 扫到线翼外取非吸收基线；② 或充纯缓冲气测背景谱扣基线；"
                "③ 或用相邻无非吸收区时做多项式外推。仿真用 I0 是'已知真值的上限'，供验证用。",
        "告知": "解读 DAS 时须向用户说明：本仿真的 DAS 基线用的是理想 I0（非吸收光强），"
                "真实实验需另做背景扣除，DAS 实际精度会低于此理想值。",
    },
    "condition_adaptation": {
        "规则": "工况参数（T/P/x/L_cm）未给时，按物种用 SPECIES_PROFILES 自动推荐（自适应），"
                "不套用全局默认；返回 condition_advice 告知推荐值。"
                "**推荐波段的可达性也在 condition_advice 里**（波段可达性/laser_params_needed），"
                "推荐前先核对，否则用户按推荐选波段会直接撞上激光调谐范围。",
        "主动询问": "绘图前必须**主动向用户确认工况**：物种/波段是否正确、浓度量级、光程、"
                    "T/P；用户不确定时给出 condition_advice 的推荐。",
        "弱吸收校验": "推荐工况应使 αL 落在 1e-3 ~ 1e-1（弱吸收线性区）；"
                      "若 αL>0.1 应建议降低 x 或 L_cm，若 <1e-5 应建议增大。",
    },
    "alpha_reporting": {
        "原则": "α（吸收系数 / αL）峰值随 T、P、网格步长 step、翼截断 wingHW、波数窗口 变化——"
                "**裸报一个 α 数值不可复现、不可比较**。故给出 α 峰值时须能同时给出这五项语境。",
        "何时必须报（自适应）": "看返回的 alpha_report.needs_report：True 时必须报"
                                "（本会话首次给出 α 峰值，或语境相对上次发生变化）；"
                                "False 说明语境未变、已播报过，可省略以保持简洁。",
        "报什么": "α 峰值数值 + T(K) + P(atm) + step(cm⁻¹) + wingHW(cm⁻¹) + 窗口(cm⁻¹)，缺一不可；"
                  "具体值见 alpha_report.alpha_peak_context。",
        "注意": "不得为求简洁而省略语境后再对 α 做定量结论；语境不同的两次 α 不可直接比较。",
    },
    "fringe_reporting": {
        "原则": "etalon 干涉条纹是 TDLAS 痕量检测的**头号系统性误差**：两个平行且反射率不可忽略的面"
                "（窗片/透镜/光纤端面）构成 F-P 腔，产生周期 FSR=1/(2nd)、峰-峰对比度≈4R/(1−R)² 的透过率起伏，"
                "其 2f 与吸收 2f 同形。模型**默认关闭**（fringe=False），绝不静默注入系统性误差。",
        "何时问": "用户提到窗片 / 光纤 / 滤光片 / 未镀膜或未楔化窗片时，应主动询问是否建模；"
                  "开启后若未给几何参数，返回的 param_requests 会列出 fringe_n / fringe_d_cm / fringe_R。",
        "汇报内容": "看返回的 fringe_report：needs_report=True（本会话首次启用或条纹语境变化）时，须说明"
                    "FSR 与吸收线宽的关系、确定性条纹可被背景扣除而只有漂移残留、"
                    "以及压不掉条纹时应采取的物理措施（窗片楔化 / AR 镀膜 / 扫频平均）。",
        "禁止": "不得把 etalon 条纹当成可被降噪 / 多次平均消掉的随机噪声——固定腔长的条纹是确定性项。",
    },
    "fidelity_reporting": {
        "原则": "仿真只包含**已建模的效应**；未建模项（自展宽、线混合、暗电流、前放 1/f…）"
                "在当前工况下可能主导真实误差。**点值不等于带误差的结果。**",
        "单一真源": "能力登记表在 tools/tdlas_fidelity.py（EFFECTS）：每项效应的实现位置、"
                    "是否默认生效、已知缺口写在同一张表里，并由 audit 与源码证据交叉核对。"
                    "本工具返回的 fidelity 块即该表的结构化快照，**以它为准**，勿凭记忆复述。",
        "何时报": "① 用户问「这个结果可信吗 / 误差多大」；② 给出任何定量结论（浓度、LOD、灵敏度）时；"
                  "③ 结论涉及 fidelity.not_implemented 中某项时——例：高浓度（自展宽）、"
                  "密集谱区（线混合）、痕量 LOD（前放 1/f 未建模 ⇒ LOD 偏乐观）。",
        "报什么": "① 本次实际生效的效应（fidelity.implemented）；"
                  "② 会影响该结论的未实现项（fidelity.not_implemented）；"
                  "③ 明确「这是点值，未含系统不确定度」。",
        "禁止": "不得把未实现项说成「已建模」；不得把点值当带误差的结果呈现；"
                "不得用 n_repeats 的统计散布冒充总不确定度（它只含 run-to-run 随机分量）。",
    },
    "clarify_protocol": {
        "触发": "返回的 clarify.needed=True（有缺省参数）时，必须进入澄清流程。",
        "流程": "① 按 clarify.questions 向用户提问；② 收到回答后填入对应参数重跑；"
                "③ 用户明确说'用默认值'才可跳过该项；④ 全部确认后才绘图/下结论。",
        "强制": "clarify.instruction 明确要求'先问再出结果'，这是硬约束，不是建议。",
        "多轮": "支持多轮：每次用户补充一个参数，就少问一个（questions 会随 assumed 缩小）。",
        "提问工具": "AI 必须用**原生结构化提问工具**（AskUserQuestion 类，点击式选择框）"
                    "把 clarify.questions 渲染成选择题，**禁止用纯文字列表让用户打字回答**；"
                    "1 次 1–4 题、每题 2–4 个固定选项 + '其他'自由输入；"
                    "超过 4 题时按优先级分批多轮：波段 > 浓度/光程 > T/P > 器件 > 噪声。",
    },
    "noise_and_interaction": {
        "默认": "**默认：RIN 与 1/f（漂移/粉红）关，但散粒/热噪声恒在**——它们是物理固有项"
                "（只取决于光电流与带宽，量级通常 0.01–0.1 mV），无法通过参数关闭；"
                "要让噪声严格为零请设 physical_noise=False（此时为纯理论对照，结果逐位可复现）。"
                "随机种子默认 seed=0 → 默认参数下结果可复现；返回里的 seed_used 即实际所用种子。",
        "询问": "MCP 必须在绘图/解读前**主动询问用户**：是否需要加噪声？加哪类？多大？"
                "可选：① RIN 白噪声(rin) ② 1/f 慢漂移(drift_frac) ③ 1/f 粉红(flicker_frac)。"
                "散粒/热噪声为物理固有、量级极小，**恒在**（若用户要求绝对无噪，用 physical_noise=False）。",
        "透明化": "每次返回必须把 noise_breakdown_mV + noise_1f 原样告知用户，"
                  "并明确「本次是否加了噪声、加了哪些、幅度多少」。",
        "多交互": "MCP 服务要**多与用户交互**，而非一次性吐结果：① 先确认工况（物种/波段/T/P/浓度/光程）；"
                  "② 主动问噪声需求；③ 解读前确认归一化方法；④ 主动问是否调噪声/换孤立线。",
    },
    "glossary": {
        "αL": "吸光度（吸收系数×光程），无量纲；≪1 才算弱吸收，DAS/2f 才与浓度成正比",
        "HWHM": "吸收线半高半宽（cm⁻¹），决定最优调制深度",
        "m": "调制系数 = 调制深度 a ÷ HWHM，最优约 2.2",
        "fm": "正弦调制频率（把信号搬到高频，避开低频噪声）",
        "fscan": "三角波扫描频率（扫过整条吸收线）",
        "RIN": "激光相对强度噪声，常为 TDLAS 主导噪声源",
        "2f/1f": "用 1f 谐波归一化 2f，抵消光强波动；弱吸收下正比于浓度（免标定核心）",
        "LOD": "检测限（最小可测浓度）",
        "m 优化": "工具会自动按 m≈2.2 反算正弦调制幅值；如需手动指定可用 mod_amp_V",
    },
}


_X_LIST_MAX = 64


QUANTITATIVE_BLOCKS = ("assumptions", "param_requests",
                       "warnings", "validation", "alpha_report", "fringe_report", "fidelity",
                       "provenance")


CONTRACT_BLOCKS = {
    "tdlas_wms_instrument":  QUANTITATIVE_BLOCKS,
    "tdlas_review":          QUANTITATIVE_BLOCKS,
    "tdlas_das_instrument":  QUANTITATIVE_BLOCKS,
    # 下列工具不走定量链路，只声明它们真正会产生的块
    "tdlas_simulate":        ("assumptions", "warnings", "alpha_report", "fidelity"),
    "tdlas_das_chain":       ("assumptions", "warnings", "alpha_report", "fidelity"),
    "tdlas_invert":          ("assumptions", "needs_confirm", "warnings", "fidelity"),
    "tdlas_detection_limit": ("assumptions", "needs_confirm", "fidelity"),
}


_INSTR_KEYS = ("scan_span_cm", "amp_V", "freq_Hz", "offset_V", "phase_deg", "eta_VI", "dnu_dI",
               "wn_ref", "i_ref", "i_th", "eta_IP", "fs", "n_samples", "adc_bits",
               "v_range", "throughput", "resp", "gain", "bw", "rin",
               # 调谐二阶非线性（两条链都经 voltage_to_laser 使用）
               "d2nu_dI2",
               # 严格理想仿真开关：False = 连散粒/热也不注入
               "physical_noise",
               # 明知扫描段有暗区（激光未出光）仍要计算的显式开关：
               # 默认 False ⇒ 引擎拒绝"部分出光"的扫描（那里的 2f/1f 是失真的，且旧版不报错）
               "allow_partial_dark",
               # etalon 干涉条纹（默认关，仅显式 fringe=True 时生效）
               "fringe", "fringe_n", "fringe_d_cm", "fringe_R", "fringe_fsr",
               "fringe_contrast", "fringe_phase_rad", "fringe_drift_frac")


_FRINGE_KEYS = ("fringe", "fringe_n", "fringe_d_cm", "fringe_R", "fringe_fsr",
                "fringe_contrast", "fringe_phase_rad", "fringe_drift_frac")


_NO_CONFIRM = {"amp_V", "offset_V", "background_subtract"}


_SCENE_DEFAULTS = {"T": 296.0, "P": 1.01325, "x": 1e-3, "L_cm": 50.0,
                   "edge": "rising", "fit_order": 3, "fit_frac": 0.3}


_LASER_ECHO_KEYS = ("eta_VI", "dnu_dI", "d2nu_dI2", "wn_ref", "i_ref", "i_th", "eta_IP")


_WMS_ONLY_KEYS = ("mod_freq_Hz", "mod_amp_V", "mod_phase_deg", "m_opt", "lockin_avg",
                  "lockin_stages", "drift_frac", "flicker_frac", "background_subtract",
                  "edge", "trim_frac", "am_i0", "am_i2", "am_psi1", "am_psi2",
                  "norm_lock", "lock_kind", "zero_phase")


_INSTR_KEYS_WMS = _INSTR_KEYS + _WMS_ONLY_KEYS


__all__ = [
    "AI_INTERACTION_GUIDE",
    "CLARIFY_QUESTIONS",
    "CONTRACT_BLOCKS",
    "EDGE_TECH_NOTE",
    "PARAM_ACQ_GUIDE",
    "QUANTITATIVE_BLOCKS",
    "SPECIES_PROFILES",
    "_ALPHA_CTX_FIELDS",
    "_DEVICE_RULES",
    "_DEVICE_SALIENT_KEYS",
    "_DEVICE_TYPES",
    "_DEVICE_TYPE_CN",
    "_FRINGE_KEYS",
    "_INSTR_KEYS",
    "_INSTR_KEYS_WMS",
    "_LASER_ECHO_KEYS",
    "_NO_CONFIRM",
    "_SCENE_DEFAULTS",
    "_SEV_ADVISORY",
    "_SEV_BLOCK",
    "_SEV_DISCLOSE",
    "_SEV_ORDER",
    "_WMS_ONLY_KEYS",
    "_X_LIST_MAX",
]

