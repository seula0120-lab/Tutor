"""회차별 시행일을 원본(문제지·확정답안)의 표지에서 뽑아 data/exam_dates.json 으로 쓴다.

찾는 글: '2026년 10월 3일 시행' 꼴의 날짜. 같은 자리(앞뒤 120자) 안에 '제N회' 가 그 회차 번호와 같을 때만 받는다.
못 찾은 회차는 파일에 넣지 않는다(추정 금지). 근거는 파일·쪽·찾은 글을 함께 남긴다.
원본은 이 프로젝트 data/raw, 없으면 /Users/seul/Desktop/PJT2_결과물 회계튜터/data/raw (읽기만).
PDF 는 PyMuPDF 로 앞 3쪽, HWP 는 hwp5html 변환 결과의 표지(첫 쪽, HWP 는 쪽 번호가 없다).
사용법: .venv/bin/python scripts/extract_exam_dates.py
"""
import html
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RAW_DIRS = [ROOT / "data" / "raw", Path("/Users/seul/Desktop/PJT2_결과물 회계튜터/data/raw")]
OUT = ROOT / "data" / "exam_dates.json"
HWP5HTML = ROOT / ".venv" / "bin" / "hwp5html"
DATE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*시행")
FILES = ("question_A", "answer")


def find_date(text, round_no):
    """text 에서 round_no 회차의 시행일을 찾는다: (ISO 날짜, 찾은 글) 또는 None."""
    for m in DATE.finditer(text):
        near = text[max(0, m.start() - 120):m.end() + 120]
        if round_no not in {int(x) for x in re.findall(r"제\s*(\d+)\s*회", near)}:
            continue
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), " ".join(m.group(0).split())
        except ValueError:
            continue
    return None


def pdf_pages(path):
    with pymupdf.open(path) as doc:
        for number in range(min(3, len(doc))):
            yield number + 1, doc[number].get_text()


def hwp_cover(path):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([str(HWP5HTML), "--output", f"{tmp}/o", str(path)], capture_output=True, check=False)
        pages = list(Path(tmp, "o").glob("*.xhtml")) + list(Path(tmp, "o").glob("*.html"))
        raw = pages[0].read_text(encoding="utf-8") if pages else ""
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S)
    yield None, " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())[:4000]


def raw_files(round_no):
    for raw in RAW_DIRS:
        for stem in FILES:
            for suffix in (".pdf", ".hwp"):
                path = raw / str(round_no) / (stem + suffix)
                if path.exists():
                    yield path


def extract(round_no):
    for path in raw_files(round_no):
        pages = pdf_pages(path) if path.suffix == ".pdf" else hwp_cover(path)
        for page, text in pages:
            found = find_date(text, round_no)
            if found:
                where = str(path).replace(str(ROOT) + "/", "")
                return {"round": round_no, "exam_date": found[0], "source": where, "page": page, "location": "표지(HWP 는 쪽 번호가 없음)" if page is None else f"{page}쪽", "text": found[1]}
    return None


def main():
    rounds = sorted(int(p.stem) for p in (ROOT / "data" / "bank").glob("*.json"))
    found, missing = [], []
    for n in rounds:
        entry = extract(n)
        (found if entry else missing).append(entry or n)
    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"시행일 찾음 {len(found)}회 / 못 찾음 {len(missing)}회: {missing}")


if __name__ == "__main__":
    main()
