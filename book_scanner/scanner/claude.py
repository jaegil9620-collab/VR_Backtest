"""Claude API 호출과 비용 계산."""
import base64
import io
import json

# 모델별 가격 ($ / 100만 토큰: 입력, 출력)
MODELS = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
MODEL_LABELS = {
    "Opus 5.5 (가장 정확)": "claude-opus-5-5",
    "Sonnet 5.5 (절반 가격)": "claude-sonnet-5-5",
    "Haiku 5.5 (가장 저렴, 표·그림 약함)": "claude-haiku-5-5",
}
# 거절됐을 때 서버가 다른 모델로 다시 시도해 주는 기능 (Haiku 는 지원 안 함)
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


class Usage:
    def __init__(self):
        self.input = 0
        self.output = 0
        self.cost = 0.0

    def add(self, model, usage):
        if usage is None:
            return
        i = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        o = getattr(usage, "output_tokens", 0) or 0
        pin, pout = MODELS.get(model, (4.0, 20.0))
        self.input += i + cr
        self.output += o
        self.cost += (i * pin + cr * pin * 0.1 + o * pout) / 1_000_000

    def text(self):
        return f"토큰 입력 {self.input:,} / 출력 {self.output:,} · 약 ${self.cost:.2f}"


def make_client(api_key):
    import anthropic
    kw = {"max_retries": 4, "timeout": 600}
    if api_key:
        kw["api_key"] = api_key
    return anthropic.Anthropic(**kw)


def image_block(img, max_side=2400):
    """PIL 이미지를 API 이미지 블록으로. 너무 크면 줄이고 PNG 로 보낸다."""
    from PIL import Image
    im = img.convert("RGB")
    if max(im.size) > max_side:
        r = max_side / max(im.size)
        im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    if buf.tell() > 4_500_000:                 # API 이미지 한도(5MB) 아래로
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        mt = "image/jpeg"
    else:
        mt = "image/png"
    return {"type": "image", "source": {"type": "base64", "media_type": mt,
                                        "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def _call(client, model, effort, max_tokens, system, content, schema=None):
    """스트리밍으로 호출하고 최종 메시지를 돌려준다. 가능하면 서버 측 대체 모델 기능을 켠다."""
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params = dict(model=model, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": content}], output_config=output_config)
    if model in FALLBACK_MODELS:
        try:
            with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"],
                                             fallbacks="default", **params) as s:
                return s.get_final_message()
        except TypeError:
            pass                                # 설치된 SDK 가 이 기능을 모르면 일반 호출로
        except Exception as e:                  # 계정·지역에서 이 기능을 못 쓰면 일반 호출로
            if type(e).__name__ != "BadRequestError" or "fallback" not in str(e).lower():
                raise
    with client.messages.stream(**params) as s:
        return s.get_final_message()


def _text(msg):
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude 가 이 요청을 거절했습니다.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("응답이 너무 길어 잘렸습니다 (max_tokens).")
    return "".join(b.text for b in msg.content if b.type == "text")


def ocr_image(client, model, effort, img, name, usage):
    from .prompts import OCR_SCHEMA, OCR_SYSTEM, OCR_USER
    content = [image_block(img), {"type": "text", "text": OCR_USER.format(name=name)}]
    msg = _call(client, model, effort, 32000, OCR_SYSTEM, content, OCR_SCHEMA)
    usage.add(getattr(msg, "model", model) or model, msg.usage)
    return json.loads(_text(msg))


def summarize(client, model, effort, book_text, focus, usage):
    from .prompts import SUMMARY_SYSTEM, SUMMARY_USER
    f = f"\n요약할 때 특히 다음 관점에 집중해 주세요: {focus}" if focus.strip() else ""
    content = [{"type": "text", "text": SUMMARY_USER.format(focus=f, book=book_text)}]
    msg = _call(client, model, effort, 64000, SUMMARY_SYSTEM, content)
    usage.add(model, msg.usage)
    return _text(msg)
