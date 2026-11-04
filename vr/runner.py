"""설정(cfg) 하나로 백테스트 + 벤치마크까지 실행. CLI와 UI가 함께 쓴다."""
import pandas as pd

from . import data as D
from . import metrics as M
from .engine import backtest


def run(cfg, log=print):
    dcfg = cfg["data"]
    log(f"{dcfg['ticker']} 가격 데이터 준비 중...")
    prices = D.get_prices(dcfg)
    ref, body = D.slice_period(prices, dcfg["start"], dcfg["end"])
    scale = 1.0
    if dcfg.get("rescale", "auto") == "auto":
        ref, body, scale = D.rescale(ref, body)
    px = pd.concat([ref, body])
    if cfg["fill"]["price_model"] == "close":
        px = px.assign(Open=px["Close"], High=px["Close"], Low=px["Close"])
    events = None
    if cfg["capital"].get("events_csv"):
        events = pd.read_csv(cfg["capital"]["events_csv"])
    log("백테스트 계산 중...")
    res = backtest(px, cfg, events)
    summary = M.summarize(res)
    if scale != 1.0:
        summary["가격 배율(분할 보정)"] = round(scale, 4)
    bench, curves = {}, {}
    for t in cfg["report"].get("benchmarks") or []:
        try:
            log(f"비교 대상 {t} 준비 중...")
            bp = px if t == dcfg["ticker"] else D.get_prices(dcfg, t)
            bp = bp[(bp.index >= res["ref_date"]) & (bp.index <= px.index[-1])]
            if bp.empty or bp.index[0] > res["ref_date"]:
                raise ValueError("테스트 기간 시작일에 데이터가 없습니다")
            bench[t], curves[t] = M.buy_and_hold(bp, res["flows"], res["ref_date"])
        except Exception as e:  # 벤치마크 실패는 본 결과에 영향 없음
            bench[t] = {"오류": str(e)}
    return res, summary, bench, curves
