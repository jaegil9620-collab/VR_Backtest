"""사용법
  python cli.py run config.yaml                     # 백테스트 1회
  python cli.py run config.yaml --set strategy.G=20 --set costs.commission_rate=0.0007
  python cli.py sweep config.yaml --grid strategy.G=5,10,20 --grid strategy.band_low=0.1,0.15,0.2
  python cli.py fetch TQQQ QQQ QLD                  # 데이터만 미리 받기
  python cli.py save 이름 config.yaml --set ... --memo "메모"   # 전략 저장
  python cli.py list                                          # 저장된 전략 목록
  python cli.py run --strategy 이름                           # 저장된 전략으로 실행
  python cli.py delete 이름
"""
import argparse
import itertools
import os
import sys

import pandas as pd
import yaml

from vr import config as C
from vr import data as D
from vr import report as R
from vr import strategies as ST
from vr.runner import run


def _parse_val(v):
    return yaml.safe_load(v)


def _overrides(pairs):
    out = {}
    for p in pairs or []:
        k, v = p.split("=", 1)
        out[k] = _parse_val(v)
    return out


def run_once(cfg, name="run", save=True, quiet=False):
    res, summary, bench, curves = run(cfg, log=(lambda m: None) if quiet else print)
    if save:
        base = R.save(res, summary, cfg, cfg["report"]["out_dir"], bench, name, curves)
        if not quiet:
            print(f"결과 저장: {base}_report.html (+ csv)")
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
    r.add_argument("config", nargs="?", default="config.yaml")
    r.add_argument("--strategy", help="저장된 전략 이름으로 실행")
    r.add_argument("--set", action="append", help="설정 덮어쓰기 key=value")
    r.add_argument("--name", default="run")
    sw = sub.add_parser("sweep")
    sw.add_argument("config")
    sw.add_argument("--set", action="append")
    sw.add_argument("--grid", action="append", required=True, help="key=v1,v2,...")
    sw.add_argument("--name", default="sweep")
    sv = sub.add_parser("save", help="전략 저장 (백테스트 결과도 함께)")
    sv.add_argument("name")
    sv.add_argument("config", nargs="?", default="config.yaml")
    sv.add_argument("--set", action="append")
    sv.add_argument("--memo", default="")
    sub.add_parser("list", help="저장된 전략 목록")
    dl = sub.add_parser("delete")
    dl.add_argument("name")
    f = sub.add_parser("fetch")
    f.add_argument("tickers", nargs="+")
    f.add_argument("--cache", default="data")
    a = ap.parse_args(argv)

    if a.cmd == "fetch":
        for t in a.tickers:
            df = D.download_yf(t, a.cache, refresh=True)
            print(f"{t}: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}일)")
        return
    if a.cmd == "save":
        cfg = C.load(a.config, _overrides(a.set))
        cfg["report"]["benchmarks"] = []
        _, summ, _ = run_once(cfg, save=False, quiet=True)
        p = ST.save(a.name, cfg, summ, a.memo)
        print(f"저장: {p}  (CAGR {ST.pick(summ, 'CAGR')}%, MDD {ST.pick(summ, 'MDD')}%)")
        return
    if a.cmd == "list":
        for it in ST.list_all():
            r_ = it["result"]
            print(f"- {it['name']} [{it['ticker']}] CAGR {ST.pick(r_, 'CAGR')}% MDD {ST.pick(r_, 'MDD')}% "
                  f"({it['saved_at']}) {it['memo']}")
        return
    if a.cmd == "delete":
        ST.delete(a.name)
        print(f"삭제: {a.name}")
        return
    if a.cmd == "run" and a.strategy:
        cfg = ST.load_config(a.strategy, _overrides(a.set))
        run_once(cfg, a.name or f"{prefix}_{ST.safe_name(a.strategy)}")
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
