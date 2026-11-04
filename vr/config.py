"""설정 로딩: 책 기본값(모드별 프리셋) + 증권사 프리셋 + 사용자 config.yaml 덮어쓰기."""
import copy
import warnings

import yaml

# PART4_01~05 책 기본값
MODE_PRESETS = {
    "accumulate": {"G": 10, "band_low": 0.15, "band_high": 0.15, "pool_limit": 0.75,
                   "initial_pool_ratio": 0.0, "periodic_type": "fixed", "periodic_amount": 250.0,
                   "periodic_ratio": None},
    "hold":       {"G": 10, "band_low": 0.15, "band_high": 0.15, "pool_limit": 0.50,
                   "initial_pool_ratio": 0.10, "periodic_type": "fixed", "periodic_amount": 0.0,
                   "periodic_ratio": None},
    "withdraw":   {"G": 20, "band_low": 0.15, "band_high": 0.15, "pool_limit": 0.25,
                   "initial_pool_ratio": 0.20, "periodic_type": "ratio", "periodic_amount": None,
                   "periodic_ratio": -0.005},   # 최초 투자금의 0.5%를 사이클마다 인출
}

# 증권사 프리셋 (실제 우대율은 계좌마다 다르므로 config 에서 덮어쓰기)
BROKER_PRESETS = {
    "kis": {"commission_rate": 0.0025, "commission_min": 0.0, "commission_per_share": 0.0,
            "sec_fee_rate": 0.0000278, "fx_spread": 0.0},   # 한국투자증권
    "none": {"commission_rate": 0.0, "commission_min": 0.0, "commission_per_share": 0.0,
             "sec_fee_rate": 0.0, "fx_spread": 0.0},
}

# 책 권장 범위 (벗어나면 경고만)
RECOMMENDED = {
    "band_low": (0.10, 0.20), "band_high": (0.10, 0.20), "pool_limit": (0.10, 1.0),
    "G": (5, 100),
}

DEFAULTS = {
    "data": {"ticker": "TQQQ", "source": "yfinance", "csv_path": None, "cache_dir": "data",
             "start": "2011-01-01", "end": "2020-12-31", "refresh": False,
             "synthetic": {"enabled": False, "base_ticker": "QQQ", "leverage": 3,
                           "expense_ratio": 0.0095, "financing_rate": 0.0}},
    "strategy": {"mode": "hold", "formula": "basic", "G": None, "G_schedule": None,
                 "band_low": None, "band_high": None, "pool_limit": None,
                 "pool_limit_rule": "nearest", "cycle_mode": "trading_days",
                 "cycle_length": 10, "lot_size": 1, "round_digits": 2},
    "capital": {"initial": 20000.0, "initial_pool_ratio": None,
                "periodic": {"type": None, "amount": None, "ratio": None, "ratio_base": "initial"},
                "withdraw_shortfall": "sell", "events_csv": None},
    "costs": {"broker": "kis", "commission_rate": None, "commission_min": None,
              "commission_per_share": None, "sec_fee_rate": None, "slippage_bps": 0.0,
              "fx_spread": None, "fx_rate": 1400.0, "cash_yield": 0.0,
              "tax": {"enabled": False, "rate": 0.22, "deduction_krw": 2500000}},
    "fill": {"price_model": "realistic", "same_day_order": "sell_first"},
    "report": {"out_dir": "results", "benchmarks": ["TQQQ", "QQQ", "QLD"], "html": True},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve(cfg):
    """None 으로 남은 값에 책/증권사 기본값을 채우고, 어디서 온 값인지 기록한다."""
    cfg = _merge(DEFAULTS, cfg)
    s, c, k = cfg["strategy"], cfg["capital"], cfg["costs"]
    mode = s["mode"]
    if mode not in MODE_PRESETS:
        raise ValueError(f"mode 는 {list(MODE_PRESETS)} 중 하나여야 합니다: {mode}")
    p = MODE_PRESETS[mode]
    source = {}

    def fill(d, key, preset_key, label):
        if d.get(key) is None:
            d[key] = p[preset_key]
            source[label] = "책 기본값"
        else:
            source[label] = "사용자 설정"

    for key in ("G", "band_low", "band_high", "pool_limit"):
        fill(s, key, key, f"strategy.{key}")
    fill(c, "initial_pool_ratio", "initial_pool_ratio", "capital.initial_pool_ratio")

    per = c["periodic"]
    if per.get("type") is None and per.get("amount") is None and per.get("ratio") is None:
        per["type"] = p["periodic_type"]
        per["amount"] = p["periodic_amount"]
        per["ratio"] = p["periodic_ratio"]
        source["capital.periodic"] = "책 기본값"
    else:
        if per.get("type") is None:
            per["type"] = "ratio" if per.get("ratio") is not None else "fixed"
        source["capital.periodic"] = "사용자 설정"

    broker = BROKER_PRESETS.get(k["broker"], BROKER_PRESETS["none"])
    for key, val in broker.items():
        if k.get(key) is None:
            k[key] = val
            source[f"costs.{key}"] = f"증권사 프리셋({k['broker']})"
        else:
            source[f"costs.{key}"] = "사용자 설정"

    warns = []
    for key, (lo, hi) in RECOMMENDED.items():
        val = s[key]
        if not (lo <= val <= hi):
            warns.append(f"strategy.{key}={val} 는 책 권장 범위({lo}~{hi}) 밖입니다")
    for w in warns:
        warnings.warn(w)
    cfg["_source"] = source
    cfg["_warnings"] = warns
    return cfg


def load(path, overrides=None):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for dotted, val in (overrides or {}).items():
        d = cfg
        parts = dotted.split(".")
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = val
    return resolve(cfg)
