"""가격 데이터: yfinance(기본, CSV 캐시) / CSV 파일 / 합성 레버리지."""
import os

import numpy as np
import pandas as pd

COLS = ["Open", "High", "Low", "Close"]


def _normalize(df):
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip().capitalize() for c in df.columns]
    if "Date" in df.columns:
        df = df.set_index("Date")
    df.index = pd.to_datetime(df.index).tz_localize(None) if getattr(df.index, "tz", None) else pd.to_datetime(df.index)
    df.index.name = "Date"
    missing = [c for c in COLS if c not in df.columns]
    if missing:
        raise ValueError(f"가격 데이터에 {missing} 열이 없습니다")
    df = df[COLS].astype(float).dropna().sort_index()
    return df[~df.index.duplicated()]


def load_csv(path):
    return _normalize(pd.read_csv(path))


def download_yf(ticker, cache_dir="data", refresh=False):
    """Yahoo Finance 일봉. 분할 반영·배당 미반영 가격(auto_adjust=False 의 OHLC)."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{ticker.replace('^', '_')}.csv")
    if os.path.exists(path) and not refresh:
        return load_csv(path)
    import yfinance as yf
    raw = yf.download(ticker, period="max", interval="1d", auto_adjust=False,
                      progress=False, actions=False)
    if raw is None or raw.empty:
        raise RuntimeError(f"{ticker} 데이터를 받지 못했습니다 (인터넷 연결/티커 확인)")
    df = _normalize(raw)
    df.to_csv(path)
    return df


def synthetic_leveraged(base, leverage=3.0, expense_ratio=0.0095, financing_rate=0.0, start_price=100.0):
    """기초자산 일봉으로 일일 L배 상품을 흉내 낸다 (TQQQ 상장 전 구간 확인용).

    일수익률 = L * 기초 일수익률 - (보수 + (L-1)*차입금리)/252
    시가·고가·저가는 전일 종가 대비 기초자산 변화율을 L배 한 값.
    """
    b = base.copy()
    prev = b["Close"].shift(1)
    daily_cost = (expense_ratio + (leverage - 1) * financing_rate) / 252.0
    r = {c: leverage * (b[c] / prev - 1) for c in COLS}
    r["Close"] = r["Close"] - daily_cost
    close = start_price * (1 + r["Close"].fillna(0)).cumprod()
    pc = close.shift(1)
    out = pd.DataFrame({"Close": close}, index=b.index)
    for c in ("Open", "High", "Low"):
        out[c] = pc * (1 + r[c])
    out = out.iloc[1:]
    out[["Open", "High", "Low", "Close"]] = out[["Open", "High", "Low", "Close"]].clip(lower=0.0001)
    out["High"] = out[COLS].max(axis=1)
    out["Low"] = out[COLS].min(axis=1)
    return out[COLS]


def get_prices(data_cfg, ticker=None):
    ticker = ticker or data_cfg["ticker"]
    syn = data_cfg.get("synthetic") or {}
    if data_cfg["source"] == "csv" and ticker == data_cfg["ticker"]:
        df = load_csv(data_cfg["csv_path"])
    elif syn.get("enabled") and ticker == data_cfg["ticker"]:
        base = download_yf(syn["base_ticker"], data_cfg["cache_dir"], data_cfg.get("refresh", False))
        df = synthetic_leveraged(base, syn["leverage"], syn["expense_ratio"], syn.get("financing_rate", 0.0))
    else:
        df = download_yf(ticker, data_cfg["cache_dir"], data_cfg.get("refresh", False))
    return df


def rescale(ref, body, target=100.0, threshold=10.0):
    """분할 반영 가격은 과거가 $0.2 처럼 작아 1센트 반올림 오차가 커진다.
    기준일 종가가 threshold 미만이면 전체 가격을 같은 비율로 키운다(수익률은 동일)."""
    p0 = float(ref["Close"].iloc[0])
    if p0 >= threshold:
        return ref, body, 1.0
    k = target / p0
    return ref * k, body * k, k


def is_24_7(df):
    """주말에도 거래되는 자산(코인)인지: 토·일 데이터가 5% 넘게 있으면 True."""
    if len(df) < 20:
        return False
    return (df.index.dayofweek >= 5).mean() > 0.05


def coin_unit(price, cash, target_units=300):
    """코인을 몇 개 단위로 사고팔지: 처음에 약 300~3000 단위가 되도록 10의 거듭제곱으로 정한다."""
    import math
    raw = cash / (price * target_units)
    return 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0


def slice_period(df, start, end):
    """start 직전 거래일(초기 V 기준일)까지 포함해서 자른다."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    before = df[df.index < start]
    body = df[(df.index >= start) & (df.index <= end)]
    if body.empty:
        raise ValueError(f"{start.date()}~{end.date()} 구간에 데이터가 없습니다 (데이터 범위 {df.index[0].date()}~{df.index[-1].date()})")
    if before.empty:
        # 직전일이 없으면 첫날을 기준일로 쓰고 다음 날부터 시작
        return body.iloc[:1], body.iloc[1:]
    return before.iloc[-1:], body


def make_random_walk(n=2600, seed=0, start="2011-01-03", start_price=50.0, vol=0.04, drift=0.0012):
    """오프라인 테스트용 가상 데이터."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    r = rng.normal(drift, vol, n)
    close = start_price * np.exp(np.cumsum(r))
    prev = np.concatenate([[start_price], close[:-1]])
    opn = prev * np.exp(rng.normal(0, vol / 3, n))
    hi = np.maximum(opn, close) * np.exp(np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(opn, close) * np.exp(-np.abs(rng.normal(0, vol / 2, n)))
    return pd.DataFrame({"Open": opn, "High": hi, "Low": lo, "Close": close}, index=pd.DatetimeIndex(idx, name="Date"))
