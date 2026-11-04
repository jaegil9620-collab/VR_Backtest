"""결과를 HTML 파일 한 장으로 만든다 (그래프 라이브러리까지 파일 안에 포함, 인터넷 없이 열림)."""
import html
from datetime import datetime

import pandas as pd

from .metrics import mdd, twr_index
from .report import CYCLE_COLS_KO

COLORS = {"VR": "#d62728", "QQQ": "#1f77b4", "SPY": "#2ca02c", "TQQQ": "#9467bd", "QLD": "#8c564b"}
MODE_KO = {"accumulate": "적립식", "hold": "거치식", "withdraw": "인출식"}
EXTRA = ["#17becf", "#bcbd22", "#e377c2", "#7f7f7f"]

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2433;--sub:#5b6475;--line:#e3e6eb;--up:#c62828;--down:#1565c0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;font-size:14px}
.wrap{max-width:1200px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}
.sub{color:var(--sub)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card .k{color:var(--sub);font-size:12px}.card .v{font-size:20px;font-weight:700;margin-top:4px}
.box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;margin-top:8px}
table{border-collapse:collapse;width:100%;background:var(--card)}th,td{border-bottom:1px solid var(--line);
padding:6px 8px;text-align:right;white-space:nowrap}th{background:#eef1f5;position:sticky;top:0}
td:first-child,th:first-child{text-align:left}.scroll{max-height:460px;overflow:auto;border:1px solid var(--line);border-radius:10px}
.pos{color:var(--up)}.neg{color:var(--down)}.warn{background:#fff6e0;border:1px solid #f0d58c;border-radius:8px;padding:8px 12px;margin-top:10px}
details{margin-top:10px}summary{cursor:pointer;font-weight:600;padding:6px 0}.src{color:var(--sub);font-size:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.grid2{grid-template-columns:1fr}}
"""


def _fmt(v, kind="num"):
    if v is None or (isinstance(v, float) and v != v):
        return "-"
    if kind == "pct":
        cls = "pos" if v > 0 else "neg" if v < 0 else ""
        return f'<span class="{cls}">{v:,.2f}%</span>'
    if kind == "usd":
        return f"${v:,.0f}"
    if hasattr(v, "is_integer") and not isinstance(v, float):
        return str(v)
    if isinstance(v, float):
        return f"{v:,.2f}"
    return html.escape(str(v))


def _table(df, max_rows=None, pct_cols=()):
    if max_rows:
        df = df.head(max_rows)
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for r in df.itertuples(index=False):
        cells = []
        for c, v in zip(df.columns, r):
            cells.append(f"<td>{_fmt(v, 'pct' if c in pct_cols else 'num')}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _annual(idx):
    y = idx.resample("YE").last()
    first = idx.iloc[0]
    prev = pd.concat([pd.Series([first], index=[idx.index[0]]), y]).shift(1).iloc[1:]
    return (y / prev.values - 1) * 100


def build(res, summary, cfg, bench, curves, path):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    d = res["daily"]
    s, c, k, dc = cfg["strategy"], cfg["capital"], cfg["costs"], cfg["data"]
    ticker = dc["ticker"]
    flows = res["flows"]
    ext = flows[flows["kind"] != "initial"]
    ext2 = ext[["date", "amount"]] if len(ext) else ext
    total = d["total"]
    # 비교 곡선 (VR 계좌총액 vs 단순 보유, 같은 입출금 일정)
    series = {f"{ticker} VR": total}
    for t, cv in curves.items():
        series[f"{t} 단순보유"] = cv.reindex(total.index).ffill()
    color = {}
    for i, name in enumerate(series):
        base = name.split()[0]
        color[name] = COLORS["VR"] if name.endswith("VR") else COLORS.get(base, EXTRA[i % len(EXTRA)])

    figs = []
    # 1) 계좌 총액 비교
    f1 = go.Figure()
    for name, ser in series.items():
        f1.add_trace(go.Scatter(x=ser.index, y=ser, name=name, line=dict(color=color[name], width=2.2 if "VR" in name else 1.6)))
    if len(ext):
        cum = flows.set_index("date")["amount"].groupby(level=0).sum().cumsum().reindex(total.index).ffill()
        f1.add_trace(go.Scatter(x=cum.index, y=cum, name="투입 원금 누계", line=dict(color="#999", dash="dash", shape="hv")))
    f1.update_layout(title="계좌 총액 비교 (같은 금액·같은 입출금 일정으로 단순 보유했을 때와 비교)",
                     yaxis_title="달러", hovermode="x unified", template="plotly_white", height=480,
                     legend=dict(orientation="h", y=-0.15),
                     updatemenus=[dict(type="buttons", direction="left", x=0, y=1.13, showactive=True,
                                       buttons=[dict(label="일반 눈금", method="relayout", args=[{"yaxis.type": "linear"}]),
                                                dict(label="로그 눈금", method="relayout", args=[{"yaxis.type": "log"}])])])
    figs.append(f1)
    # 2) 낙폭 비교 (입출금 효과 제거)
    f2 = go.Figure()
    for name, ser in series.items():
        idx = twr_index(ser.dropna(), ext2)
        dd = (idx / idx.cummax() - 1) * 100
        f2.add_trace(go.Scatter(x=dd.index, y=dd, name=name, line=dict(color=color[name], width=1.4)))
    f2.update_layout(title="낙폭(고점 대비 하락률, %)", hovermode="x unified", template="plotly_white",
                     height=340, legend=dict(orientation="h", y=-0.2))
    figs.append(f2)
    # 3) VR 상세 (책 그림 형태)
    f3 = go.Figure()
    f3.add_trace(go.Scatter(x=d.index, y=d["eval"], name="평가금", line=dict(color="#d62728")))
    f3.add_trace(go.Scatter(x=d.index, y=d["V"], name="V", line=dict(color="#ff7f0e", shape="hv")))
    f3.add_trace(go.Scatter(x=d.index, y=d["max_band"], name="최대밴드", line=dict(color="#2ca02c", dash="dot", shape="hv")))
    f3.add_trace(go.Scatter(x=d.index, y=d["min_band"], name="최소밴드", line=dict(color="#2ca02c", dash="dot", shape="hv")))
    f3.add_trace(go.Scatter(x=d.index, y=d["pool"], name="Pool", line=dict(color="#1f77b4")))
    if cfg.get("safety", {}).get("enabled"):
        if "stop_line" in d:
            f3.add_trace(go.Scatter(x=d.index, y=d["stop_line"], name="안전장치 매도선",
                                    line=dict(color="#555", dash="dash", width=1, shape="hv")))
        trd = res["trades"]
        for reason, label, sym, col in (("stop", "안전장치 전량 매도", "triangle-down", "#000"),
                                        ("reentry", "재진입", "triangle-up", "#2ca02c")):
            m = trd[trd["reason"] == reason] if len(trd) else trd
            if len(m):
                dts = pd.to_datetime(m["date"])
                f3.add_trace(go.Scatter(x=dts, y=d["total"].reindex(dts).values, mode="markers", name=label,
                                        marker=dict(symbol=sym, size=11, color=col)))
                for dt in dts:
                    f1.add_vline(x=dt, line_width=1, line_dash="dot",
                                 line_color="#999" if reason == "stop" else "#9c9")
    f3.update_layout(title="VR 진행 모습 (평가금 · V · 밴드 · Pool)", hovermode="x unified",
                     template="plotly_white", height=460, legend=dict(orientation="h", y=-0.15))
    figs.append(f3)

    chart_html = []
    for i, f in enumerate(figs):
        chart_html.append('<div class="box">' + f.to_html(full_html=False, include_plotlyjs=(i == 0),
                                                          config={"displaylogo": False, "responsive": True}) + "</div>")

    # 비교표
    rows = [{"구분": f"{ticker} VR", "CAGR(%)": summary["CAGR(시간가중)"], "MDD(%)": summary["MDD(시간가중)"],
             "MDD 사이클 종료일(%)": summary["MDD(사이클 종료일 기준)"], "최종 계좌총액": summary["최종 계좌총액"]}]
    for t, b in bench.items():
        if "오류" in b:
            rows.append({"구분": f"{t} 단순보유", "CAGR(%)": None, "MDD(%)": None, "MDD 사이클 종료일(%)": None,
                         "최종 계좌총액": f"오류: {b['오류']}"})
        else:
            rows.append({"구분": f"{t} 단순보유", "CAGR(%)": b["CAGR(시간가중)"], "MDD(%)": b["MDD(시간가중)"],
                         "MDD 사이클 종료일(%)": None, "최종 계좌총액": b["최종 계좌총액"]})
    comp = pd.DataFrame(rows)

    # 연도별 수익률
    ann = {}
    for name, ser in series.items():
        ann[name] = _annual(twr_index(ser.dropna(), ext2))
    ann = pd.DataFrame(ann)
    ann.index = ann.index.year
    ann = ann.reset_index().rename(columns={"index": "연도", "Date": "연도", "date": "연도"})
    ann.columns = ["연도"] + list(ann.columns[1:])

    # 설정표
    per = c["periodic"]
    per_txt = (f"사이클마다 {per['ratio']*100:+.2f}% ({'최초 투자금' if per.get('ratio_base','initial')=='initial' else '현재 계좌총액'} 기준)"
               if per["type"] == "ratio" else f"사이클마다 ${per['amount'] or 0:+,.2f}")
    src = cfg["_source"]
    settings = [
        ("종목", ticker, ""), ("기간", f"{dc['start']} ~ {dc['end']}", ""),
        ("초기 투자금", f"${float(c['initial']):,.0f}", ""),
        ("방식", f"{MODE_KO[s['mode']]} / {'실력공식' if s['formula']=='skill' else '기본공식'}", ""),
        ("G", s["G"], src.get("strategy.G", "")),
        ("밴드", f"-{s['band_low']*100:g}% / +{s['band_high']*100:g}%", src.get("strategy.band_low", "")),
        ("Pool 사용한도", f"{s['pool_limit']*100:g}% ({'한도에 가장 가까운 개수' if s['pool_limit_rule']=='nearest' else '한도 초과 안 함'})", src.get("strategy.pool_limit", "")),
        ("초기 Pool 비율", f"{c['initial_pool_ratio']*100:g}%", src.get("capital.initial_pool_ratio", "")),
        ("적립/인출", per_txt, src.get("capital.periodic", "")),
        ("사이클", f"{s['cycle_length']}거래일" if s["cycle_mode"] == "trading_days" else "2주(달력)", ""),
        ("수수료", f"{k['commission_rate']*100:g}% (최소 ${k['commission_min']:g})", src.get("costs.commission_rate", "")),
        ("슬리피지", f"{k['slippage_bps']:g} bp", ""),
        ("체결 방식", {"realistic": "지정가 (갭이면 시가)", "limit": "지정가 그대로", "close": "종가 기준"}[cfg["fill"]["price_model"]], ""),
        ("양도세", "반영" if k["tax"]["enabled"] else "미반영", ""),
    ]
    sf = cfg.get("safety") or {}
    if sf.get("enabled"):
        re_txt = (f"{sf['reentry_ma']}일 이동평균 위로 올라오면" if sf.get("reentry_mode") == "ma"
                  else f"현금화 후 최저 종가에서 {sf['reentry_pct']*100:g}% 오르면")
        settings.append(("하락 안전장치", f"최소밴드보다 {sf['stop_pct']*100:g}% 더 내려가면 전량 매도, {re_txt} 재진입", "추가 옵션"))
    else:
        settings.append(("하락 안전장치", "끔", ""))
    set_rows = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(str(b))}</td><td class='src'>{html.escape(cs)}</td></tr>"
                       for a, b, cs in settings)

    cards = [("최종 계좌총액", _fmt(summary["최종 계좌총액"], "usd")),
             ("CAGR (연평균)", _fmt(summary["CAGR(시간가중)"], "pct")),
             ("MDD (최대 낙폭)", _fmt(summary["MDD(시간가중)"], "pct")),
             ("총 투입금", _fmt(summary["초기 투자금"] + summary["추가 적립 합계"], "usd")),
             ("총 인출금", _fmt(summary["인출 합계"], "usd")),
             ("매수 / 매도 체결", f"{summary['매수 체결 수']} / {summary['매도 체결 수']}"),
             ("수수료 + 세금", _fmt(summary["수수료 합계"] + summary["세금 합계"], "usd")),
             ("최종 Pool", _fmt(summary["최종 Pool"], "usd"))]
    if (cfg.get("safety") or {}).get("enabled"):
        cards.append(("안전장치 발동 / 재진입", f"{summary['안전장치 발동(전량 매도)']} / {summary['재진입']}"))
        cards.append(("현금화로 보낸 날", f"{summary['현금화 상태로 보낸 날']}일"))
    card_html = "".join(f'<div class="card"><div class="k">{a}</div><div class="v">{b}</div></div>' for a, b in cards)

    warns = list(cfg["_warnings"])
    if summary.get("같은 날 매수·매도 충돌"):
        warns.append(f"하루에 매수·매도가 모두 걸린 날이 {summary['같은 날 매수·매도 충돌']}번 있었습니다 (일봉이라 순서는 가정).")
    warn_html = "".join(f'<div class="warn">⚠ {html.escape(w)}</div>' for w in warns)

    cyc = res["cycles"].rename(columns=CYCLE_COLS_KO)
    keep = ["사이클", "시작일", "종료일", "시작 평가금", "마지막 평가금", "V", "최소밴드", "최대밴드",
            "시작 Pool", "마지막 Pool", "마지막 보유수", "매수 체결", "매도 체결", "적립(+)/인출(-)", "다음 V"]
    cyc = cyc[[x for x in keep if x in cyc.columns]]
    tr = res["trades"].copy()
    if len(tr):
        tr["date"] = pd.to_datetime(tr["date"]).dt.date
        tr = tr.rename(columns={"date": "날짜", "side": "구분", "qty": "수량", "price": "가격", "amount": "금액",
                                "fee": "수수료", "pool_after": "체결 후 Pool", "shares_after": "체결 후 보유수", "reason": "사유"})
        tr["구분"] = tr["구분"].map({"buy": "매수", "sell": "매도"})
        tr["사유"] = tr["사유"].replace({"stop": "안전장치 전량 매도", "reentry": "재진입", "initial": "최초 매수"})

    title = f"{ticker} VR 백테스트"
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>{html.escape(title)} · {MODE_KO[s['mode']]}</h1>
<div class="sub">{html.escape(summary['기간'])} · 만든 시각 {datetime.now():%Y-%m-%d %H:%M}</div>
<div class="cards">{card_html}</div>{warn_html}
<h2>비교 요약</h2><div class="scroll" style="max-height:none">{_table(comp, pct_cols=('CAGR(%)','MDD(%)','MDD 사이클 종료일(%)'))}</div>
<div class="sub" style="margin-top:6px">단순보유 = 같은 날 같은 금액을 넣고(적립·인출도 같은 날) 그냥 들고 있었을 때. CAGR·MDD는 입출금 효과를 뺀 시간가중 기준.</div>
<h2>그래프</h2>{''.join(chart_html)}
<div class="grid2">
<div><h2>연도별 수익률(%)</h2><div class="scroll">{_table(ann, pct_cols=tuple(ann.columns[1:]))}</div></div>
<div><h2>사용한 설정</h2><table><thead><tr><th>항목</th><th>값</th><th>출처</th></tr></thead><tbody>{set_rows}</tbody></table></div>
</div>
<details><summary>사이클별 정리표 ({len(cyc)}개, 책 정리표와 같은 형식)</summary><div class="scroll">{_table(cyc)}</div></details>
<details><summary>체결 내역 ({len(tr)}건)</summary><div class="scroll">{_table(tr) if len(tr) else '없음'}</div></details>
</div></body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path
