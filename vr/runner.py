"""설정(cfg) 하나로 백테스트 + 벤치마크까지 실행. CLI와 UI가 함께 쓴다."""
import pandas as pd

from . import data as D
from . import metrics as M
from .engine import backtest


def run(cfg, log=print):
    dcfg = cfg["data"]
    log(f"{dcfg['ticker']} 가격 데이터 준비 중...")
    prices = D.get_prices(dcfg)
    sf = cfg.get("safety") or {}
    if sf.get("enabled") and sf.get("reentry_mode") == "ma":
        # 이동평균은 시작일 이전 데이터까지 써서 미리 계산
        prices = prices.assign(MA=prices["Close"].rolling(int(sf.get("reentry_ma", 200)), min_periods=1).mean())
    ref, body = D.slice_period(prices, dcfg["start"], dcfg["end"])
    scale = 1.0
    crypto = D.is_24_7(prices)
    unit = 1.0
    if crypto:
        # 코인: 소수점 수량을 'unit 개 = 1단위'로 바꿔 계산 (가격 x unit)
        cash = float(cfg["capital"]["initial"]) * (1 - cfg["capital"]["initial_pool_ratio"])
        unit = dcfg.get("unit_size") or D.coin_unit(float(ref["Close"].iloc[0]), cash)
        ref, body, scale = ref * unit, body * unit, unit
        s = cfg["strategy"]
        if s["cycle_mode"] == "trading_days" and s["cycle_length"] == 10:
            s["cycle_length"] = 14
            log("주말에도 거래되는 종목이라 사이클을 14일(2주)로 잡습니다.")
        log(f"코인 수량은 {unit:g}개 단위로 사고팝니다.")
    elif dcfg.get("rescale", "auto") == "auto":
        ref, body, scale = D.rescale(ref, body)
    px = pd.concat([ref, body])
    if cfg["fill"]["price_model"] == "close":
        px = px.assign(Open=px["Close"], High=px["Close"], Low=px["Close"])
    events = None
    if cfg["capital"].get("events_csv"):
        events = pd.read_csv(cfg["capital"]["events_csv"])
    log("백테스트 계산 중...")
    res = backtest(px, cfg, events)
    if crypto:
        _to_coin_units(res, unit)
    summary = M.summarize(res)
    if crypto:
        summary["매매 단위(코인 개수)"] = unit
    elif scale != 1.0:
        summary["가격 배율(분할 보정)"] = round(scale, 4)
    bench, curves = {}, {}
    for t in cfg["report"].get("benchmarks") or []:
        try:
            log(f"비교 대상 {t} 준비 중...")
            full = px if t == dcfg["ticker"] else D.get_prices(dcfg, t)
            bp = full[(full.index >= res["ref_date"]) & (full.index <= px.index[-1])]
            if bp.empty or bp.index[0] > res["ref_date"] + pd.Timedelta(days=7):
                raise ValueError(f"{t} 데이터는 {full.index[0].date()}부터 있어서 이 기간과 비교할 수 없습니다")
            bench[t], curves[t] = M.buy_and_hold(bp, res["flows"], res["ref_date"])
        except Exception as e:  # 벤치마크 실패는 본 결과에 영향 없음
            bench[t] = {"오류": str(e)}
    return res, summary, bench, curves


def _to_coin_units(res, unit):
    """계산용 단위(unit 개 묶음)를 실제 코인 개수·코인 가격으로 바꿔 표시한다."""
    t = res["trades"]
    if len(t):
        t["qty"] = (t["qty"] * unit).round(10)
        t["price"] = (t["price"] / unit).round(2)
        t["shares_after"] = (t["shares_after"] * unit).round(10)
    d = res["daily"]
    d["shares"] = d["shares"] * unit
    d["close"] = d["close"] / unit
    c = res["cycles"]
    for col in ("start_shares", "end_shares"):
        c[col] = (c[col] * unit).round(10)
    c["close"] = c["close"] / unit
