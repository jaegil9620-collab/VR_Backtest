"""마음에 드는 설정을 전략으로 저장/불러오기. 포트폴리오 백테스터와 나중의 자동매매 프로그램도 이 파일을 읽는다.

저장 위치: strategies/<이름>.yaml  (사람이 읽고 고칠 수 있는 YAML)
  name, memo, saved_at : 이름, 메모, 저장 시각
  program              : 어느 백테스터의 전략인지 (vr)
  result               : 저장할 때의 백테스트 결과 요약 (참고용)
  config               : config.yaml 과 같은 구조 (보고서 설정 제외)
  ui                   : 화면(UI) 입력값 그대로 (화면에서 다시 불러올 때 씀)

다른 프로그램에서 쓰는 법:
    from vr import strategies as ST
    cfg = ST.load_config("이름")          # 바로 실행할 수 있는 설정 (기본값 채워짐)
"""
import copy
import os
import re
from datetime import datetime

import yaml

from . import config as C

PROGRAM = "vr"
DIR = "strategies"
SUMMARY_PREFIX = ("기간", "CAGR", "MDD", "연평균", "총 수익률", "최종", "수수료 합계", "사이클 수")


def _dir(folder=None):
    d = folder or DIR
    if not os.path.isabs(d):
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d)
    os.makedirs(d, exist_ok=True)
    return d


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", str(name).strip()).strip("._")
    if not name:
        raise ValueError("전략 이름을 입력하세요")
    return name


def path_of(name, folder=None):
    return os.path.join(_dir(folder), safe_name(name) + ".yaml")


def clean_config(cfg):
    """실행에 필요한 설정만 남긴다 (내부 계산 값·보고서 설정·PC 경로 제외)."""
    out = {}
    for sec, val in cfg.items():
        if str(sec).startswith("_") or sec == "report":
            continue
        out[sec] = copy.deepcopy(val) if not isinstance(val, dict) else \
            {k: copy.deepcopy(v) for k, v in val.items() if not str(k).startswith("_")}
    d = out.get("data", {})
    d.pop("cache_dir", None)
    d.pop("refresh", None)
    if d.get("source", "yfinance") == "yfinance":
        d.pop("csv_path", None)
    return out


def _plain(v):
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "item"):
        return v.item()
    if hasattr(v, "isoformat") and not isinstance(v, str):
        return str(v)[:10]
    return v


def short_result(summary):
    if not summary:
        return None
    out = {k: v for k, v in summary.items() if str(k).startswith(SUMMARY_PREFIX) and not isinstance(v, (dict, list))}
    return out or None


def save(name, cfg, summary=None, memo="", ui=None, folder=None):
    doc = {"name": safe_name(name), "memo": memo or "", "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "program": PROGRAM, "result": short_result(summary), "config": clean_config(cfg)}
    if ui:
        doc["ui"] = ui
    p = path_of(name, folder)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(_plain(doc), f, allow_unicode=True, sort_keys=False)
    return p


def load(name, folder=None):
    p = path_of(name, folder)
    if not os.path.exists(p):
        raise FileNotFoundError(f"저장된 전략 '{name}' 이 없습니다 ({p})")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(name, overrides=None, folder=None):
    """저장된 전략을 실행 가능한 설정으로 (빈 값은 기본값으로 채움)."""
    cfg = copy.deepcopy(load(name, folder).get("config") or {})
    for dotted, val in (overrides or {}).items():
        d = cfg
        parts = dotted.split(".")
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = val
    return C.resolve(cfg)


def pick(result, prefix):
    """결과 요약에서 'CAGR', 'MDD' 처럼 이름이 prefix 로 시작하는 첫 값."""
    for k, v in (result or {}).items():
        if str(k).startswith(prefix) and isinstance(v, (int, float)):
            return v
    return None


def list_all(folder=None):
    out = []
    d = _dir(folder)
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".yaml"):
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    doc = yaml.safe_load(f) or {}
                out.append({"name": doc.get("name", fn[:-5]), "memo": doc.get("memo", ""),
                            "saved_at": doc.get("saved_at", ""), "result": doc.get("result") or {},
                            "ticker": (doc.get("config") or {}).get("data", {}).get("ticker", ""),
                            "has_ui": bool(doc.get("ui"))})
            except Exception as e:
                out.append({"name": fn[:-5], "memo": f"읽기 오류: {e}", "saved_at": "", "result": {}, "ticker": "",
                            "has_ui": False})
    return out


def delete(name, folder=None):
    p = path_of(name, folder)
    if os.path.exists(p):
        os.remove(p)
