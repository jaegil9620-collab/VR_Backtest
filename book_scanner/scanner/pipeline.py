"""이미지(또는 PDF) → 페이지별 인식 → 장별 Markdown + 그림 파일."""
import hashlib
import json
import os
import re

from PIL import Image

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
CACHE_VERSION = 1


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def list_sources(src):
    """폴더면 그 안의 이미지·PDF 를 이름순으로, 파일이면 그 파일 하나."""
    if os.path.isfile(src):
        files = [src]
    else:
        files = [os.path.join(src, f) for f in sorted(os.listdir(src), key=natural_key)
                 if f.lower().endswith(IMG_EXT + (".pdf",))]
    return files


def iter_images(files, pdf_dpi=200):
    """(이름, PIL 이미지, 원본 경로) 를 순서대로. PDF 는 쪽마다 하나."""
    for path in files:
        base = os.path.basename(path)
        if path.lower().endswith(".pdf"):
            import pymupdf
            doc = pymupdf.open(path)
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=pdf_dpi)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                yield f"{base} p{i + 1}", img, path
        else:
            with Image.open(path) as im:
                yield base, im.convert("RGB"), path


def split_parts(img, mode):
    """펼침면(가로가 긴 이미지)이면 왼쪽·오른쪽 쪽으로 나눈다. (이름 꼬리, 이미지, 원본 내 x 오프셋)"""
    w, h = img.size
    if mode == "split" or (mode == "auto" and w > h * 1.15):
        m = w // 2
        return [("L", img.crop((0, 0, m, h)), 0), ("R", img.crop((m, 0, w, h)), m)]
    return [("", img, 0)]


def _hash(img, model):
    hsh = hashlib.sha1(img.tobytes())
    hsh.update(f"{img.size}|{model}|{CACHE_VERSION}".encode())
    return hsh.hexdigest()[:20]


def recognize(src, out_dir, ocr_fn, model, split_mode="auto", log=print, stop=lambda: False):
    """모든 이미지를 인식해 pages.json 에 모은다. 이미 인식한 이미지는 cache 에서 읽어 비용이 들지 않는다.

    ocr_fn(img, name) -> dict (prompts.OCR_SCHEMA 형식)
    """
    cache_dir = os.path.join(out_dir, "_cache")
    os.makedirs(cache_dir, exist_ok=True)
    files = list_sources(src)
    if not files:
        raise RuntimeError(f"이미지나 PDF 가 없습니다: {src}")
    pages = []
    no = 0
    for name, img, path in iter_images(files):
        no += 1
        for tail, part, xoff in split_parts(img, split_mode):
            if stop():
                raise InterruptedError("중지했습니다.")
            key = _hash(part, model)
            cpath = os.path.join(cache_dir, key + ".json")
            label = f"#{no}{tail} {name}"
            if os.path.exists(cpath):
                with open(cpath, encoding="utf-8") as f:
                    res = json.load(f)
                log(f"{label}  (저장된 결과 사용)")
            else:
                log(f"{label}  인식 중...")
                res = ocr_fn(part, name)
                with open(cpath, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=1)
            pages.append({"no": no, "part": tail, "name": name, "path": path, "xoff": xoff,
                          "w": part.width, "h": part.height, "full_w": img.width, "full_h": img.height,
                          "pdf_page": _pdf_page(name), **res})
    with open(os.path.join(out_dir, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=1)
    return pages


def _pdf_page(name):
    m = re.search(r" p(\d+)$", name)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- 그림 잘라내기

def _load_full(page, cache={}):
    key = (page["path"], page.get("pdf_page"))
    if key not in cache:
        cache.clear()
        if page.get("pdf_page"):
            import pymupdf
            doc = pymupdf.open(page["path"])
            pix = doc[page["pdf_page"] - 1].get_pixmap(dpi=200)
            cache[key] = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        else:
            with Image.open(page["path"]) as im:
                cache[key] = im.convert("RGB")
    return cache[key]


def crop_figure(page, bbox, pad=0.015):
    """0~1000 좌표 bbox 를 인식한 이미지 기준으로 잘라 PIL 이미지로 돌려준다 (약간 여유를 둔다)."""
    x0, y0, x1, y1 = [max(0.0, min(1000.0, float(v))) / 1000 for v in (bbox + [0, 0, 1000, 1000])[:4]]
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(1, x1 + pad), min(1, y1 + pad)
    w, h, off = page["w"], page["h"], page["xoff"]
    box = (int(off + x0 * w), int(y0 * h), int(off + x1 * w), int(y1 * h))
    if box[2] - box[0] < 20 or box[3] - box[1] < 20:
        return None
    return _load_full(page).crop(box)


# ---------------------------------------------------------------- Markdown 조립

def slug(s, n=40):
    s = re.sub(r"[#*\[\]()`<>:\"/\\|?!.,'’“”]", "", s).strip()
    s = re.sub(r"\s+", "_", s)
    return s[:n].strip("_") or "untitled"


def build_markdown(pages, out_dir, split_level=2, log=print):
    """페이지 결과를 이어 붙이고, 그림을 잘라 저장하고, 제목 단계(split_level) 기준으로 장 파일을 나눈다.
    돌려주는 값: [(파일명, 제목, 스캔 번호 범위)]"""
    img_dir = os.path.join(out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    text = ""
    notes = []
    for p in pages:
        md = p.get("markdown", "") or ""
        figs = {f["n"]: f for f in p.get("figures", [])}

        def fig_md(n, p=p, figs=figs):
            f = figs.get(n)
            if not f:
                return ""
            fname = f"fig_{p['no']:03d}{p['part']}_{n}_{slug(f['title'], 30)}.png"
            crop = crop_figure(p, f["bbox"])
            if crop is None:
                return f"\n> **[그림] {f['title']}** (잘라내기 실패)\n> {f['description']}\n"
            crop.save(os.path.join(img_dir, fname))
            return (f"\n![{f['title']}](images/{fname})\n\n"
                    f"> **[그림] {f['title']}**  \n> {f['description']}\n")

        md = re.sub(r"\[\[FIG:(\d+)\]\]", lambda m: fig_md(int(m.group(1))), md)
        # 본문에 표시가 빠진 그림도 끝에 붙인다
        used = set(int(x) for x in re.findall(r"\[\[FIG:(\d+)\]\]", p.get("markdown", "") or ""))
        for n, f in figs.items():
            if n not in used:
                md += fig_md(n)
        marker = f"<!-- 이미지 #{p['no']}{p['part']} ({p['name']}) -->"
        if p.get("notes"):
            notes.append(f"- #{p['no']}{p['part']} {p['name']}: {p['notes']}")
        j = p.get("join_with_previous", "none")
        md = md.strip()
        if text and j in ("space", "nospace") and md and not md.startswith(("#", "|", "!", ">")):
            first, _, rest = md.partition("\n")
            sep = " " if j == "space" else ""
            text = text.rstrip() + sep + first + f" {marker}\n" + rest + "\n\n"
        else:
            text += f"{marker}\n\n{md}\n\n"

    chapters = _split(text, split_level)
    written = []
    for i, (title, body) in enumerate(chapters):
        fname = f"{i:02d}_{slug(title)}.md"
        nos = re.findall(r"<!-- 이미지 #(\d+)", body)
        rng = f"#{nos[0]}–{nos[-1]}" if nos else ""
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(re.sub(r"\n{3,}", "\n\n", body).strip() + "\n")
        written.append((fname, title, rng))
        log(f"저장: {fname}")
    with open(os.path.join(out_dir, "_all.md"), "w", encoding="utf-8") as f:
        f.write(re.sub(r"\n{3,}", "\n\n", text))
    _write_index(out_dir, pages, written, notes)
    return written


def _split(text, level):
    """'#'*level 이하 제목이 나올 때마다 새 파일. 앞 조각에 본문이 아직 없으면(예: 부 제목 바로 뒤 장 제목) 함께 묶는다."""
    pat = re.compile(r"^(#{1,%d}) (.+)" % level)
    chunks = []
    cur, heads = [], []

    def has_body():
        return any(l.strip() and not l.startswith("<!--") and not pat.match(l) for l in cur)

    def flush():
        if cur and "\n".join(cur).strip():
            exact = [t for d, t in heads if d == level]
            title = exact[0] if exact else (heads[0][1] if heads else "앞부분")
            chunks.append((title, "\n".join(cur)))

    for ln in text.split("\n"):
        m = pat.match(ln)
        if m and has_body():
            flush()
            cur, heads = [], []
        if m:
            heads.append((len(m.group(1)), m.group(2).strip()))
        cur.append(ln)
    flush()
    return chunks


def _write_index(out_dir, pages, written, notes):
    lines = ["# 스캔 → Markdown 변환본", "",
             f"- 원본 이미지 {len({p['no'] for p in pages})}장, 인식 단위 {len(pages)}개.",
             "- 각 md 안의 `<!-- 이미지 #N -->` 주석이 원본 위치입니다. 번호↔파일명은 `_source_index.txt`.",
             "- 그림은 `images/` 에 잘라 저장했고, 위치가 어긋나면 원본에서 직접 다시 잘라 같은 이름으로 덮어쓰면 됩니다.",
             "- 전체 본문을 한 파일로 보려면 `_all.md`.", "", "## 목차", "", "| 파일 | 제목 | 스캔 |", "|---|---|---|"]
    lines += [f"| [{f}]({f}) | {t} | {r} |" for f, t, r in written]
    if notes:
        lines += ["", "## 인식 중 특이사항", ""] + notes
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    seen = []
    for p in pages:
        if (p["no"], p["name"]) not in seen:
            seen.append((p["no"], p["name"]))
    with open(os.path.join(out_dir, "_source_index.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(f"{n:3d} {name}" for n, name in seen) + "\n")


def book_text(out_dir):
    """요약용: README 에 있는 장 파일들을 순서대로 이어 붙인다 (그림 파일 링크는 빼고 설명은 남긴다)."""
    files = sorted(f for f in os.listdir(out_dir) if re.match(r"\d\d_.*\.md$", f))
    parts = []
    for f in files:
        with open(os.path.join(out_dir, f), encoding="utf-8") as fh:
            body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", fh.read())
        parts.append(f"\n\n===== 파일: {f} =====\n\n{body}")
    return "".join(parts), files
