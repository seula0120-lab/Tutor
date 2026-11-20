"""문제 글 안의 표를 원본(확정답안 PDF·HWP)에서 뽑아 data/tables.json 으로 쓴다(행·열 머리글과 병합 칸을 유지).

- PDF: PyMuPDF 의 find_tables. 칸마다 글자(chars)를 좌표로 다시 모아 쉼표·점이 떨어져 찍힌 숫자('3000000000원 , , ,')를 바로잡는다.
- HWP: 기존 hwp5html 변환 결과의 <table>(rowspan·colspan 그대로).
- 어느 문항의 표인지: 문항 번호 줄('4. …') 뒤, 그 문항의 '[답]' 줄 앞에 있는 표를 그 문항 것으로 본다(답 뒤의 표는 해설 표라 제외).
- 확인: 표 칸의 글이 DB 문항(문제 글+보기)에 80% 이상 들어 있을 때만 받는다. 아니면 unmatched 목록에 이유와 함께 남긴다(지어내지 않음).
출력 data/tables.json = {"tables": [{id, round, number, source, page, n_rows, n_cols, header_rows, row_header, cells: [{r, c, rs, cs, text}]}],
                         "unmatched": [{round, number?, page, reason, preview}]}
사용법: .venv/bin/python scripts/extract_tables.py
"""
import json
import re
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tutor.answer_lines import _hwp_to_html, find_answer_file  # noqa: E402
from tutor.bank import read_bank_files  # noqa: E402

RAW_DIRS = [ROOT / "data" / "raw", Path("/Users/seul/Desktop/PJT2_결과물 회계튜터/data/raw")]
OUT = ROOT / "data" / "tables.json"
START = re.compile(r"^\s*(\d{1,2})\s*\.\s")
MATCH_RATIO = 0.8


def norm(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"[\s,ㆍ•·:：]", "", text)


# ------------------------------------------------------------------ PDF
def cell_text(page, rect, chars):
    """칸 안의 글자를 줄로 모아 읽는다. 쉼표·점은 숫자 줄에서 조금 떨어져 찍혀 있어 가장 가까운 줄에 붙인다."""
    inside = [c for c in chars if rect.x0 - 1 <= (c[1] + c[3]) / 2 <= rect.x1 + 1 and rect.y0 - 1 <= (c[2] + c[4]) / 2 <= rect.y1 + 1]
    body = sorted((c for c in inside if c[0] not in ",.· \u00a0"), key=lambda c: (c[2] + c[4]) / 2)
    lines = []
    for c in body:
        cy, size = (c[2] + c[4]) / 2, c[4] - c[2]
        if lines and abs(cy - lines[-1]["cy"]) <= size * 0.6:
            lines[-1]["chars"].append(c)
        else:
            lines.append({"cy": cy, "chars": [c]})
    for c in (c for c in inside if c[0] in ",.·"):
        if lines:
            min(lines, key=lambda ln: abs((c[2] + c[4]) / 2 - ln["cy"]))["chars"].append(c)
    out = []
    for ln in lines:
        text, prev = "", None
        for c in sorted(ln["chars"], key=lambda c: c[1]):
            if prev is not None and c[1] - prev[3] > (prev[4] - prev[2]) * 0.35 and c[0] not in ",.":
                text += " "
            text += c[0]
            prev = c
        out.append(text.strip())
    return " ".join(t for t in out if t)


def page_chars(page):
    chars = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for ch in span["chars"]:
                    b = ch["bbox"]
                    chars.append((ch["c"], b[0], b[1], b[2], b[3]))
    return chars


def pdf_table_cells(page, table, chars):
    """find_tables 의 표 하나 → (n_rows, n_cols, [{r, c, rs, cs, text}]). 병합은 칸 좌표로 구한다."""
    cells = [pymupdf.Rect(c) for c in table.cells]
    xs = sorted({round(v, 0) for r in cells for v in (r.x0, r.x1)})
    ys = sorted({round(v, 0) for r in cells for v in (r.y0, r.y1)})
    def merge(values):
        out = []
        for v in values:
            if not out or v - out[-1] > 3:
                out.append(v)
        return out
    xs, ys = merge(xs), merge(ys)
    idx = lambda edges, v: min(range(len(edges)), key=lambda i: abs(edges[i] - v))
    out = []
    for r in cells:
        c0, c1, r0, r1 = idx(xs, r.x0), idx(xs, r.x1), idx(ys, r.y0), idx(ys, r.y1)
        out.append({"r": r0, "c": c0, "rs": max(1, r1 - r0), "cs": max(1, c1 - c0), "text": cell_text(page, r, chars)})
    return len(ys) - 1, len(xs) - 1, sorted(out, key=lambda x: (x["r"], x["c"]))


def pdf_events(path):
    """(쪽, y, 종류, 값) 목록: 문항 시작 'start', 답 줄 'answer', 표 'table'."""
    events = []
    with pymupdf.open(path) as doc:
        for number, page in enumerate(doc, 1):
            chars = page_chars(page)
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    x0, y0 = line["bbox"][0], line["bbox"][1]
                    if x0 < 110 and START.match(text):
                        events.append((number, y0, "start", int(START.match(text).group(1))))
                    elif text.startswith("[답]"):
                        events.append((number, y0, "answer", None))
            for table in page.find_tables().tables:
                n_rows, n_cols, cells = pdf_table_cells(page, table, chars)
                events.append((number, table.bbox[1], "table", {"n_rows": n_rows, "n_cols": n_cols, "cells": cells, "page": number}))
    return sorted(events, key=lambda e: (e[0], e[1]))


# ------------------------------------------------------------------ HWP
class _HwpTables(HTMLParser):
    """HTML 을 훑어 문단 글·표(가장 안쪽 표만)를 순서대로 모은다."""

    def __init__(self):
        super().__init__()
        self.events, self.stack, self.parts, self.p_depth = [], [], [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            if self.stack:
                self.stack[-1]["nested"] = True
            self.stack.append({"rows": [], "nested": False})
        elif tag == "tr" and self.stack:
            self.stack[-1]["rows"].append([])
        elif tag in ("td", "th") and self.stack and self.stack[-1]["rows"]:
            self.stack[-1]["rows"][-1].append({"rs": int(a.get("rowspan") or 1), "cs": int(a.get("colspan") or 1), "text": ""})
            self.parts = []
        elif tag in ("p", "br") and not self.stack:
            self._flush_p()

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.stack and self.stack[-1]["rows"] and self.stack[-1]["rows"][-1]:
            self.stack[-1]["rows"][-1][-1]["text"] = " ".join("".join(self.parts).split())
            self.parts = []
        elif tag == "table" and self.stack:
            table = self.stack.pop()
            if not table["nested"]:
                self.events.append(("table", table["rows"]))
        elif tag == "p" and not self.stack:
            self._flush_p()

    def handle_data(self, data):
        self.parts.append(data)

    def _flush_p(self):
        text = " ".join("".join(self.parts).split())
        if text:
            self.events.append(("p", text))
        self.parts = []


def hwp_events(path):
    import html as htmllib
    with tempfile.TemporaryDirectory() as tmp:
        page = _hwp_to_html(path, Path(tmp) / "out")
    page = re.sub(r"<style.*?</style>", " ", page[page.find("<body"):], flags=re.S)
    parser = _HwpTables()
    parser.feed(htmllib.unescape(page) if False else page)
    events = []
    for n, (kind, value) in enumerate(parser.events):
        text = htmllib.unescape(value) if kind == "p" else None
        if kind == "p":
            if START.match(text):
                events.append((0, n, "start", int(START.match(text).group(1))))
            elif text.startswith("[답]"):
                events.append((0, n, "answer", None))
        else:
            grid, cells, filled = len(value), [], set()
            for r, row in enumerate(value):
                c = 0
                for cell in row:
                    while (r, c) in filled:
                        c += 1
                    for dr in range(cell["rs"]):
                        for dc in range(cell["cs"]):
                            filled.add((r + dr, c + dc))
                    cells.append({"r": r, "c": c, "rs": cell["rs"], "cs": cell["cs"], "text": htmllib.unescape(cell["text"])})
                    c += cell["cs"]
            n_cols = max((x["c"] + x["cs"] for x in cells), default=0)
            events.append((0, n, "table", {"n_rows": grid, "n_cols": n_cols, "cells": cells, "page": None}))
    return events


# ------------------------------------------------------------------ 공통
LABEL_NUMBER = re.compile(r"\d{4}\s*년|\d+\s*(?:월|기|차|형|번|분기|년|부문)|[<(]\d+[>)]")   # 연도·기수 같은 이름표 숫자는 자료가 아니다


def header_rows_of(cells, n_rows):
    """머리글 줄 수. 맨 윗줄에 숫자·'ㆍ' 글머리가 없는 이름표만 있으면 머리글이다(없으면 0).
    윗줄에 행·열을 걸친 칸이 있으면(여러 줄 머리글) 걸친 줄 수만큼 머리글로 늘린다."""
    top = [x for x in cells if x["r"] == 0]
    if n_rows < 2 or not top or any(re.search(r"\d|ㆍ", LABEL_NUMBER.sub("", x["text"])) for x in top):
        return 0
    span = max([x["rs"] for x in top] + [2 if any(x["cs"] > 1 for x in top) else 1])
    return min(span, n_rows - 1)


def build_entry(round_no, number, source, table):
    cells = table["cells"]
    header_rows = header_rows_of(cells, table["n_rows"])
    body_first = [x for x in cells if x["c"] == 0 and x["r"] >= header_rows]
    row_header = bool(header_rows and table["n_cols"] >= 2 and body_first and all(x["text"] and not re.search(r"\d", LABEL_NUMBER.sub("", x["text"])) for x in body_first))
    return {"id": f"{round_no}-{number}", "round": round_no, "number": number, "source": source, "page": table["page"],
            "n_rows": table["n_rows"], "n_cols": table["n_cols"], "header_rows": header_rows, "row_header": row_header, "cells": cells}


def matches(cells, question_text):
    """표 칸 글이 문항 글에 들어 있는 비율(길이 2 이상인 칸만)."""
    pool = norm(question_text)
    words = [norm(x["text"]) for x in cells if len(norm(x["text"])) >= 2]
    return (sum(1 for w in words if w in pool) / len(words), len(words)) if words else (0.0, 0)


def find_raw(round_no):
    for raw in RAW_DIRS:
        path = find_answer_file(raw / str(round_no))
        if path:
            return path
    return None


def main():
    bank = {}
    for round_no, items in read_bank_files():
        for item in items:
            bank[f"{round_no}-{item['number']}"] = item
    tables, unmatched, boxes = [], [], 0
    rounds = sorted({int(k.split("-")[0]) for k in bank})
    for round_no in rounds:
        path = find_raw(round_no)
        if not path:
            continue
        events = pdf_events(path) if path.suffix == ".pdf" else hwp_events(path)
        current, answered, last_start, in_theory = None, True, 0, True
        for page, pos, kind, value in events:
            if kind == "start":
                if in_theory and value == last_start + 1:             # 이론 문항 번호는 1,2,3… 순서로만 받는다(문항 안의 '1. …' 목록은 무시)
                    last_start, current, answered = value, value, False
            elif kind == "answer":
                answered = True
                if current == 15:
                    in_theory = False                                 # 15번 답 뒤는 실무 시험 문제
            else:
                if len(value["cells"]) <= 1 or value["n_rows"] * value["n_cols"] <= 1:
                    boxes += 1                                        # 글상자(칸 1개)는 표가 아님
                    continue
                preview = " | ".join(x["text"] for x in value["cells"][:4])
                where = {"round": round_no, "page": value["page"], "preview": preview[:80]}
                if answered and current is not None:
                    continue                                          # 해설 안의 표
                if not in_theory:
                    unmatched.append({**where, "number": current, "reason": "실무 시험 문제의 표(이론 문항이 아님)"})
                    continue
                if current is None:
                    unmatched.append({**where, "reason": "문항 번호 앞의 표(정답표·표지 등)"})
                    continue
                if answered:
                    continue                                          # 해설 안의 표
                item = bank.get(f"{round_no}-{current}")
                if not item:
                    unmatched.append({**where, "number": current, "reason": "DB 에 없는 문항 번호(이론 15문항 밖)"})
                    continue
                ratio, count = matches(value["cells"], item["question"] + " " + " ".join(item["choices"]))
                if count < 2 or ratio < MATCH_RATIO:
                    unmatched.append({**where, "number": current, "reason": f"표 칸 글이 문항 글과 {ratio:.0%}만 일치(칸 {count}개)"})
                    continue
                tables.append(build_entry(round_no, current, str(path).replace(str(ROOT) + "/", ""), value))
    OUT.write_text(json.dumps({"tables": tables, "unmatched": unmatched, "boxes_skipped": boxes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"표 {len(tables)}개({len({t['id'] for t in tables})}문항), 못 바꾼 표 {len(unmatched)}개, 글상자 {boxes}개 제외")


if __name__ == "__main__":
    main()
