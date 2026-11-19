"""용어 사전 검토 화면(/glossary-review)의 데이터: 용어별 기출 문제 글 출현 횟수와 검토 상태·메모.

- 검토 상태·메모·수정 제안은 서버 DB(glossary_review 테이블)에 저장하고, 같은 내용을 data/glossary_review.json 에도
  쌓는다. data/glossary.json(사전 원본)은 이 모듈이 절대 고치지 않는다.
- 파일 위치는 환경변수 GLOSSARY_REVIEW_PATH 로 바꿀 수 있다(화면 자동 점검이 진짜 파일을 건드리지 않도록).
"""
import json
import os
import re
import time
from pathlib import Path

from .glossary import load_glossary

REVIEW_PATH = Path(os.environ.get("GLOSSARY_REVIEW_PATH")
                   or Path(__file__).resolve().parent.parent / "data" / "glossary_review.json")
STATUSES = ("", "검토 완료", "수정 필요")        # 빈 값 = 아직 검토 안 함


def _compact(text):
    return re.sub(r"\s+", "", text)


def usage_counts(conn, entries):
    """{용어: 그 용어(공백 무시)가 문제 글에 나온 문항 수}. 보기·해설은 세지 않는다."""
    texts = [_compact(r["question"]) for r in conn.execute("SELECT question FROM questions")]
    return {e["term"]: sum(1 for t in texts if _compact(e["term"]) in t) for e in entries}


def saved_reviews(conn):
    """{용어: {status, memo, proposed_meaning, updated}} — 저장된 검토 내용."""
    return {r["term"]: dict(r) for r in conn.execute("SELECT * FROM glossary_review")}


def list_rows(conn, entries=None):
    """용어·풀이·동의어 + 출현 횟수 + 검토 상태·메모. 출현 횟수가 많은 순(같으면 가나다순)."""
    entries = load_glossary() if entries is None else entries
    counts, saved = usage_counts(conn, entries), saved_reviews(conn)
    rows = []
    for e in entries:
        review = saved.get(e["term"], {})
        rows.append({"term": e["term"], "meaning": e["meaning"], "synonyms": e["synonyms"], "count": counts[e["term"]],
                     "status": review.get("status", ""), "memo": review.get("memo", ""),
                     "proposed_meaning": review.get("proposed_meaning", "")})
    return sorted(rows, key=lambda r: (-r["count"], r["term"]))


def save_review(conn, term, status, memo, proposed_meaning="", entries=None, path=None):
    """검토 상태·메모·수정 제안을 DB 에 저장하고 data/glossary_review.json 을 갱신한다. 사전에 없는 용어는 ValueError."""
    entries = load_glossary() if entries is None else entries
    if term not in {e["term"] for e in entries}:
        raise ValueError("사전에 없는 용어입니다.")
    if status not in STATUSES:
        raise ValueError("검토 상태는 '검토 완료' 또는 '수정 필요' 이어야 합니다.")
    with conn:
        conn.execute(
            "INSERT INTO glossary_review(term, status, memo, proposed_meaning, updated) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(term) DO UPDATE SET status=excluded.status, memo=excluded.memo, "
            "proposed_meaning=excluded.proposed_meaning, updated=excluded.updated",
            (term, status, memo.strip(), proposed_meaning.strip(), time.time()))
    write_review_file(conn, entries, path)


def write_review_file(conn, entries, path=None):
    """상태·메모·수정 제안이 하나라도 있는 용어를 원래 풀이·동의어와 함께 JSON 파일로 쓴다(가나다순)."""
    by_term = {e["term"]: e for e in entries}
    reviews = []
    for term, r in sorted(saved_reviews(conn).items()):
        if term in by_term and (r["status"] or r["memo"] or r["proposed_meaning"]):
            reviews.append({"term": term, "status": r["status"], "memo": r["memo"], "proposed_meaning": r["proposed_meaning"],
                            "original_meaning": by_term[term]["meaning"], "original_synonyms": by_term[term]["synonyms"],
                            "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["updated"]))})
    target = Path(path or REVIEW_PATH)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"note": "용어 사전 검토 결과. data/glossary.json 은 바꾸지 않고 여기에만 쌓는다. 사람이 보고 반영한다.",
                                "reviews": reviews}, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(target)
