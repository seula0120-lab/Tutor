"""세무 노트(data/study/세무회계/*/*.json)의 수치를 구조화해 각 노트의 `numbers` 칸에 쓴다(다시 돌려도 같은 결과).

기준일(as_of): 개정 항목은 개정세법 책자의 '적용 시기'(when) 글 그대로, 개념 줄은 줄의 출처 회차 중 가장 최근 회차의 시행일
('120회(2025년 4월 시행 시험) 기준'), 개정세법 쪽에서 온 줄은 같은 쪽의 개정 항목 적용 시기(없으면 '기준일 미표기').
사용법: .venv/bin/python scripts/structure_numbers.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tutor import exam_dates, numbers  # noqa: E402

STUDY = ROOT / "data" / "study" / "세무회계"


def main():
    dates = exam_dates.read()
    total = 0
    for path in sorted(STUDY.glob("*/*.json")):
        note = json.loads(path.read_text(encoding="utf-8"))
        pages = {c["page"]: c["when"] for c in note.get("changes") or []}

        def as_of(line):
            if line.get("pdf"):
                return pages.get(line["pdf"]["page"]) or "기준일 미표기"
            rounds = sorted({int(s.split("-")[0]) for s in line.get("sources", [])})
            if not rounds:
                return "기준일 미표기"
            latest = rounds[-1]
            entry = dates.get(latest)
            if not entry:
                return f"{latest}회(시행일 미상) 기준"
            d = date.fromisoformat(entry["exam_date"])
            return f"{latest}회({d.year}년 {d.month}월 시행 시험) 기준"

        note["numbers"] = numbers.structure(note, as_of)
        total += len(note["numbers"])
        path.write_text(json.dumps(note, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"수치 {total}개 구조화")


if __name__ == "__main__":
    main()
