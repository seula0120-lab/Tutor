"""기출 답안 탭: 회차·번호 조회, 단원 퀴즈, 정답 확인. 정답·해설은 규칙에 따라서만 내보낸다.

- 조회·퀴즈 문항에는 정답과 해설을 넣지 않는다(public_question).
- 정답을 고르면 공식 해설을 함께 돌려준다. 오답이면 오답이라는 사실만 돌려준다(정답·해설 숨김).
- '정답·해설 바로 보기'(reveal)는 풀이 기록 없이 공개한다.
"""
import json
import random

from .notice import tax_notice


def accepted_answers(answer):
    """'3' 또는 복수정답 '1,3' 을 {'1', '3'} 집합으로 바꾼다."""
    return {a.strip() for a in answer.split(",") if a.strip()}


def public_question(row):
    """화면에 보여 줄 문항. 정답·해설은 뺀다. 복수정답이면 multi=True 로 알린다."""
    return {
        "id": row["id"], "round": row["round"], "number": row["number"], "subject": row["subject"],
        "tax": row["tax"], "unit": row["unit"], "points": row["points"], "question": row["question"],
        "choices": json.loads(row["choices"]), "multi": len(accepted_answers(row["answer"])) > 1,
        "tax_notice": tax_notice(row["subject"], row["round"]),
    }


def get_row(conn, question_id):
    return conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()


def find_question(conn, round_no, number):
    """회차·번호로 문항을 찾아 공개용으로 돌려준다. 없으면 None."""
    return _public_or_none(get_row(conn, f"{int(round_no)}-{int(number)}"))


def _public_or_none(row):
    return public_question(row) if row else None


def list_units(conn):
    """퀴즈에서 고를 수 있는 단원 목록: [{subject, tax, unit, label, count}]."""
    rows = conn.execute("""SELECT subject, tax, unit, COUNT(*) AS n FROM questions
                           GROUP BY subject, tax, unit ORDER BY subject, tax, unit""").fetchall()
    return [{"subject": r["subject"], "tax": r["tax"], "unit": r["unit"], "count": r["n"],
             "label": " › ".join(p for p in (r["subject"], r["tax"], r["unit"]) if p)} for r in rows]


def pick_quiz_question(conn, subject=None, tax=None, unit=None, exclude=(), rng=random):
    """조건에 맞는 문항 하나를 무작위로 공개용으로 돌려준다(exclude 는 이미 푼 id). 없으면 None."""
    where, args = [], []
    for column, value in (("subject", subject), ("tax", tax), ("unit", unit)):
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    sql = "SELECT * FROM questions" + (" WHERE " + " AND ".join(where) if where else "")
    rows = [r for r in conn.execute(sql, args).fetchall() if r["id"] not in set(exclude)]
    return public_question(rng.choice(rows)) if rows else None


def check_answer(conn, question_id, choice):
    """고른 보기를 채점한다. 정답이면 정답·해설을, 오답이면 오답이라는 사실만 돌려준다."""
    row = get_row(conn, question_id)
    if row is None:
        return {"error": f"문항 {question_id} 없음"}
    if str(choice).strip() not in accepted_answers(row["answer"]):
        return {"id": question_id, "correct": False}
    return {"id": question_id, "correct": True, "answer": row["answer"], "explanation": row["explanation"]}


def reveal(conn, question_id):
    """'정답·해설 바로 보기': 채점 없이 정답과 공식 해설을 공개한다."""
    row = get_row(conn, question_id)
    if row is None:
        return {"error": f"문항 {question_id} 없음"}
    return {"id": question_id, "answer": row["answer"], "explanation": row["explanation"]}


def pick_set(conn, subject=None, tax=None, unit=None, count=5, rng=random):
    """한 단원에서 count 문항을 무작위로 골라 id 목록으로 돌려준다. 아직 못 맞힌 문항을 먼저, 모자라면 맞힌 문항으로 채운다."""
    from .records import correct_ids
    solved = correct_ids(conn)
    where, args = [], []
    for column, value in (("subject", subject), ("tax", tax), ("unit", unit)):
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    rows = conn.execute("SELECT id FROM questions" + (" WHERE " + " AND ".join(where) if where else ""), args).fetchall()
    ids = [r["id"] for r in rows]
    rng.shuffle(ids)
    ids.sort(key=lambda i: i in solved)
    return ids[:count]
