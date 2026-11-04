"""결과 저장: CSV(엑셀용 utf-8-sig), 요약 텍스트, HTML 그래프."""
import json
import os

CYCLE_COLS_KO = {
    "cycle": "사이클", "start": "시작일", "end": "종료일", "start_eval": "시작 평가금",
    "end_eval": "마지막 평가금", "V": "V", "min_band": "최소밴드", "max_band": "최대밴드",
    "start_pool": "시작 Pool", "end_pool": "마지막 Pool", "start_shares": "시작 보유수",
    "end_shares": "마지막 보유수", "planned_buys": "예약 매수 칸수", "planned_buy_amount": "예약 매수 총액",
    "buys": "매수 체결", "sells": "매도 체결", "same_day_conflicts": "같은날 충돌", "close": "마지막 종가",
    "G": "G", "E": "E", "flow": "적립(+)/인출(-)", "event": "목돈 이벤트", "tax": "세금",
    "next_V": "다음 V", "pool_after_flow": "적립/인출 후 Pool", "fees_cum": "누적 수수료",
}


def save(res, summary, cfg, out_dir, bench=None, name="run"):
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, name)
    res["cycles"].rename(columns=CYCLE_COLS_KO).to_csv(f"{base}_cycles.csv", index=False, encoding="utf-8-sig")
    res["trades"].to_csv(f"{base}_trades.csv", index=False, encoding="utf-8-sig")
    res["daily"].to_csv(f"{base}_daily.csv", encoding="utf-8-sig")
    lines = ["# VR 백테스트 결과", ""]
    lines += [f"- {k}: {v}" for k, v in summary.items()]
    if bench:
        lines += ["", "## 단순 보유 비교 (같은 입출금 일정)"]
        for t, b in bench.items():
            lines.append(f"- {t}: " + ", ".join(f"{k} {v}" for k, v in b.items()))
    lines += ["", "## 사용한 설정 (출처)"]
    s, c, k = cfg["strategy"], cfg["capital"], cfg["costs"]
    shown = {
        "strategy.mode": s["mode"], "strategy.formula": s["formula"], "strategy.G": s["G"],
        "strategy.band_low": s["band_low"], "strategy.band_high": s["band_high"],
        "strategy.pool_limit": s["pool_limit"], "strategy.pool_limit_rule": s["pool_limit_rule"],
        "capital.initial_pool_ratio": c["initial_pool_ratio"], "capital.periodic": c["periodic"],
        "costs.commission_rate": k["commission_rate"], "costs.commission_min": k["commission_min"],
        "costs.sec_fee_rate": k["sec_fee_rate"], "costs.slippage_bps": k["slippage_bps"],
        "fill.price_model": cfg["fill"]["price_model"], "data.ticker": cfg["data"]["ticker"],
    }
    for key, val in shown.items():
        src = cfg["_source"].get(key, "")
        lines.append(f"- {key} = {val}" + (f"  ({src})" if src else ""))
    if cfg["_warnings"]:
        lines += ["", "## 경고"] + [f"- {w}" for w in cfg["_warnings"]]
    with open(f"{base}_summary.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(f"{base}_summary.json", "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "benchmarks": bench or {}}, fh, ensure_ascii=False, indent=2, default=str)
    if cfg["report"].get("html", True):
        _html(res, f"{base}_chart.html", cfg)
    return base


def _html(res, path, cfg):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return
    d = res["daily"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
                        vertical_spacing=0.04, subplot_titles=("평가금 · V · 밴드 · Pool", "계좌총액 낙폭"))
    fig.add_trace(go.Scatter(x=d.index, y=d["eval"], name="평가금", line=dict(color="#d62728")), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["V"], name="V", line=dict(color="#ff7f0e", shape="hv")), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["max_band"], name="최대밴드",
                             line=dict(color="#2ca02c", dash="dot", shape="hv")), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["min_band"], name="최소밴드",
                             line=dict(color="#2ca02c", dash="dot", shape="hv")), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["pool"], name="Pool", line=dict(color="#1f77b4")), 1, 1)
    dd = d["total"] / d["total"].cummax() - 1
    fig.add_trace(go.Scatter(x=d.index, y=dd * 100, name="낙폭(%)", fill="tozeroy",
                             line=dict(color="#7f7f7f")), 2, 1)
    s = cfg["strategy"]
    fig.update_layout(title=f"{cfg['data']['ticker']} VR ({s['mode']}, G={s['G']}, 밴드 -{s['band_low']:.0%}/+{s['band_high']:.0%}, 사용한도 {s['pool_limit']:.0%})",
                      height=760, hovermode="x unified", template="plotly_white")
    fig.write_html(path, include_plotlyjs=True)
