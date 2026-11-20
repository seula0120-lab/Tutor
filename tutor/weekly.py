"""주간 돌아보기: 이번 주·지난주의 계획 달성률·공부한 날 수·O/X·기출 정답률·단원별 정답률, 그리고 약한 단원 3개.

주는 일요일부터 토요일(캘린더 격자와 같다). 이번 주는 오늘까지만 센다.
정답률은 '확인만 한 기록'과 모의고사를 뺀 O/X·기출 풀이(records 의 source ox·quiz)로 계산한다. 푼 게 없으면 정답률은 None(지어내지 않는다).
약한 단원: 최근 14일(오늘 포함) 단원별 풀이가 5문제 이상인 단원 중 정답률 낮은 순 3개(같으면 푼 수가 많은 쪽 먼저).
풀이가 1~4문제인 단원은 '표본 부족'으로 따로 보이고 정답률을 내지 않는다.
날짜는 clock.py 만, 기록은 이 사용자의 것만 쓴다.
"""
from . import clock, match, ox

WINDOW_DAYS = 14
MIN_SAMPLE = 5
WEAK_COUNT = 3


def week_start(day):
    return day - (clock.weekday(day) + 1) % 7


def unit_results(conn, first, last):
    """first~last(일 번호) 단원별 O/X·기출 풀이 {단원: {n, right, ox_n, ox_right, quiz_n, quiz_right}}. 단원을 모르는 기록은 뺀다."""
    ox_unit = {k: v["unit"] for k, v in ox.pool(conn).items()}
    quiz_unit = {r["id"]: r["unit"] for r in conn.execute("SELECT id, unit FROM questions")}
    start, _ = clock.day_range(first)
    _, end = clock.day_range(last)
    out = {}
    for r in conn.execute("""SELECT question_id, correct, source FROM records WHERE user_id = ? AND seen_only = 0 AND correct IS NOT NULL
                             AND source IN ('ox', 'quiz') AND ts >= ? AND ts < ?""", (conn.user_id, start, end)):
        qid = r["question_id"]
        unit = ox_unit.get(qid[len(ox.PREFIX):]) if r["source"] == "ox" and qid.startswith(ox.PREFIX) else quiz_unit.get(qid) if r["source"] == "quiz" else None
        if not unit:
            continue
        slot = out.setdefault(unit, {"n": 0, "right": 0, "ox_n": 0, "ox_right": 0, "quiz_n": 0, "quiz_right": 0})
        slot["n"] += 1
        slot["right"] += r["correct"]
        slot[r["source"] + "_n"] += 1
        slot[r["source"] + "_right"] += r["correct"]
    return out


def _rate(right, n):
    return round(right / n, 3) if n else None


def _week(conn, label, first, last, today):
    reports = match.report_range(conn, first, last, today)
    acts = match.actuals(conn, first, last)
    counted = [r["pct"] for r in reports if r["pct"] is not None and r["day"] <= today]
    units = unit_results(conn, first, last)
    totals = {k: sum(u[k] for u in units.values()) for k in ("ox_n", "ox_right", "quiz_n", "quiz_right")}
    rows = [{"unit": name, "n": u["n"], "right": u["right"], "rate": _rate(u["right"], u["n"]), "enough": u["n"] >= MIN_SAMPLE} for name, u in units.items()]
    rows.sort(key=lambda r: (r["rate"], -r["n"], r["unit"]))
    return {"label": label, "from": clock.iso(first), "to": clock.iso(last),
            "plan_pct": round(sum(counted) / len(counted)) if counted else None, "plan_days": len(counted),
            "study_days": sum(1 for d in range(first, last + 1) if match.has_activity(acts[d])),
            "ox": {"n": totals["ox_n"], "right": totals["ox_right"], "rate": _rate(totals["ox_right"], totals["ox_n"])},
            "quiz": {"n": totals["quiz_n"], "right": totals["quiz_right"], "rate": _rate(totals["quiz_right"], totals["quiz_n"])},
            "units": rows}


def weak_units(conn, today):
    """{weak: [{unit, n, right, rate}] 최대 3개, insufficient: [{unit, n}] 표본 부족, window: {from, to}}."""
    first = today - WINDOW_DAYS + 1
    units = unit_results(conn, first, today)
    enough = [{"unit": name, "n": u["n"], "right": u["right"], "rate": _rate(u["right"], u["n"])} for name, u in units.items() if u["n"] >= MIN_SAMPLE]
    enough.sort(key=lambda r: (r["rate"], -r["n"], r["unit"]))
    few = sorted(({"unit": name, "n": u["n"]} for name, u in units.items() if u["n"] < MIN_SAMPLE), key=lambda r: (-r["n"], r["unit"]))
    return {"weak": enough[:WEAK_COUNT], "insufficient": few, "window": {"from": clock.iso(first), "to": clock.iso(today)}, "min_sample": MIN_SAMPLE}


def review_week(conn, today=None):
    today = clock.today() if today is None else today
    start = week_start(today)
    return {"today": clock.iso(today), "weeks": [_week(conn, "이번 주", start, start + 6, today), _week(conn, "지난주", start - 7, start - 1, today)],
            **weak_units(conn, today)}
