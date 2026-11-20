"""계획 ↔ 실제 매칭: 날짜별 계획 항목과 그날 실제 기록을 맞춰 항목별 달성도와 하루 달성률을 낸다.

계산은 match_day 한 함수에서 날짜 하나씩 한다(순수 함수: 계획 줄 + 그날 실제 → 보고). 실제 기록을 모으는 일은 actuals 가 한다.

항목 종류와 '실제'의 뜻
- note   노트: 그날 그 단원을 읽음·이해함으로 표시했으면 1.
- ox     O/X: 그날 그 단원의 O/X 문장을 푼 수(확인만 한 기록 제외).
- quiz   기출: 그날 푼 기출 문항 수(source 'quiz'. 모의고사에서 푼 것은 세지 않는다). 단원이 ''(지정 없음)이면 모든 단원.
- review 복습: 그날 푼 것 중, 앞선 날 이미 틀린 적이 있는 문항·문장 수(같은 문항은 하루 한 번만 센다).
         복습할 수 있는 것(그날 이전에 틀린 적 있는 문항 수)이 목표보다 적으면 목표를 그 수로 낮춰 센다(need). 0 이면 그날 복습 항목은 달성률에서 뺀다(skipped).
- mock   모의고사: 그날 제출한 모의고사 횟수.
항목 달성도 = min(실제 ÷ 목표, 1). 하루 달성률 = 항목 달성도의 평균(항목마다 같은 무게) → % 반올림.

하루 상태: rest(쉬는 날) · exam(시험일) · empty(계획 없음) · future(아직 안 함: 앞으로의 날, 또는 오늘 0%)
          · done(100%) · partial(오늘 1~99%, 지난 날 50~99%) · missed(지난 날 50% 미만).
"""
import json

from . import clock, ox, study

KINDS = ("note", "ox", "quiz", "review", "mock")
LABELS = {"note": "노트", "ox": "O/X", "quiz": "기출", "review": "복습", "mock": "모의고사"}


def _empty_actual():
    return {"notes": [], "ox": {}, "quiz": {}, "review": 0, "mock": 0, "mocks": [],
            "ox_n": 0, "ox_right": 0, "quiz_n": 0, "quiz_right": 0, "reviewable": 0}


def actuals(conn, first, last):
    """first~last(일 번호, 양끝 포함) 날짜별 실제 기록 {일: {...}}. 이 사용자의 기록만 쓴다."""
    out = {d: _empty_actual() for d in range(first, last + 1)}
    ox_unit = {k: v["unit"] for k, v in ox.pool(conn).items()}
    quiz_unit = {r["id"]: r["unit"] for r in conn.execute("SELECT id, unit FROM questions")}
    first_wrong = {}                         # 문항 → 처음 틀린 날
    seen_review = set()
    for r in conn.execute("""SELECT question_id, correct, source, ts FROM records
                             WHERE user_id = ? AND seen_only = 0 AND correct IS NOT NULL ORDER BY ts, id""", (conn.user_id,)):
        day, qid = clock.day_of(r["ts"]), r["question_id"]
        if day in out and r["source"] in ("ox", "quiz"):
            slot = out[day]
            if r["source"] == "ox":
                unit = ox_unit.get(qid[len(ox.PREFIX):]) if qid.startswith(ox.PREFIX) else None
                bucket, n_key, right_key = "ox", "ox_n", "ox_right"
            else:
                unit, bucket, n_key, right_key = quiz_unit.get(qid), "quiz", "quiz_n", "quiz_right"
            if unit:
                slot[bucket][unit] = slot[bucket].get(unit, 0) + 1
            slot[n_key] += 1
            slot[right_key] += r["correct"]
            if qid in first_wrong and first_wrong[qid] < day and (day, qid) not in seen_review:
                seen_review.add((day, qid))
                slot["review"] += 1
        if not r["correct"] and qid not in first_wrong:
            first_wrong[qid] = day
    for day, slot in out.items():            # 복습할 수 있는 것 = 그날 이전에 이미 틀린 적 있는 문항·문장 수
        slot["reviewable"] = sum(1 for d in first_wrong.values() if d < day)
    for r in conn.execute("SELECT unit, updated FROM study_progress WHERE user_id = ? AND status != ''", (conn.user_id,)):
        day = clock.day_of(r["updated"])
        if day in out:
            out[day]["notes"].append(r["unit"])
    for r in conn.execute("SELECT taken_at, score, max_score FROM mock_results WHERE user_id = ?", (conn.user_id,)):
        day = clock.day_of(r["taken_at"])
        if day in out:
            out[day]["mock"] += 1
            out[day]["mocks"].append({"score": r["score"], "max": r["max_score"]})
    return out


def has_activity(actual):
    return bool(actual["notes"] or actual["ox_n"] or actual["quiz_n"] or actual["mock"])


def _item_actual(kind, unit, actual):
    if kind == "note":
        return int(unit in actual["notes"])
    if kind in ("ox", "quiz"):
        return actual[kind].get(unit, 0) if unit else actual[kind + "_n"]
    return actual[kind]


def summarize(rows):
    """계획 줄 → 한 줄 요약. 같은 단원 항목을 묶는다: '유형자산 노트·O/X 20·기출 5 / 복습 10'."""
    if any(r["kind"] == "rest" for r in rows):
        return "쉬는 날"
    groups, order = {}, []
    for r in rows:
        name = r["unit"] if r["kind"] in ("note", "ox", "quiz") else ""
        if name not in groups:
            groups[name] = []
            order.append(name)
        part = LABELS[r["kind"]] if r["kind"] == "note" else f"{LABELS[r['kind']]} {r['target']}"
        if r["kind"] == "quiz" and not r["unit"]:
            part = f"기출 {r['target']}(단원 무관)"
        groups[name].append((KINDS.index(r["kind"]), part))
    pieces = []
    for name in sorted(order, key=lambda n: (n == "", order.index(n))):
        parts = "·".join(p for _, p in sorted(groups[name]))
        pieces.append(f"{name} {parts}".strip())
    return " / ".join(pieces)


def match_day(rows, actual, day, today, weekday_rest=False, exam_day=None):
    """날짜 하나의 보고. rows: 그날 계획 줄 [{kind, unit, target, edited}], actual: 그날 실제(actuals 의 값)."""
    plan_rows = [r for r in rows if r["kind"] != "rest"]
    base = {"day": day, "date": clock.iso(day), "weekday": clock.weekday(day), "items": [], "pct": None,
            "edited": any(r["edited"] for r in rows), "summary": summarize(rows) if rows else "", "actual": actual}
    if day == exam_day:
        return {**base, "state": "exam", "summary": "시험일"}
    if any(r["kind"] == "rest" for r in rows) or (not rows and weekday_rest):
        return {**base, "state": "rest", "summary": "쉬는 날"}
    if not plan_rows:
        return {**base, "state": "empty"}
    items = []
    for r in plan_rows:
        have = _item_actual(r["kind"], r["unit"], actual)
        need = min(r["target"], actual["reviewable"]) if r["kind"] == "review" else r["target"]
        items.append({"kind": r["kind"], "label": LABELS[r["kind"]], "unit": r["unit"], "target": r["target"], "need": need, "actual": have,
                      "skipped": need == 0, "pct": None if need == 0 else round(min(have / need, 1.0), 3), "edited": bool(r["edited"])})
    counted = [i["pct"] for i in items if i["pct"] is not None]
    pct = round(100 * sum(counted) / len(counted)) if counted else 100
    if day > today:
        state = "future"
    elif pct >= 100:
        state = "done"
    elif day == today:
        state = "partial" if pct > 0 else "future"
    else:
        state = "partial" if pct >= 50 else "missed"
    return {**base, "state": state, "pct": pct, "items": items}


def plan_rows_by_day(conn, first, last):
    rows = {}
    for r in conn.execute("SELECT day, kind, unit, target, edited FROM plans WHERE user_id = ? AND day BETWEEN ? AND ? ORDER BY day, kind, unit",
                          (conn.user_id, first, last)):
        rows.setdefault(r["day"], []).append(dict(r))
    return rows


def report_range(conn, first, last, today=None):
    """first~last 날짜별 보고 목록(설정의 쉬는 요일·시험일 반영)."""
    from . import plan
    today = clock.today() if today is None else today
    settings = plan.get_settings(conn)
    rest_days = set(settings["rest_days"])
    exam = settings["exam_day"]
    rows, act = plan_rows_by_day(conn, first, last), actuals(conn, first, last)
    return [match_day(rows.get(d, []), act[d], d, today, clock.weekday(d) in rest_days, exam) for d in range(first, last + 1)]


def report(conn, day, today=None):
    return report_range(conn, day, day, today)[0]


def details(actual):
    """날짜 상세에 보여 줄 실제 기록 요약: 푼 문항·O/X 정오·읽은 노트·모의고사 점수."""
    return {"notes": actual["notes"], "quiz": {"n": actual["quiz_n"], "right": actual["quiz_right"]},
            "ox": {"n": actual["ox_n"], "right": actual["ox_right"]}, "mocks": actual["mocks"], "review": actual["review"]}
