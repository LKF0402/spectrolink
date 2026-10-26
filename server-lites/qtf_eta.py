#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QTF 器件全波段吸收率 κ_A(λ) —— LITES 的 η_dev 波长化查表模块

来源（实测数据版，见 server-lites/tmp/qtf_absorption_model_v2.py）：
  · 银 n,k = Rakić 1998 数值表（Appl. Opt. 37, 5271；0.248–12.4 µm）
  · 石英 n,k = Franta 2017 熔融石英实测宽谱（refractiveindex.info-database），
    3.33 µm 处经单晶 α-石英透射锚点标定（马欲飞组博论 FTIR：0.75 mm 透射 90%）
  · 器件结构：商用 32 kHz 裸音叉，振臂 250 µm、两侧镀银 0.5 µm、银覆盖率 75%，
    非相干多层膜功率递推（空气|Ag|SiO2|Ag|空气），垂直入射

此处内嵌 20 个关键波长锚点（1–12 µm），log 空间插值，自包含、不依赖运行期文件。
能量守恒 |A+R+T−1| < 1e-15 已验证；0.75 mm 石英透射 91.1%/0/0/0 对撞文献 90/0/0/0。
"""
import math

#: (λ/µm, κ_A) 锚点表（v2 实测数据版，见上述脚本）
_KAPPA_ANCHORS = (
    (1.000, 1.5404e-2), (1.250, 1.2896e-2), (1.500, 1.1560e-2),
    (1.650, 1.1037e-2), (2.000, 1.0260e-2), (2.500, 1.4367e-2),
    (3.000, 1.6464e-2), (3.300, 1.2016e-2), (4.000, 3.1264e-2),
    (4.500, 6.8098e-2), (4.600, 6.2184e-2), (5.000, 2.4551e-1),
    (5.300, 2.5284e-1), (6.000, 2.4996e-1), (7.300, 2.5813e-1),
    (8.000, 1.9513e-1), (9.000, 9.2749e-2), (10.300, 2.2311e-1),
    (11.000, 2.3360e-1), (12.000, 2.4392e-1),
)

#: 默认标定基准波长（µm）：器件 cal_species=C2H2 → 1.53 µm 线；
#: 与 1.367 µm 水线锚点的 κ_A 差异 <0.1%，取用 C2H2 波段
CAL_WL_UM_DEFAULT = 1.53

_WL = [p[0] for p in _KAPPA_ANCHORS]
_KA = [math.log(p[1]) for p in _KAPPA_ANCHORS]

_CLIP_LO, _CLIP_HI = 1.0, 12.0


def kappa_A(wl_um: float) -> float:
    """器件全波段吸收率 κ_A(λ)，1–12 µm，log 插值；越界钳位到端点。"""
    w = min(max(wl_um, _CLIP_LO), _CLIP_HI)
    if w <= _WL[0]:
        return _KAPPA_ANCHORS[0][1]
    if w >= _WL[-1]:
        return _KAPPA_ANCHORS[-1][1]
    # log-log 插值
    lw = math.log(w)
    for i in range(1, len(_WL)):
        if lw <= math.log(_WL[i]):
            x0, x1 = math.log(_WL[i - 1]), math.log(_WL[i])
            y0, y1 = _KA[i - 1], _KA[i]
            t = (lw - x0) / (x1 - x0)
            return math.exp(y0 + t * (y1 - y0))
    return _KAPPA_ANCHORS[-1][1]


def eta_dev_scale(wl_um: float, cal_wl_um: float = CAL_WL_UM_DEFAULT) -> float:
    """波长相对吸收率：κ_A(λ) / κ_A(λ_cal)。

    LITES 绝对电压由标定锚点 g 固定（cal_eta_abs），跨波长信号比由本函数给出：
        V_2f(λ) / V_2f(λ_cal) = η_dev(λ)/η_dev(λ_cal) = κ_A(λ)/κ_A(λ_cal)
    """
    k0 = kappa_A(cal_wl_um)
    return kappa_A(wl_um) / k0 if k0 > 0 else 1.0


def wn_to_wl_um(wn_cm1: float) -> float:
    """波数 cm^-1 → 波长 µm。"""
    return 1.0e4 / float(wn_cm1)


if __name__ == "__main__":
    for w in [1.367, 1.53, 1.65, 3.3, 4.6, 5.3, 7.3, 10.3]:
        print(f"κ_A({w:5.2f} µm) = {kappa_A(w)*100:6.2f}%  scale={eta_dev_scale(w):6.3f}")
