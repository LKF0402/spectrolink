# Changelog

本文件以最简形式记录功能演进（不做过程细节罗列）。

## [1.0.0] — 2026-11-16

**首个正式版本**：7 技术（TDLAS-DA/WMS · LITES · NDIR · CRDS · FTIR · DOAS）、6 个 MCP server、共用 `spectrolink_core` 物理内核；统一交互契约与校验层（各技术不再只有一句 `overall=warn`）、协议层单一实现（JSON-RPC 语义只此一份）、部署形态收敛为本地 stdio。离线契约自检 191 项与保真度审计同为 CI 硬门禁。

以下各轮为达成 1.0.0 的演进记录（按轮次原样保留）。

### 第二十五轮：CRDS / NDIR / FTIR / DOAS 接入交互契约 + 标定数值修复
- 新建 `spectrolink_core/interaction_server.py`：把 `interaction_block` 统一接到四 server 的 `DISPATCH`，只做一次包装；会话态改为进程内存储，避免给只读安装目录增加写盘依赖，`*_selftest` 不参与记账
- 新建 `spectrolink_core/validation.py`：`check` / `validation_block` 统一 `checks[]` 与 `overall` 归并；四 server 不再只有一句 `overall=warn`
- CRDS / NDIR / FTIR / DOAS 的仪器/分析工具统一返回 `interaction` + `next_required_actions`，动作只依据真实字段（浓度定义域、`x_error_frac`、`ringdown_fit.r2`、`fit.r2`、`r_squared`、`max_abs_err_frac`、非 HITRAN 谱源、缺输入 `usage`）
- NDIR 标定符号修复：`calibrate()` 的 `R²/R0_fit` 与 `A_fit` 符号不一致，默认 `r2=-13.0 / R0_fit=0.9951`；统一到 `y=-A·x` 后 `r2=1.0 / R0_fit=1.0`，selftest 增加 `r2/R0_fit` 守卫
- NDIR 反演域校验：默认输入解出 `x=1.389>1` 时返回 `validation.overall=fail` 并阻断结论，不再把越界值当浓度
- DOAS 标定误差口径修复：`max_abs_err_frac` 在 `x=0` 处除以 `1e-30` 产生 `2.3e10` 虚假巨值；改为按浓度满量程归一化，默认 `0.0`，selftest 增加守卫
- FTIR / DOAS 无参数反演：`usage` 提示不再被当成“有结果”，`validation.overall=fail` + `input_required` 阻断结论
- CRDS / FTIR 补强吸收动态范围守卫：τ 缩短 >98%、恢复谱 T≤2% 判 `fail`，50%/10% 判 `warn`，避免在不可定量区照常给浓度
- 停掉遗留 `doas_mcp.py --http --port 8816` 进程；`hitran.py` 的 HTTP 并发注释改为本地多线程口径

### 第二十四轮：协议层收敛为单一实现 + 代码卫生
- 新建 `spectrolink_core/mcp_runtime.py`：`schema_index` / `validate_args` / `make_handle_request` / `serve_stdio`，JSON-RPC 语义只此一份
- 六个 server 的 `_validate_args` + `handle_request` + stdio 循环删除，改为 `make_handle_request(...)` 绑定 + `serve_stdio`；工具面、`DISPATCH`、`--selftest` 行为不变
- 行为统一为严格口径：crds/ndir/ftir 此前**不校验必填与未知键**（拼错参数名被静默丢弃、工具照常返回"看起来正常"的结果），doas 此前无批量/通知/校验且能吃位置参数——现全部与 tdlas 同一严格语义
- 新建 `spectrolink_core/jsonio.py`：`atomic_write_text` 从 `lites_mcp` 与 `tdlas_state` 两份 28 行副本收敛为一份（Windows `os.replace` 重试/降级语义不变）
- 新建 `spectrolink_core/fidelity.py`：`audit_effects` / `fidelity_summary` 的判定逻辑从 tdlas/lites 两份 fidelity 脚本收敛为一份（各技术只保留 EFFECTS 登记表与薄封装），两套口径不再可能漂移
- 新建 `spectrolink_core/interaction.py`：证据路径解析（`ev_ok`）、动作指纹（`action_sig`）、按需下发与 stage 判定（`interaction_block`）收敛为一份；各 server 只提供本技术的动作清单与严重度常量——此前这段 68 行在 tdlas/lites 各有一份，`conclusion_allowed` 语义存在漂移风险
- 新建 `spectrolink_core/report_blocks.py`：工况取值、物种缺省、设备参数校验、α 语境播报、etalon 条纹播报的判定与措辞收敛为一份（会话读写由各 server 以回调注入）
- 删除 lites 从 tdlas 拷来但从未接线的死代码：`_resolve_conditions`（引用了根本不存在的 `_SCENE_DEFAULTS`，一旦调用必 NameError）、`_species_defaults`、`_alpha_report_block`、`_fringe_report_block`，以及 `build_next_actions` 里永远无法触发的 α/条纹分支与对应说明（LITES 没有 etalon 模型，原说明会让 AI 去找不存在的字段）
- 删除死代码：`tdlas_mcp.apply_contract_blocks`（从未被调用，契约块由各工具手拼、契约自检直接调 `CONTRACT_BLOCK_PRODUCERS` 校验）、`tdlas_constants._MEANINGLESS_NAME_RE`（定义为 None 且全仓无引用）
- 未用 import 清零：`tdlas_mcp` 去掉 `QUANTITATIVE_BLOCKS` / `_DEVICE_RULES` / `_MEANINGLESS_NAME_RE`（`_WMS_ONLY_KEYS` 保留，契约自检按模块属性读取）
- 宽异常收窄：可选依赖加载 `ImportError`；`lites_tools` 斜率拟合收窄到 `ValueError/TypeError/LinAlgError`、设备构建收窄到 `TypeError/ValueError`；`tdlas_state._device_provenance` 收窄到 `KeyError/TypeError/ValueError/OSError`；编码重配收窄到 `AttributeError/ValueError/OSError`。产品代码仅剩 6 处刻意宽兜底（HITRAN 降级 ×3、selftest/保真度探针 ×3），均带注释说明
- 仓库根清理：22 个未跟踪 scratch（`_test_*` / `_plot_*` / `_fix_*`）与 3 个 `.bak` 备份归档到 `tmp/legacy_root/`（仍被 gitignore 覆盖），根目录不再污染
- 文档同步：README 架构表、TECHNICAL §8「协议层单一实现」
- **LITES 交互契约真正接线**：`lites_mcp._interaction_block` 此前从未被任何工具调用，`interaction` 恒为 `{}`、`next_required_actions` 恒为空；现 9 个仪器/分析工具统一下发，动作清单改为只依据 LITES **真实产出**的字段（`validation` / `result.x` / `linearity_check` / `assumptions` / `findings`），删掉照抄 TDLAS 的 `warnings` / `normalization` / `fidelity` / `clarify` 永不触发分支
- `lites_invert` 新增物理校验：`x ∉ (0,1]` 判 `fail`（基线过扣/灵敏度异常/参数不同源），`αL ≥ 0.05` 判 `warn`（线性反演误差 >2.5%）；报出浓度必须同时说明未附不确定度
- `_block` 的字符串提示统一转为动作 dict，`next_required_actions` 在两种技术下不再混用两种类型；会话写盘失败时降级为「不记账、每次重新下发」，只读安装不再让工具调用失败
- LITES schema 与实现对齐：`lites_forward` 补 `wn_cm1`（QTF 全波段吸收率模型）、删实现中从未使用的 `species`；`lites_waveform` 补 `gas` / `wn_center` / `scan_span_cm` / `iso`（真实 HITRAN 多线波段，此前功能可达但 AI 无法按 schema 调用）；生成器二次运行 SHA256 不变（幂等）
- 删除 lites 剩余 TDLAS 复制残留与假功能（器件库读写、物种推荐、激光可达性、三角波说明、`AI_INTERACTION_GUIDE`、`_fidelity_digest`、`adaptive_condition` 等），`lites_mcp.py` 1356 → 909 行；`server-lites/SKILL.md` 参数口径修正（`wn_cm1` 属 `lites_forward`，`lites_waveform` 走 `gas`+`wn_center`）
- pyflakes 全仓清理：未用 import（`tdlas_mcp` 的 `os`/`time`/`_atomic_write_text`、`tdlas_state` 的 `os`、`alpha_crossval` 的 `cmath` 等）、未用局部变量、无占位符 f-string；剩余仅契约测试按模块属性读取的 4 个 `M.*` 名字（已注释「勿删」）
- LITES 正演/波形/扫描补线性区与浓度定义域判定：`lites_forward` / `lites_waveform` 此前对 `x=0.5`（αL≈39）照常返回信号、无任何提示；现 `x ∉ (0,1]` 判 `block_conclusion`，`αL ≥ 0.05` 判 `must_disclose`（与 `lites_invert` 同一阈值 0.05）；`lites_sweep` 的 `power_law_index` 偏离 1 超过 0.10 时也要求披露，避免把饱和扫描当线性标定
- 删除 `lites_device(action="groups")` 空占位（只返回 `{}`、无真实分组）；`lites_resonance` 的输出键 `groups` 改名 `temp_sweep`，避免与器件分组混淆

### 第二十三轮：撤除全部远程能力，项目只做本地 stdio
- 用户结论：远程那套（HTTP 入口 + cloudflared 隧道 + Bearer 鉴权）留着不好用，且项目定位就是本地给 AI 客户端直接调，故整体移除
- 删除 `spectrolink_core/http_transport.py`、`spectrolink_core/tunnel.py`、六个 server 的 `tools/remote_link.py`
- 六个 server 移除 `--http` 分支与 `_arg`/`_run_http` 辅助，入口回到「`--selftest` 或 stdio 循环」两种；`run_mcp_http` 不再被引用
- 路径脱敏未受累：`make_path_sanitizer` 迁到 `spectrolink_core/sanitize.py`（六个 server 返回值仍需脱敏），不依赖任何网络代码
- 文档口径同步：README「远程部署」→「仅本地」、SKILL §5 端口表 → stdio 说明、TECHNICAL、server-lites SKILL、`mcp.config.example.json` 删除 http 条目

### 第二十二轮：异常捕获收窄 + 隧道脚本收敛（隧道部分已被第二十三轮移除）
- 宽 `except Exception` 收窄到真实可达异常类型（tdlas_mcp 15 → 2、tdlas_sim 6 → 0、core/hitran 5 → 1）；只保留两处真兜底：JSON-RPC 分发边界、可选依赖 `tdlas_fidelity` 加载
- ~~新增 `spectrolink_core/tunnel.py`：cloudflared 隧道实现收敛为一份，六个 server 的 `tools/remote_link.py` 统一为薄封装~~（第二十三轮已删除）
- ~~LITES 隧道默认端口 8000 → 8001；四个原本缺失 `remote_link.py` 的 server 补齐~~（第二十三轮已删除）
- 修 DOAS 缺 `--http` 分支：此前 `doas_mcp.py --http` 不监听端口、静默走 stdio，HTTP 部署实际不可用（第二十三轮随远程形态一并移除）

### 第二十一轮：代码组织重构（收敛重复传输层 + 拆分 tdlas_mcp）
- ~~新建 `spectrolink_core/http_transport.py`：MCP Streamable HTTP 传输层与路径脱敏收敛为一份~~（HTTP 部分第二十三轮已删除，脱敏迁至 `sanitize.py`）
- `tdlas_mcp.py` 拆出 `tdlas_constants.py`（25 个纯数据常量，零逻辑零包内依赖）与 `tdlas_state.py`（会话/设备库读写）：主文件 4193 → 3547 行，只保留协议与工具层
- 契约隔离修正：状态文件路径归状态层后，测试隔离必须同时打到 `tdlas_state`，否则会读用户真实设备库、在本地出现假失败；现恢复 191 通过 / 0 失败 / 0 跳过
- 契约项数口径 189 → 191（README、VALIDATION、ADAPTATION_MATRIX）

### 第二十轮：全仓口径整改 + 一键接入可跑通
- 新增 `spectrolink_core/pyproject.toml`：此前 `pip install -e ./spectrolink_core` 直接报 "not a Python project"，README / CI / 一键 prompt 全部卡在这一步
- README 新增零占位一键接入 prompt（AI 自己 clone / 装依赖 / 写 MCP 配置 / 装 Skill / 自检），快速上手补 `git clone`
- 旧仓库名清零：README（CI badge、引用）、USAGE（标题、链接）、server-lites（README / TECHNICAL / CHANGELOG / docs/VALIDATION）
- USAGE 标题改为 SpectroLink，补 LITES / NDIR / CRDS / FTIR / DOAS 的问法
- `server-lites/SKILL.md` HTTP 端口 8000 → 8001（与端口表一致）
- 契约项数口径统一为 189（README、ADAPTATION_MATRIX）

### 第十九轮：吸收谱抓取窗自动外扩（修窗口边缘静默偏低）
- 线表抓取窗改为「计算窗 ± ΩWingHW·Γ(P)」，输出网格与 `WavenumberRange` 不变（CH₄ 窗左缘 −2.74% → 0.00%，峰值不受影响）
- 复用已加载的更宽线表，窗口微调不再重复下载整张表
- `info` 新增 `fetch_window_cm-1`；混合气对 x ≥ 1% 组分显式警告 self-broadening 未计
- 契约自检新增 core 抓取窗 4 项（AST 守"抓取窗 ≠ 计算窗"）

### 第十八轮：实测收尾 + SKILL 渐进式披露 + 端口/目录统一
- 全项目实测通过（六 server 自检 + 契约自检 + 保真度审计 + MCP 协议冒烟）
- SKILL 重构为总入口 + 分技术参考（AI 自动调度、渐进式披露）
- ndir HTTP 端口调整为 8005（消除与 lites 冲突）；本地目录与远端统一命名

### 第十七轮：全项目文档统一为 SpectroLink
- 整仓品牌统一、CI 全仓编译 + 多技术自检硬门禁、lites 子页收敛、内核包说明

### 第十六轮：补齐 NDIR / CRDS / FTIR / DOAS 四 server
- 四技术实现并自检通过（含关键物理修复：FTIR 奈奎斯特/保护带、DOAS 联合最小二乘/列归一化等）

### 第十五轮：SpectroLink 多技术重构（monorepo + 共用内核）
- 抽取 spectrolink_core 共用内核；TDLAS/LITES 独立服务器，数值一致性验证通过

### 第十四轮：同位素开关（iso）
- 支持主同位素 / 全部同位素 / 指定编号，密集谱区峰形对齐实测（radis 交叉验证）

### 第十三轮：锁相低通可配置（boxcar / butter + 零相位）
- lock_kind / cutoff_ratio / zero_phase 透传，契约自检固化

### 第十二轮：多浓度锁定与 DAS 叠加修复
- norm_lock / 调制系数多浓度锁定，修复 DAS 多浓度叠加取键错误

### 第十一轮：多浓度锁定调制系数
- 多浓度扫描复用基准浓度最优调制，防止叠加图幅值失真

### 第十轮：背景扣除默认关闭
- 默认输出原始谱，显式披露三层（返回字段 / warnings / validation）

### 第九轮：标准六子图支持多浓度同图
- 多浓度叠加进标准图、纵轴统一、向后兼容

## [v0.2.0] - 2026-09-19
- fail-closed 收紧、输出凭据 provenance、参数来源追踪、谱线级最小二乘反演、α(ν) 独立交叉验证
- 混合气多组分吸收、交互契约层（next_required_actions）、保真度台账、测量不确定度
- 多浓度 x_list + 防呆与线性/饱和诊断、png_overlay 多浓度同图
- 可达性判据收敛、设备库参数校验、etalon 条纹（默认关）、α 语境自适应播报
- 契约自检体系（离线硬门禁）、CI 加固、安全修复（返回值路径脱敏）

## [v0.1.0] - 2026-09-13
- TDLAS/WMS 仿真内核（DAS + 免标定 WMS + 数字锁相 + 浓度反演 + 检测限）
- 仪器级全链路建模（DAQ→激光→吸收→PD→ADC→锁相）
- AI 交互层（主动澄清 / 自动校验 / 会话状态机 / 工况自适应）
- 设备管理（tdlas_device 四级引用）
- 统一六子图与绘图规范、HTTP 远程直链（cloudflared）
- 安全修复：MCP 返回值路径脱敏
