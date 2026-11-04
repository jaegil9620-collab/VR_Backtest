"""사용법
  python cli.py run config.yaml                     # 백테스트 1회
  python cli.py run config.yaml --set strategy.G=20 --set costs.commission_rate=0.0007
  python cli.py sweep config.yaml --grid strategy.G=5,10,20 --grid strategy.band_low=0.1,0.15,0.2
  python cli.py fetch TQQQ QQQ QLD                  # 데이터만 미리 받기
"""
import argparse
import itertools
import os
import sys

import pandas as pd
import yaml

from vr import config as C
from vr import data as D
from vr import metrics as M
from vr import report as R
from vr.engine import backtest


def _parse_val(v):
    return yaml.safe_load(v)


def _overrides(pairs):
    out = {}
    for p in pairs or []:
        k, v = p.split("=", 1)
        out[k] = _parse_val(v)
    return out


def run_once(cfg, name="run", save=True, quiet=False):
    dcfg = cfg["data"]
    prices = D.get_prices(dcfg)
    ref, body = D.slice_period(prices, dcfg["start"], dcfg["end"])
    scale = 1.0
    if dcfg.get("rescale", "auto") == "auto":
        ref, body, scale = D.rescale(ref, body)
    px = pd.concat([ref, body])
    if cfg["fill"]["price_model"] == "close":
        # 종가 기준(책 백테스트 방식 추정): 장중 고저가를 무시하고 종가에서만 체결 판정
        px = px.assign(Open=px["Close"], High=px["Close"], Low=px["Close"])
    events = None
    if cfg["capital"].get("events_csv"):
        events = pd.read_csv(cfg["capital"]["events_csv"])
    res = backtest(px, cfg, events)
    summary = M.summarize(res)
    if scale != 1.0:
        summary["가격 배율(분할 보정)"] = round(scale, 4)
    bench = {}
    for t in cfg["report"].get("benchmarks") or []:
        try:
            bp = px if t == dcfg["ticker"] else D.get_prices(dcfg, t)
            bp = bp[(bp.index >= res["ref_date"]) & (bp.index <= px.index[-1])]
            bench[t], _ = M.buy_and_hold(bp, res["flows"], res["ref_date"])
        except Exception as e:  # 벤치마크 실패는 본 결과에 영향 없음
            bench[t] = {"오류": str(e)}
    if save:
        base = R.save(res, summary, cfg, cfg["report"]["out_dir"], bench, name)
        if not quiet:
            print(f"결과 저장: {base}_*.csv / _summary.md / _chart.html")
    if not quiet:
        for k, v in summary.items():
            print(f"  {k}: {v}")
        for t, b in bench.items():
            print(f"  [단순보유 {t}] {b}")
        for w in cfg["_warnings"]:
            print(f"  [경고] {w}")
    return res, summary, bench


def main(argv=None):
    ap = argparse.ArgumentParser(description="라오어 VR 백테스터")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("config")
    r.add_argument("--set", action="append", help="설정 덮어쓰기 key=value")
    r.add_argument("--name", default="run")
    sw = sub.add_parser("sweep")
    sw.add_argument("config")
    sw.add_argument("--set", action="append")
    sw.add_argument("--grid", action="append", required=True, help="key=v1,v2,...")
    sw.add_argument("--name", default="sweep")
    f = sub.add_parser("fetch")
    f.add_argument("tickers", nargs="+")
    f.add_argument("--cache", default="data")
    a = ap.parse_args(argv)

    if a.cmd == "fetch":
        for t in a.tickers:
            df = D.download_yf(t, a.cache, refresh=True)
            print(f"{t}: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}일)")
        return
    if a.cmd == "run":
        cfg = C.load(a.config, _overrides(a.set))
        run_once(cfg, a.name)
        return
    if a.cmd == "sweep":
        base = _overrides(a.set)
        keys, values = [], []
        for g in a.grid:
            k, v = g.split("=", 1)
            keys.append(k)
            values.append([_parse_val(x) for x in v.split(",")])
        rows = []
        for combo in itertools.product(*values):
            ov = dict(base, **dict(zip(keys, combo)))
            cfg = C.load(a.config, ov)
            cfg["report"]["benchmarks"] = []
            _, summ, _ = run_once(cfg, save=False, quiet=True)
            row = dict(zip(keys, combo))
            row.update({k: summ[k] for k in ("CAGR(시간가중)", "IRR(금액가중)", "MDD(시간가중)", "MDD(사이클 종료일 기준)", "MDD(계좌총액)",
                                            "최종 계좌총액", "매수 체결 수", "매도 체결 수", "수수료 합계")})
            rows.append(row)
            print(row)
        out = os.path.join(cfg["report"]["out_dir"], f"{a.name}.csv")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"비교표 저장: {out}")


if __name__ == "__main__":
    sys.exit(main())
