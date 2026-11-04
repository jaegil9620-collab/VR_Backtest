"""수수료·슬리피지 모델."""


class CostModel:
    def __init__(self, costs):
        self.rate = costs["commission_rate"]
        self.min = costs["commission_min"]
        self.per_share = costs["commission_per_share"]
        self.sec = costs["sec_fee_rate"]
        self.slip = costs["slippage_bps"] / 10000.0

    def fee(self, side, price, qty):
        amount = price * qty
        f = amount * self.rate + qty * self.per_share
        if amount > 0:
            f = max(f, self.min)
        if side == "sell":
            f += amount * self.sec
        return round(f, 2)

    def slipped(self, side, price):
        return price * (1 + self.slip) if side == "buy" else price * (1 - self.slip)
