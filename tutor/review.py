"""간격 복습: 틀린 기출 문항과 틀린 O/X 문장을 1일 → 3일 → 7일 → 14일 뒤에 다시 보여 준다.

기록은 오답노트와 같은 records 다(별도 복습 표 없음). 복습 상태는 기록을 시간 순으로 읽어 매번 계산한다.
- 틀리면(언제든) 1일 단계부터 다시: 그날 + 1일이 복습일.
- 복습일이 되었거나 지난 뒤 맞히면 다음 간격으로: 3일 → 7일 → 14일 단계. 14일 단계에서 맞히면 복습 완료.
- 복습일 전에 맞힌 기록은 간격을 넘기지 않는다(그냥 다시 풀어 본 것).
- 확인만 한 기록(정답·해설 바로 보기)과 정오 없는 기록은 세지 않는다.
날짜 계산은 advance() 한 곳에서만 한다. 날짜는 clock 의 일 번호다.
"""
from . import clock
from .ox import PREFIX, pool
from .quiz import get_row
from .records import first_line

INTERVALS = (1, 3, 7, 14)       # 일


def advance(state, day, correct):
    """복습 상태 {stage, due, done} 를 기록 하나(day 일에 correct)만큼 진행한다. 날짜 계산은 여기만."""
    if not correct:
        return {"stage": 0, "due": day + INTERVALS[0], "done": False}
    if state is None or state["done"] or day < state["due"]:
        return state
    stage = state["stage"]
    if stage == len(INTERVALS) - 1:
        return {"stage": stage, "due": None, "done": True}
    return {"stage": stage + 1, "due": day + INTERVALS[stage + 1], "done": False}


def states(conn):
    """{기록 대상 id: 복습 상태}. 대상 id 는 기출 문항 id('128-1') 또는 'ox:<키>'. 한 번도 틀린 적 없으면 없다."""
    out = {}
    for r in conn.execute("""SELECT question_id, correct, ts FROM records
                             WHERE user_id = ? AND seen_only = 0 AND correct IS NOT NULL ORDER BY id""", (conn.user_id,)):
        state = advance(out.get(r["question_id"]), clock.day_of(r["ts"]), bool(r["correct"]))
        if state is not None:
            out[r["question_id"]] = state
    return out


def _describe(conn, target, state, items):
    base = {"target": target, "stage": state["stage"], "due": state["due"], "interval": INTERVALS[state["stage"]]}
    if target.startswith(PREFIX):
        item = items.get(target[len(PREFIX):])
        if item is None:
            return None
        return {**base, "kind": "ox", "key": item["key"], "text": item["text"], "stem": item["stem"], "subject": item["subject"], "tax": item["tax"],
                "unit": item["unit"], "old_tax": item["old_tax"], "tax_label": item["tax_label"]}
    row = get_row(conn, target)
    if row is None:
        return None
    return {**base, "kind": "question", "id": row["id"], "subject": row["subject"], "tax": row["tax"], "unit": row["unit"],
            "first_line": first_line(row["question"])}


def due_items(conn, today=None):
    """오늘(또는 지난 날) 복습일이 된 대상. 복습일이 빠른 것부터."""
    today = clock.today() if today is None else today
    items = pool(conn)
    due = sorted(((t, s) for t, s in states(conn).items() if not s["done"] and s["due"] <= today), key=lambda p: (p[1]["due"], p[0]))
    return [d for d in (_describe(conn, t, s, items) for t, s in due) if d]


def summary(conn, today=None):
    """복습 현황: 오늘 할 것(due), 아직 기다리는 것(waiting), 복습 완료(done) 개수와 오늘 할 목록."""
    today = clock.today() if today is None else today
    all_states = states(conn)
    due = due_items(conn, today)
    return {"due_count": len(due), "due": due,
            "waiting": sum(1 for s in all_states.values() if not s["done"] and s["due"] > today),
            "done": sum(1 for s in all_states.values() if s["done"]),
            "intervals": list(INTERVALS)}
