"""매수·매도 사다리(예약 지정가 주문표). 책 PART4_03 매수표/매도표와 1:1."""
from dataclasses import dataclass

from .utils import rnd


@dataclass
class Order:
    side: str      # "buy" | "sell"
    price: float   # 지정가 (inf 이면 시장가처럼 바로 체결)
    qty: int
    step: int      # 사다리 몇 번째 칸인지 (1부터)


def buy_ladder(min_band, shares0, pool, pool_limit, rule="nearest", lot=1,
               digits=2, fee_fn=None, max_orders=100000):
    """k번째 매수가 = 최소밴드 / (보유수 + (k-1)*lot).

    사용한도: 누적 매수액이 pool*pool_limit 에
      - nearest: 가장 가까워지는 개수까지 (책 예시와 일치, 한도를 살짝 넘을 수 있음)
      - floor  : 넘지 않는 최대 개수까지
    어느 경우든 실제 Pool(수수료 포함)을 넘는 주문은 만들지 않는다.
    """
    budget = pool * pool_limit
    fee_fn = fee_fn or (lambda side, price, qty: 0.0)
    orders, cums = [], [0.0]
    cum = 0.0
    for k in range(1, max_orders + 1):
        denom = shares0 + (k - 1) * lot
        price = float("inf") if denom <= 0 else rnd(min_band / denom, digits)
        if price == float("inf"):
            # 보유 0주: 가격 기준이 없으므로 이번 사이클은 매수 없음(엔진에서 별도 처리)
            break
        if price <= 0:
            break
        cost = price * lot + fee_fn("buy", price, lot)
        if cum + cost > pool + 1e-9:
            break
        if rule == "floor" and cum + cost > budget + 1e-9:
            break
        if rule == "nearest" and cum > budget:
            break
        orders.append(Order("buy", price, lot, k))
        cum += cost
        cums.append(cum)
    if rule == "nearest" and orders:
        # 누적액이 한도에 가장 가까운 개수 선택 (동률이면 적게)
        best = min(range(len(cums)), key=lambda i: (abs(cums[i] - budget), i))
        orders = orders[:best]
    return orders


def sell_ladder(max_band, shares0, lot=1, digits=2):
    """k번째 매도가 = 최대밴드 / (보유수 - (k-1)*lot). 매도는 한도 없음."""
    orders = []
    k = 1
    while shares0 - (k - 1) * lot >= lot:
        denom = shares0 - (k - 1) * lot
        orders.append(Order("sell", rnd(max_band / denom, digits), lot, k))
        k += 1
    return orders
