#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 lites_mcp.py 的 _COND_PROPS / TOOLS / _SCHEMA_BY_NAME 段并**就地替换**。

为什么用生成而不是手写：JSON Schema 是纯数据，手写 12 个工具的嵌套字典
极易漏括号（已经在此处栽过 6 次）。用 dict 字面量 + 自渲染输出，
语法由解释器保证，且生成结果可重复。

用法：
    python tools/_gen_schema.py            # 生成并就地替换 lites_mcp.py 中的 schema 段
    python tools/_gen_schema.py --dry-run  # 只打印，不改文件

幂等：生成结果是确定性的，重复运行不产生 diff。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

COND = {
    "T": {"type": "number", "description": "气体温度 K，默认 296"},
    "P": {"type": "number", "description": "气体压力 atm，默认 1.01325"},
    "gamma_L": {"type": "number", "description": "洛伦兹半宽 HWHM cm⁻¹，默认 0.06"},
    "L_gas_cm": {"type": "number",
                 "description": "气体吸收光程 cm；缺省 = 器件标称光程（MPC 为 2580）"},
    "line_strength": {"type": "number",
                      "description": "谱线强度 cm⁻¹/(molecule·cm⁻²)；缺省 = 该器件标定的锚定值"},
    "f_m": {"type": "number", "description": "调制频率 Hz；缺省 = f0/2"},
    "power_mW": {"type": "number", "description": "器件处入射光功率 mW；缺省 = 标定值"},
}

D = {"type": "string"}          # 器件键名
X = {"type": "number"}          # 浓度


# ── 默认器件：从物理内核**单一来源**读取，禁止在此处硬编码 ────────────
# 当前默认：qtf-commercial-decapped（去壳商用 32.768 kHz 音叉晶振）。
# 默认值统一由 _DEF 从物理内核渲染，schema 描述与实际签名不会漂移。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lites_physics as lph  # noqa: E402

_DEF = lph.DEFAULT_DEVICE
_DEF_NOTE = f"默认 {_DEF}（去壳裸音叉）"


def _dev(desc=None):
    """器件键名字段。desc 为 None 时用统一默认说明。"""
    return {**D, "description": desc or _DEF_NOTE}


def tool(name, desc, props, required=None):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props,
                            "required": required or []}}


TOOLS = [
    tool("lites_forward",
         "【LITES 单点正向预测】给定工况返回 2f 幅值，并**显式拆分**"
         "基线 V_2f_baseline（器件自身吸收产生的 offset）与气体增量 V_2f_delta。"
         "做浓度反演时必须用 delta 口径，用总量口径会得到错误的线性度。"
         "返回含 SBR_eta = 气体项/器件项，这是 LITES 区别于 TDLAS 的核心指标。",
         {**COND,
          "device": {**D, "description": "器件键名，如 qtf-commercial-decapped / "
                                         "qtf-commercial-decapped（默认）/"
                                         "用 lites_device(action='list') 查全部"},
          "x": {**X, "description": "摩尔分数；缺省 = 器件标定的锚定浓度"},
          "mod_depth_cm1": {**X, "description": "波长调制深度 cm⁻¹，默认 0.3"},
          "f0_shift_ppm": {**X, "description": "f0 相对标称值的偏移 ppm（模拟温漂/装配误差）"},
          "eta_spurious": {**X, "description": "寄生吸收（窗口污染/散射）附加的 η；不填=0"},
          "species": {"type": "string", "description": "物种名覆盖，默认取器件所属物种"}}),

    tool("lites_sweep",
         "【单变量扫描】对某一参数扫值并自动拟合幂律指数。"
         "可用于验证'信号∝功率''信号∝光程'这类标度律，或找出饱和拐点。"
         "log_scale=True 时按对数均匀取点（适合跨 2~3 个数量级的扫描）。",
         {"device": _dev(),
          "var": {"type": "string",
                  "description": "被扫参数：power_mW / L_gas_cm / x / line_strength / "
                                 "gamma_L / T / f_m / mod_depth_cm1 / f0_shift_ppm"},
          "values": {"type": "array", "items": {"type": "number"},
                     "description": "显式取值列表；给了就不用 n_points 自动生成"},
          "log_scale": {"type": "boolean", "description": "是否对数取点，默认 true"},
          "n_points": {"type": "integer", "description": "自动取点数量，默认 25"},
          "base": {"type": "object", "description": "其余工况的基准值（透传给 lites_forward）"}},
         ["var"]),

    tool("lites_waveform",
         "【合成 2f 波形 + 仪器级出图】沿慢扫三角波逐点计算，生成完整 2f 波形，"
         "并输出 6 子图（吸收线型 / 机械传递函数 / 热扩散低通 / 2f 信号 / 扣基线后 / 噪声预算）。"
         "注意基线**故意不置零** —— 这是 LITES 的真实特征，扣基线动作由调用方决定。",
         {**COND,
          "device": _dev(),
          "x": {**X, "description": "摩尔分数；缺省 = 器件标定值"},
          "mod_depth_cm1": {**X, "description": "调制深度 cm⁻¹，默认 0.3"},
          "f_scan": {**X, "description": "慢扫频率 Hz，默认 0.1"},
          "n_scan": {"type": "integer", "description": "扫描采样点数，默认 4000"},
          "sigma_V": {**X, "description": "输出电压噪声 V，默认 9.16e-6"},
          "seed": {"type": "integer", "description": "噪声随机种子"},
          "save_png": {"type": "boolean", "description": "是否出图，默认 true"},
          "out_path": {"type": "string",
                       "description": "PNG 输出路径；缺省 = docs/assets/lites_waveform.png"}}),

    tool("lites_invert",
         "【浓度反演】由实测 2f 幅值反推摩尔分数。"
         "use_delta=True（默认）表示传入的已是扣基线后的气体增量；"
         "若手持的是含基线的绝对读数，传 use_delta=False 并给出 v_2f_baseline_V。"
         "返回含线性度自检：反推值再正演一轮，核对是否回到原幅值。",
         {**COND,
          "v_2f_measured_V": {**X, "description": "实测 2f 幅值 V"},
          "device": _dev(),
          "use_delta": {"type": "boolean",
                        "description": "true=输入是扣基线后的增量（默认）；false=输入含基线"},
          "v_2f_baseline_V": {**X, "description": "use_delta=False 时必须给出基线值 V"}},
         ["v_2f_measured_V"]),

    tool("lites_mdl",
         "【探测限 MDL】由灵敏度 + 噪声算出最小可探测浓度，并给出 Allan 偏差随积分时间的变化。"
         "关键提醒：LITES 工作在音频段，1/f 噪声主导，"
         "积分时间延长后 MDL 下降会**早于**纯白噪声预期的 √t 规律而饱和。"
         "注意：本工具按**单位浓度灵敏度**外推 MDL，"
         "不需要传参考浓度 x（弱吸收线性区与 x 无关）。",
         {**COND,
          "device": _dev(),
          "sigma_V": {**X, "description": "输出电压噪声 V；缺省 = 器件标定值。"
                                          "**强烈建议给实测值**，否则 MDL 只是模型估计"},
          "n_sigma": {**X, "description": "几倍σ作为判据，默认 1.0"},
          "integration_s": {**X, "description": "指定积分时间 s，返回该点的 MDL"}}),

    tool("lites_noise_budget",
         "【噪声预算】把总噪声拆成 1/f、白噪声、TIA 三部分并给出各自占比。"
         "用于判断'当前 LOD 是被哪一项卡住的' —— 这是决定下一步该改光学还是改电路的依据。",
         {"device": _dev(),
          "bandwidth_Hz": {**X, "description": "等效噪声带宽 Hz，默认 100"},
          "v_rms_1f": {**X, "description": "实测 1f 处电压噪声 V_rms；给了就用实测而非模型值"},
          "c_in_F": {**X, "description": "TIA 输入电容 F；给了才做 TIA 噪声项"},
          "resp_V_per_C": {**X, "description": "电荷灵敏放大器响应 V/C"},
          "compare_literature": {"type": "boolean",
                                 "description": "是否对照文献锚点的噪声值，默认 true"}}),

    tool("lites_device",
         "【器件库】查/建器件。内置器件均来自文献实测锚点（f0、Q、V_2f、噪声、几何）。"
         "action='list' 列全部；'get' 取单个详情；'groups' 看标定分组（同组内可比）；"
         "'build' 由参数现场构造一个虚拟器件做假设性推演。",
         {"action": {"type": "string", "enum": ["list", "get", "groups", "build"],
                     "description": "list / get / groups / build"},
          "key": {"type": "string",
                  "description": "get/build 时的器件键名（build 时为新建的名字）"},
          "overrides": {"type": "object",
                        "description": "build 时的字段覆盖，如 "
                                       "{material:'quartz', f0:9500, q:10800, "
                                       "coating:'pdms', spot_w_m:3e-4}"}},
         ["action"]),

    tool("lites_resonance",
         "【共振跟踪分析】给定温漂或装配误差，算出 f0 偏移、2f 失谐惩罚(dB)、"
         "以及'必须主动跟踪还是被动温控够用'的结论。"
         "LITES 的 Q 很高（~10⁴），失谐 0.01% 就会明显掉信号。",
         {"device": _dev(),
          "delta_T_K": {**X, "description": "温升 K，默认 1.0"},
          "assume_f0": {**X, "description": "用实测 f0 覆盖标称值 Hz"},
          "freq_error_pct": {**X,
                             "description": "直接指定相对频率误差 %（与 delta_T_K 二选一）"}}),

    tool("lites_compare",
         "【多器件统一口径对比】强制所有条目用同一线强/浓度/噪声，输出可比的对比表。"
         "默认对比 3 个典型器件。注意：光程与功率**按各自默认值**，"
         "反映的是'各器件在自己的工作点上'；若要比本征性能，"
         "请在 common 里显式把 L_gas_cm 与 power_mW 设为同一值。",
         {"devices": {"type": "array", "items": {"type": "string"},
                      "description": "器件键名列表"},
          "common": {"type": "object",
                     "description": "统一工况，可含 line_strength / x / sigma_V / "
                                    "L_gas_cm / power_mW"},
          "metrics": {"type": "array", "items": {"type": "string"},
                      "description": "要输出的指标名，默认 ['V_delta','SNR','MDL']"}}),

    tool("lites_review",
         "【实验方案评审】按 LITES 的 7 类已知失效模式逐条检查给定方案，"
         "返回 verdict + 逐条 finding（含严重度与建议）。"
         "7 类失效模式：η_dev 未标定 / 基线漂移误判为信号 / 共振失谐 / "
         "热扩散截止压制 2f / 1/f 噪声主导被误当白噪声 / "
         "MPC 吞吐损失被忽略 / 光功率密度超损伤阈值。",
         {**COND,
          "device": _dev(),
          "x": {**X, "description": "摩尔分数"},
          "mod_depth_cm1": {**X, "description": "调制深度 cm⁻¹"},
          "sigma_V": {**X, "description": "电压噪声 V"}}),

    tool("lites_guide",
         "【使用指南】返回 LITES 的交互协议：参数索取优先级、术语表、参数物理含义、"
         "以及新手最常踩的坑。topic 传入关键词可做术语检索。"
         "第一次接触 LITES 时建议先调这个。",
         {"topic": {"type": "string",
                    "description": "关键词，如 quickstart / SBR / tau_acc / Q / "
                                   "MDL / 噪声；留空返回全量"}}),

    tool("lites_selftest",
         "【全链路自检】跑物理内核 + 仪器口径两层的全部自检项，"
         "返回通过/失败数与逐条日志。改动模型后必须先跑这个。",
         {}),
]


def _py(obj, indent=0):
    """把 JSON 兼容的 dict/list 渲染成 Python 字面量（保证合法缩进）。"""
    pad = " " * indent
    pad2 = " " * (indent + 4)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = []
        for k, v in obj.items():
            items.append(f'{pad2}"{k}": {_py(v, indent + 4)},')
        return "{\n" + "\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        return "[" + ", ".join(_py(v, indent) for v in obj) + "]"
    if isinstance(obj, bool):
        return "True" if obj else "False"
    if obj is None:
        return "None"
    if isinstance(obj, (int, float)):
        return repr(obj)
    return json.dumps(obj, ensure_ascii=False)


HEADER = '''

# ══════════════════════════════════════════════════════════════════════
# JSON Schema 定义
#
# 与实现层的签名**必须一致**：MCP 层 _validate_args 会拦未声明的键，
# 若这里漏写一个参数，AI 传了就会被拒（而不是静默丢弃 —— 这是有意的，
# "以为改了、实际没改"比直接报错危险得多）。
#
# ⚠️ 本段由 tools/_gen_schema.py 生成，请勿手工编辑嵌套结构。
#    改 schema 请改生成脚本后重跑，避免括号错配。
# ══════════════════════════════════════════════════════════════════════

'''

FOOTER = '''

# 工具名 → inputSchema 的索引。_validate_args 依赖它做未知键/必填/类型校验。
# ⚠️ 本段随 schema 一起生成（不要手工挪动），否则重新生成 schema 时会丢失，
#    表现为 tools/call 抛 NameError: _SCHEMA_BY_NAME（已栽过一次）。
_SCHEMA_BY_NAME = {t["name"]: t["inputSchema"] for t in TOOLS}
'''

def render() -> str:
    """渲染完整的 schema 段（含 _SCHEMA_BY_NAME 索引）。"""
    return (HEADER + "_COND_PROPS = " + _py(COND) + "\n\n\nTOOLS = " + _py(TOOLS)
            + "\n" + FOOTER)


def splice(target: Path, block: str) -> None:
    """把 schema 段替换进 target（从 'JSON Schema 定义' 段首到 'def _validate_args'）。

    幂等要求：拼接处必须**恰好**两个空行。两个锚点都用确定性定位：
      · 起点 = 'JSON Schema 定义' 上方那条 ═ 分隔线**之前**的第一个空行再上溯，
        实现上等价于从分隔线行本身开始替换；
      · 终点 = 'def _validate_args' 行，其**前面的所有空行**一并吃掉。
    这样无论跑多少次，结果逐字节一致。
    """
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    # 起点：分隔线（'# ═══...'）中带 'JSON Schema 定义' 的那一行的上一行分隔线
    i_txt = next(i for i, l in enumerate(lines) if "JSON Schema 定义" in l)
    a = i_txt - 1                      # 分隔线行
    while a > 0 and lines[a - 1].strip() == "":
        a -= 1                         # 再上溯吃掉所有前导空行
    # 终点：def _validate_args 行，并吃掉它前面的空行
    b = next(i for i, l in enumerate(lines) if l.startswith("def _validate_args"))
    body = block.strip("\n")
    target.write_text("".join(lines[:a]) + "\n\n" + body + "\n\n\n"
                      + "".join(lines[b:]), encoding="utf-8")


def _selftest(out: str) -> None:
    ns = {}
    exec(out, ns)
    assert len(ns["TOOLS"]) == len(TOOLS), "工具数不符"
    assert len(ns["_SCHEMA_BY_NAME"]) == len(TOOLS), "_SCHEMA_BY_NAME 缺失或有遗漏"
    for t in ns["TOOLS"]:
        assert t["name"].startswith("lites_"), t["name"]
        assert isinstance(t["inputSchema"]["properties"], dict)
        assert t["inputSchema"]["required"] is not None
    print(f"self-check OK: {len(ns['TOOLS'])} tools, "
          f"{len(ns['_SCHEMA_BY_NAME'])} schema entries")


if __name__ == "__main__":
    block = render()
    _selftest(block)
    target = Path(__file__).with_name("lites_mcp.py")
    if "--dry-run" in sys.argv:
        print(f"--- dry run, {len(block)} bytes would be spliced into {target.name} ---")
        print(block[:600])
    else:
        splice(target, block)
        print(f"spliced {len(block)} bytes into {target.name}")
        # 兜底：替换后必须仍能 import
        import importlib.util
        spec = importlib.util.spec_from_file_location("_lmcp_check", target)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        assert len(m.TOOLS) == len(TOOLS)
        assert set(m.DISPATCH) == {t["name"] for t in m.TOOLS}, "dispatch 与 schema 不一致"
        print(f"post-splice import OK: {len(m.TOOLS)} tools, "
              f"schema ↔ dispatch 一一对应")
