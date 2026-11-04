"""VR 백테스터 화면(UI). 설정을 고르고 [테스트 실행]을 누르면 HTML 보고서가 브라우저에 열린다.

실행: python gui.py   (또는 VR_Backtest.exe / 실행.bat)
"""
import json
import os
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk


def base_dir():
    if getattr(sys, "frozen", False):          # exe 로 실행될 때: exe 가 있는 폴더
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = base_dir()
os.chdir(BASE)
sys.path.insert(0, BASE)

from vr import config as C          # noqa: E402
from vr import report as R          # noqa: E402
from vr.runner import run           # noqa: E402

SETTINGS_FILE = os.path.join(BASE, "gui_settings.json")
MODES = {"적립식": "accumulate", "거치식": "hold", "인출식": "withdraw"}
MODES_R = {v: k for k, v in MODES.items()}
FILLS = {"지정가 (갭이면 시가) - 추천": "realistic", "지정가 그대로 (책 예시)": "limit", "종가 기준": "close"}
FILLS_R = {v: k for k, v in FILLS.items()}
RULES = {"한도에 가장 가까운 개수 (책)": "nearest", "한도를 넘지 않게": "floor"}
RULES_R = {v: k for k, v in RULES.items()}
FLOW_UNITS = ["$ (고정 금액)", "% (최초 투자금 기준)", "% (현재 계좌총액 기준)"]
BENCH_CHOICES = ["QQQ", "SPY", "TQQQ", "QLD"]

DEFAULTS = {
    "ticker": "TQQQ", "start": "2011-01-01", "end": "2020-12-31", "initial": "20000", "refresh": False,
    "mode": "거치식", "formula": "기본공식", "cycle_length": "10",
    "commission": "0.25", "commission_min": "0", "slippage": "0", "cash_yield": "0",
    "tax": False, "fx_rate": "1400", "fill": FILLS_R["realistic"], "rule": RULES_R["nearest"],
    "bench": {"QQQ": True, "SPY": True, "TQQQ": True, "QLD": False}, "bench_extra": "",
}


def book_values(mode_ko):
    p = C.MODE_PRESETS[MODES[mode_ko]]
    if p["periodic_type"] == "ratio":
        flow, unit = f"{p['periodic_ratio'] * 100:g}", FLOW_UNITS[1]
    else:
        flow, unit = f"{p['periodic_amount']:g}", FLOW_UNITS[0]
    return {"G": f"{p['G']:g}", "band_low": f"{p['band_low'] * 100:g}", "band_high": f"{p['band_high'] * 100:g}",
            "pool_limit": f"{p['pool_limit'] * 100:g}", "init_pool": f"{p['initial_pool_ratio'] * 100:g}",
            "flow": flow, "flow_unit": unit}


class App:
    def __init__(self, root):
        self.root = root
        root.title("VR 백테스터 (라오어 밸류 리밸런싱)")
        root.geometry("760x780")
        root.minsize(700, 700)
        self.v = {}
        self.bench = {}
        self.last_report = None
        saved = self.load_settings()

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)

        # --- 기본 ---
        f1 = ttk.LabelFrame(main, text=" 기본 ", padding=8)
        f1.pack(fill="x")
        self.entry(f1, 0, 0, "종목", "ticker", saved, width=10)
        self.entry(f1, 0, 2, "초기 투자금($)", "initial", saved, width=12)
        self.entry(f1, 1, 0, "시작일", "start", saved, width=12, hint="예: 2011-01-01")
        self.entry(f1, 1, 2, "종료일", "end", saved, width=12, hint="예: 2020-12-31")
        self.v["refresh"] = tk.BooleanVar(value=saved.get("refresh", False))
        ttk.Checkbutton(f1, text="가격 데이터 새로 받기 (최신 데이터가 필요할 때)", variable=self.v["refresh"]).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # --- VR 설정 ---
        f2 = ttk.LabelFrame(main, text=" VR 설정 ", padding=8)
        f2.pack(fill="x", pady=(10, 0))
        self.combo(f2, 0, 0, "방식", "mode", list(MODES), saved, cmd=self.on_mode)
        self.combo(f2, 0, 2, "V 공식", "formula", ["기본공식", "실력공식"], saved)
        self.entry(f2, 1, 0, "G", "G", saved, width=8)
        self.entry(f2, 1, 2, "사이클(거래일)", "cycle_length", saved, width=8)
        self.entry(f2, 2, 0, "최소밴드 -%", "band_low", saved, width=8)
        self.entry(f2, 2, 2, "최대밴드 +%", "band_high", saved, width=8)
        self.entry(f2, 3, 0, "Pool 사용한도 %", "pool_limit", saved, width=8)
        self.entry(f2, 3, 2, "시작 Pool 비율 %", "init_pool", saved, width=8)
        self.entry(f2, 4, 0, "사이클당 적립(+)/인출(-)", "flow", saved, width=10)
        self.combo(f2, 4, 2, "단위", "flow_unit", FLOW_UNITS, saved, width=22)
        self.combo(f2, 5, 0, "사용한도 해석", "rule", list(RULES), saved, width=28, span=3)
        ttk.Button(f2, text="책 기본값으로 되돌리기", command=self.fill_book).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.book_label = ttk.Label(f2, foreground="#666")
        self.book_label.grid(row=6, column=2, columnspan=2, sticky="w", pady=(6, 0))

        # --- 비용·체결 ---
        f3 = ttk.LabelFrame(main, text=" 수수료 · 체결 ", padding=8)
        f3.pack(fill="x", pady=(10, 0))
        self.entry(f3, 0, 0, "수수료 %", "commission", saved, width=8, hint="한투 기본 0.25")
        self.entry(f3, 0, 2, "최소 수수료 $", "commission_min", saved, width=8)
        self.entry(f3, 1, 0, "슬리피지 bp", "slippage", saved, width=8, hint="1bp=0.01%")
        self.entry(f3, 1, 2, "Pool 이자 연%", "cash_yield", saved, width=8)
        self.combo(f3, 2, 0, "체결 방식", "fill", list(FILLS), saved, width=28, span=3)
        self.v["tax"] = tk.BooleanVar(value=saved.get("tax", False))
        ttk.Checkbutton(f3, text="양도세 반영 (연 250만원 공제 후 22%)", variable=self.v["tax"]).grid(row=3, column=0, columnspan=2, sticky="w")
        self.entry(f3, 3, 2, "환율(원/$)", "fx_rate", saved, width=8)

        # --- 비교 대상 ---
        f4 = ttk.LabelFrame(main, text=" 그래프 비교 대상 (그냥 사서 들고 있었을 때) ", padding=8)
        f4.pack(fill="x", pady=(10, 0))
        sb = saved.get("bench", DEFAULTS["bench"])
        for i, t in enumerate(BENCH_CHOICES):
            self.bench[t] = tk.BooleanVar(value=sb.get(t, False))
            ttk.Checkbutton(f4, text=t, variable=self.bench[t]).grid(row=0, column=i, sticky="w", padx=(0, 14))
        ttk.Label(f4, text="추가(쉼표로 구분)").grid(row=0, column=4, padx=(10, 4))
        self.v["bench_extra"] = tk.StringVar(value=saved.get("bench_extra", ""))
        ttk.Entry(f4, textvariable=self.v["bench_extra"], width=14).grid(row=0, column=5)

        # --- 실행 ---
        f5 = ttk.Frame(main)
        f5.pack(fill="x", pady=(12, 0))
        self.run_btn = ttk.Button(f5, text="▶  테스트 실행", command=self.start)
        self.run_btn.pack(side="left", ipadx=16, ipady=6)
        ttk.Button(f5, text="마지막 결과 열기", command=self.open_last).pack(side="left", padx=8, ipady=6)
        ttk.Button(f5, text="결과 폴더 열기", command=self.open_folder).pack(side="left", ipady=6)
        self.prog = ttk.Progressbar(f5, mode="indeterminate", length=140)
        self.prog.pack(side="right")

        self.log = tk.Text(main, height=9, wrap="word", state="disabled", background="#f7f7f7")
        self.log.pack(fill="both", expand=True, pady=(10, 0))
        self.write("설정을 고른 뒤 [테스트 실행]을 누르세요. 결과는 브라우저에 열립니다.")
        self.on_mode(initial=True, saved=saved)

    # ---------- 위젯 도우미 ----------
    def entry(self, parent, r, c, label, key, saved, width=12, hint=None):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="w", padx=(0, 6), pady=3)
        self.v[key] = tk.StringVar(value=str(saved.get(key, DEFAULTS.get(key, ""))))
        fr = ttk.Frame(parent)
        fr.grid(row=r, column=c + 1, sticky="w", padx=(0, 18))
        ttk.Entry(fr, textvariable=self.v[key], width=width).pack(side="left")
        if hint:
            ttk.Label(fr, text=hint, foreground="#888").pack(side="left", padx=4)

    def combo(self, parent, r, c, label, key, values, saved, width=12, span=1, cmd=None):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="w", padx=(0, 6), pady=3)
        self.v[key] = tk.StringVar(value=saved.get(key, DEFAULTS.get(key, values[0])))
        cb = ttk.Combobox(parent, textvariable=self.v[key], values=values, state="readonly", width=width)
        cb.grid(row=r, column=c + 1, columnspan=span, sticky="w", padx=(0, 18))
        if cmd:
            cb.bind("<<ComboboxSelected>>", lambda e: cmd())

    def write(self, msg):
        def _w():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _w)

    # ---------- 동작 ----------
    def on_mode(self, initial=False, saved=None):
        bv = book_values(self.v["mode"].get())
        if initial and saved and "G" in saved:
            for k in bv:
                if not self.v.get(k) or not self.v[k].get():
                    self.v[k].set(bv[k])
        else:
            for k, val in bv.items():
                self.v[k].set(val)
        self.book_label.config(text=f"책: G {bv['G']}, 밴드 ±{bv['band_low']}%, 사용한도 {bv['pool_limit']}%, 시작 Pool {bv['init_pool']}%")

    def fill_book(self):
        self.on_mode()

    def num(self, key, label):
        txt = self.v[key].get().strip().replace(",", "")
        try:
            return float(txt)
        except ValueError:
            raise ValueError(f"'{label}' 값이 숫자가 아닙니다: {txt!r}")

    def build_cfg(self):
        import pandas as pd
        for key, label in (("start", "시작일"), ("end", "종료일")):
            try:
                pd.Timestamp(self.v[key].get().strip())
            except Exception:
                raise ValueError(f"'{label}' 형식이 잘못됐습니다. 예: 2011-01-01")
        unit = self.v["flow_unit"].get()
        flow = self.num("flow", "적립/인출")
        if unit == FLOW_UNITS[0]:
            periodic = {"type": "fixed", "amount": flow, "ratio": None, "ratio_base": "initial"}
        else:
            periodic = {"type": "ratio", "amount": None, "ratio": flow / 100,
                        "ratio_base": "initial" if unit == FLOW_UNITS[1] else "total"}
        benches = [t for t, b in self.bench.items() if b.get()]
        benches += [t.strip().upper() for t in self.v["bench_extra"].get().split(",") if t.strip()]
        ticker = self.v["ticker"].get().strip().upper()
        cfg = {
            "data": {"ticker": ticker, "source": "yfinance", "cache_dir": os.path.join(BASE, "data"),
                     "start": self.v["start"].get().strip(), "end": self.v["end"].get().strip(),
                     "refresh": bool(self.v["refresh"].get())},
            "strategy": {"mode": MODES[self.v["mode"].get()],
                         "formula": "skill" if self.v["formula"].get() == "실력공식" else "basic",
                         "G": self.num("G", "G"), "band_low": self.num("band_low", "최소밴드") / 100,
                         "band_high": self.num("band_high", "최대밴드") / 100,
                         "pool_limit": self.num("pool_limit", "Pool 사용한도") / 100,
                         "pool_limit_rule": RULES[self.v["rule"].get()],
                         "cycle_length": int(self.num("cycle_length", "사이클"))},
            "capital": {"initial": self.num("initial", "초기 투자금"),
                        "initial_pool_ratio": self.num("init_pool", "시작 Pool 비율") / 100, "periodic": periodic},
            "costs": {"broker": "kis", "commission_rate": self.num("commission", "수수료") / 100,
                      "commission_min": self.num("commission_min", "최소 수수료"),
                      "slippage_bps": self.num("slippage", "슬리피지"),
                      "cash_yield": self.num("cash_yield", "Pool 이자") / 100,
                      "fx_rate": self.num("fx_rate", "환율"),
                      "tax": {"enabled": bool(self.v["tax"].get()), "rate": 0.22, "deduction_krw": 2500000}},
            "fill": {"price_model": FILLS[self.v["fill"].get()]},
            "report": {"out_dir": os.path.join(BASE, "results"), "benchmarks": list(dict.fromkeys(benches)), "html": True},
        }
        if cfg["capital"]["initial"] <= 0:
            raise ValueError("초기 투자금은 0보다 커야 합니다")
        return C.resolve(cfg)

    def start(self):
        try:
            cfg = self.build_cfg()
        except Exception as e:
            messagebox.showerror("설정 확인", str(e))
            return
        self.save_settings()
        self.run_btn.config(state="disabled")
        self.prog.start(12)
        self.write("-" * 40)
        threading.Thread(target=self.work, args=(cfg,), daemon=True).start()

    def work(self, cfg):
        try:
            res, summary, bench, curves = run(cfg, log=self.write)
            name = f"VR_{cfg['data']['ticker']}_{cfg['strategy']['mode']}_{datetime.now():%Y%m%d_%H%M%S}"
            self.write("보고서 만드는 중...")
            base = R.save(res, summary, cfg, cfg["report"]["out_dir"], bench, name, curves)
            self.last_report = base + "_report.html"
            self.write(f"완료: CAGR {summary['CAGR(시간가중)']}%, MDD {summary['MDD(시간가중)']}%, 최종 ${summary['최종 계좌총액']:,.0f}")
            for t, b in bench.items():
                if "오류" in b:
                    self.write(f"  [{t}] 비교 데이터 없음: {b['오류']}")
            self.write(f"보고서: {self.last_report}")
            webbrowser.open("file:///" + self.last_report.replace("\\", "/"))
        except Exception as e:
            msg = str(e)
            if any(w in msg for w in ("받지 못했", "SSL", "timed out", "Connection", "curl")):
                msg += "\n\n회사망 등에서 Yahoo Finance 접속이 막힐 수 있어요. 휴대폰 핫스팟으로 연결한 뒤 다시 실행해 보세요."
            self.write("오류: " + msg)
            self.write(traceback.format_exc(limit=3))
            self.root.after(0, lambda: messagebox.showerror("실행 오류", msg))
        finally:
            self.root.after(0, lambda: (self.prog.stop(), self.run_btn.config(state="normal")))

    def open_last(self):
        if self.last_report and os.path.exists(self.last_report):
            webbrowser.open("file:///" + self.last_report.replace("\\", "/"))
        else:
            self.open_folder()

    def open_folder(self):
        path = os.path.join(BASE, "results")
        os.makedirs(path, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        else:
            webbrowser.open("file://" + path)

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return {**DEFAULTS, **json.load(f)}
        except Exception:
            return dict(DEFAULTS)

    def save_settings(self):
        data = {k: (v.get() if not isinstance(v, tk.BooleanVar) else bool(v.get())) for k, v in self.v.items()}
        data["bench"] = {t: bool(b.get()) for t, b in self.bench.items()}
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if sys.platform.startswith("win") else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
