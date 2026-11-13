"""엔진 전체 흐름 점검 (가상 데이터)."""
import pandas as pd
import pytest

from vr import config as C
from vr.data import make_random_walk, synthetic_leveraged
from vr.engine import backtest
from vr.metrics import summarize


def _cfg(**over):
    cfg = {"strategy": {"mode": over.pop("mode", "hold")}, "report": {"benchmarks": [], "html": False}}
    for k, v in over.items():
        sec, key = k.split("__")
        cfg.setdefault(sec, {})[key] = v
    return C.resolve(cfg)


@pytest.mark.parametrize("mode", ["accumulate", "hold", "withdraw"])
def test_cash_accounting(mode):
    px = make_random_walk(800, seed=3, vol=0.03, drift=0.001)
    cfg = _cfg(mode=mode)
    res = backtest(px, cfg)
    t, fl = res["trades"], res["flows"]
    buys = (t.loc[t.side == "buy", "amount"]).sum()
    sells = (t.loc[t.side == "sell", "amount"]).sum()
    expected = fl["amount"].sum() - buys + sells - t["fee"].sum()
    assert res["state"].pool == pytest.approx(expected, abs=0.05)
    shares = t.loc[t.side == "buy", "qty"].sum() - t.loc[t.side == "sell", "qty"].sum()
    assert res["state"].shares == shares
    s = summarize(res)
    assert s["사이클 수"] == len(res["cycles"])


def test_book_defaults_and_override():
    cfg = _cfg(mode="withdraw")
    assert cfg["strategy"]["G"] == 20 and cfg["strategy"]["pool_limit"] == 0.25
    assert cfg["capital"]["initial_pool_ratio"] == 0.20
    assert cfg["_source"]["strategy.G"] == "책 기본값"
    cfg = _cfg(mode="withdraw", strategy__G=30, strategy__band_low=0.3)
    assert cfg["strategy"]["G"] == 30 and cfg["_source"]["strategy.G"] == "사용자 설정"
    assert any("band_low" in w for w in cfg["_warnings"])
    assert cfg["costs"]["commission_rate"] == 0.0025   # 한투 프리셋


def test_pool_limit_respected_each_cycle():
    px = make_random_walk(600, seed=5, vol=0.05, drift=-0.002)
    res = backtest(px, _cfg(mode="hold", costs__broker="none"))
    c = res["cycles"]
    # nearest 규칙: 예약 매수 총액이 한도 + 한 칸 가격을 넘지 않음
    assert (c["planned_buy_amount"] <= c["start_pool"] * 0.5 + c["close"].max()).all()
    assert (c["end_pool"] >= -1e-6).all()


def test_synthetic_leverage_tracks_3x():
    base = make_random_walk(300, seed=2, vol=0.01, drift=0.0)
    syn = synthetic_leveraged(base, 3, 0.0)
    r_b = base["Close"].pct_change().iloc[2:]
    r_s = syn["Close"].pct_change().iloc[1:].reindex(r_b.index)
    assert (r_s - 3 * r_b).abs().max() < 1e-9


def test_rescale_keeps_returns():
    from vr.data import rescale
    px = make_random_walk(50, seed=1, start_price=0.3)
    ref, body, k = rescale(px.iloc[:1], px.iloc[1:])
    assert k > 1 and ref["Close"].iloc[0] == pytest.approx(100)
    assert (body["Close"].pct_change().dropna() - px.iloc[1:]["Close"].pct_change().dropna()).abs().max() < 1e-12


def test_safety_stop_and_reentry():
    import numpy as np
    idx = pd.bdate_range("2020-01-01", periods=80)
    # 40일 동안 100 → 30으로 하락 후 40일 동안 30 → 90으로 회복
    close = np.concatenate([np.linspace(100, 30, 40), np.linspace(30, 90, 40)])
    px = pd.DataFrame({"Open": close, "High": close * 1.001, "Low": close * 0.999, "Close": close}, index=idx)
    base = backtest(px, _cfg(mode="hold", costs__broker="none"))
    cfg = _cfg(mode="hold", costs__broker="none", safety__enabled=True, safety__stop_pct=0.10,
               safety__reentry_mode="rebound", safety__reentry_pct=0.20)
    res = backtest(px, cfg)
    st = res["state"]
    assert st.stops >= 1 and st.reentries >= 1
    reasons = list(res["trades"]["reason"])
    assert reasons.index("stop") < reasons.index("reentry")
    # 큰 하락을 피했으므로 최저 계좌총액이 안전장치 없을 때보다 높다
    assert res["daily"]["total"].min() > base["daily"]["total"].min()


def test_crypto_detect_and_unit():
    import numpy as np
    from vr.data import coin_unit, is_24_7
    idx = pd.date_range("2020-01-01", periods=60, freq="D")
    assert is_24_7(pd.DataFrame({"Close": np.ones(60)}, index=idx))
    assert not is_24_7(make_random_walk(60))
    assert coin_unit(60000, 18000) == pytest.approx(0.001)   # 18000/(60000*300)=0.001


def test_strategy_save_load(tmp_path):
    from vr import config as C
    from vr import strategies as ST
    cfg = C.resolve({"data": {"ticker": "TQQQ", "cache_dir": "x", "refresh": True}})
    ST.save("내 전략", cfg, {"CAGR": 10.0, "MDD(계좌총액)": -20.0, "기타": 1}, "메모", folder=str(tmp_path))
    it = ST.list_all(folder=str(tmp_path))[0]
    assert it["name"] == "내_전략" and ST.pick(it["result"], "MDD") == -20.0 and "기타" not in it["result"]
    doc = ST.load("내 전략", folder=str(tmp_path))
    assert "cache_dir" not in doc["config"]["data"] and "report" not in doc["config"]
    c2 = ST.load_config("내 전략", {"data.ticker": "SOXL"}, folder=str(tmp_path))
    assert c2["data"]["ticker"] == "SOXL"
    ST.delete("내 전략", folder=str(tmp_path))
    assert ST.list_all(folder=str(tmp_path)) == []
