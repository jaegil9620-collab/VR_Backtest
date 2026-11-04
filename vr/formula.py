"""V 갱신 공식 (PART4_01 기본공식, PART7_02 실력공식)."""
import math

from .utils import rnd


def next_v(V, pool, G, flow=0.0, formula="basic", E=None, digits=2):
    """V_new = V + Pool/G [+ (E-V)/(2*sqrt(G))] + flow

    pool : 사이클 마지막 Pool (적립/인출 반영 전)
    flow : 적립금(+) 또는 인출금(-)
    E    : 사이클 마지막 날 평가금 (실력공식에서만 사용)
    """
    v = V + pool / G
    if formula == "skill":
        if E is None:
            raise ValueError("실력공식에는 E(마지막 평가금)가 필요합니다")
        v += (E - V) / (2 * math.sqrt(G))
    elif formula != "basic":
        raise ValueError(f"알 수 없는 formula: {formula}")
    return rnd(v + flow, digits)


def bands(V, band_low, band_high, digits=2):
    return rnd(V * (1 - band_low), digits), rnd(V * (1 + band_high), digits)
