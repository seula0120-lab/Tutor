"""밀린 계획 넘기기와 약한 단원 복습 추가.

밀린 것: 오늘 이전 날 중 상태가 '부분'·'미달'인 날의 항목별 못 한 양(필요량 − 실제). 이미 넘긴 양(plan_carry, source='carry')은 뺀다.
넘기기: 오늘부터 시험 전날 사이 '공부일'(쉬는 요일·'그날 쉬기'·마무리 기간·시험일 제외)에 항목별로 이월 표시와 함께 더한다.
  - 하루 총량 상한 = 설정의 1.5배(노트·O/X·기출은 오늘의 공부 설정, 복습은 계획의 하루 복습 수, 모의고사는 하루 1회).
    그날 계획(이미 넘어온 것 포함)이 상한에 닿으면 그다음 공부일로 나눠 담는다. 시험 전까지 못 담은 양은 밀린 것으로 남고 알린다.
  - 원래 날의 계획·실적은 그대로다(지난 실적을 고치지 않는다). 같은 (원래 날·항목)은 이미 넘긴 양만큼 빼고 계산하므로 두 번 눌러도 두 번 넘어가지 않는다.
복습 추가: 다음 주(일~토)의 공부일마다 그 단원 O/X·기출을 더한다(상한 규칙 동일). 같은 주·같은 단원은 한 번만.
날짜는 clock.py 만 쓴다. 모든 줄에 user_id 가 있다.
"""
from . import clock, daily, match, ox, plan
from .quiz import list_units

CAP = 1.5                         # 하루 총량 상한 = 설정 × 1.5
MOCK_CAP = 1                      # 모의고사는 하루 1회까지
ADD_OX, ADD_QUIZ = 5, 3           # 약한 단원 복습 추가: 공부일마다 O/X 5개·기출 3문제
CARRY_KINDS = ("note", "ox", "quiz", "mock")      # 복습(review)은 그날 틀린 것 기준이라 넘기지 않는다
KIND_ORDER = {k: i for i, k in enumerate(match.KINDS)}


def _caps(conn):
    d = daily.get_settings(conn)
    return {"note": int(CAP * d["daily_notes"]), "ox": int(CAP * d["daily_ox"]), "quiz": int(CAP * d["daily_questions"]),
            "mock": MOCK_CAP}


def study_days(conn, first):
    """first 부터 시험 전날까지의 공부일(쉬는 요일·'그날 쉬기'·마무리 기간 제외). 시험일이 없으면 ValueError."""
    s = plan.get_settings(conn)
    if not s["exam_day"]:
        raise ValueError("시험일을 먼저 저장하세요.")
    exam = s["exam_day"]
    final_start = exam - s["final_days"] if s["final_days"] else exam
    rest_marked = {r["day"] for r in conn.execute("SELECT day FROM plans WHERE user_id = ? AND kind = 'rest' AND day >= ?", (conn.user_id, first))}
    rest = set(s["rest_days"])
    return [d for d in range(first, final_start) if clock.weekday(d) not in rest and d not in rest_marked]


def _room(conn, days):
    """{일: {종류: 더 담을 수 있는 양}}: 상한 − 그날 계획(넘어온 것·추가한 것 포함)."""
    if not days:
        return {}
    caps, rows = _caps(conn), match.plan_rows_by_day(conn, days[0], days[-1])
    room = {}
    for d in days:
        used = {k: 0 for k in caps}
        for r in rows.get(d, []):
            if r["kind"] in used:
                used[r["kind"]] += r["target"]
        room[d] = {k: max(caps[k] - used[k], 0) for k in caps}
    return room


def _carried_sum(conn):
    return {(r["from_day"], r["kind"], r["unit"]): r["total"] for r in conn.execute(
        "SELECT from_day, kind, unit, SUM(amount) AS total FROM plan_carry WHERE user_id = ? AND source = 'carry' GROUP BY from_day, kind, unit", (conn.user_id,))}


def pending(conn, today=None):
    """밀린 것 목록(원래 날·종류 순): [{day, date, kind, label, unit, short, need, actual, state}]. 넘긴 양은 뺀다."""
    today = clock.today() if today is None else today
    first = conn.execute("SELECT MIN(day) AS d FROM plans WHERE user_id = ?", (conn.user_id,)).fetchone()["d"]
    if first is None or first >= today:
        return []
    done = _carried_sum(conn)
    out = []
    for report in match.report_range(conn, first, today - 1, today):
        if report["state"] not in ("partial", "missed"):
            continue
        for item in report["items"]:
            if item["skipped"] or item["kind"] not in CARRY_KINDS:
                continue
            short = max(item["need"] - item["actual"], 0) - done.get((report["day"], item["kind"], item["unit"]), 0)
            if short > 0:
                out.append({"day": report["day"], "date": report["date"], "kind": item["kind"], "label": item["label"], "unit": item["unit"],
                            "short": short, "need": item["need"], "actual": item["actual"], "state": report["state"]})
    out.sort(key=lambda p: (p["day"], KIND_ORDER[p["kind"]], p["unit"]))
    return out


def summary(conn, today=None):
    """캘린더 맨 위 표시용: 밀린 것 개수와 넘길 첫 공부일."""
    today = clock.today() if today is None else today
    items = pending(conn, today)
    try:
        days = study_days(conn, today)
    except ValueError:
        days = []
    return {"count": len(items), "items": items, "next_date": clock.iso(days[0]) if days else None}


def carry_over(conn, today=None):
    """밀린 것을 다음 공부일들에 넘긴다. {moved: [{date(원래 날), kind, label, unit, amount, to: [{date, amount}]}], unplaced: [...], placed_total, unplaced_total}."""
    today = clock.today() if today is None else today
    items = pending(conn, today)
    days = study_days(conn, today)
    room = _room(conn, days)
    moved, unplaced, writes = [], [], []
    for p in items:
        left, to = p["short"], []
        for d in days:
            put = min(left, room[d][p["kind"]])
            if put > 0:
                room[d][p["kind"]] -= put
                left -= put
                to.append({"date": clock.iso(d), "amount": put})
                writes.append((conn.user_id, "carry", p["day"], p["kind"], p["unit"], d, put))
            if left == 0:
                break
        if to:
            moved.append({"date": p["date"], "kind": p["kind"], "label": p["label"], "unit": p["unit"], "amount": p["short"] - left, "to": to})
        if left:
            unplaced.append({"date": p["date"], "kind": p["kind"], "label": p["label"], "unit": p["unit"], "amount": left})
    with conn:
        for w in writes:                                         # 같은 키가 이미 있으면(같은 날로 다시 담기) 양을 더한다
            conn.execute("""INSERT INTO plan_carry(user_id, source, from_day, kind, unit, to_day, amount) VALUES (?,?,?,?,?,?,?)
                            ON CONFLICT(user_id, source, from_day, kind, unit, to_day) DO UPDATE SET amount = amount + excluded.amount""", w)
    return {"moved": moved, "unplaced": unplaced, "placed_total": sum(m["amount"] for m in moved), "unplaced_total": sum(u["amount"] for u in unplaced),
            "message": ("" if not unplaced else f"시험 전까지 못 담은 것이 {len(unplaced)}개 있습니다. 계획 화면에서 공부일을 늘리거나 하루 분량을 조정하세요.")}


def next_week(today):
    """다음 주(일~토)의 (첫날, 끝날) 일 번호."""
    this_start = today - (clock.weekday(today) + 1) % 7
    return this_start + 7, this_start + 13


def add_review(conn, unit, today=None):
    """약한 단원 unit 의 O/X·기출을 다음 주 공부일들에 더한다. 같은 주·같은 단원은 한 번만(이미 했으면 ValueError)."""
    today = clock.today() if today is None else today
    if unit not in {u["unit"] for u in plan.unit_options(conn)}:
        raise ValueError("없는 단원입니다.")
    start, end = next_week(today)
    if conn.execute("SELECT 1 FROM plan_carry WHERE user_id = ? AND source = 'review' AND from_day = ? AND unit = ? LIMIT 1", (conn.user_id, start, unit)).fetchone():
        raise ValueError("이 단원의 복습은 다음 주 계획에 이미 추가했습니다.")
    days = [d for d in study_days(conn, start) if d <= end]
    if not days:
        raise ValueError("다음 주에는 복습을 더할 공부일이 없습니다(쉬는 날·마무리 기간·시험 뒤).")
    ox_total = {u["unit"]: u["total"] for u in ox.stats(conn)["units"]}.get(unit, 0)
    q_total = {r["unit"]: r["count"] for r in list_units(conn)}.get(unit, 0)
    room, writes, placed = _room(conn, days), [], []
    for d in days:
        for kind, want in (("ox", min(ADD_OX, ox_total)), ("quiz", min(ADD_QUIZ, q_total))):
            put = min(want, room[d][kind])
            if put > 0:
                room[d][kind] -= put
                writes.append((conn.user_id, "review", start, kind, unit, d, put))
                placed.append({"date": clock.iso(d), "kind": kind, "amount": put})
    if not writes:
        raise ValueError("다음 주 공부일의 하루 총량이 가득 차서 복습을 더할 수 없습니다.")
    with conn:
        conn.executemany("INSERT INTO plan_carry(user_id, source, from_day, kind, unit, to_day, amount) VALUES (?,?,?,?,?,?,?)", writes)
    return {"unit": unit, "added": placed, "days": len(days), "total": sum(p["amount"] for p in placed)}
