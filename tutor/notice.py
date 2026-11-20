"""세법 개정 확인 표시. 세무회계(부가가치세·소득세·법인세) 문항에만 붙고 재무·원가 문항에는 붙지 않는다.

- 시행 연도는 data/bank/<회차>.json 의 exam_date 에서만 읽는다. 값이 없거나 연도를 읽을 수 없으면 회차만 표시하고 연도를 짐작하지 않는다.
- data/tax_changes.json(연도·세목·핵심어·메모 목록, 처음엔 빈 목록)에 적은 핵심어가 문제 글·보기에 있으면 그 메모를 함께 보여 준다.
- 두 파일 모두 수정 시각이 바뀔 때만 다시 읽는다.
"""
import json
import re
from datetime import date
from pathlib import Path

from . import exam_dates

DATA = Path(__file__).resolve().parent.parent / "data"
BANK_DIR = DATA / "bank"
TAX_CHANGES = DATA / "tax_changes.json"
TAX_SUBJECT = "세무회계"

_cache = {}


def _cached(path, loader):
    """파일 수정 시각이 같으면 읽은 결과를 다시 쓰고, 바뀌었으면 loader 로 다시 읽는다."""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return loader(None)
    hit = _cache.get(path)
    if not hit or hit[0] != stamp:
        _cache[path] = (stamp, loader(path))
    return _cache[path][1]


def _dir_stamp(bank_dir):
    return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in Path(bank_dir).glob("*.json"))) if Path(bank_dir).is_dir() else ()


def exam_years(bank_dir=BANK_DIR):
    """{회차: 시행 연도(int)}. 시행일을 모르는 회차는 넣지 않는다(bank JSON 의 exam_date 와 data/exam_dates.json)."""
    bank_dir = Path(bank_dir)
    stamp = (_dir_stamp(bank_dir), exam_dates.PATH.stat().st_mtime_ns if exam_dates.PATH.exists() else 0)
    hit = _cache.get(("years", bank_dir))
    if hit and hit[0] == stamp:
        return hit[1]
    years = {}
    for path in bank_dir.glob("*.json") if bank_dir.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        match = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", str(data.get("exam_date") or ""))
        if match and isinstance(data.get("round"), int):
            years[data["round"]] = int(match.group(0))
    if bank_dir == BANK_DIR:                                # 진짜 문제은행이면, 원본 표지에서 뽑은 시행일(data/exam_dates.json)이 우선한다
        for round_no, entry in exam_dates.read().items():
            years[round_no] = int(entry["exam_date"][:4])
    _cache[("years", bank_dir)] = (stamp, years)
    return years


def exam_day(round_no, bank_dir=BANK_DIR):
    """회차의 시행일(일 번호). 모르면 None. 진짜 문제은행(data/exam_dates.json)일 때만 알 수 있다."""
    if Path(bank_dir) != BANK_DIR:
        return None
    entry = _cached(exam_dates.PATH, lambda p: exam_dates.read() if p else {}).get(round_no)
    return date.fromisoformat(entry["exam_date"]).toordinal() if entry else None


def exam_basis(subject, round_no, bank_dir=BANK_DIR):
    """세무회계면 '2026년 10월 시행 시험 기준'. 시행일을 모르거나 세무가 아니면 None."""
    day = exam_day(round_no, bank_dir) if subject == TAX_SUBJECT else None
    return exam_dates.label(day) if day is not None else None


def tax_changes(path=TAX_CHANGES):
    """tax_changes.json 의 항목 목록. 파일이 없거나 형식이 틀리면 빈 목록."""
    def load(p):
        if p is None:
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [c for c in data if isinstance(c, dict) and c.get("keyword") and c.get("memo")] if isinstance(data, list) else []
    return _cached(Path(path), load)


def tax_notice(subject, round_no, bank_dir=BANK_DIR):
    """세무회계면 '128회(2026년 시행) · 세법 개정 확인 필요'(연도를 모르면 '128회 · 세법 개정 확인 필요'), 아니면 None."""
    if subject != TAX_SUBJECT:
        return None
    year = exam_years(bank_dir).get(round_no)
    head = f"{round_no}회({year}년 시행)" if year else f"{round_no}회"
    return f"{head} · 세법 개정 확인 필요"


def tax_notes(subject, round_no, text="", tax=None, bank_dir=BANK_DIR, changes_path=TAX_CHANGES):
    """화면에 줄 안내 목록: 회차 안내 + 문제 글에 핵심어가 있는 세법 개정 메모. 세무회계가 아니면 빈 목록."""
    base = tax_notice(subject, round_no, bank_dir)
    if base is None:
        return []
    notes = [base]
    for change in tax_changes(changes_path):
        if change["keyword"] in (text or "") and (not change.get("tax") or change["tax"] == tax):
            year = f'{change["year"]}년 ' if change.get("year") else ""
            notes.append(f'{year}세법 개정: {change["memo"]}')
    return notes
