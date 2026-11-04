"""화면 자동 캡처: 지정한 영역을 찍고 → 다음 페이지 키를 누르고 → 반복 (Windows).

브라우저나 전자책 뷰어에 책을 띄워 두고 쓰면 됩니다. 마지막 페이지에서 화면이 더 바뀌지 않으면 자동으로 멈추고,
Esc 키를 누르면 언제든 멈춥니다.
"""
import ctypes
import os
import sys
import time

from PIL import ImageChops, ImageGrab, ImageStat

IS_WIN = sys.platform.startswith("win")

# 가상 키 코드
MANUAL = "직접 넘기기 (내가 넘기면 자동으로 찍음)"
KEYS = {
    "→ (오른쪽 화살표)": 0x27,
    "Page Down": 0x22,
    "스페이스": 0x20,
    "← (왼쪽 화살표, 오른쪽→왼쪽 책)": 0x25,
    "↓ (아래 화살표)": 0x28,
    MANUAL: None,
}
CLICK = "마우스 클릭 (뷰어의 '다음' 버튼 위치 지정)"
KEYS = {CLICK: "click", **KEYS}
VK_ESCAPE = 0x1B


def make_dpi_aware():
    """화면 배율(125%, 150%)이 있어도 좌표와 캡처 픽셀이 맞도록."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def press_key(vk):
    if not IS_WIN:
        raise RuntimeError("자동 페이지 넘김은 Windows 에서만 됩니다.")
    if isinstance(vk, tuple):                   # ("click", x, y): 다음 버튼 클릭
        click_at(vk[1], vk[2], restore=True)
        return
    u = ctypes.windll.user32
    ext = 0x0001 if vk in (0x21, 0x22, 0x25, 0x26, 0x27, 0x28) else 0  # 화살표·PageUp/Down 은 확장 키
    scan = u.MapVirtualKeyW(vk, 0)              # 웹 뷰어는 스캔 코드(event.code)로 키를 구분하는 경우가 많다
    u.keybd_event(vk, scan, ext, 0)
    time.sleep(0.05)
    u.keybd_event(vk, scan, ext | 0x0002, 0)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def click_at(x, y, restore=False):
    if not IS_WIN:
        return
    u = ctypes.windll.user32
    old = _POINT()
    u.GetCursorPos(ctypes.byref(old))
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.03)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    if restore:                                 # 마우스를 원래 자리로 (버튼 강조가 찍히지 않게)
        time.sleep(0.05)
        u.SetCursorPos(old.x, old.y)


def esc_pressed():
    if not IS_WIN:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


def grab(region):
    """region = (x0, y0, x1, y1) 화면 좌표."""
    return ImageGrab.grab(bbox=region, all_screens=True).convert("RGB")


def diff(a, b):
    """두 이미지가 얼마나 다른지 (0 = 같음, 255 = 완전히 다름)."""
    if a.size != b.size:
        return 255.0
    small = (max(1, a.width // 4), max(1, a.height // 4))
    d = ImageChops.difference(a.resize(small), b.resize(small))
    return sum(ImageStat.Stat(d).mean) / 3


def _wait_manual(region, prev, stop):
    """사용자가 페이지를 넘길 때까지 기다렸다가, 화면이 멈추면 새 화면을 돌려준다. 중지하면 None."""
    while True:
        if stop() or esc_pressed():
            return None
        time.sleep(0.3)
        cur = grab(region)
        if diff(cur, prev) > 0.5:
            new, _ = wait_stable(region, 10, prev)
            time.sleep(0.5)
            return grab(region)


def wait_stable(region, timeout, prev_shot):
    """페이지 넘김 뒤 화면이 바뀌고 멈출 때까지 기다린다. (새 화면, 바뀌었는지)"""
    t0 = time.time()
    last = grab(region)
    changed = diff(last, prev_shot) > 0.5
    while time.time() - t0 < timeout:
        time.sleep(0.4)
        cur = grab(region)
        if diff(cur, prev_shot) > 0.5:
            changed = True
        if changed and diff(cur, last) < 0.3:     # 바뀐 뒤 잠잠해짐 = 로딩 끝
            return cur, True
        last = cur
    return last, changed


def beep():
    if IS_WIN:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass


def run_capture(region, out_dir, key_vk, max_pages=500, delay=1.5, start_no=1, focus_click=None,
                log=print, stop=lambda: False, countdown=3):
    """영역을 반복 캡처해 out_dir/page_0001.png ... 로 저장. 저장한 장 수를 돌려준다.
    key_vk 가 None 이면 직접 넘기기: 사용자가 페이지를 넘겨 화면이 바뀌고 멈추면 찍는다."""
    os.makedirs(out_dir, exist_ok=True)
    manual = key_vk is None
    for s in range(countdown, 0, -1):
        log(f"{s}초 뒤 시작. 지금 책 화면을 한 번 클릭해 두세요. (멈추기: Esc)")
        time.sleep(1)
    if focus_click:
        click_at(*focus_click)          # 책 창에 키 입력이 가도록 한 번 클릭
        time.sleep(0.3)
    shot = grab(region)
    n = 0
    no = start_no
    while n < max_pages:
        if stop() or esc_pressed():
            log(f"중지했습니다. 모두 {n}장 저장.")
            break
        path = os.path.join(out_dir, f"page_{no:04d}.png")
        shot.save(path)
        n += 1
        no += 1
        beep()
        if manual:
            log(f"{n}장째 저장했습니다. 다음 페이지로 넘기세요. (끝내기: Esc)")
            new = _wait_manual(region, shot, stop)
            if new is None:
                log(f"중지했습니다. 모두 {n}장 저장.")
                break
            shot = new
            continue
        log(f"{n}장째 저장 → 다음 페이지로 넘기는 중... (멈추기: Esc)")
        press_key(key_vk)
        wait_stable(region, delay + 4, shot)    # 화면이 바뀌고 잠잠해질 때까지
        time.sleep(delay)                       # 그림 로딩 여유
        new = grab(region)
        if diff(new, shot) < 0.5:               # 안 넘어갔으면 한 번 더 눌러 본다
            press_key(key_vk)
            time.sleep(delay + 1.5)
            new = grab(region)
            if diff(new, shot) < 0.5:
                if n == 1:
                    log("페이지가 넘어가지 않았습니다. 책 화면을 클릭해 두었는지 확인하거나, "
                        "넘김 방식을 '마우스 클릭'이나 '직접 넘기기'로 바꿔 보세요.")
                else:
                    log(f"화면이 더 이상 바뀌지 않아 마지막 페이지로 보고 끝냈습니다. 모두 {n}장 저장.")
                break
        shot = new
    return n


class RegionPicker:
    """반투명 전체화면 창에서 마우스로 끌어 영역을 고른다. callback((x0,y0,x1,y1) 또는 None)."""

    def __init__(self, root, callback, point=False):
        import tkinter as tk
        self.cb = callback
        self.point = point
        top = self.top = tk.Toplevel(root)
        # 여러 모니터 전체를 덮는다
        vx, vy, vw, vh = _virtual_screen(root)
        top.geometry(f"{vw}x{vh}+{vx}+{vy}")
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.30)
        self.ox, self.oy = vx, vy
        c = self.c = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
        c.pack(fill="both", expand=True)
        c.create_text(root.winfo_screenwidth() // 2 - vx, 40, fill="white", font=("Malgun Gothic", 18, "bold"),
                      text=("뷰어의 '다음 페이지' 버튼(또는 누르면 넘어가는 곳)을 클릭하세요  (취소: Esc)" if point else
                            "책 페이지 영역을 마우스로 끌어서 고르세요  (취소: Esc)"))
        self.rect = None
        self.start = None
        c.bind("<ButtonPress-1>", self.down)
        c.bind("<B1-Motion>", self.move)
        c.bind("<ButtonRelease-1>", self.up)
        top.bind("<Escape>", lambda e: self.done(None))
        top.focus_force()

    def down(self, e):
        self.start = (e.x, e.y)
        self.rect = self.c.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)

    def move(self, e):
        if self.rect:
            self.c.coords(self.rect, self.start[0], self.start[1], e.x, e.y)

    def up(self, e):
        if not self.start:
            return
        if self.point:
            self.done((e.x + self.ox, e.y + self.oy))
            return
        x0, y0 = self.start
        x0, x1 = sorted((x0, e.x))
        y0, y1 = sorted((y0, e.y))
        if x1 - x0 < 50 or y1 - y0 < 50:
            self.done(None)
            return
        self.done((x0 + self.ox, y0 + self.oy, x1 + self.ox, y1 + self.oy))

    def done(self, region):
        self.top.destroy()
        self.cb(region)


def _virtual_screen(root):
    if IS_WIN:
        u = ctypes.windll.user32
        return u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
