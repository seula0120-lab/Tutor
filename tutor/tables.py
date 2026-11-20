"""문제 글 속 표. data/tables.json(scripts/extract_tables.py 가 원본 PDF·HWP 에서 뽑음)에서 문항 id 로 찾는다.

표 하나: {n_rows, n_cols, header_rows(머리글 줄 수), row_header(첫 열이 행 머리글인가), page, cells: [{r, c, rs, cs, text}]}.
rs·cs 는 칸 병합(행·열 걸침)이라 머리글과 칸의 연결이 그대로 남는다. 표로 바꾸지 못한 표는 data/tables.json 의 unmatched 에 사유와 함께 남는다.
"""
import json
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
