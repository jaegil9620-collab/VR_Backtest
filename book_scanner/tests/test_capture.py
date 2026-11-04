"""캡처 반복 로직 (화면 대신 가짜 이미지 사용)."""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scanner import capture as CAP  # noqa: E402


class FakeScreen:
    def __init__(self, pages):
        self.pages = [Image.new("RGB", (200, 300), c) for c in pages]
        self.i = 0

    def grab(self, region):
        return self.pages[self.i]

    def next(self, vk=None):
        self.i = min(self.i + 1, len(self.pages) - 1)


def _patch(monkeypatch, scr):
    monkeypatch.setattr(CAP, "grab", scr.grab)
    monkeypatch.setattr(CAP, "press_key", scr.next)
    monkeypatch.setattr(CAP.time, "sleep", lambda s: None)
    monkeypatch.setattr(CAP, "esc_pressed", lambda: False)


def test_auto_stops_at_last_page(tmp_path, monkeypatch):
    scr = FakeScreen(["red", "green", "blue"])
    _patch(monkeypatch, scr)
    msgs = []
    n = CAP.run_capture((0, 0, 200, 300), str(tmp_path), 0x27, delay=0, log=msgs.append, countdown=1)
    assert n == 3
    assert sorted(os.listdir(tmp_path)) == ["page_0001.png", "page_0002.png", "page_0003.png"]
    assert "마지막 페이지" in msgs[-1]


def test_auto_page_not_turning(tmp_path, monkeypatch):
    scr = FakeScreen(["red", "green"])
    _patch(monkeypatch, scr)
    monkeypatch.setattr(CAP, "press_key", lambda vk: None)   # 키가 안 먹는 뷰어
    msgs = []
    n = CAP.run_capture((0, 0, 200, 300), str(tmp_path), 0x27, delay=0, log=msgs.append, countdown=0)
    assert n == 1 and "넘어가지 않았습니다" in msgs[-1]


def test_manual_mode(tmp_path, monkeypatch):
    scr = FakeScreen(["red", "green", "blue"])
    _patch(monkeypatch, scr)
    polls = {"k": 0}
    real = scr.grab

    def grab(region):          # 사용자가 몇 번 조회 뒤 페이지를 넘긴 것처럼
        polls["k"] += 1
        if polls["k"] % 4 == 0:
            scr.next()
        return real(region)

    monkeypatch.setattr(CAP, "grab", grab)
    stop = {"n": 0}

    def stopper():
        stop["n"] += 1
        return len(os.listdir(tmp_path)) >= 3

    n = CAP.run_capture((0, 0, 200, 300), str(tmp_path), None, log=lambda m: None, stop=stopper, countdown=0)
    assert n == 3
