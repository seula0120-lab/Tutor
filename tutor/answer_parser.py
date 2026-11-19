"""확정답안 줄 목록(answer_lines.py) → 이론 15문항. 검사에 하나라도 걸리면 그 회차는 변환하지 않는다.

흐름: 줄 목록 → 이론 영역만 자르기 → 문항 번호(1. 2. ...)로 블록 나누기 → 블록마다 문제·보기·[답]·해설 해석
      → 첫 장 정답표(A형)와 대조 → (문항 목록, 문제점 목록).
문제점(problems)이 비어 있어야만 적재할 수 있다. 이 파일은 파일을 읽거나 쓰지 않는다(값만 돌려준다).
"""
import re

from .tagging import tag_question

CIRCLED = "①②③④"
EXPECTED_QUESTIONS = 15
EXPECTED_CHOICES = 4
ALL_CORRECT = "1,2,3,4"

QUESTION_START = re.compile(r"^(\d{1,2})\.\s*(.*)")
MULTI_ANSWER = re.compile(r"^[①②③④](\s*,\s*[①②③④])*")
DIGIT_KEY = re.compile(r"^[1-4](\s*,\s*[1-4])*$")  # 옛 형식 정답표는 숫자로 적혀 있다


# ── 정답 글자 읽기 ──────────────────────────────────────

def read_answer_text(text):
    """'④ 해설…' → ('4', '해설…'), '①,④' → ('1,4', ''), '모두정답' → ('1,2,3,4', ''). 못 읽으면 (None, 원문)."""
    text = re.sub(r"^복수\s*정답\s*", "", text.strip())
    if re.match(r"^모두\s*정답", text):
        return ALL_CORRECT, re.sub(r"^모두\s*정답", "", text)
    found = MULTI_ANSWER.match(text)
    if not found:
        return None, text
    numbers = [str(CIRCLED.index(c) + 1) for c in found.group(0) if c in CIRCLED]
    return ",".join(numbers), text[found.end():]


def key_cell(text):
    """정답표 한 칸 → '4' / '1,4'. 정답 칸이 아니면 None."""
    answer, rest = read_answer_text(text)
    if answer and not rest.strip():
        return answer
    if DIGIT_KEY.match(text.strip()):
        return re.sub(r"\s", "", text)
    return None


def read_answer_key(lines, form="A"):
    """첫 장 정답표에서 한 형의 정답을 읽는다(복수정답 칸도 한 칸). 'A형' 표시가 없으면 빈 목록."""
    start = next((i for i, l in enumerate(lines) if re.sub(r"\s", "", l["text"]) == f"{form}형"), None)
    if start is None:
        return []
    cells = [key_cell(l["text"]) for l in lines[start + 1:]]
    return [c for c in cells if c][:EXPECTED_QUESTIONS]


# ── 영역·블록 나누기 ────────────────────────────────────

def theory_lines(lines):
    """이론 영역의 줄만 돌려준다. '실무시험' 표시 앞까지다.
    최근 형식은 세로로 한 글자씩('실','무'), 옛 형식은 한 줄('실 무 시 험', 사이에 제어문자)."""
    for i in range(len(lines)):
        compact = re.sub(r"[\s\x00-\x1f]", "", lines[i]["text"])
        next_is_mu = i + 1 < len(lines) and lines[i]["text"] == "실" and lines[i + 1]["text"] == "무"
        if next_is_mu or compact == "실무시험":
            return lines[:i]
    raise ValueError("실무 영역 시작('실무시험')을 찾지 못했습니다.")


def split_blocks(lines):
    """문항 번호가 1, 2, ... 순서로 나오고 앞 문항에 [답] 이 이미 나왔을 때만 새 문항으로 본다.
    (본문 속 '1. 2. 3.' 하위 항목을 새 문항으로 착각하지 않으려는 조건이다.)"""
    blocks, expected = [], 1
    for line in lines:
        found = QUESTION_START.match(line["text"])
        previous_done = not blocks or any(l["text"].startswith("[답]") for l in blocks[-1])
        if found and int(found.group(1)) == expected and previous_done:
            blocks.append([{**line, "text": found.group(2)}])
            expected += 1
        elif blocks:
            blocks[-1].append(line)
    return blocks


def split_inline_markers(line):
    """한 줄에 보기 기호가 여러 개('① 가  ② 나')면 기호마다 한 줄로 나눈다. 나눈 조각의 x 는 글자 위치 비율로 어림한다."""
    text = line["text"]
    starts = [m.start() for m in re.finditer(r"[①②③④]", text)]
    if not starts or (len(starts) == 1 and starts[0] == 0):
        return [line]
    width = max(line.get("x1", line["x"]) - line["x"], 1)
    head = text[:starts[0]].strip()
    pieces = [{**line, "text": head}] if head else []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(text)
        pieces.append({**line, "text": text[start:end].strip(), "x": round(line["x"] + width * start / len(text), 1)})
    return pieces


def marker_owner(markers, line):
    """글 한 줄이 속한 보기 기호: 그 줄보다 위·왼쪽에 있는 기호 중 가장 아래, 그다음 가장 오른쪽.
    한 줄에 보기가 두 개씩 놓인 2×2 배치(①② / ③④)도 이렇게 맞게 나뉜다."""
    candidates = [m for m in markers if m["page"] == line["page"] and m["y"] <= line["y"] + 2 and m["x"] <= line["x"] + 2]
    return max(candidates, key=lambda m: (round(m["y"]), m["x"])) if candidates else markers[-1]


def gather_choices(markers, body_lines):
    """보기 기호마다 글을 모은 뒤 ①~④ 순서로 돌려준다."""
    texts = {id(m): m["text"][1:].strip() for m in markers}
    for line in body_lines:
        owner = marker_owner(markers, line)
        texts[id(owner)] = (texts[id(owner)] + " " + line["text"]).strip()
    return [texts[id(m)] for m in sorted(markers, key=lambda m: CIRCLED.index(m["text"][0]))]


def parse_block(block):
    """문항 블록 하나 → {question, choices, answer, explanation, marker_count}. 해석이 안 되면 예외."""
    answer_at = next(i for i, l in enumerate(block) if l["text"].startswith("[답]"))
    head = [piece for line in block[:answer_at] for piece in split_inline_markers(line)]  # 해설 속 ①② 는 건드리지 않는다
    block = head + block[answer_at:]
    answer_at = len(head)
    marker_idx = [i for i, l in enumerate(head) if l["text"][:1] in CIRCLED]
    first = marker_idx[0]
    markers = [block[i] for i in marker_idx]
    body = [l for i, l in enumerate(block[first:answer_at], first) if i not in marker_idx]
    answer, rest = read_answer_text(block[answer_at]["text"][3:].strip())
    explanation = " ".join([rest.strip()] + [l["text"] for l in block[answer_at + 1:]]).strip()
    return {"question": " ".join(l["text"] for l in block[:first]), "choices": gather_choices(markers, body),
            "answer": answer, "explanation": explanation, "marker_count": len(markers)}


# ── 검사와 문항 만들기 ──────────────────────────────────

def check_item(number, parsed, key):
    """문항 하나의 문제점 목록(문장). 보기 4개·정답 형식·정답표 일치를 본다."""
    problems = []
    choices = parsed["choices"]
    if parsed["marker_count"] != EXPECTED_CHOICES or len(choices) != EXPECTED_CHOICES or not all(choices):
        problems.append(f"{number}번: 보기가 4개가 아닙니다(기호 {parsed['marker_count']}개, 빈 보기 있음 여부 확인).")
    if not parsed["answer"]:
        problems.append(f"{number}번: [답] 에서 정답을 읽지 못했습니다.")
    elif key and parsed["answer"] != key[number - 1]:
        problems.append(f"{number}번: 정답 불일치([답]={parsed['answer']}, 정답표={key[number - 1]}).")
    return problems


def build_item(round_no, number, parsed):
    """검사를 통과한 문항을 은행 JSON 형식(dict)으로 만든다. 과목·세목·단원 태그를 붙인다."""
    subject, tax, unit = tag_question(number, parsed["question"], parsed["choices"], parsed["explanation"])
    return {"id": f"{round_no}-A-{number}", "round": round_no, "form": "A", "part": 0, "number": number,
            "kind": "이론", "subject": subject, "tax": tax, "unit": unit, "points": 2,
            "question": parsed["question"], "choices": parsed["choices"], "answer": parsed["answer"],
            "explanation": parsed["explanation"]}


def parse_theory(round_no, lines):
    """줄 목록 → (문항 목록, 문제점 목록). 문제점이 있으면 문항 목록은 빈 목록이다(부분 적재 방지)."""
    try:
        blocks = split_blocks(theory_lines(lines))
    except ValueError as err:
        return [], [str(err)]
    key = read_answer_key(lines)
    problems = []
    if len(key) != EXPECTED_QUESTIONS:
        problems.append(f"첫 장 정답표에서 정답 {len(key)}개만 읽었습니다({EXPECTED_QUESTIONS}개여야 함).")
    if len(blocks) != EXPECTED_QUESTIONS:
        problems.append(f"이론 문항이 {len(blocks)}개입니다({EXPECTED_QUESTIONS}개여야 함).")
    parsed_items = []
    for number, block in enumerate(blocks, 1):
        try:
            parsed = parse_block(block)
        except (StopIteration, IndexError, ValueError, KeyError) as err:
            problems.append(f"{number}번: 해석 실패({type(err).__name__}).")
            continue
        problems.extend(check_item(number, parsed, key if len(key) == EXPECTED_QUESTIONS else None))
        parsed_items.append((number, parsed))
    if problems:
        return [], problems
    return [build_item(round_no, n, p) for n, p in parsed_items], []
