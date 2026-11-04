"""성과 지표: CAGR, MDD, 시간가중수익률(TWR), 내부수익률(IRR)."""
import numpy as np
import pandas as pd


def mdd(series):
    s = pd.Series(series).astype(float)
    peak = s.cummax()
    dd = s / peak - 1
    return float(dd.min()), dd


def cagr(start_value, end_value, years):
    if start_value <= 0 or years <= 0 or end_value <= 0:
        return float("nan")
    return (end_value / start_value) ** (1 / years) - 1


def twr_index(total, flows):
    """외부 입출금 효과를 뺀 수익률 지수. flows: 날짜별 입출금(+입금, -출금, 종가 시점)."""
    total = total.astype(float)
    f = flows.groupby("date")["amount"].sum() if len(flows) else pd.Series(dtype=float)
    f = f.reindex(total.index).fillna(0.0)
    prev = total.shift(1).where(lambda x: x > 0)
    r = (total - f) / prev - 1
    r.iloc[0] = 0.0
    return (1 + r.fillna(0)).cumprod()


def xirr(dates, amounts):
    """투자자 관점 현금흐름(입금 -, 출금/최종평가 +)의 연 내부수익률."""
    d = pd.to_datetime(pd.Series(dates))
    t = ((d - d.iloc[0]).dt.days / 365.25).values
    a = np.asarray(amounts, float)

    def npv(r):
        return np.sum(a / (1 + r) ** t)

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def summarize(res):
    daily, flows, trades, cycles = res["daily"], res["flows"], res["trades"], res["cycles"]
    total = daily["total"]
    start, end = res["ref_date"], daily.index[-1]
    years = (end - start).days / 365.25
    initial = float(flows.loc[flows["kind"] == "initial", "amount"].sum())
    ext = flows[flows["kind"] != "initial"]
    deposits = float(ext.loc[ext["amount"] > 0, "amount"].sum())
    withdrawals = float(-ext.loc[ext["amount"] < 0, "amount"].sum()) + 0.0
    idx = twr_index(total, ext[["date", "amount"]] if len(ext) else ext)
    dd_twr, _ = mdd(idx)
    dd_eq, _ = mdd(total)
    ce = daily.groupby("cycle").tail(1)
    ce_idx = idx.reindex(ce.index)
    dd_cycle, _ = mdd(ce_idx)
    cf_dates = [start] + list(ext["date"]) + [end]
    cf_amts = [-initial] + [-a for a in ext["amount"]] + [float(total.iloc[-1])]
    st = res["state"]
    n_buy = int((trades["side"] == "buy").sum()) if len(trades) else 0
    n_sell = int((trades["side"] == "sell").sum()) if len(trades) else 0
    return {
        "기간": f"{start.date()} ~ {end.date()} ({years:.2f}년)",
        "사이클 수": int(len(cycles)),
        "초기 투자금": round(initial, 2),
        "추가 적립 합계": round(deposits, 2),
        "인출 합계": round(withdrawals, 2),
        "최종 계좌총액": round(float(total.iloc[-1]), 2),
        "최종 평가금(주식)": round(float(daily["eval"].iloc[-1]), 2),
        "최종 Pool": round(float(daily["pool"].iloc[-1]), 2),
        "최종 V": float(cycles["V"].iloc[-1]),
        "CAGR(시간가중)": round(cagr(1, float(idx.iloc[-1]), years) * 100, 2),
        "IRR(금액가중)": round(xirr(cf_dates, cf_amts) * 100, 2),
        "MDD(시간가중)": round(dd_twr * 100, 2),
        "MDD(계좌총액)": round(dd_eq * 100, 2),
        "MDD(사이클 종료일 기준)": round(dd_cycle * 100, 2),
        "매수 체결 수": n_buy - int((trades["reason"] == "initial").sum()) if len(trades) else 0,
        "매도 체결 수": n_sell,
        "수수료 합계": round(st.fees, 2),
        "세금 합계": round(st.taxes, 2),
        "같은 날 매수·매도 충돌": int(cycles["same_day_conflicts"].sum()),
        "Pool 최저": round(float(daily["pool"].min()), 2),
        "안전장치 발동(전량 매도)": st.stops,
        "재진입": st.reentries,
        "현금화 상태로 보낸 날": int(daily["in_cash"].sum()) if "in_cash" in daily else 0,
    }


def buy_and_hold(prices, flows, ref_date):
    """같은 입출금 일정으로 단순 보유했을 때 (소수 주 허용, 비용 없음).
    휴장일(주말 등)의 입출금은 다음 거래일에 넣는다."""
    close = prices["Close"]
    close = close[close.index >= ref_date]
    if close.empty:
        raise ValueError("테스트 기간에 데이터가 없습니다")
    f = {}
    for d, a in flows.groupby("date")["amount"].sum().items():
        i = close.index.searchsorted(pd.Timestamp(d))
        if i < len(close):
            f[close.index[i]] = f.get(close.index[i], 0.0) + a
    units, vals = 0.0, []
    for d, px in close.items():
        if d in f:
            units = max(units + f[d] / px, 0.0)
        vals.append(units * px)
    total = pd.Series(vals, index=close.index)
    ext = flows[flows["kind"] != "initial"]
    idx = twr_index(total, ext[["date", "amount"]] if len(ext) else ext)
    years = (close.index[-1] - close.index[0]).days / 365.25
    return {"CAGR(시간가중)": round(cagr(1, float(idx.iloc[-1]), years) * 100, 2),
            "MDD(시간가중)": round(mdd(idx)[0] * 100, 2),
            "최종 계좌총액": round(float(total.iloc[-1]), 2)}, total
