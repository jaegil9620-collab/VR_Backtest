"""Claude 에게 보내는 지시문과 응답 형식(JSON 스키마)."""

OCR_SYSTEM = """당신은 스캔한 책 이미지를 Markdown 으로 옮기는 전문 전사자입니다.
규칙:
- 본문은 요약하거나 고치지 말고 원문 그대로 옮깁니다. 맞춤법도 원문을 따릅니다.
- 머리말/꼬리말(쪽 번호, 반복되는 책 제목, 장 제목 띠)은 본문에서 빼고 page_labels 에만 적습니다.
- 제목 단계: 큰 부(PART, 1부 등) 표지 제목은 '# ', 장(챕터) 제목은 '## ', 장 안의 소제목은 '### ' 를 씁니다.
  '쉬어가기', '칼럼' 같은 상자 글의 제목도 '### ' 로 씁니다.
- 표는 Markdown 표로 옮기고, 표 바로 위에 **[표] 표 제목** 을 굵게 적습니다. 숫자는 정확히 옮깁니다.
- 차트·도식·사진 같은 그림은 본문에서 그 자리에 [[FIG:n]] (n=1,2,...) 표시만 넣고,
  figures 배열에 위치(bbox)와 제목, 그림이 보여주는 내용(축, 추세, 핵심 숫자)을 자세히 적습니다.
  bbox 는 이 이미지 전체를 가로 0~1000, 세로 0~1000 으로 본 좌표 [x0, y0, x1, y1] 이며 그림 제목과 범례까지 포함합니다.
  표를 이미지로 옮기지 말고, 글자로 옮길 수 있는 표는 Markdown 표로 옮깁니다.
- 수식은 읽기 쉬운 텍스트로 적습니다 (예: V_new = V + Pool/G).
- 글자가 가려지거나 잘려서 읽을 수 없으면 [가려짐: 추정 내용] 또는 [판독불가] 로 표시합니다.
- 이미지가 책이 아니거나 빈 페이지면 markdown 을 빈 문자열로 둡니다.
- join_with_previous: 이 이미지 첫 문장이 앞 페이지에서 이어지는 문장이면 'space'(단어 사이에서 끊김)
  또는 'nospace'(단어 중간에서 끊김, 예: 'VR' 다음 '을'), 새 문단으로 시작하면 'none'.
"""

OCR_USER = "이 이미지({name})를 규칙대로 Markdown 으로 옮겨 주세요."

OCR_SCHEMA = {
    "type": "object",
    "properties": {
        "page_labels": {"type": "array", "items": {"type": "string"},
                        "description": "이미지에 보이는 쪽 번호들(없으면 빈 배열)"},
        "join_with_previous": {"type": "string", "enum": ["none", "space", "nospace"]},
        "markdown": {"type": "string"},
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "bbox": {"type": "array", "items": {"type": "number"}},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["n", "bbox", "title", "description"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "가려짐, 흐림 등 특이사항(없으면 빈 문자열)"},
    },
    "required": ["page_labels", "join_with_previous", "markdown", "figures", "notes"],
    "additionalProperties": False,
}

SUMMARY_SYSTEM = """당신은 투자 전략 책을 분석해 백테스트와 자동매매 설계의 기초 자료를 만드는 분석가입니다.
책 본문(Markdown, 장별)을 읽고 한국어 Markdown 으로 다음을 작성합니다.

# 《책 제목》 요약
1. **책 개요**: 저자의 핵심 주장과 전략을 5~10줄로.
2. **장별 요약 표**: | 파일 | 내용(한 줄) | 핵심 숫자·규칙 | (파일 링크는 주어진 파일명으로 [파일명](파일명) 형식)
3. **자동매매 설계용 핵심 규칙**: 책 원문에 근거한 규칙만. 종목, 단위, 상태 변수, 초기화, 주기,
   매수·매도 조건, 주문 방식, 금액 한도, 예외 상황, 파라미터 기본값과 허용 범위를 코드로 옮기기 쉽게 정리.
   수식은 코드 블록이나 인라인 코드로. 규칙마다 근거 파일을 (→ 파일명) 으로 표시.
4. **백테스트 검증용 숫자**: 책에 나온 백테스트 결과(기간, CAGR, MDD 등)를 표로. 내 코드 결과와 비교할 때 씁니다.
5. **책이 밝힌 한계와 주의점**.
6. **불확실하거나 빠진 부분**: 스캔 누락, 판독불가, 책 안에서 서로 다른 설명.
책에 없는 내용을 지어내지 말고, 해석이 들어간 부분은 (해석) 이라고 표시합니다."""

SUMMARY_USER = """다음은 책 본문입니다.{focus}

{book}"""
