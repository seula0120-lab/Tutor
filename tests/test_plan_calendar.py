"""계획 세우기·계획↔실제 매칭·캘린더·비밀번호: 계획 생성 규칙, 고친 날 보존, 날짜 넘기며 부분→완료, 사용자별 분리."""
import pytest

from test_ox_review_daily import db  # noqa: F401  (문제은행·시계 되돌리기 fixture)
from tutor import auth, clock, daily, match, ox, plan, schedule, study
from tutor.web import dispatch

EXAM_IN = 21


def setup_plan(db, **extra):
    today = clock.today()
    values = {"exam_date": clock.iso(today + EXAM_IN), "rest_days": [6], "final_days": 5, "review_per_day": 10, **extra}
    plan.save_settings(db, values)
    return today


def rows(db, day):
    return [dict(r) for r in db.execute("SELECT kind, unit, target, edited FROM plans WHERE user_id = ? AND day = ? ORDER BY kind, unit", (db.user_id, day))]


def all_days(db):
    return sorted({r["day"] for r in db.execute("SELECT day FROM plans WHERE user_id = ?", (db.user_id,))})


def do_note_ox_quiz(db, day_plan_items):
    """계획 항목대로 오늘 실제로 공부한다(노트 읽음 표시, O/X·기출을 목표만큼)."""
    for item in day_plan_items:
        if item["kind"] == "note":
            study.save_progress(db, item["unit"], "read")
        elif item["kind"] == "ox":
            subject, tax, _ = study.find_unit(db, item["unit"])
            for p in ox.pick(db, subject, tax, item["unit"], item["target"]):
                ox.answer(db, p["key"], "O")
        elif item["kind"] == "quiz":
            from tutor import records
            ids = [r["id"] for r in db.execute("SELECT id FROM questions WHERE unit = ? LIMIT ?", (item["unit"], item["target"]))]
            for qid in ids:
                records.save(db, qid, "1", True)


# ------------------------------------------------------------------ 생성 규칙
def test_settings_validation(db):
    today = clock.today()
    for bad in ({"exam_date": clock.iso(today)}, {"exam_date": "내일"}, {"rest_days": [0, 1, 2, 3, 4, 5, 6]}, {"rest_days": [9]},
                {"final_days": 99}, {"review_per_day": "많이"}):
        with pytest.raises(ValueError):
            plan.save_settings(db, bad)
    plan.save_settings(db, {"exam_date": clock.iso(today + 10)})
    with pytest.raises(ValueError):
        plan.save_settings(db, {"start_date": clock.iso(today + 11)})          # 시작일 >= 시험일
    with pytest.raises(ValueError):
        plan.generate(auth_less(db))                                            # (아래 헬퍼: 시험일 없는 새 사용자)


def auth_less(db):
    other = auth.create_user(db, "nosettings", "nosettings-pass")
    db.user_id = other["id"]
    return db


def test_generate_rules(db):
    today = setup_plan(db)
    result = plan.generate(db)
    exam = today + EXAM_IN
    days = all_days(db)
    assert min(days) == today and max(days) == exam - 1                       # 오늘 ~ 시험 전날
    assert not [d for d in days if clock.weekday(d) == 6]                     # 쉬는 요일에는 계획이 없다
    final = [d for d in days if d >= exam - 5]
    assert final and all({"review"} <= {r["kind"] for r in rows(db, d)} for d in final)
    assert any(r["kind"] == "mock" for d in final for r in rows(db, d))
    assert [r["kind"] for r in rows(db, exam - 1)] == ["review"]               # 시험 전날은 복습만
    assert not [r for d in days if d < exam - 5 for r in rows(db, d) if r["kind"] == "mock"]
    assert result["final_days"] == len(final) and result["to"] == clock.iso(exam - 1)
    assert all(r["edited"] == 0 for d in days for r in rows(db, d))
    first_day = rows(db, min(d for d in days if d < exam - 5))
    assert {r["kind"] for r in first_day} >= {"note", "ox", "quiz", "review"}
    assert next(r for r in first_day if r["kind"] == "review")["target"] == 10


def test_understood_units_go_last_and_notes_not_repeated(db):
    today = setup_plan(db, final_days=0)
    first = study.roadmap(db)
    noted = [r["unit"] for r in first if r["has_note"]]
    assert len(noted) >= 2
    study.save_progress(db, noted[0], "understood")
    plan.generate(db)
    order = [r["unit"] for d in all_days(db) for r in rows(db, d) if r["kind"] == "note"]
    assert order.index(noted[0]) == len(order) - 1                            # '이해함' 단원은 맨 뒤
    assert len(order) == len(set(order)) == len(noted)                        # 노트는 한 단원당 한 번만


def test_cycle_passes_plan_ox_and_quiz_without_notes(db):
    setup_plan(db, final_days=0)
    plan.generate(db)
    noted = [r for r in study.roadmap(db) if r["has_note"]]
    note_days = [d for d in all_days(db) if any(r["kind"] == "note" for r in rows(db, d))]
    later = [d for d in all_days(db) if d > max(note_days)]
    assert later, "남는 날은 노트 없이 O/X·기출을 돈다"
    assert all(not any(r["kind"] == "note" for r in rows(db, d)) and any(r["kind"] in ("ox", "quiz") for r in rows(db, d)) for d in later)
    assert len(noted) == len([1 for d in note_days for r in rows(db, d) if r["kind"] == "note"])


def test_edited_day_survives_regeneration_and_rest_edit(db):
    today = setup_plan(db)
    plan.generate(db)
    target_day = today + 3
    unit = next(r["unit"] for r in rows(db, target_day) if r["kind"] == "ox")
    other = next(u["unit"] for u in plan.unit_options(db) if u["unit"] != unit)
    plan.edit_day(db, target_day, [{"kind": "ox", "unit": other, "target": 7}])
    plan.edit_day(db, today + 4, rest=True)
    plan.generate(db)
    assert rows(db, target_day) == [{"kind": "ox", "unit": other, "target": 7, "edited": 1}]
    assert rows(db, today + 4) == [{"kind": "rest", "unit": "", "target": 0, "edited": 1}]
    assert all(r["edited"] == 0 for r in rows(db, today + 2))
    plan.reset_day(db, target_day)
    plan.generate(db)
    assert all(r["edited"] == 0 for r in rows(db, target_day)) and rows(db, target_day)


@pytest.mark.parametrize("items", [[], [{"kind": "ox", "unit": "", "target": 5}], [{"kind": "ox", "unit": "없는단원", "target": 5}],
                                   [{"kind": "quiz", "unit": "", "target": 0}], [{"kind": "foo", "unit": "", "target": 1}],
                                   [{"kind": "review", "target": 5}, {"kind": "review", "target": 6}]])
def test_edit_day_validation(db, items):
    with pytest.raises(ValueError):
        plan.edit_day(db, clock.today() + 1, items)


def test_regenerate_keeps_today_when_already_studied(db):
    today = setup_plan(db)
    plan.generate(db)
    do_note_ox_quiz(db, rows(db, today))
    before = rows(db, today)
    plan.generate(db)
    assert rows(db, today) == before                                          # 한 일이 있는 오늘은 그대로
    assert all(rows(db, today + 1) for _ in [0])


# ------------------------------------------------------------------ 매칭
def test_match_day_states_and_rate():
    empty = match._empty_actual()
    rows_ = [{"kind": "ox", "unit": "A", "target": 10, "edited": 0}, {"kind": "quiz", "unit": "A", "target": 5, "edited": 0}]
    today = 100000
    actual = {**empty, "ox": {"A": 10}, "ox_n": 10, "quiz": {"A": 1}, "quiz_n": 1}
    r = match.match_day(rows_, actual, today, today)
    assert r["pct"] == 60 and r["state"] == "partial"                         # (1.0 + 0.2) / 2
    assert [i["pct"] for i in r["items"]] == [1.0, 0.2]
    assert match.match_day(rows_, empty, today, today)["state"] == "future"   # 오늘 0% 는 아직
    assert match.match_day(rows_, empty, today - 1, today)["state"] == "missed"
    assert match.match_day(rows_, actual, today - 1, today)["state"] == "partial"   # 지난 날 50% 이상
    done = {**empty, "ox": {"A": 12}, "ox_n": 12, "quiz": {"A": 5}, "quiz_n": 5}
    assert match.match_day(rows_, done, today - 1, today)["state"] == "done"
    assert match.match_day(rows_, empty, today + 1, today)["state"] == "future"
    assert match.match_day([{"kind": "rest", "unit": "", "target": 0, "edited": 1}], empty, today, today)["state"] == "rest"
    assert match.match_day([], empty, today, today, weekday_rest=True)["state"] == "rest"
    assert match.match_day([], empty, today, today)["state"] == "empty"
    assert match.match_day([], empty, today, today, exam_day=today)["state"] == "exam"


def test_review_actual_counts_only_previously_wrong_items(db):
    from tutor import records
    qid = db.execute("SELECT id FROM questions LIMIT 1").fetchone()["id"]
    today = clock.today()
    records.save(db, qid, "9", False)                          # 오늘 처음 틀림: 복습 아님
    assert match.actuals(db, today, today)[today]["review"] == 0
    clock.set_offset(1)
    records.save(db, qid, "1", False)
    records.save(db, qid, "1", False, now=clock.now() + 60)                   # 같은 문항을 하루에 두 번 풀어도 복습은 1
    assert match.actuals(db, today + 1, today + 1)[today + 1]["review"] == 1


def test_summarize():
    got = match.summarize([{"kind": "note", "unit": "유형자산", "target": 1}, {"kind": "ox", "unit": "유형자산", "target": 20},
                           {"kind": "quiz", "unit": "유형자산", "target": 5}, {"kind": "review", "unit": "", "target": 10}])
    assert got == "유형자산 노트·O/X 20·기출 5 / 복습 10"
    assert match.summarize([{"kind": "rest", "unit": "", "target": 0}]) == "쉬는 날"


def test_scenario_partial_done_next_day_new_plan(db):
    today = setup_plan(db, rest_days=[])
    plan.generate(db)
    items = [r for r in rows(db, today) if r["kind"] != "review"]
    assert schedule.day_detail(db, today)["state"] == "future"
    do_note_ox_quiz(db, items[:1])                                            # 일부만
    assert schedule.day_detail(db, today)["state"] == "partial"
    card = daily.today_plan(db)
    assert card["plan"] is True and {t["unit"] for t in card["tasks"] if t["unit"]} == {r["unit"] for r in items if r["unit"]}
    do_note_ox_quiz(db, items[1:])
    detail = schedule.day_detail(db, today)
    assert detail["state"] == "done" and detail["pct"] == 100                 # 복습할 것이 없으면 복습 항목은 뺀다
    assert next(i for i in detail["items"] if i["kind"] == "review")["skipped"] is True
    clock.set_offset(1)
    assert schedule.day_detail(db, today)["state"] == "done"                  # 어제는 완료
    tomorrow = daily.today_plan(db)
    assert tomorrow["plan"] and tomorrow["date"] == clock.iso(today + 1) and tomorrow["tasks"] and tomorrow["complete"] is False


def test_card_shows_rest_day_and_falls_back_without_plan(db):
    assert daily.today_plan(db)["plan"] is False                              # 계획이 없으면 예전 카드
    today = setup_plan(db)
    plan.edit_day(db, today, rest=True)
    card = daily.today_plan(db)
    assert card["rest"] is True and card["complete"] is True and card["tasks"] == []


def test_month_grid_and_header(db):
    today = setup_plan(db, rest_days=[])
    plan.generate(db)
    year, month = (int(x) for x in clock.iso(today).split("-")[:2])
    data = schedule.month(db, year, month)
    assert len(data["days"]) % 7 == 0 and data["days"][0]["weekday"] == 6      # 일요일 시작
    assert data["header"]["dday"] == EXAM_IN and data["header"]["streak"] == 0
    in_month = [d for d in data["days"] if d["in_month"]]
    assert in_month[0]["date"].endswith("-01") and any(d["date"] == clock.iso(today) and d["summary"] for d in in_month)
    assert any(d["state"] == "exam" for d in data["days"] + schedule.month(db, *((year, month + 1) if month < 12 else (year + 1, 1)))["days"])


# ------------------------------------------------------------------ 사용자별 분리·API·비밀번호
def test_plans_are_per_user(db):
    setup_plan(db)
    plan.generate(db)
    mine = len(all_days(db))
    other = auth.create_user(db, "second", "second-pass-1")
    db.user_id = other["id"]
    assert all_days(db) == [] and plan.get_settings(db)["exam_day"] is None and not plan.configured(db)
    assert daily.today_plan(db)["plan"] is False
    db.user_id = 0
    assert len(all_days(db)) == mine


def test_plan_api_routes(db):
    today = clock.today()
    status, body = dispatch("POST", "/api/plan/settings", {}, {"exam_date": clock.iso(today + 14), "rest_days": [5, 6]}, db)
    assert status == 200 and body["settings"]["rest_days"] == [5, 6]
    status, body = dispatch("POST", "/api/plan/generate", {}, {}, db)
    assert status == 200 and body["result"]["study_days"] > 0 and body["days"]
    status, body = dispatch("POST", "/api/plan/day", {}, {"date": clock.iso(today + 2), "items": [{"kind": "mock", "target": 1}]}, db)
    assert status == 200 and body["day"]["edited"] is True and body["day"]["items"][0]["kind"] == "mock"
    assert dispatch("POST", "/api/plan/day", {}, {"date": "bad", "items": []}, db)[0] == 400
    assert dispatch("POST", "/api/plan/settings", {}, {"exam_date": clock.iso(today)}, db)[0] == 400
    status, body = dispatch("GET", "/api/calendar", {"month": clock.iso(today)[:7]}, {}, db)
    assert status == 200 and body["header"]["dday"] == 14
    assert dispatch("GET", "/api/calendar", {"month": "2026-13"}, {}, db)[0] == 400
    status, body = dispatch("GET", "/api/calendar/day", {"date": clock.iso(today)}, {}, db)
    assert status == 200 and "actual" in body["day"] and body["day"]["is_today"]


def test_pages_and_tabs_exist():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / "tutor" / "static"
    for name in ("plan.html", "calendar.html", "account.html"):
        assert (static / name).exists()
    assert '"calendar", "캘린더"' in (static / "quizcard.js").read_text(encoding="utf-8")
    assert 'href="/calendar"' in (static / "index.html").read_text(encoding="utf-8")


def test_change_password_and_admin_reset(db):
    auth.reset_throttle()
    admin = auth.create_user(db, "boss", "boss-pass-1", is_admin=True)
    user = auth.create_user(db, "stud", "stud-pass-1")
    token_here, token_other = auth.create_session(db, user["id"]), auth.create_session(db, user["id"])
    with pytest.raises(auth.LoginError):
        auth.change_password(db, user["id"], "wrong-pass-1", "new-password-1")
    with pytest.raises(ValueError):
        auth.change_password(db, user["id"], "stud-pass-1", "short")
    auth.change_password(db, user["id"], "stud-pass-1", "new-password-1", keep_token=token_here)
    assert auth.authenticate(db, "stud", "new-password-1")
    with pytest.raises(auth.LoginError):
        auth.authenticate(db, "stud", "stud-pass-1")
    assert auth.user_for_token(db, token_here) and auth.user_for_token(db, token_other) is None
    auth.reset_password(db, user["id"], "reset-pass-12")
    assert auth.user_for_token(db, token_here) is None
    assert auth.authenticate(db, "stud", "reset-pass-12")["id"] == user["id"]
    with pytest.raises(ValueError):
        auth.reset_password(db, 9999, "reset-pass-12")
    db.user, db.token = None, ""
    db.user_id = user["id"]
    db.user = auth.list_users(db)[1]
    assert dispatch("POST", "/api/users/password", {}, {"user_id": user["id"], "password": "another-pass-1"}, db)[0] == 403   # 관리자가 아니면 거부
    db.user = {**auth.list_users(db)[0]}
    assert dispatch("POST", "/api/users/password", {}, {"user_id": user["id"], "password": "another-pass-1"}, db)[0] == 200
    assert admin["is_admin"]


def test_review_need_is_capped_by_reviewable_items():
    empty = match._empty_actual()
    rows_ = [{"kind": "review", "unit": "", "target": 10, "edited": 0}]
    today = 100000
    r = match.match_day(rows_, {**empty, "review": 2, "reviewable": 4}, today, today)
    assert r["items"][0]["need"] == 4 and r["pct"] == 50
    r = match.match_day(rows_, {**empty, "reviewable": 0}, today - 1, today)
    assert r["items"][0]["skipped"] is True and r["pct"] == 100 and r["state"] == "done"



def test_regenerate_requeues_notes_not_read_in_past_days(db):
    today = setup_plan(db, rest_days=[], final_days=0)
    plan.generate(db)
    unit = next(r["unit"] for r in rows(db, today) if r["kind"] == "note")
    clock.set_offset(2)                                                      # 이틀 뒤: 그 노트를 읽지 않음
    plan.generate(db)
    later = [r["unit"] for d in all_days(db) if d >= today + 2 for r in rows(db, d) if r["kind"] == "note"]
    assert unit in later
    study.save_progress(db, unit, "read")                                     # 읽은 단원은 다시 담기지 않는다(오늘 기록이 생겨 오늘 계획은 그대로 두고 내일부터 다시 만든다)
    plan.generate(db)
    later = [r["unit"] for d in all_days(db) if d >= today + 3 for r in rows(db, d) if r["kind"] == "note"]
    assert unit not in later
