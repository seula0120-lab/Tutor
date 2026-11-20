"""오늘의 공부: 첫 화면 맨 위 카드. 오늘 할 것 · 완료 표시 · 연속 공부 일수 · 지난 7일 기록.

오늘 할 것
- 복습: 복습일이 된 틀린 문항·문장(review). 남은 것이 없으면 완료.
- 단원마다(하루 노트 수만큼): ① 노트 읽기 ② O/X ③ 기출. O/X·기출 개수는 하루 전체 목표를 그날 단원들에 나눈 몫이다(plan.split). 단원은 복귀 순서(study.roadmap)에서 노트가 있고 아직 '이해함'이 아닌 앞쪽 단원이며,
  그날 처음 열 때 정해 daily_plan 에 저장해 하루 동안 바뀌지 않는다(중간에 '이해함' 으로 바꿔도 오늘 할 일이 사라지지 않는다).
- 완료는 기록에서 계산한다(체크 버튼 없음): 노트는 오늘 읽음·이해함으로 표시, O/X 와 기출은 오늘 푼 수가 분량(단원 문항이 적으면 그 수) 이상.
연속 공부 일수 = 풀이 기록이 있거나 단원 진도를 표시한 날이 이어진 일수(오늘 아직 안 했으면 어제까지 센다).
"""
import json

from . import clock, match, ox, plan, review, study
from .quiz import list_units

DEFAULTS = {"daily_notes": 1, "daily_ox": 20, "daily_questions": 5}
LIMITS = {"daily_notes": (1, 5), "daily_ox": (5, 50), "daily_questions": (1, 30)}
LABELS = {"daily_notes": "하루 노트 수", "daily_ox": "하루 O/X 개수", "daily_questions": "하루 기출 개수"}


def get_settings(conn):
    out = dict(DEFAULTS)
    for r in conn.execute("SELECT key, value FROM settings WHERE user_id = ?", (conn.user_id,)):
        if r["key"] in out:
            out[r["key"]] = r["value"]
    return out


def save_settings(conn, values):
    """설정을 저장한다. 범위를 벗어나거나 숫자가 아니면 ValueError."""
    clean = {}
    for key, (low, high) in LIMITS.items():
        if key not in values:
            continue
        try:
            number = int(values[key])
        except (TypeError, ValueError):
            raise ValueError(f"{LABELS[key]}는 숫자여야 합니다.")
        if not low <= number <= high:
            raise ValueError(f"{LABELS[key]}는 {low}~{high} 사이여야 합니다.")
        clean[key] = number
    with conn:
        for key, number in clean.items():
            conn.execute("INSERT INTO settings(user_id, key, value) VALUES (?,?,?) ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", (conn.user_id, key, number))
    return get_settings(conn)


def plan_units(conn, today, notes):
    """오늘 공부할 단원 이름 목록(notes 개). 이미 정한 것은 유지하고 모자라면 복귀 순서에서 채운다."""
    row = conn.execute("SELECT units FROM daily_plan WHERE user_id = ? AND day = ?", (conn.user_id, today)).fetchone()
    units = json.loads(row["units"]) if row else []
    if len(units) < notes:
        for r in study.roadmap(conn):
            if len(units) >= notes:
                break
            if r["has_note"] and r["status"] != "understood" and r["unit"] not in units:
                units.append(r["unit"])
    units = units[:notes]
    with conn:
        conn.execute("INSERT INTO daily_plan(user_id, day, units) VALUES (?,?,?) ON CONFLICT(user_id, day) DO UPDATE SET units=excluded.units", (conn.user_id, today, json.dumps(units, ensure_ascii=False)))
    return units


def _day_range(today):
    """오늘 하루의 시각 범위 [시작, 끝) epoch 초. 날짜 문자열을 거치지 않고 일 번호의 로컬 자정으로 구한다."""
    from datetime import datetime, time as dtime, date
    start = datetime.combine(date.fromordinal(today), dtime.min).timestamp()
    return start, datetime.combine(date.fromordinal(today + 1), dtime.min).timestamp()


def _solved_today(conn, today, source_sql, unit_of):
    """오늘 푼 기록 수(확인만 한 기록 제외). unit_of(question_id) 가 단원 이름을 돌려준다."""
    start, end = _day_range(today)
    counts = {}
    for r in conn.execute(f"SELECT question_id FROM records WHERE user_id = ? AND seen_only = 0 AND correct IS NOT NULL AND ts >= ? AND ts < ? AND {source_sql}", (conn.user_id, start, end)):
        unit = unit_of(r["question_id"])
        if unit:
            counts[unit] = counts.get(unit, 0) + 1
    return counts


def _planned_card(conn, today, settings, due):
    """계획(/plan)이 있으면 그날 계획을 카드로 보여 준다(plans 표 + match 의 실제 대조). 계획 없는 날이면 None."""
    if not plan.configured(conn):
        return None
    report = match.report(conn, today, today)
    if report["state"] in ("empty",):
        return None
    base = {"day": today, "date": clock.iso(today), "settings": settings, "plan": True, "state": report["state"], "pct": report["pct"],
            "review": {k: due[k] for k in ("due_count", "waiting", "done", "intervals")}}
    if report["state"] in ("rest", "exam"):
        return {**base, "tasks": [], "complete": True, "rest": True, "message": "오늘은 시험일입니다." if report["state"] == "exam" else "오늘은 쉬는 날입니다."}
    tasks = []
    for item in report["items"]:
        unit, kind = item["unit"], item["kind"]
        subject, tax = (study.find_unit(conn, unit)[:2] if unit else ("", ""))
        need, have = item["need"], item["actual"]
        shown = f"({min(have, need)}/{need})"
        detail = {"note": f"{unit} 노트 읽기(읽음·이해함 표시)", "ox": f"{unit} O/X {need}개 {shown}",
                  "quiz": f"{unit or '단원 무관'} 기출 {need}문제 {shown}",
                  "review": f"복습 {need}개 {shown}" if need else "오늘 복습할 것이 없습니다.",
                  "mock": f"모의고사 {need}회 {shown}"}[kind]
        tasks.append({"key": f"{kind}:{unit}", "kind": kind, "label": item["label"], "unit": unit, "subject": subject, "tax": tax,
                      "need": need, "have": have, "done": have >= need, "detail": detail})
    return {**base, "tasks": tasks, "complete": all(t["done"] for t in tasks), "rest": False}


def today_plan(conn, today=None):
    """오늘의 공부 카드: 복습·단원별 할 일과 완료 여부. 계획(/plan)이 있으면 그날 계획이 우선한다."""
    today = clock.today() if today is None else today
    settings = get_settings(conn)
    due = review.summary(conn, today)
    planned = _planned_card(conn, today, settings, due)
    if planned is not None:
        return planned
    units = plan_units(conn, today, settings["daily_notes"])
    info = {u: study.find_unit(conn, u) for u in units}
    ox_pool, ox_stats = ox.pool(conn), ox.stats(conn)["units"]
    ox_total = {u["unit"]: u["total"] for u in ox_stats}
    q_total = {r["unit"]: r["count"] for r in list_units(conn)}
    unit_of_question = {r["id"]: r["unit"] for r in conn.execute("SELECT id, unit FROM questions")}
    ox_done = _solved_today(conn, today, "source = 'ox'",
                            lambda qid: (ox_pool.get(qid[len(ox.PREFIX):]) or {}).get("unit"))
    quiz_done = _solved_today(conn, today, "source IN ('quiz', 'mock')", unit_of_question.get)
    start, end = _day_range(today)
    noted = {r["unit"] for r in conn.execute("SELECT unit FROM study_progress WHERE user_id = ? AND status != '' AND updated >= ? AND updated < ?", (conn.user_id, start, end))}

    tasks = [{"key": "review", "kind": "review", "label": "복습", "unit": "", "need": due["due_count"], "have": 0,
              "done": due["due_count"] == 0, "detail": (f"오늘 복습할 문항·문장 {due['due_count']}개" if due["due_count"] else "오늘 복습할 것이 없습니다.")}]
    ox_share, q_share = plan.split(settings["daily_ox"], len(units)), plan.split(settings["daily_questions"], len(units))
    for unit, share_ox, share_q in zip(units, ox_share, q_share):          # 하루 분량은 '하루 전체 목표': 오늘 단원들에 나눠 담는다
        subject, tax, _ = info[unit]
        need_ox = min(share_ox, ox_total.get(unit, 0))
        need_q = min(share_q, q_total.get(unit, 0))
        have_ox, have_q = ox_done.get(unit, 0), quiz_done.get(unit, 0)
        tasks += [
            {"key": f"note:{unit}", "kind": "note", "label": "노트", "unit": unit, "subject": subject, "tax": tax, "need": 1, "have": int(unit in noted),
             "done": unit in noted, "detail": f"{unit} 노트 읽기(읽음·이해함 표시)"},
            {"key": f"ox:{unit}", "kind": "ox", "label": "O/X", "unit": unit, "subject": subject, "tax": tax, "need": need_ox, "have": have_ox,
             "done": have_ox >= need_ox, "detail": f"{unit} O/X {need_ox}개 ({min(have_ox, need_ox)}/{need_ox})"},
            {"key": f"quiz:{unit}", "kind": "quiz", "label": "기출", "unit": unit, "subject": subject, "tax": tax, "need": need_q, "have": have_q,
             "done": have_q >= need_q, "detail": f"{unit} 기출 {need_q}문제 ({min(have_q, need_q)}/{need_q})"}]
    return {"day": today, "date": clock.iso(today), "tasks": tasks, "complete": all(t["done"] for t in tasks), "settings": settings, "plan": False,
            "review": {k: due[k] for k in ("due_count", "waiting", "done", "intervals")}}


def _activity_days(conn):
    days = {clock.day_of(r["ts"]) for r in conn.execute("SELECT ts FROM records WHERE user_id = ?", (conn.user_id,))}
    days |= {clock.day_of(r["updated"]) for r in conn.execute("SELECT updated FROM study_progress WHERE user_id = ? AND status != ''", (conn.user_id,))}
    return days


def streak(conn, today=None):
    """연속 공부 일수(오늘 아직 안 했으면 어제까지)."""
    today = clock.today() if today is None else today
    days = _activity_days(conn)
    day = today if today in days else today - 1
    count = 0
    while day in days:
        count += 1
        day -= 1
    return count


def week(conn, today=None):
    """지난 7일(오늘 포함, 오래된 날 먼저): 날마다 O/X 와 기출의 푼 수·맞힌 수·정답률(푼 것이 없으면 None)."""
    today = clock.today() if today is None else today
    rows = {d: {"ox": [0, 0], "quiz": [0, 0]} for d in range(today - 6, today + 1)}
    start, _ = _day_range(today - 6)
    for r in conn.execute("SELECT source, correct, ts FROM records WHERE user_id = ? AND seen_only = 0 AND correct IS NOT NULL AND ts >= ?", (conn.user_id, start)):
        day = clock.day_of(r["ts"])
        if day in rows:
            slot = rows[day]["ox" if r["source"] == "ox" else "quiz"]
            slot[0] += 1
            slot[1] += r["correct"]
    rate = lambda s: round(s[1] / s[0], 3) if s[0] else None
    return [{"date": clock.iso(d), "ox": {"n": v["ox"][0], "right": v["ox"][1], "rate": rate(v["ox"])},
             "quiz": {"n": v["quiz"][0], "right": v["quiz"][1], "rate": rate(v["quiz"])}} for d, v in rows.items()]


def today_card(conn):
    plan = today_plan(conn)
    return {**plan, "streak": streak(conn, plan["day"]), "week": week(conn, plan["day"])}
