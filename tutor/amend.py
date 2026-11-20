"""2025 개정세법 항목의 적용일 이전 시험 문장에 '개정 전 기준' 배지를 붙이는 규칙.

- 개정 항목은 세무 노트(data/study/세무회계/*/*.json)의 `changes` 칸이다. 항목마다 `when`(적용 시기)과 `keywords`(같은 주제인지 가르는 낱말)가 있다.
- 적용일: `when` 맨 앞의 날짜('’26.1.1. 이후 …', '’26.7.1. …'). 날짜가 없는 항목('개정 시행령 적용', '시행 유예' …)은 시험 날짜와 견줄 수 없어 배지를 만들지 않는다.
- 배지 조건(셋 다): ① 문장이 나온 시험의 시행일이 적용일보다 앞선다 ② 문장의 단원이 항목의 단원과 같다 ③ 문장에 항목의 keywords 중 하나가 들어 있다.
  시험 시행일을 모르는 회차는 견줄 수 없어 배지를 붙이지 않는다(지어내지 않음).
"""
import json
import re
from datetime import date
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent.parent / "data" / "study" / "세무회계"
APPLY = re.compile(r"^\s*[’']?(\d{2}|\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?")
BADGE = "개정 전 기준"

_cache = {}


def apply_day(when):
    """'’26.1.1. 이후 …' → 일 번호. 맨 앞에 날짜가 없으면 None."""
    match = APPLY.match(when or "")
    if not match:
        return None
    year = int(match.group(1))
    year += 2000 if year < 100 else 0
    try:
        return date(year, int(match.group(2)), int(match.group(3))).toordinal()
    except ValueError:
        return None


def changes(study_dir=STUDY_DIR):
    """날짜와 keywords 가 있는 개정 항목 [{tax, unit, what, when, page, apply, keywords}]. 노트 파일이 바뀌면 다시 읽는다."""
    study_dir = Path(study_dir)
    paths = sorted(study_dir.glob("*/*.json")) if study_dir.is_dir() else []
    stamp = tuple((p.name, p.stat().st_mtime_ns) for p in paths)
    hit = _cache.get(study_dir)
    if hit and hit[0] == stamp:
        return hit[1]
    out = []
    for path in paths:
        try:
            note = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for change in note.get("changes") or []:
            day = apply_day(change.get("when"))
            if day is not None and change.get("keywords"):
                out.append({"tax": note.get("tax"), "unit": note.get("unit"), "what": change["what"], "when": change["when"],
                            "page": change.get("page"), "apply": day, "keywords": list(change["keywords"])})
    _cache[study_dir] = (stamp, out)
    return out


def badges(unit, text, exam_day, study_dir=STUDY_DIR):
    """문장(text, 단원 unit)이 시행일 exam_day(일 번호)의 시험 것일 때 붙일 배지 목록.
    [{label: '개정 전 기준', what, when, page, text: '개정 전 기준 — 법인세 세율 (’26.1.1. 이후 …, 2025 개정세법 p26)'}]. 시행일을 모르면 []."""
    if exam_day is None:
        return []
    out = []
    for change in changes(study_dir):
        if change["unit"] == unit and exam_day < change["apply"] and any(k in text for k in change["keywords"]):
            out.append({"label": BADGE, "what": change["what"], "when": change["when"], "page": change["page"],
                        "text": f"{BADGE} — {change['what']} ({change['when']}, 2025 개정세법 p{change['page']})"})
    return out
