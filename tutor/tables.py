"""문제 글 속 표. data/tables.json(scripts/extract_tables.py 가 원본 PDF·HWP 에서 뽑음)에서 문항 id 로 찾는다.

표 하나: {n_rows, n_cols, header_rows(머리글 줄 수), row_header(첫 열이 행 머리글인가), page, cells: [{r, c, rs, cs, text}]}.
rs·cs 는 칸 병합(행·열 걸침)이라 머리글과 칸의 연결이 그대로 남는다. 표로 바꾸지 못한 표는 data/tables.json 의 unmatched 에 사유와 함께 남는다.
"""
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "tables.json"
_cache = {}


def _load(path):
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _cache.get("stamp") != (path, stamp):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        by_id = {}
        for t in data.get("tables", []) if isinstance(data, dict) else []:
            by_id.setdefault(t["id"], []).append({k: t[k] for k in ("n_rows", "n_cols", "header_rows", "row_header", "page", "cells")})
        _cache.update(stamp=(path, stamp), by_id=by_id)
    return _cache["by_id"]


def for_question(question_id, path=PATH):
    """문항의 표 목록(보통 0~1개, 둘 이상이면 원본 순서). 없으면 []."""
    return _load(Path(path)).get(question_id, [])


# ── 화면용 본문: 표로 따로 보여 주는 글자를 본문에서 숨긴다 ──────────────────
CHOICE_MARKS = ("①", "②", "③", "④", "⑤")
HIDE_COVERAGE = 0.8      # 표 칸 낱말의 이만큼 이상이 본문에서 이어져 있어야 숨긴다


def _norm(word):
    return re.sub(r"[,ㆍ•·]", "", unicodedata.normalize("NFKC", word))


def _hide_one(text, table):
    """본문에서 표 칸 낱말이 끊기지 않고 이어진 구간(가장 긴 것)을 찾아 뺀 글을 돌려준다. 못 찾으면 None.
    규칙: 표 칸의 낱말(공백 기준, 쉼표 뺀 것)을 한 번씩만 쓸 수 있는 묶음으로 보고, 본문 낱말이 그 묶음에서 계속 나오는 구간 중 가장 긴 것을 고른다.
    구간 안 낱말의 80% 이상(표 낱말 기준)을 채울 때만 숨긴다. 순서는 따지지 않는다(PDF 에서 표 글자가 뒤섞여 풀린다)."""
    choice_rows = {c["r"] for c in table["cells"] if c["c"] == 0 and c["text"].strip() in CHOICE_MARKS}      # 보기 ①~④ 줄은 본문에 없다(보기 칸에 따로 있음)
    pool = Counter(w for c in table["cells"] if c["r"] not in choice_rows for w in map(_norm, c["text"].split()) if w)
    total = sum(pool.values())
    if total < 3:
        return None
    words = [(m.start(), m.end(), _norm(m.group(0))) for m in re.finditer(r"\S+", text)]
    best = None
    for i in range(len(words)):
        left, used, j, last = Counter(pool), 0, i, None
        while j < len(words):
            w = words[j][2]
            if w and left[w] > 0:
                left[w] -= 1
                used += 1
                last = j
            elif w and not re.fullmatch(r"[?\-–~=]+", w):
                break
            j += 1
        if last is not None and words[i][2] and used and (best is None or used > best[0]):
            best = (used, i, last)
    if not best or best[0] < HIDE_COVERAGE * total:
        return None
    _, i, last = best
    return (text[:words[i][0]].rstrip() + " " + text[words[last][1]:].lstrip()).strip()


def view_text(question, tables_of_question):
    """(화면에 보일 본문, 숨겼는가). 표가 없거나 표 글자 구간을 못 찾으면 원문 그대로. 원문·검색 색인은 바꾸지 않는다."""
    text, hidden = question, False
    for table in tables_of_question or []:
        cut = _hide_one(text, table)
        if cut is not None and cut != text:
            text, hidden = cut, True
    return text, hidden
