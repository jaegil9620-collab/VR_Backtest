"""VR 사이클 엔진.

한 사이클 = (1) 시작 시 V로 밴드·사다리 계산 → (2) 일봉마다 예약 지정가 체결 판정
→ (3) 마지막 날 E 계산, 목돈 이벤트·세금 반영 → (4) V 갱신, 적립/인출.
"""
import math
from dataclasses import dataclass, field

import pandas as pd

from .costs import CostModel
from .formula import bands, next_v
from .ladder import buy_ladder, sell_ladder
from .utils import rnd


@dataclass
class State:
    V: float
    pool: float
    shares: int
    cost_basis: float = 0.0          # 보유분 총 매입원가(수수료 포함, 이동평균법)
    realized: dict = field(default_factory=dict)   # 연도별 실현손익(USD)
    fees: float = 0.0
    taxes: float = 0.0
    in_cash: bool = False            # 안전장치로 전량 현금화된 상태
    low_since_exit: float = 0.0
    stops: int = 0
    reentries: int = 0


@dataclass
class Params:
    G: float = 10
    band_low: float = 0.15
    band_high: float = 0.15
    pool_limit: float = 0.75
    pool_limit_rule: str = "nearest"
    formula: str = "basic"
    lot: int = 1
    digits: int = 2
    price_model: str = "realistic"     # limit | realistic
    same_day_order: str = "sell_first"  # sell_first | buy_first | skip
    cash_yield: float = 0.0
    # 하락 안전장치 (책에 없는 추가 옵션)
    stop_enabled: bool = False
    stop_pct: float = 0.15           # 평가금이 최소밴드보다 이만큼 더 내려가면(종가 기준) 전량 매도
    reentry_mode: str = "rebound"    # rebound(현금화 후 최저 종가 대비 반등) | ma(이동평균 위로)
    reentry_pct: float = 0.20
    reentry_ma: int = 200
    reentry_pool_ratio: float = 0.10  # 재진입 시 현금으로 남길 비율


def _trade(state, date, side, qty, price, cm, trades, reason):
    price = rnd(price, 2)   # 미국 주식 호가 단위 $0.01
    fee = cm.fee(side, price, qty)
    amount = price * qty
    if side == "buy":
        state.pool -= amount + fee
        state.cost_basis += amount + fee
        state.shares += qty
    else:
        avg = state.cost_basis / state.shares if state.shares else 0.0
        gain = amount - fee - avg * qty
        state.realized[date.year] = state.realized.get(date.year, 0.0) + gain
        state.cost_basis -= avg * qty
        state.shares -= qty
        state.pool += amount - fee
    state.pool = round(state.pool, 6)
    state.fees += fee
    trades.append({"date": date, "side": side, "qty": qty, "price": round(price, 4),
                   "amount": round(amount, 2), "fee": fee, "pool_after": round(state.pool, 2),
                   "shares_after": state.shares, "reason": reason})


def _reenter(state, date, close, p, cm, trades):
    total = state.pool
    cash = total * (1 - p.reentry_pool_ratio)
    qty = int(cash // (close * (1 + cm.rate + cm.slip)))
    while qty > 0 and qty * close + cm.fee("buy", close, qty) > cash:
        qty -= 1
    if qty > 0:
        _trade(state, date, "buy", qty, cm.slipped("buy", close), cm, trades, "reentry")
    state.V = rnd(state.shares * close, p.digits)
    state.in_cash = False
    state.reentries += 1


def run_cycle(state, bars, p, cm, cycle_no=0, trades=None, daily=None):
    """사이클 하나를 진행한다. state 를 직접 바꾸고 정리표 한 줄(dict)을 돌려준다."""
    trades = [] if trades is None else trades
    shares0, pool0 = state.shares, state.pool
    lo_band, hi_band = bands(state.V, p.band_low, p.band_high, p.digits)
    fee_fn = cm.fee
    if state.in_cash:
        buys, sells = [], []
    else:
        buys = buy_ladder(lo_band, shares0, pool0, p.pool_limit, p.pool_limit_rule, p.lot, p.digits, fee_fn)
        sells = sell_ladder(hi_band, shares0, p.lot, p.digits)
    planned_buy = sum(o.price * o.qty for o in buys)
    planned_n = len(buys)
    start_eval = None
    conflicts = 0
    first = True
    for date, bar in bars.iterrows():
        if start_eval is None:
            start_eval = shares0 * bar["Open"]
        if p.cash_yield and state.pool > 0:
            state.pool *= (1 + p.cash_yield) ** (1 / 252)
        if first and shares0 == 0 and not state.in_cash and state.pool > 0 and p.pool_limit > 0:
            # 보유 0주이면 사다리 기준가가 없으므로 첫날 시가에 사용한도만큼 매수 (책에 없는 경우)
            budget = min(lo_band, state.pool * p.pool_limit)
            qty = int(budget // (bar["Open"] * p.lot)) * p.lot
            if qty > 0:
                _trade(state, date, "buy", qty, cm.slipped("buy", bar["Open"]), cm, trades, "zero_shares")
        first = False
        hit_b = [o for o in buys if bar["Low"] <= o.price]
        hit_s = [o for o in sells if bar["High"] >= o.price]
        if hit_b and hit_s:
            conflicts += 1
            if p.same_day_order == "skip":
                hit_b, hit_s = [], []
        groups = [("sell", hit_s), ("buy", hit_b)]
        if p.same_day_order == "buy_first":
            groups.reverse()
        for side, hits in groups:
            for o in hits:
                if side == "buy":
                    px = min(o.price, bar["Open"]) if p.price_model == "realistic" else o.price
                    px = cm.slipped("buy", px)
                    if state.pool + 1e-9 < px * o.qty + cm.fee("buy", px, o.qty):
                        continue
                    buys.remove(o)
                else:
                    if state.shares < o.qty:
                        continue
                    px = max(o.price, bar["Open"]) if p.price_model == "realistic" else o.price
                    px = cm.slipped("sell", px)
                    sells.remove(o)
                _trade(state, date, side, o.qty, px, cm, trades, f"ladder#{o.step}")
        stop_line = lo_band * (1 - p.stop_pct)
        if p.stop_enabled:
            close = bar["Close"]
            if state.in_cash:
                state.low_since_exit = min(state.low_since_exit, close)
                if p.reentry_mode == "ma":
                    ma = bar.get("MA", float("nan"))
                    ok = ma == ma and close > ma
                else:
                    ok = close >= state.low_since_exit * (1 + p.reentry_pct)
                if ok:
                    _reenter(state, date, close, p, cm, trades)
                    lo_band, hi_band = bands(state.V, p.band_low, p.band_high, p.digits)
            elif state.shares > 0 and state.shares * close < stop_line:
                _trade(state, date, "sell", state.shares, cm.slipped("sell", close), cm, trades, "stop")
                buys, sells = [], []
                state.in_cash = True
                state.low_since_exit = close
                state.stops += 1
        if daily is not None:
            daily.append({"date": date, "close": bar["Close"], "shares": state.shares,
                          "pool": state.pool, "eval": state.shares * bar["Close"],
                          "total": state.shares * bar["Close"] + state.pool,
                          "V": state.V, "min_band": lo_band, "max_band": hi_band, "cycle": cycle_no,
                          "stop_line": stop_line if p.stop_enabled else None, "in_cash": state.in_cash})
    last = bars.iloc[-1]
    E = state.shares * last["Close"]
    n_buy = sum(1 for t in trades if t["date"] >= bars.index[0] and t["side"] == "buy")
    n_sell = sum(1 for t in trades if t["date"] >= bars.index[0] and t["side"] == "sell")
    return {"cycle": cycle_no, "start": bars.index[0].date(), "end": bars.index[-1].date(),
            "start_eval": round(start_eval or 0.0, 2), "end_eval": round(E, 2),
            "V": state.V, "min_band": lo_band, "max_band": hi_band,
            "start_pool": round(pool0, 2), "end_pool": round(state.pool, 2),
            "start_shares": shares0, "end_shares": state.shares,
            "planned_buys": planned_n, "planned_buy_amount": round(planned_buy, 2),
            "buys": n_buy, "sells": n_sell, "same_day_conflicts": conflicts,
            "close": last["Close"]}


def split_cycles(index, mode="trading_days", length=10):
    """거래일 인덱스를 사이클 번호로 나눈다."""
    if mode == "trading_days":
        return pd.Series([i // length for i in range(len(index))], index=index)
    if mode == "calendar":
        # 시작 주 월요일부터 length 거래일이 아닌 2주(14일) 단위 (length 무시, weeks=2)
        monday = index[0] - pd.Timedelta(days=index[0].weekday())
        return pd.Series(((index - monday).days // 14), index=index)
    raise ValueError(f"cycle_mode 는 trading_days | calendar: {mode}")


def _g_for(cfg_s, date):
    sched = cfg_s.get("G_schedule")
    G = cfg_s["G"]
    if sched:
        for row in sorted(sched, key=lambda r: str(r["start"])):
            if pd.Timestamp(row["start"]) <= date:
                G = row["G"]
    return G


def _sell_to_cover(state, date, close, need, cm, trades, reason):
    """Pool 이 need 만큼 부족할 때 종가로 주식을 팔아 채운다."""
    if need <= 0 or state.shares <= 0:
        return
    qty = math.ceil(need / (close * (1 - cm.rate - cm.sec) or close))
    while qty < state.shares and qty * close - cm.fee("sell", close, qty) < need:
        qty += 1
    _trade(state, date, "sell", min(qty, state.shares), cm.slipped("sell", close), cm, trades, reason)


def _apply_event(state, date, close, amount, cm, trades):
    """PART6_04: 목돈 추가/인출. 현재 주식:Pool 비율대로 나누고 P/V 유지."""
    eval_ = state.shares * close
    total = eval_ + state.pool
    pv_old = state.pool / state.V if state.V else 0.0
    pool_before = state.pool
    stock_part = amount * (eval_ / total) if total > 0 else 0.0
    if amount > 0:
        state.pool += amount
        qty = int(stock_part // close)
        if qty > 0:
            _trade(state, date, "buy", qty, cm.slipped("buy", close), cm, trades, "event_add")
    else:
        qty = math.ceil(-stock_part / close)
        if qty > 0:
            _trade(state, date, "sell", min(qty, state.shares), cm.slipped("sell", close), cm, trades, "event_withdraw")
        state.pool += amount
        if state.pool < 0:
            _sell_to_cover(state, date, close, -state.pool, cm, trades, "event_withdraw")
    if pv_old > 0 and state.pool > 0:
        state.V = rnd(state.pool / pv_old, 2)
    else:
        new_total = state.shares * close + state.pool
        state.V = rnd(state.V * (new_total / total), 2) if total > 0 else state.V
    return state.pool - pool_before


def _pay_tax(state, year, close, date, tax_cfg, fx_rate, cm, trades):
    gain = state.realized.get(year, 0.0)
    taxable_krw = gain * fx_rate - tax_cfg["deduction_krw"]
    if taxable_krw <= 0:
        return 0.0
    tax = round(taxable_krw * tax_cfg["rate"] / fx_rate, 2)
    if state.pool < tax:
        _sell_to_cover(state, date, close, tax - state.pool, cm, trades, f"tax_{year}")
    state.pool -= tax
    state.taxes += tax
    return tax


def backtest(prices, cfg, events=None):
    """prices: 기준일(시작 직전 거래일) 1행 + 본 구간. cfg: config.resolve() 결과."""
    s, c, k, f = cfg["strategy"], cfg["capital"], cfg["costs"], cfg["fill"]
    cm = CostModel(k)
    ref, body = prices.iloc[:1], prices.iloc[1:]
    p = Params(G=s["G"], band_low=s["band_low"], band_high=s["band_high"],
               pool_limit=s["pool_limit"], pool_limit_rule=s["pool_limit_rule"],
               formula=s["formula"], lot=s["lot_size"], digits=s["round_digits"],
               price_model=f["price_model"], same_day_order=f["same_day_order"],
               cash_yield=k["cash_yield"])
    sf = cfg.get("safety") or {}
    if sf.get("enabled"):
        p.stop_enabled = True
        p.stop_pct = float(sf.get("stop_pct", 0.15))
        p.reentry_mode = sf.get("reentry_mode", "rebound")
        p.reentry_pct = float(sf.get("reentry_pct", 0.20))
        p.reentry_ma = int(sf.get("reentry_ma", 200))
        rpr = sf.get("reentry_pool_ratio")
        p.reentry_pool_ratio = float(c["initial_pool_ratio"] if rpr is None else rpr)
        if p.reentry_mode == "ma":
            ma = prices["Close"].rolling(p.reentry_ma, min_periods=1).mean()
            if "MA" in prices.columns:
                ma = prices["MA"]
            prices = prices.assign(MA=ma)
            ref, body = prices.iloc[:1], prices.iloc[1:]
    trades, daily, cycles, flows = [], [], [], []
    ref_date, P0 = ref.index[0], ref["Close"].iloc[0]
    initial = float(c["initial"])
    state = State(V=0.0, pool=initial, shares=0)
    flows.append({"date": ref_date, "amount": initial, "kind": "initial"})
    stock_cash = initial * (1 - c["initial_pool_ratio"])
    qty = int(stock_cash // (P0 * (1 + cm.rate + cm.slip)))
    while qty > 0 and qty * P0 + cm.fee("buy", P0, qty) > stock_cash:
        qty -= 1
    if qty > 0:
        _trade(state, ref_date, "buy", qty, cm.slipped("buy", P0), cm, trades, "initial")
    state.V = rnd(state.shares * P0, s["round_digits"])

    ev = []
    if events is not None and len(events):
        ev = [(pd.Timestamp(d), float(a)) for d, a in zip(events["date"], events["amount"])]
    per = c["periodic"]
    tax_cfg = k["tax"]
    groups = split_cycles(body.index, s["cycle_mode"], s["cycle_length"])
    keys = list(dict.fromkeys(groups.values))
    for i, key in enumerate(keys):
        bars = body[groups.values == key]
        p.G = _g_for(s, bars.index[0])
        row = run_cycle(state, bars, p, cm, i + 1, trades, daily)
        end_date, close = bars.index[-1], bars["Close"].iloc[-1]
        E = state.shares * close
        # 목돈 이벤트
        ev_amt = 0.0
        for d, a in [e for e in ev if bars.index[0] <= e[0] <= end_date]:
            ev_amt += _apply_event(state, end_date, close, a, cm, trades)
            flows.append({"date": end_date, "amount": a, "kind": "event"})
        # 세금 (연도가 바뀌거나 마지막 사이클이면 그 해 정산)
        tax = 0.0
        is_last = i == len(keys) - 1
        next_year = body[groups.values == keys[i + 1]].index[0].year if not is_last else None
        if tax_cfg["enabled"] and (is_last or next_year != end_date.year):
            tax = _pay_tax(state, end_date.year, close, end_date, tax_cfg, k["fx_rate"], cm, trades)
        # 적립/인출 금액
        if per["type"] == "ratio":
            base = initial if per.get("ratio_base", "initial") == "initial" else state.shares * close + state.pool
            flow = rnd(per["ratio"] * base, 2)
        else:
            flow = float(per["amount"] or 0.0)
        actual = flow
        pool_for_v = state.pool
        if not is_last:
            if flow < 0 and state.pool < -flow:
                mode = c["withdraw_shortfall"]
                if mode == "skip":
                    actual = 0.0
                elif mode == "partial":
                    actual = -max(state.pool, 0.0)
                else:  # sell
                    _sell_to_cover(state, end_date, close, -flow - state.pool, cm, trades, "withdraw")
                if state.pool < -actual:   # 다 팔아도 부족하면 남은 만큼만
                    actual = -max(state.pool, 0.0)
            if not state.in_cash:   # 현금화 상태에서는 V를 멈춰 둔다
                state.V = next_v(state.V, pool_for_v, p.G, actual, p.formula, E, s["round_digits"])
            state.pool += actual
            if actual:
                flows.append({"date": end_date, "amount": actual, "kind": "periodic"})
        row.update({"in_cash": state.in_cash, "G": p.G, "E": round(E, 2), "flow": actual if not is_last else 0.0,
                    "event": round(ev_amt, 2), "tax": tax, "next_V": state.V if not is_last else None,
                    "pool_after_flow": round(state.pool, 2), "fees_cum": round(state.fees, 2)})
        cycles.append(row)
        if daily:
            daily[-1]["pool"] = state.pool
            daily[-1]["total"] = state.shares * close + state.pool
            daily[-1]["shares"] = state.shares
            daily[-1]["eval"] = state.shares * close
    return {"cycles": pd.DataFrame(cycles), "trades": pd.DataFrame(trades),
            "daily": pd.DataFrame(daily).set_index("date"), "flows": pd.DataFrame(flows),
            "state": state, "ref_date": ref_date, "P0": P0}
