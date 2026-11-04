"""책 스캔 → Markdown → 요약 프로그램 화면.

실행: 실행.bat 더블클릭 (또는 python app.py)
"""
import json
import os
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
sys.path.insert(0, BASE)

from scanner import capture as CAP      # noqa: E402
from scanner import claude as CL        # noqa: E402
from scanner import pipeline as PL      # noqa: E402

SETTINGS = os.path.join(BASE, "settings.json")
DEFAULTS = {
    "api_key": "", "model": "Opus 5.5 (가장 정확)", "ocr_effort": "low", "summary_effort": "high",
    "cap_dir": os.path.join(BASE, "captures", "새 책"), "cap_key": "→ (오른쪽 화살표)", "cap_delay": "1.5",
    "cap_max": "400", "cap_region": None, "cap_click": False, "cap_point": None,
    "src": "", "out": "", "split": "자동 (가로로 긴 펼침면이면 반으로)", "level": "장(##) 단위로 파일 나누기",
    "focus": "",
}
SPLITS = {"자동 (가로로 긴 펼침면이면 반으로)": "auto", "항상 반으로 나누기": "split", "나누지 않기": "none"}
LEVELS = {"장(##) 단위로 파일 나누기": 2, "부(#) 단위로 파일 나누기": 1}


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    return s


def open_path(p):
    if sys.platform.startswith("win"):
        os.startfile(p)
    else:
        subprocess.Popen(["xdg-open", p])


class App:
    def __init__(self, root):
        self.root = root
        self.s = load_settings()
        self.stop_flag = False
        self.busy = False
        self.usage = CL.Usage()
        root.title("책 스캔 · 요약")
        style = ttk.Style()
        try:
            style.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except Exception:
            pass
        style.configure(".", font=("Malgun Gothic", 10))
        style.configure("Big.TButton", font=("Malgun Gothic", 11, "bold"), padding=6)

        # ---- 공통: API 키, 모델
        top = ttk.LabelFrame(root, text=" Claude 설정 ", padding=8)
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.v_key = tk.StringVar(value=self.s["api_key"])
        self.v_model = tk.StringVar(value=self.s["model"])
        ttk.Label(top, text="API 키").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.v_key, show="•", width=50).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(top, text="저장", command=self.save).grid(row=0, column=2)
        ttk.Label(top, text="모델").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(top, textvariable=self.v_model, values=list(CL.MODEL_LABELS), state="readonly",
                     width=36).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        top.columnconfigure(1, weight=1)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=False, padx=10, pady=4)
        self.nb = nb
        nb.add(self._tab_capture(nb), text="  ① 화면 캡처  ")
        nb.add(self._tab_convert(nb), text="  ② Markdown 변환  ")
        nb.add(self._tab_summary(nb), text="  ③ 요약  ")

        # ---- 진행 기록
        bottom = ttk.Frame(root)
        bottom.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        bar = ttk.Frame(bottom)
        bar.pack(fill="x")
        self.v_usage = tk.StringVar(value=self.usage.text())
        ttk.Label(bar, textvariable=self.v_usage, foreground="#555").pack(side="left")
        ttk.Button(bar, text="중지", command=self.stop).pack(side="right")
        self.log_box = tk.Text(bottom, height=8, font=("Consolas", 9), wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))
        self.log("준비됐습니다. ① 화면 캡처로 책을 찍거나, 이미 있는 스캔 파일이면 ② 로 바로 가세요.")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._fit_window()

    def _fit_window(self):
        """화면 배율(125%·150%)에 상관없이 버튼이 다 보이도록 필요한 크기로 창을 연다."""
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), int(self.root.winfo_fpixels("8.5i")))
        h = self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(w, int(sw * 0.95)), min(h, int(sh * 0.9))
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        self.root.minsize(min(w, 600), min(h, 500))

    # ------------------------------------------------------------ 탭 ①
    def _tab_capture(self, nb):
        f = ttk.Frame(nb, padding=10)
        self.v_cap_dir = tk.StringVar(value=self.s["cap_dir"])
        self.v_cap_key = tk.StringVar(value=self.s["cap_key"])
        self.v_cap_delay = tk.StringVar(value=self.s["cap_delay"])
        self.v_cap_max = tk.StringVar(value=self.s["cap_max"])
        self.v_cap_click = tk.BooleanVar(value=self.s["cap_click"])
        self.region = tuple(self.s["cap_region"]) if self.s["cap_region"] else None
        self.point = tuple(self.s["cap_point"]) if self.s.get("cap_point") else None
        self.v_region = tk.StringVar(value=self._region_text())

        ttk.Label(f, text="브라우저·전자책 뷰어에 책을 띄워 두고, 페이지 영역을 고른 뒤 시작하면 "
                          "캡처 → 다음 페이지를 자동으로 반복합니다.", wraplength=740).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="저장 폴더").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_cap_dir).grid(row=1, column=1, sticky="we", padx=6)
        ttk.Button(f, text="찾기", command=lambda: self._pick_dir(self.v_cap_dir)).grid(row=1, column=2)
        ttk.Label(f, text="캡처 영역").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Label(f, textvariable=self.v_region).grid(row=2, column=1, sticky="w", padx=6)
        rb = ttk.Frame(f)
        rb.grid(row=2, column=2, sticky="e")
        ttk.Button(rb, text="영역 고르기", command=self.pick_region).pack(side="left")
        ttk.Label(f, text="페이지 넘기기").grid(row=3, column=0, sticky="w", pady=4)
        kr = ttk.Frame(f)
        kr.grid(row=3, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Combobox(kr, textvariable=self.v_cap_key, values=list(CAP.KEYS), state="readonly",
                     width=38).pack(side="left")
        self.v_point = tk.StringVar(value=self._point_text())
        self.btn_point = ttk.Button(kr, text="클릭 위치 고르기", command=self.pick_point)
        self.lbl_point = ttk.Label(kr, textvariable=self.v_point)
        self.v_cap_key.trace_add("write", lambda *a: self._show_point())
        self._show_point()
        row = ttk.Frame(f)
        row.grid(row=4, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(f, text="넘김 후 대기").grid(row=4, column=0, sticky="w")
        ttk.Entry(row, textvariable=self.v_cap_delay, width=6).pack(side="left")
        ttk.Label(row, text="초      최대").pack(side="left")
        ttk.Entry(row, textvariable=self.v_cap_max, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="장").pack(side="left")
        ttk.Checkbutton(f, text="시작할 때 영역 위쪽 가장자리를 한 번 클릭해서 책 창을 선택",
                        variable=self.v_cap_click).grid(row=5, column=1, sticky="w", padx=6)
        ttk.Button(f, text="캡처 시작", style="Big.TButton", command=self.start_capture).grid(
            row=6, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Label(f, text="시작하면 이 창이 작아지고 화면 구석에 진행 표시창이 뜹니다. 5초 안에 책 화면을 한 번 클릭하세요. "
                          "그다음은 프로그램이 페이지를 넘기며 찍고, 마지막 페이지에서 저절로 끝납니다(중간에 멈추기: Esc). "
                          "키로 안 넘어가면 '마우스 클릭'(뷰어의 다음 버튼을 대신 눌러 줌)이나 '직접 넘기기'(내가 넘길 때마다 찍음)를 고르세요.",
                  foreground="#666", wraplength=740).grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        f.columnconfigure(1, weight=1)
        return f

    def _region_text(self):
        if not self.region:
            return "(아직 안 고름)"
        x0, y0, x1, y1 = self.region
        return f"{x1 - x0} × {y1 - y0} 픽셀  (위치 {x0}, {y0})"

    def _point_text(self):
        return f"({self.point[0]}, {self.point[1]})" if self.point else "(아직 안 고름)"

    def _show_point(self):
        if CAP.KEYS.get(self.v_cap_key.get()) == "click":
            self.btn_point.pack(side="left", padx=6)
            self.lbl_point.pack(side="left")
        else:
            self.btn_point.pack_forget()
            self.lbl_point.pack_forget()

    def pick_point(self):
        self.root.iconify()

        def done(pt):
            self.root.deiconify()
            if pt:
                self.point = pt
                self.v_point.set(self._point_text())
                self.save(quiet=True)

        self.root.after(400, lambda: CAP.RegionPicker(self.root, done, point=True))

    def pick_region(self):
        self.root.iconify()

        def done(region):
            self.root.deiconify()
            if region:
                self.region = region
                self.v_region.set(self._region_text())
                self.save(quiet=True)

        self.root.after(400, lambda: CAP.RegionPicker(self.root, done))

    def start_capture(self):
        if not self.region:
            messagebox.showinfo("캡처", "먼저 [영역 고르기]로 책 페이지 영역을 고르세요.")
            return
        out = self.v_cap_dir.get().strip()
        try:
            delay = float(self.v_cap_delay.get())
            mx = int(self.v_cap_max.get())
        except ValueError:
            messagebox.showerror("캡처", "대기 시간과 최대 장 수는 숫자로 적어 주세요.")
            return
        start_no = 1
        if os.path.isdir(out):
            existing = [x for x in os.listdir(out) if x.startswith("page_") and x.endswith(".png")]
            if existing:
                if not messagebox.askyesno("캡처", f"이 폴더에 이미 {len(existing)}장이 있습니다.\n"
                                                  "이어서 저장할까요? (아니오 = 취소)"):
                    return
                start_no = max(int(x[5:9]) for x in existing) + 1
        self.save(quiet=True)
        x0, y0, x1, _ = self.region
        click = ((x0 + x1) // 2, y0 + 8) if self.v_cap_click.get() else None
        vk = CAP.KEYS[self.v_cap_key.get()]
        if vk == "click":
            if not self.point:
                messagebox.showinfo("캡처", "[클릭 위치 고르기]로 뷰어의 '다음' 버튼 위치를 먼저 고르세요.")
                return
            vk = ("click", *self.point)
        self.root.iconify()
        status = StatusBox(self.root, self.region)

        def log(m):
            self.log(m)
            status.set(m)

        def job():
            try:
                n = CAP.run_capture(self.region, out, vk, max_pages=mx, delay=delay, start_no=start_no,
                                    focus_click=click, log=log, stop=lambda: self.stop_flag, countdown=5)
            finally:
                status.close()
            self.log(f"캡처 끝: {n}장 → {out}")
            self.root.after(0, self.root.deiconify)
            self.root.after(0, lambda: (self.v_src.set(out), self._default_out(), self.nb.select(1)))

        self.run(job)

    # ------------------------------------------------------------ 탭 ②
    def _tab_convert(self, nb):
        f = ttk.Frame(nb, padding=10)
        self.v_src = tk.StringVar(value=self.s["src"])
        self.v_out = tk.StringVar(value=self.s["out"])
        self.v_split = tk.StringVar(value=self.s["split"])
        self.v_level = tk.StringVar(value=self.s["level"])
        ttk.Label(f, text="스캔 이미지 폴더(png/jpg) 또는 PDF 를 고르면 본문·표는 Markdown 으로, 그림은 잘라서 저장합니다. "
                          "한 번 인식한 페이지는 저장해 두어 다시 돌려도 비용이 들지 않습니다.",
                  wraplength=740).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, text="원본").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_src).grid(row=1, column=1, sticky="we", padx=6)
        ttk.Button(f, text="폴더", command=lambda: (self._pick_dir(self.v_src), self._default_out())).grid(row=1, column=2)
        ttk.Button(f, text="PDF", command=self._pick_pdf).grid(row=1, column=3, padx=(4, 0))
        ttk.Label(f, text="결과 폴더").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_out).grid(row=2, column=1, sticky="we", padx=6)
        ttk.Button(f, text="찾기", command=lambda: self._pick_dir(self.v_out)).grid(row=2, column=2)
        ttk.Label(f, text="펼침면").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=self.v_split, values=list(SPLITS), state="readonly",
                     width=34).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Label(f, text="파일 나누기").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=self.v_level, values=list(LEVELS), state="readonly",
                     width=34).grid(row=4, column=1, sticky="w", padx=6)
        b = ttk.Frame(f)
        b.grid(row=5, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Button(b, text="비용 미리 보기", command=self.estimate).pack(side="left")
        ttk.Button(b, text="변환 시작", style="Big.TButton", command=self.start_convert).pack(side="left", padx=8)
        ttk.Button(b, text="결과 폴더 열기", command=lambda: self._open(self.v_out.get())).pack(side="left")
        f.columnconfigure(1, weight=1)
        return f

    def _pick_pdf(self):
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p:
            self.v_src.set(p)
            self._default_out()

    def _default_out(self):
        src = self.v_src.get().strip().rstrip("\\/")
        if not src:
            return
        if os.path.isfile(src):
            out = os.path.splitext(src)[0] + "_md"
        else:
            out = os.path.join(os.path.dirname(src), os.path.basename(src) + "_md")
        self.v_out.set(out)
        if not self.v_sum_dir.get():
            self.v_sum_dir.set(out)

    def _count_units(self):
        files = PL.list_sources(self.v_src.get().strip())
        mode = SPLITS[self.v_split.get()]
        n = 0
        for _, img, _ in PL.iter_images(files):
            n += len(PL.split_parts(img, mode))
        return n

    def estimate(self):
        def job():
            n = self._count_units()
            model = CL.MODEL_LABELS[self.v_model.get()]
            pin, pout = CL.MODELS[model]
            # 한 장당 대략 입력 3천, 출력 3천 토큰 (생각 포함, 글자 많은 쪽 기준)
            cost = n * (3000 * pin + 3000 * pout) / 1e6
            self.log(f"인식할 쪽 {n}개 · 예상 비용 약 ${cost:.1f} (± 50%, 이미 인식한 쪽은 무료)")
        self.run(job)

    def start_convert(self):
        src, out = self.v_src.get().strip(), self.v_out.get().strip()
        if not src or not os.path.exists(src):
            messagebox.showinfo("변환", "원본 폴더나 PDF 를 고르세요.")
            return
        if not out:
            self._default_out()
            out = self.v_out.get().strip()
        if not self._client_ok():
            return
        self.save(quiet=True)
        model = CL.MODEL_LABELS[self.v_model.get()]
        effort = self.s.get("ocr_effort", "low")
        mode, level = SPLITS[self.v_split.get()], LEVELS[self.v_level.get()]

        def job():
            client = CL.make_client(self.v_key.get().strip())

            def ocr(img, name):
                r = CL.ocr_image(client, model, effort, img, name, self.usage)
                self.v_usage.set(self.usage.text())
                return r

            os.makedirs(out, exist_ok=True)
            pages = PL.recognize(src, out, ocr, model, mode, log=self.log, stop=lambda: self.stop_flag)
            written = PL.build_markdown(pages, out, level, log=self.log)
            self.log(f"변환 끝: 장 파일 {len(written)}개 → {out}\\README.md")
            self.v_sum_dir.set(out)
            open_path(out)

        self.run(job)

    # ------------------------------------------------------------ 탭 ③
    def _tab_summary(self, nb):
        f = ttk.Frame(nb, padding=10)
        self.v_sum_dir = tk.StringVar(value=self.s["out"])
        self.v_focus = tk.StringVar(value=self.s["focus"])
        ttk.Label(f, text="변환된 Markdown 폴더를 읽고 책 개요, 장별 요약, 자동매매 설계용 핵심 규칙, 백테스트 검증용 숫자를 "
                          "SUMMARY.md 로 만듭니다.", wraplength=740).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Markdown 폴더").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_sum_dir).grid(row=1, column=1, sticky="we", padx=6)
        ttk.Button(f, text="찾기", command=lambda: self._pick_dir(self.v_sum_dir)).grid(row=1, column=2)
        ttk.Label(f, text="요약 관점 (선택)").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_focus).grid(row=2, column=1, sticky="we", padx=6)
        ttk.Label(f, text="예: TQQQ 매매 규칙과 파라미터 위주로 / 위험 관리 규칙 자세히",
                  foreground="#666").grid(row=3, column=1, sticky="w", padx=6)
        b = ttk.Frame(f)
        b.grid(row=4, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Button(b, text="요약 만들기", style="Big.TButton", command=self.start_summary).pack(side="left")
        ttk.Button(b, text="요약 열기", command=lambda: self._open(os.path.join(self.v_sum_dir.get(), "SUMMARY.md"))
                   ).pack(side="left", padx=8)
        f.columnconfigure(1, weight=1)
        return f

    def start_summary(self):
        d = self.v_sum_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showinfo("요약", "변환된 Markdown 폴더를 고르세요.")
            return
        if not self._client_ok():
            return
        self.save(quiet=True)
        model = CL.MODEL_LABELS[self.v_model.get()]
        effort = self.s.get("summary_effort", "high")
        focus = self.v_focus.get()

        def job():
            text, files = PL.book_text(d)
            if not files:
                raise RuntimeError("이 폴더에 장 파일(00_*.md)이 없습니다. 먼저 ② 변환을 하세요.")
            self.log(f"장 파일 {len(files)}개, {len(text):,}자를 요약합니다. 몇 분 걸릴 수 있습니다...")
            client = CL.make_client(self.v_key.get().strip())
            md = CL.summarize(client, model, effort, text, focus, self.usage)
            self.v_usage.set(self.usage.text())
            path = os.path.join(d, "SUMMARY.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(md)
            self.log(f"요약 끝: {path}")
            open_path(path)

        self.run(job)

    # ------------------------------------------------------------ 공통
    def _client_ok(self):
        if self.v_key.get().strip() or os.environ.get("ANTHROPIC_API_KEY"):
            return True
        messagebox.showinfo("API 키", "Claude API 키를 넣어 주세요.\nconsole.anthropic.com → API Keys 에서 만들 수 있습니다.")
        return False

    def _pick_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or BASE)
        if d:
            var.set(os.path.normpath(d))

    def _open(self, p):
        if p and os.path.exists(p):
            open_path(p)
        else:
            messagebox.showinfo("열기", f"아직 없습니다:\n{p}")

    def log(self, msg):
        def w():
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
        self.root.after(0, w)

    def run(self, fn):
        if self.busy:
            messagebox.showinfo("진행 중", "다른 작업이 진행 중입니다. 끝나거나 [중지]한 뒤 해 주세요.")
            return
        self.busy, self.stop_flag = True, False

        def wrap():
            try:
                fn()
            except InterruptedError as e:
                self.log(str(e))
            except Exception as e:
                self.log(f"오류: {friendly(e)}")
                self.log(traceback.format_exc(limit=3))
            finally:
                self.busy = False
                self.root.after(0, self.root.deiconify)

        threading.Thread(target=wrap, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.log("중지 요청... (지금 처리 중인 쪽이 끝나면 멈춥니다)")

    def save(self, quiet=False):
        self.s.update({
            "api_key": self.v_key.get().strip(), "model": self.v_model.get(),
            "cap_dir": self.v_cap_dir.get(), "cap_key": self.v_cap_key.get(), "cap_delay": self.v_cap_delay.get(),
            "cap_max": self.v_cap_max.get(), "cap_region": list(self.region) if self.region else None,
            "cap_point": list(self.point) if self.point else None,
            "cap_click": self.v_cap_click.get(), "src": self.v_src.get(), "out": self.v_out.get(),
            "split": self.v_split.get(), "level": self.v_level.get(), "focus": self.v_focus.get(),
        })
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(self.s, f, ensure_ascii=False, indent=1)
        if not quiet:
            self.log("설정을 저장했습니다 (settings.json, 이 PC에만 있음).")

    def close(self):
        try:
            self.save(quiet=True)
        finally:
            self.root.destroy()


class StatusBox:
    """캡처하는 동안 화면 구석에 떠 있는 작은 진행 표시창 (캡처 영역과 겹치지 않는 쪽에)."""

    def __init__(self, root, region):
        self.root = root
        top = self.top = tk.Toplevel(root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.9)
        except Exception:
            pass
        frm = tk.Frame(top, bg="#1f2937", padx=14, pady=10)
        frm.pack()
        tk.Label(frm, text="책 캡처 중", bg="#1f2937", fg="#9ca3af", font=("Malgun Gothic", 9)).pack(anchor="w")
        self.var = tk.StringVar(value="준비 중...")
        tk.Label(frm, textvariable=self.var, bg="#1f2937", fg="white", font=("Malgun Gothic", 11, "bold"),
                 wraplength=360, justify="left").pack(anchor="w")
        tk.Button(frm, text="중지", command=self._stop, takefocus=0).pack(anchor="e", pady=(6, 0))
        top.update_idletasks()
        w, h = 400, top.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x0, y0, x1, y1 = region
        # 영역 오른쪽·왼쪽·아래 중 빈 곳, 없으면 화면 오른쪽 아래
        if sw - x1 >= w + 10:
            x, y = x1 + 10, max(0, y0)
        elif x0 >= w + 10:
            x, y = x0 - w - 10, max(0, y0)
        elif sh - y1 >= h + 10:
            x, y = max(0, x0), y1 + 10
        else:
            x, y = sw - w - 10, sh - h - 60
        top.geometry(f"{w}x{h}+{x}+{y}")
        _no_activate(top)

    def _stop(self):
        app = getattr(self.root, "_app", None)
        if app:
            app.stop()

    def set(self, text):
        self.root.after(0, lambda: self.var.set(text))

    def close(self):
        self.root.after(0, self.top.destroy)


def _no_activate(win):
    """표시창이 키보드 입력을 가로채지 않도록 (Windows)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
        st = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, st | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except Exception:
        pass


def friendly(e):
    name = type(e).__name__
    if name == "AuthenticationError":
        return "API 키가 틀렸습니다. 키를 다시 확인해 주세요."
    if name == "PermissionDeniedError":
        return "이 API 키로는 쓸 수 없는 모델이거나 권한이 없습니다."
    if name in ("APIConnectionError", "APITimeoutError"):
        return "Claude 서버에 연결하지 못했습니다. 회사/집 네트워크가 막고 있으면 휴대폰 핫스팟으로 해 보세요."
    if name == "RateLimitError":
        return "요청이 너무 많거나 잔액이 부족합니다. 잠시 뒤 다시 하거나 console.anthropic.com 에서 결제 상태를 확인하세요."
    if name == "BadRequestError" and "credit" in str(e).lower():
        return "API 잔액이 부족합니다. console.anthropic.com → Billing 에서 충전하세요."
    return f"{name}: {e}"


def main():
    CAP.make_dpi_aware()
    root = tk.Tk()
    root._app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
