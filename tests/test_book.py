"""책 예시 숫자 재현 테스트 (수수료 0, 지정가 체결)."""
import pandas as pd
import pytest

from vr.costs import CostModel
from vr.engine import Params, State, run_cycle, _apply_event
from vr.formula import bands, next_v
from vr.ladder import buy_ladder, sell_ladder

NOFEE = CostModel({"commission_rate": 0, "commission_min": 0, "commission_per_share": 0,
                   "sec_fee_rate": 0, "slippage_bps": 0})


def prices(o):
    return [x.price for x in o]


# PART4_03 적립식 -------------------------------------------------------------
def test_cycle1_bands_and_ladders():
    assert bands(4999.5, 0.15, 0.15) == (4249.58, 5749.43)
    assert prices(sell_ladder(5749.43, 110))[:4] == [52.27, 52.75, 53.24, 53.73]
    assert buy_ladder(4249.58, 110, 0.5, 0.75) == []   # Pool 0.5 → 매수 불가


def test_v2_v3():
    v2 = next_v(4999.5, 0.5, 10, 250)
    assert v2 == 5249.55
    assert bands(v2, 0.15, 0.15) == (4462.12, 6036.98)
    v3 = next_v(v2, 250.5, 10, 250)
    assert v3 == 5524.6
    assert bands(v3, 0.15, 0.15) == (4695.91, 6353.29)


def test_cycle2_buy_ladder_nearest_75pct():
    o = buy_ladder(4462.12, 110, 250.50, 0.75, "nearest")
    assert prices(o) == [40.56, 40.20, 39.84, 39.49, 39.14]
    assert round(250.50 - sum(prices(o)), 2) == 51.27
    assert prices(sell_ladder(6036.98, 110))[:4] == [54.88, 55.39, 55.90, 56.42]


def test_floor_rule_never_exceeds():
    o = buy_ladder(4462.12, 110, 250.50, 0.75, "floor")
    assert len(o) == 4 and sum(prices(o)) <= 250.50 * 0.75


def test_cycle3_ladder_9_buys():
    o = buy_ladder(4695.91, 110, 500.50, 0.75)
    assert len(o) == 9 and o[0].price == 42.69 and o[-1].price == 39.80
    assert prices(sell_ladder(6353.29, 110))[:8] == [57.76, 58.29, 58.83, 59.38, 59.94, 60.51, 61.09, 61.68]


@pytest.mark.parametrize("pool,minb,n", [(665.5, 4943.73, 12), (379.57, 4919.43, 7), (1044.70, 4975.96, 18)])
def test_cycle4_ladder_counts(pool, minb, n):
    shares = {665.5: 112, 379.57: 119, 1044.70: 105}[pool]
    assert len(buy_ladder(minb, shares, pool, 0.75)) == n


def _cycle3(low, high, close):
    st = State(V=5524.6, pool=500.50, shares=110)
    bars = pd.DataFrame({"Open": [45.0], "High": [high], "Low": [low], "Close": [close]},
                        index=pd.DatetimeIndex([pd.Timestamp("2021-02-12")]))
    p = Params(G=10, pool_limit=0.75, price_model="limit")
    row = run_cycle(st, bars, p, NOFEE)
    return st, row


def test_example1_partial_buy():
    st, row = _cycle3(42, 46, 45)
    assert st.shares == 112 and round(st.pool, 2) == 415.50 and row["end_eval"] == 5040
    assert next_v(5524.6, st.pool, 10, 250) == 5816.15
    assert bands(5816.15, 0.15, 0.15) == (4943.73, 6688.57)


def test_example2_all_buys():
    st, row = _cycle3(38, 46, 39)
    assert st.shares == 119 and round(st.pool, 2) == 129.57 and row["end_eval"] == 4641
    assert next_v(5524.6, st.pool, 10, 250) == 5787.56


def test_example3_partial_sell():
    st, row = _cycle3(44, 60, 54)
    assert st.shares == 105 and round(st.pool, 2) == 794.70 and row["end_eval"] == 5670
    assert next_v(5524.6, st.pool, 10, 250) == 5854.07


# PART4_04 거치식 / PART4_05 인출식 ------------------------------------------
def test_hold_cycle1():
    assert bands(18300, 0.15, 0.15) == (15555, 21045)
    assert prices(buy_ladder(15555, 300, 2000, 0.5))[:5] == [51.85, 51.68, 51.51, 51.34, 51.17]
    assert prices(sell_ladder(21045, 300))[:5] == [70.15, 70.38, 70.62, 70.86, 71.10]
    assert next_v(18300, 2000, 10) == 18500


def test_withdraw_v2():
    assert next_v(39500, 10000, 20, -250) == 39750


# PART7_02 실력공식 -----------------------------------------------------------
def test_skill_formula():
    assert next_v(18500, 1231.51, 10, 0, "skill", E=16380) == 18287.95
    assert bands(18287.95, 0.15, 0.15) == (15544.76, 21031.14)
    assert next_v(18500, 2356.97, 10, 0, "skill", E=20650) == 19075.64
    assert bands(19075.64, 0.15, 0.15) == (16214.29, 21936.99)
    # 기본공식 비교값
    assert next_v(18500, 1231.51, 10) == 18623.15
    assert next_v(18500, 2356.97, 10) == 18735.70


# PART6_04 목돈 추가/인출 ------------------------------------------------------
def test_lump_sum_add_keeps_pv():
    # 평가금 18,000 (100주 x 180), Pool 2,000, V 20,000 → 1만 달러 추가
    st = State(V=20000, pool=2000, shares=100, cost_basis=18000)
    _apply_event(st, pd.Timestamp("2021-03-01"), 180.0, 10000, NOFEE, [])
    assert st.shares == 150 and round(st.pool, 2) == 3000 and st.V == 30000


def test_lump_sum_withdraw_keeps_pv():
    st = State(V=20000, pool=2000, shares=100, cost_basis=18000)
    _apply_event(st, pd.Timestamp("2021-03-01"), 180.0, -10000, NOFEE, [])
    assert st.shares == 50 and round(st.pool, 2) == 1000 and st.V == 10000
