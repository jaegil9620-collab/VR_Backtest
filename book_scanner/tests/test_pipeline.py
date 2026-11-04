"""API 없이 조립·그림 자르기·장 나누기를 확인한다 (가짜 인식 결과 사용)."""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scanner import pipeline as PL  # noqa: E402


def fake_ocr_factory():
    calls = []

    def ocr(img, name):
        calls.append(name)
        i = len(calls)
        if i == 1:   # 왼쪽 쪽: 부 제목 + 장 제목 + 그림
            return {"page_labels": ["1"], "join_with_previous": "none", "notes": "",
                    "markdown": "# PART 1 시작\n\n## 01. 첫 장\n\n본문 첫 문단입니다.\n\n[[FIG:1]]\n\n문장이 다음 쪽으로 이어",
                    "figures": [{"n": 1, "bbox": [100, 100, 600, 500], "title": "빨간 상자", "description": "테스트 그림"}]}
        if i == 2:
            return {"page_labels": ["2"], "join_with_previous": "nospace", "notes": "",
                    "markdown": "집니다.\n\n**[표] 예시**\n\n| a | b |\n|---|---|\n| 1 | 2 |",
                    "figures": []}
        return {"page_labels": [str(i)], "join_with_previous": "none", "notes": "오른쪽 아래 가려짐",
                "markdown": "## 02. 둘째 장\n\n### 소제목\n\n둘째 장 본문.", "figures": []}
    return ocr, calls


def make_spread(path, w=1600, h=1000):
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    # 왼쪽 쪽의 (100,100)-(600,500)/1000 위치 = 픽셀 (80,100)-(480,500)
    d.rectangle([80, 100, 480, 500], fill="red")
    im.save(path)


def test_end_to_end(tmp_path):
    src = tmp_path / "scans"
    src.mkdir()
    make_spread(src / "page_0001.png")
    one = Image.new("RGB", (800, 1000), "white")                          # 한 쪽짜리
    ImageDraw.Draw(one).text((100, 100), "page two", fill="black")
    one.save(src / "page_0002.png")
    out = tmp_path / "md"
    ocr, calls = fake_ocr_factory()
    pages = PL.recognize(str(src), str(out), ocr, "m", "auto", log=lambda *_: None)
    assert len(calls) == 3                     # 펼침면 2 + 한 쪽 1
    assert [p["part"] for p in pages] == ["L", "R", ""]

    written = PL.build_markdown(pages, str(out), 2, log=lambda *_: None)
    names = [w[0] for w in written]
    assert len(names) == 2, names
    assert written[0][1] == "01. 첫 장" and written[1][1] == "02. 둘째 장"
    first = (out / names[0]).read_text(encoding="utf-8")
    assert "# PART 1 시작" in first            # 부 제목은 첫 장 파일에 함께
    assert "이어집니다." in first               # 쪽 사이 끊긴 단어가 붙음
    assert "| 1 | 2 |" in first
    figs = os.listdir(out / "images")
    assert len(figs) == 1
    crop = Image.open(out / "images" / figs[0])
    # 여유분을 빼면 거의 빨간색이어야 한다
    c = crop.crop((15, 15, crop.width - 15, crop.height - 15)).convert("RGB")
    r, g, b = [sum(ch) / len(ch) for ch in zip(*c.getdata())]
    assert r > 240 and g < 30, (r, g, b)
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "가려짐" in readme and names[1] in readme

    # 다시 돌리면 저장된 결과를 써서 API 를 부르지 않는다
    ocr2, calls2 = fake_ocr_factory()
    PL.recognize(str(src), str(out), ocr2, "m", "auto", log=lambda *_: None)
    assert calls2 == []

    text, files = PL.book_text(str(out))
    assert files == names and "images/" not in text


def test_pdf_source(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=400, height=600).insert_text((50, 100), "hello")
    pdf = tmp_path / "book.pdf"
    doc.save(pdf)
    imgs = list(PL.iter_images(PL.list_sources(str(pdf))))
    assert [n for n, _, _ in imgs] == ["book.pdf p1", "book.pdf p2"]
