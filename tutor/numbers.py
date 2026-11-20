"""세무 노트 문장 속 수치(세율·한도·금액·기간)를 찾아 {값, 단위, 적용 대상, 기준일, 예외 조건, 출처} 구조로 만든다.

- 찾기 규칙(`find`)은 노트를 고칠 때와 테스트가 같은 것을 쓴다. 날짜(’26.1.1.·2025.12.31.·2026년 1월)·법 조문(§28의5·제3항)·원 번호(①)는 수치가 아니라서 뺀다.
- 구조화한 결과는 각 세무 노트 JSON 의 `numbers` 칸에 저장한다(scripts/structure_numbers.py). 화면은 이 칸을 읽어 수치 옆에 작은 글씨로 대상·기준일을 보인다.
- 적용 대상은 수치 앞뒤 문장 조각 그대로(요약·추측 없음), 예외 조건은 같은 문장의 '다만/단/제외/불구하고/아닌 경우' 조각과 괄호 안 설명 그대로다.
"""
import re

DATE = re.compile(r"\d{2}\.\d{1,2}\.\d{1,2}\.|[’']\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.?|(?:19|20)\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.?|(?:19|20)\d{2}년(?:\s*\d{1,2}월)?(?:\s*\d{1,2}일)?|\d{1,2}월\s*\d{1,2}일|[’']\d{2}\.\d{1,2}\.")
STATUTE = re.compile(r"(?:제\s*)?\d+조(?:의\d+)?|§\s*\d+(?:의\d+)?(?:[①-⑳]+)?|[①-⑳]|\d+항|\d+호")
UNITS = ("조원", "억원", "천만원", "백만원", "만원", "천원", "원", "%p", "%", "퍼센트", "개월", "년", "월", "일", "회", "세", "명", "배", "개", "인", "곳", "분의", "종", "기")
MAGNITUDE = "조억천백만"
# 수치 하나: '1천 5백만원', '1천만원', '200억원', '3,000억원', '9%', '2개 과세기간', '80분의 100', '1주택자', '12로 나눈'
_PART = r"\d[\d,]*(?:\.\d+)?\s*[조억천백만]*"
_UNIT = r"(?:원|%p|%|퍼센트|개월|년|월|일|회|세|명|배|개|인|곳|종|기|주택|대|학년|분의\s*\d+)"
NUMBER = re.compile(r"(?<![\w§])(" + _PART + r"(?:\s+" + _PART + r")*\s*(?:" + _UNIT + r"|(?=로 나눈))?)")
SPLIT = re.compile(r"[。.!?](?=\s|$)|[;；]")
CLAUSE_BREAK = re.compile(r"(?<!\d),|,(?!\d)|[→/;:(·)]")     # 천 단위 쉼표(3,000)는 구분이 아니다
EXCEPT = re.compile(r"(다만[^.;]*|단,[^.;]*|[^,;.()]*(?:제외|불구하고|아닌 경우|한하여|에 한함)[^,;.()]*)")


def _mask(text):
    """날짜·조문 번호를 같은 길이의 공백으로 바꿔 수치 찾기에서 빼 준다."""
    for pattern in (DATE, STATUTE):
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


UNIT_END = re.compile(r"(분의\s*\d+|%p|%|퍼센트|원|개월|년|월|일|회|세|명|배|개|인|곳|종|기|주택|대|학년)$")


def unit_of(token):
    """수치 글자에서 단위. 크기 글자(억·만 …)만 있고 '원'이 없으면 금액이라 '원'. '12로 나눈' 은 '나눗수'. 단위를 못 찾으면 ''."""
    t = token.strip()
    match = UNIT_END.search(t)
    if match:
        return match.group(1).replace(" ", "")
    return "원" if re.search(r"[조억천백만]$", t) else ""


def value_of(token):
    """'1천 5백만원' → '1천 5백만'(원문 그대로, 끝의 단위 글자는 뺌)."""
    t = token.strip()
    match = UNIT_END.search(t)
    return (t[: match.start()] if match else t).strip()


def find(text):
    """문장에서 수치를 찾는다. [{token, value, unit, start, end}]. 숫자가 아닌 글자만 있는 낱말('1인당'의 1 등)도 숫자면 잡는다."""
    masked = _mask(text)
    out = []
    for m in NUMBER.finditer(masked):
        token = m.group(1).strip()
        if not token or not re.search(r"\d", token):
            continue
        unit = unit_of(token) or ("나눗수" if text[m.end(1):].startswith("로 나눈") else "")
        out.append({"token": token, "value": value_of(token), "unit": unit, "start": m.start(1), "end": m.end(1)})
    return out


def clause_of(text, start, end):
    """수치가 걸린 말: 앞 구분(쉼표·화살표·슬래시·세미콜론·괄호·가운뎃점) 뒤에서 수치 끝까지(예: '식사를 제공받지 않는 근로자의 식사대는 월 20만원'). 최대 40자(앞을 자름)."""
    left = max((m.end() for m in CLAUSE_BREAK.finditer(text, 0, start)), default=0)
    piece = " ".join(text[left:end].split())
    return ("…" + piece[-40:].lstrip()) if len(piece) > 40 else piece


def exception_of(text):
    """같은 문장에서 예외 조건 조각(다만·단·제외·불구하고 …) 그대로. 없으면 ''."""
    found = [m.group(0).strip(" ,") for m in EXCEPT.finditer(text)]
    return "; ".join(found)[:120]


PDF_SOURCE = "2025 핵심 개정세법"
REQUIRED = ("value", "unit", "applies_to", "as_of", "source")


def sentences(note):
    """노트에서 수치 구조화 대상 문장 [(위치, 글, 종류, 줄 dict 또는 개정 dict)]. 개정 항목은 what·how, 개념 줄은 text."""
    out = []
    for i, line in enumerate((note.get("concept") or {}).get("lines", [])):
        out.append((f"concept.lines[{i}]", line["text"], "concept", line))
    for i, change in enumerate(note.get("changes") or []):
        for key in ("what", "how"):
            out.append((f"changes[{i}].{key}", change[key], "change", change))
    return out


def _source_of(kind, holder, exam_label):
    if kind == "change":
        return f"{PDF_SOURCE} p{holder['page']}"
    pdf = holder.get("pdf")
    if pdf:
        return f"{PDF_SOURCE} p{pdf['page']}"
    return "기출 " + ", ".join(holder.get("sources", [])) if holder.get("sources") else ""


def structure(note, as_of_of_line):
    """노트 한 개의 수치를 구조화한다. as_of_of_line(줄 dict) → 개념 줄의 기준일 글(출처 회차의 시행일 등).

    항목: {where(위치), token(원문), value, unit, applies_to, as_of, exception, source} + 개정 항목은 page·change(무슨 개정인지)."""
    items = []
    for where, text, kind, holder in sentences(note):
        for found in find(text):
            item = {"where": where, "token": found["token"], "value": found["value"], "unit": found["unit"],
                    "applies_to": clause_of(text, found["start"], found["end"]),
                    "as_of": holder["when"] if kind == "change" else as_of_of_line(holder),
                    "exception": exception_of(text), "source": _source_of(kind, holder, None)}
            if kind == "change":
                item.update(page=holder["page"], change=holder["what"])
            elif holder.get("pdf"):
                item["page"] = holder["pdf"]["page"]
            items.append(item)
    return items


def problems(note):
    """note["numbers"] 가 문장 속 수치를 모두, 빠짐없는 칸으로 담고 있는지 점검해 문제 목록을 돌려준다(없으면 [])."""
    have = {}
    for item in note.get("numbers") or []:
        have.setdefault((item.get("where"), item.get("token")), []).append(item)
    found = []
    for where, text, kind, holder in sentences(note):
        for number in find(text):
            entries = have.get((where, number["token"]))
            if not entries:
                found.append(f"{where}: '{number['token']}' 가 numbers 에 없음")
                continue
            for item in entries:
                for key in REQUIRED:
                    if not str(item.get(key) or "").strip():
                        found.append(f"{where}: '{number['token']}' 의 {key} 가 비어 있음")
                if kind == "change" or holder.get("pdf"):
                    if not item.get("page"):
                        found.append(f"{where}: '{number['token']}' 개정 항목에 쪽 번호가 없음")
    return found
