# VR 백테스터 (라오어 밸류 리밸런싱)

책 《라오어의 미국주식 밸류 리밸런싱》의 VR 규칙을 그대로 계산하는 백테스트 프로그램입니다.
종목, 기간, G, 밴드, Pool 사용한도, 적립/인출, 수수료, 세금을 `config.yaml`에서 바꿀 수 있습니다.
값을 비워 두면(null) 모드(적립/거치/인출)에 맞는 책 기본값이 들어갑니다.

## 설치 (Windows, 처음 한 번)
```
cd C:\Workspace\vr_backtest
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 실행
```
python -m pytest -q                       # 책 예시 숫자 재현 테스트
python cli.py fetch TQQQ QQQ QLD          # Yahoo Finance 데이터 받기 (data\ 에 CSV 저장)
python cli.py run config.yaml             # 기본: 2011~2020 거치식, 책 기본값
python cli.py run config.yaml --set strategy.mode=accumulate --set capital.initial=5000
python cli.py run config.yaml --set strategy.formula=skill --set costs.commission_rate=0.0009
python cli.py sweep config.yaml --grid strategy.G=5,10,20,30,40,50,100   # 책 PART6_03 표 재현
```
결과는 `results\` 에 저장됩니다.
- `*_cycles.csv`: 책 정리표와 같은 사이클별 표 (엑셀에서 바로 열림)
- `*_trades.csv`: 체결 내역 / `*_daily.csv`: 일별 평가금·Pool·V
- `*_summary.md`: CAGR, MDD, 수수료·세금 합계, 단순 보유 비교, 사용한 설정(책 기본값인지 직접 바꾼 값인지)
- `*_chart.html`: 책 그림처럼 평가금·V·밴드·Pool 그래프

## 주요 설정
| 설정 | 의미 | 책 기본값 |
|---|---|---|
| `strategy.mode` | accumulate 적립 / hold 거치 / withdraw 인출 | |
| `strategy.G` | 기울기 | 10 / 10 / 20 |
| `strategy.band_low`, `band_high` | 밴드 폭 (위아래 따로 가능) | 0.15 |
| `strategy.pool_limit` | 사이클당 Pool 사용한도 | 0.75 / 0.50 / 0.25 |
| `capital.initial_pool_ratio` | 시작 현금 비율 | 0 / 0.10 / 0.20 |
| `capital.periodic` | 적립(+)/인출(-), 고정 $ 또는 비율 | +250 / 0 / 최초금액의 -0.5% |
| `costs.broker` | 증권사 프리셋 (kis=한국투자증권 0.25%) | |
| `fill.price_model` | limit(책) / realistic(갭이면 시가 체결) | realistic |
| `data.synthetic.enabled` | QQQ·^NDX로 3배 상품 흉내(닷컴버블 확인용) | false |

## 책과 다른 점 / 가정
- "Pool 사용한도 75% 근처"는 누적 매수액이 한도에 **가장 가까운 개수**로 해석(책 예시 5건과 일치). `pool_limit_rule: floor`로 바꾸면 한도를 절대 넘지 않음.
- 일봉만 쓰므로 하루 안의 체결 순서는 모릅니다. 매수·매도가 같은 날 모두 걸리면 `same_day_order` 설정을 따르고, 횟수를 결과에 표시합니다.
- 목돈 추가/인출(`events_csv`)은 해당 날짜가 속한 사이클의 마지막 날 종가로 처리합니다.
- 인출금이 Pool보다 크면 기본은 부족분만큼 종가에 매도(`withdraw_shortfall`).
- 세금은 이동평균 단가 기준 연 실현손익으로 근사 계산(기본 꺼짐).

## 책 결과와 비교
`results\VALIDATION.md` 참고. 2011~2020 거치식에서 G=5~100 모두 책과 같은 경향이고, MDD(사이클 종료일 기준)는 대부분 1%p 안쪽, CAGR은 1~1.8%p 낮게 나옵니다.
- Yahoo 가격은 분할이 반영돼 2011년 TQQQ가 $0.3 수준이라, 시작가가 $10 미만이면 가격 전체를 같은 비율로 키워서 계산합니다(`data.rescale: auto`, 수익률은 동일).
- MDD는 매일 기준, 사이클 종료일 기준(책 방식으로 추정) 둘 다 보여줍니다.

## 구조
```
vr/formula.py  V 갱신(기본·실력공식), 밴드
vr/ladder.py   매수·매도 사다리(예약 주문표)  ← 자동매매에서도 재사용
vr/engine.py   사이클 진행, 체결 판정, 적립/인출, 목돈, 세금
vr/costs.py    수수료·슬리피지
vr/data.py     yfinance / CSV / 합성 레버리지
vr/metrics.py  CAGR, MDD, 시간가중·금액가중 수익률, 단순보유 비교
vr/report.py   CSV·요약·그래프 저장
cli.py         run / sweep / fetch
```
