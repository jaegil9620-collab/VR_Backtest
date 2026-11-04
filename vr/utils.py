from decimal import Decimal, ROUND_HALF_UP


def rnd(x, digits):
    """책 방식 반올림(소수점 digits+1 자리에서 반올림). digits=None 이면 그대로."""
    if digits is None or x is None:
        return x
    if x != x or x in (float("inf"), float("-inf")):
        return x
    q = Decimal(1).scaleb(-digits)
    # 부동소수 오차(5749.424999...)를 먼저 정리한 뒤 반올림
    return float(Decimal(repr(round(float(x), 9))).quantize(q, rounding=ROUND_HALF_UP))
