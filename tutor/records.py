"""풀이 기록과 오답노트. 기록은 사용자가 만든 데이터라 문제은행을 다시 적재해도 지워지지 않는다.

규칙
- 보기를 고르면 정오(correct 1/0)를 남긴다. '정답·해설 바로 보기'는 seen_only=1·correct=NULL 로 남기고 정답으로 세지 않는다.
- 같은 문항에 같은 내용의 기록이 DEDUPE_SECONDS 안에 연달아 오면 한 번만 남긴다(더블 클릭 방지).
- 오답노트 = 오답 기록이 있고, 그 뒤에 정답 기록이 없는 문항. 다시 풀어 맞히면 빠진다. 확인만 한 기록은 넣지도 빼지도 않는다.
"""
import time

DEDUPE_SECONDS = 3.0


def save(conn, question_id, choice, correct, *, seen_only=False, source="quiz", now=None):
    """기록 한 줄을 남기고 True, 바로 앞의 같은 기록(더블 클릭)이라 건너뛰면 False 를 돌려준다."""
    now = time.time() if now is None else now
    choice = str(choice)
    correct_value = None if seen_only else int(bool(correct))
    last = conn.execute("""SELECT choice, correct, seen_only, source, ts FROM records
                           WHERE question_id = ? ORDER BY id DESC LIMIT 1""", (question_id,)).fetchone()
    if (last and last["choice"] == choice and last["correct"] == correct_value
            and last["seen_only"] == int(seen_only) and last["source"] == source
            and 0 <= now - last["ts"] < DEDUPE_SECONDS):
        return False
    with conn:
        conn.execute("INSERT INTO records(question_id, choice, correct, seen_only, source, ts) VALUES (?,?,?,?,?,?)",
                     (question_id, choice, correct_value, int(seen_only), source, now))
    return True


def first_line(text, limit=60):
    """문제 글의 첫 줄(길면 limit 글자까지)."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[:limit] + "…"


def notebook(conn, subject=None, unit=None):
    """오답노트 목록: 오답 기록이 있고 그 뒤에 정답 기록이 없는 문항. 최근에 틀린 순. 정답·해설은 넣지 않는다."""
    where, args = [], []
    for column, value in (("q.subject", subject), ("q.unit", unit)):
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    rows = conn.execute(f"""
        SELECT q.id, q.round, q.number, q.subject, q.tax, q.unit, q.question,
               SUM(r.correct = 0 AND r.seen_only = 0) AS wrong_count,
               MAX(CASE WHEN r.correct = 0 AND r.seen_only = 0 THEN r.id END) AS last_wrong_id,
               MAX(CASE WHEN r.correct = 1 THEN r.id END) AS last_right_id,
               MAX(CASE WHEN r.correct = 0 AND r.seen_only = 0 THEN r.ts END) AS last_wrong_ts
        FROM records r JOIN questions q ON q.id = r.question_id
        {"WHERE " + " AND ".join(where) if where else ""}
        GROUP BY q.id HAVING last_wrong_id IS NOT NULL
                         AND (last_right_id IS NULL OR last_right_id < last_wrong_id)
        ORDER BY last_wrong_ts DESC""", args).fetchall()
    return [{"id": r["id"], "round": r["round"], "number": r["number"], "subject": r["subject"], "tax": r["tax"],
             "unit": r["unit"], "wrong_count": r["wrong_count"], "last_wrong_ts": r["last_wrong_ts"],
             "first_line": first_line(r["question"])} for r in rows]


def unit_wrong_counts(conn):
    """단원별 틀린 횟수: 전체 오답 기록 수(wrong_total)와 지금 오답노트에 남은 문항 수(open_questions). 많이 틀린 순."""
    totals = conn.execute("""SELECT q.subject, q.tax, q.unit, COUNT(*) AS n
                             FROM records r JOIN questions q ON q.id = r.question_id
                             WHERE r.correct = 0 AND r.seen_only = 0 GROUP BY q.subject, q.tax, q.unit""").fetchall()
    open_count = {}
    for item in notebook(conn):
        key = (item["subject"], item["tax"], item["unit"])
        open_count[key] = open_count.get(key, 0) + 1
    rows = [{"subject": t["subject"], "tax": t["tax"], "unit": t["unit"],
             "label": " › ".join(p for p in (t["subject"], t["tax"], t["unit"]) if p),
             "wrong_total": t["n"], "open_questions": open_count.get((t["subject"], t["tax"], t["unit"]), 0)}
            for t in totals]
    return sorted(rows, key=lambda r: (-r["wrong_total"], r["label"]))


def unit_stats(conn):
    """단원별 풀이 통계 {(과목, 세목, 단원): {attempts, correct, questions}}. 확인만 한 기록은 센 적 없다."""
    rows = conn.execute("""SELECT q.subject, q.tax, q.unit, COUNT(*) AS attempts, SUM(r.correct = 1) AS right,
                                  COUNT(DISTINCT r.question_id) AS questions
                           FROM records r JOIN questions q ON q.id = r.question_id
                           WHERE r.seen_only = 0 GROUP BY q.subject, q.tax, q.unit""").fetchall()
    return {(r["subject"], r["tax"], r["unit"]): {"attempts": r["attempts"], "correct": r["right"],
                                                   "questions": r["questions"]} for r in rows}


def correct_ids(conn):
    """한 번이라도 맞힌 문항 id 집합(모의고사·추천에서 뒤로 미룰 때 쓴다)."""
    return {r["question_id"] for r in conn.execute("SELECT DISTINCT question_id FROM records WHERE correct = 1")}
