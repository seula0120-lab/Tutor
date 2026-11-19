"""모의고사: 재무 5·원가 5·세무 5(부가세·소득세·법인세를 섞음)를 전체 회차에서 무작위로 뽑고, 제출하면 채점한다.

- 이미 맞힌 문항은 뒤로 미룬다: 같은 조건이면 한 번도 못 맞힌 문항을 먼저 뽑고, 모자랄 때만 맞힌 문항을 쓴다.
- 풀이 중에는 정답·해설을 내보내지 않는다(public_question). 정답은 제출 뒤 틀린 문항에 한해 해설과 함께 돌려준다.
- 점수는 문항 배점(points) 합, 15문항 × 2점 = 30점 만점. 미응답은 오답이다.
- 제출한 답은 풀이 기록(source='mock')에 남기고 결과는 mock_results 에 쌓아 점수 추이를 보여 준다.
"""
import json
import random
import time

from . import records
from .quiz import accepted_answers, explanation_of, get_row, public_question

SUBJECTS = ("재무회계", "원가회계", "세무회계")
PER_SUBJECT = 5
TAXES = ("부가가치세", "소득세", "법인세")
TAX_SPLIT = (2, 2, 1)           # 세무 5문항 = 두 세목 2개씩 + 한 세목 1개(어느 세목이 1개인지는 무작위)
EXAM_SIZE = PER_SUBJECT * len(SUBJECTS)
# 회차만 다르고 글이 같은 진짜 중복 문항(docs/data_cleanup.md 2절). 한 모의고사에 둘 다 나오지 않게 한다.
DUPLICATE_PAIRS = (("118-15", "122-13"), ("70-8", "81-8"), ("67-1", "80-4"))
PARTNER = {a: b for a, b in DUPLICATE_PAIRS} | {b: a for a, b in DUPLICATE_PAIRS}


def _draw(conn, where, args, count, solved, rng, taken):
    """조건에 맞는 문항에서 count 개를 뽑는다. 한 번도 못 맞힌 문항 먼저, 이미 뽑힌(taken) 문항은 제외."""
    rows = [r for r in conn.execute(f"SELECT * FROM questions WHERE {where}", args).fetchall() if r["id"] not in taken]
    rng.shuffle(rows)
    rows.sort(key=lambda r: r["id"] in solved)      # 안정 정렬: 섞인 순서를 유지한 채 맞힌 문항만 뒤로
    chosen = []
    for r in rows:                                   # 앞에서부터 고르되, 이미 고른(이전 묶음 포함) 문항의 중복쌍은 건너뛴다
        if len(chosen) == count:
            break
        if PARTNER.get(r["id"]) not in taken and PARTNER.get(r["id"]) not in {c["id"] for c in chosen}:
            chosen.append(r)
    return chosen


def pick_exam(conn, rng=random):
    """모의고사 15문항(공개용)을 뽑는다. 재무 5 → 원가 5 → 세무 5 순서."""
    solved = records.correct_ids(conn)
    taken, picked = set(), []

    def take(rows):
        for r in rows:
            taken.add(r["id"])
            picked.append(r)

    for subject in SUBJECTS[:2]:
        take(_draw(conn, "subject = ?", (subject,), PER_SUBJECT, solved, rng, taken))
    split = list(TAX_SPLIT)
    rng.shuffle(split)
    for tax, count in zip(TAXES, split):
        take(_draw(conn, "subject = '세무회계' AND tax = ?", (tax,), count, solved, rng, taken))
    shortage = EXAM_SIZE - len(picked)
    if shortage > 0:                  # 어느 세목이 모자라면 다른 세무 문항으로 채운다
        take(_draw(conn, "subject = '세무회계'", (), shortage, solved, rng, taken))
    return [public_question(r) for r in picked]


def grade(conn, ids, answers, *, now=None):
    """제출을 채점한다. ids: 푼 문항 id 목록(중복 불가), answers: {id: 고른 보기 번호}. 점수·과목별 점수·틀린 문항 해설을 돌려준다."""
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("문항 목록이 비었거나 중복이 있습니다.")
    rows = []
    for qid in ids:
        row = get_row(conn, qid)
        if row is None:
            raise ValueError(f"문항 {qid} 없음")
        rows.append(row)
    by_subject = {s: {"score": 0, "max": 0} for s in SUBJECTS}
    wrong = []
    now = time.time() if now is None else now
    for row in rows:
        choice = str(answers.get(row["id"], "") or "").strip()
        correct = choice in accepted_answers(row["answer"])
        by_subject.setdefault(row["subject"], {"score": 0, "max": 0})
        by_subject[row["subject"]]["max"] += row["points"]
        if correct:
            by_subject[row["subject"]]["score"] += row["points"]
        else:
            wrong.append({"id": row["id"], "subject": row["subject"], "unit": row["unit"], "question": row["question"],
                          "your_choice": choice, "answer": row["answer"], "explanation": explanation_of(row)})
        records.save(conn, row["id"], choice, correct, source="mock", now=now)
    score = sum(v["score"] for v in by_subject.values())
    max_score = sum(v["max"] for v in by_subject.values())
    with conn:
        conn.execute("INSERT INTO mock_results(taken_at, score, max_score, by_subject, wrong_ids) VALUES (?,?,?,?,?)",
                     (now, score, max_score, json.dumps(by_subject, ensure_ascii=False),
                      json.dumps([w["id"] for w in wrong])))
    return {"score": score, "max_score": max_score, "by_subject": by_subject, "wrong": wrong, "history": history(conn)}


def history(conn):
    """지난 모의고사 점수 추이: 오래된 순(표의 위가 첫 시험). 각 행에 직전 시험과의 점수 차이를 붙인다."""
    rows = conn.execute("SELECT * FROM mock_results ORDER BY id").fetchall()
    result, previous = [], None
    for n, r in enumerate(rows, 1):
        result.append({"n": n, "taken_at": r["taken_at"], "score": r["score"], "max_score": r["max_score"],
                       "by_subject": json.loads(r["by_subject"]), "wrong_count": len(json.loads(r["wrong_ids"])),
                       "diff": None if previous is None else r["score"] - previous})
        previous = r["score"]
    return result
