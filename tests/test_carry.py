"""이월(밀린 것 넘기기)·주간 돌아보기·약한 단원 복습 추가."""
import pytest

from test_ox_review_daily import db  # noqa: F401
from test_plan_calendar import all_days, rows, setup_plan
from tutor import auth, carry, clock, daily, match, plan, records, schedule, weekly
from tutor.web import dispatch


def miss_a_day(db, **extra):
    """계획을 만들고 아무것도 안 한 채 이틀을 보낸다. 반환: (처음 날, 오늘)."""
    first = setup_plan(db, rest_days=[], **extra)
    plan.generate(db)
    clock.set_offset(2)
    return first, clock.today()


def pending_map(db):
    return {(p["day"], p["kind"], p["unit"]): p["short"] for p in carry.pending(db)}


def test_shortfall_is_need_minus_actual(db):
    first, _ = miss_a_day(db)
    day_rows = [r for r in rows(db, first) if r["kind"] in ("ox", "quiz", "note")]
    got = pending_map(db)
    for r in day_rows:
        assert got[(first, r["kind"], r["unit"])] == r["target"]               # 하나도 안 했으면 목표 전부가 밀림
    unit = next(r["unit"] for r in day_rows if r["kind"] == "ox")
    from test_plan_calendar import do_note_ox_quiz
    do_note_ox_quiz(db, [{"kind": "ox", "unit": unit, "target": 1}])         # 이미 지난 날은 못 고치므로 오늘 한 것은 오늘 몫
    assert pending_map(db)[(first, "ox", unit)] == next(r["target"] for r in day_rows if r["kind"] == "ox" and r["unit"] == unit)


def test_carry_moves_shortfall_to_next_study_day_and_keeps_origin(db):
    first, today = miss_a_day(db)
    before_origin = rows(db, first)
    before_today = {(r["kind"], r["unit"]): r["target"] for r in rows(db, today)}
    short = pending_map(db)
    result = carry.carry_over(db)
    assert result["placed_total"] > 0
    assert rows(db, first) == before_origin                                    # 원래 날의 계획은 그대로
    assert schedule.day_detail(db, first)["state"] == "missed"                  # 원래 날의 상태·실적도 그대로
    items = {(i["kind"], i["unit"]): i for i in schedule.day_detail(db, today)["items"]}
    carried = sum(i["carried"] for i in items.values())
    assert carried > 0 and all(set(i["carried_from"]) <= {clock.iso(first), clock.iso(first + 1)} for i in items.values() if i["carried"])
    for (kind, unit), i in items.items():
        assert i["target"] == before_today.get((kind, unit), 0) + i["carried"] + i["added"]
    assert sum(short.values()) == result["placed_total"] + result["unplaced_total"]


def test_carry_is_idempotent(db):
    miss_a_day(db)
    first_run = carry.carry_over(db)
    snapshot = [tuple(r) for r in db.execute("SELECT * FROM plan_carry WHERE user_id = ? ORDER BY 2,3,4,5,6", (db.user_id,))]
    again = carry.carry_over(db)
    assert again["placed_total"] == 0 and again["moved"] == []
    assert [tuple(r) for r in db.execute("SELECT * FROM plan_carry WHERE user_id = ? ORDER BY 2,3,4,5,6", (db.user_id,))] == snapshot
    assert first_run["placed_total"] > 0 and carry.summary(db)["count"] == first_run["unplaced_total"] and carry.summary(db)["count"] == len(first_run["unplaced"])


def test_carry_spills_over_1_5x_cap(db):
    daily.save_settings(db, {"daily_ox": 10, "daily_notes": 2, "daily_questions": 4})
    first, today = miss_a_day(db)
    carry.carry_over(db)
    caps = carry._caps(db)
    assert caps["ox"] == 15
    to_days = {r["to_day"] for r in db.execute("SELECT to_day FROM plan_carry WHERE user_id = ?", (db.user_id,))}
    for d in to_days:                                                           # 넘어온 날은 어느 종류도 1.5배를 넘지 않는다
        for kind in ("ox", "quiz", "note"):
            assert sum(r["target"] for r in match.plan_rows_by_day(db, d, d).get(d, []) if r["kind"] == kind) <= caps[kind]
    days_used = {r["to_day"] for r in db.execute("SELECT to_day FROM plan_carry WHERE user_id = ?", (db.user_id,))}
    assert len(days_used) >= 2                                                  # 하루에 다 못 담아 다음 공부일로 넘침


def test_carry_skips_rest_weekdays_and_final_period(db):
    today = clock.today()
    exam = today + 12
    plan.save_settings(db, {"exam_date": clock.iso(exam), "rest_days": [clock.weekday(today + 3)], "final_days": 5, "review_per_day": 10})
    plan.generate(db)
    clock.set_offset(2)
    days = carry.study_days(db, clock.today())
    assert days and max(days) == exam - 6                                        # 마무리 5일(exam-5~exam-1)은 빠진다
    assert today + 3 not in days and all(clock.weekday(d) != clock.weekday(today + 3) for d in days)
    plan.edit_day(db, today + 4, rest=True)
    assert today + 4 not in carry.study_days(db, clock.today())                  # '그날 쉬기'도 뺀다
    carry.carry_over(db)
    to_days = {r["to_day"] for r in db.execute("SELECT to_day FROM plan_carry WHERE user_id = ?", (db.user_id,))}
    assert to_days and to_days <= set(carry.study_days(db, clock.today()))


def test_unplaceable_items_stay_pending_and_alert(db):
    today = clock.today()
    plan.save_settings(db, {"exam_date": clock.iso(today + 7), "rest_days": [], "final_days": 5, "review_per_day": 10})
    plan.generate(db)
    clock.set_offset(2)                                                          # 오늘 = 시험 6일 전 → 공부일 없음(마무리 기간)
    summary = carry.summary(db)
    assert summary["count"] > 0 and summary["next_date"] is None
    result = carry.carry_over(db)
    assert result["placed_total"] == 0 and result["unplaced_total"] > 0 and "못 담은" in result["message"]
    assert carry.summary(db)["count"] == summary["count"]


def test_card_marks_items_carried_from_yesterday(db):
    first = setup_plan(db, rest_days=[])
    plan.generate(db)
    clock.set_offset(1)                                                          # 첫날을 통째로 놓친 다음 날
    carry.carry_over(db)
    card = daily.today_plan(db)
    carried = [t for t in card["tasks"] if t["carried"]]
    assert carried and all(t["carried_note"] == "어제에서 넘어옴" for t in carried)
    assert all(not t["carried"] and t["carried_note"] == "" for t in card["tasks"] if t not in carried)
    clock.set_offset(2)                                                          # 이틀 전에서 넘어온 것은 날짜로 표시
    assert daily._carried_note([clock.iso(first)], clock.today()).endswith("에서 넘어옴") and "어제" not in daily._carried_note([clock.iso(first)], clock.today())


def test_carry_is_per_user(db):
    miss_a_day(db)
    carry.carry_over(db)
    mine = db.execute("SELECT COUNT(*) AS n FROM plan_carry WHERE user_id = ?", (db.user_id,)).fetchone()["n"]
    other = auth.create_user(db, "second", "second-pass-1")
    db.user_id = other["id"]
    assert carry.pending(db) == [] and carry.summary(db)["count"] == 0
    assert weekly.weak_units(db, clock.today())["weak"] == []
    db.user_id = 0
    assert db.execute("SELECT COUNT(*) AS n FROM plan_carry WHERE user_id = 0").fetchone()["n"] == mine


# ------------------------------------------------------------------ 주간 돌아보기
def solve(db, unit, right, total):
    """unit 의 문항을 돌려 가며 total 번 풀어 right 번 맞힌다(선택 보기를 달리해 중복 기록 제거를 피한다)."""
    ids = [r["id"] for r in db.execute("SELECT id FROM questions WHERE unit = ?", (unit,))]
    for n in range(total):
        records.save(db, ids[n % len(ids)], str(n + 1), n < right)


def test_weak_units_need_five_solves_and_few_are_separate(db):
    solve(db, "자본", 1, 5)                  # 1/5 = 20%
    solve(db, "근로소득·연말정산", 5, 5)       # 5/5
    solve(db, "유형자산", 0, 4)               # 0/4: 표본 부족(정답률을 내지 않는다)
    result = weekly.weak_units(db, clock.today())
    assert [(w["unit"], w["n"], w["rate"]) for w in result["weak"]] == [("자본", 5, 0.2), ("근로소득·연말정산", 5, 1.0)]
    assert result["insufficient"] == [{"unit": "유형자산", "n": 4}]
    assert "rate" not in result["insufficient"][0]


def test_weak_units_are_capped_at_three(db):
    for unit, right in (("자본", 0), ("근로소득·연말정산", 1), ("영세율·면세", 2), ("유형자산", 3)):
        solve(db, unit, right, 5)
    weak = weekly.weak_units(db, clock.today())["weak"]
    assert [w["unit"] for w in weak] == ["자본", "근로소득·연말정산", "영세율·면세"]


def test_old_records_fall_out_of_the_14_day_window(db):
    solve(db, "자본", 0, 5)
    assert weekly.weak_units(db, clock.today())["weak"]
    clock.set_offset(14)
    assert weekly.weak_units(db, clock.today())["weak"] == [] and weekly.weak_units(db, clock.today())["insufficient"] == []


def test_review_week_numbers(db):
    first, today = miss_a_day(db)
    unit = "자본"
    solve(db, unit, 3, 4)
    data = weekly.review_week(db)
    this, last = data["weeks"]
    assert this["label"] == "이번 주" and last["label"] == "지난주" and this["from"] <= clock.iso(today) <= this["to"]
    assert clock.weekday(clock.parse_iso(this["from"])) == 6                      # 일요일 시작
    total = this["quiz"]["n"] + last["quiz"]["n"]
    assert total == 4 and (this["quiz"]["right"] + last["quiz"]["right"]) == 3
    row = next(u for w in data["weeks"] for u in w["units"] if u["unit"] == unit)
    assert row["enough"] is False and row["rate"] == 0.75                         # 4문제는 표에는 있으나 '표본 부족'으로 표시


def test_add_review_places_ox_and_quiz_next_week_once(db):
    first, today = miss_a_day(db)
    unit = "자본"
    result = carry.add_review(db, unit)
    start, end = carry.next_week(today)
    assert result["total"] > 0 and all(start <= clock.parse_iso(a["date"]) <= end for a in result["added"]) and {a["kind"] for a in result["added"]} <= {"ox", "quiz"}
    items = [i for d in range(start, end + 1) for i in schedule.day_detail(db, d)["items"] if i["unit"] == unit and i["added"]]
    assert items and sum(i["added"] for i in items) == result["total"]
    with pytest.raises(ValueError):
        carry.add_review(db, unit)                                                # 같은 주·같은 단원은 한 번만
    with pytest.raises(ValueError):
        carry.add_review(db, "없는 단원")


def test_carry_and_review_week_api(db):
    miss_a_day(db)
    status, body = dispatch("GET", "/api/carry", {}, {}, db)
    assert status == 200 and body["count"] > 0 and body["next_date"]
    status, body = dispatch("POST", "/api/carry", {}, {}, db)
    assert status == 200 and body["result"]["placed_total"] > 0
    status, body = dispatch("GET", "/api/review-week", {}, {}, db)
    assert status == 200 and len(body["weeks"]) == 2 and "weak" in body and "insufficient" in body
    status, body = dispatch("POST", "/api/review-week/add", {}, {"unit": "없는 단원"}, db)
    assert status == 400
    assert dispatch("GET", "/api/calendar", {"month": clock.iso(clock.today())[:7]}, {}, db)[1]["header"]["carry"]["count"] >= 0
