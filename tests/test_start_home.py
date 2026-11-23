"""로그인 후 첫 화면(시작하기 /start)과 오늘의 공부 카드 순서."""
from pathlib import Path

from test_login import call, login, server  # noqa: F401
from test_ox_review_daily import db  # noqa: F401
from test_plan_calendar import setup_plan
from tutor import auth, clock, daily, plan, records, start, study
from tutor.db import connect
from tutor.web import STATIC_DIR, PAGES, dispatch

STATIC = Path(STATIC_DIR)


def user(db, name="newbie"):
    u = auth.create_user(db, name, "newbie-pass-1")
    db.user_id = u["id"]
    return u


# ------------------------------------------------------------------ 로그인 후 어디로 가나
def test_login_tells_whether_user_has_plan(server):
    base, path = server
    conn = connect(path)
    auth.create_first_admin(conn, "admin", "admin-pass-1")
    mine = auth.create_user(conn, "planner", "planner-pass-1")
    other = auth.create_user(conn, "empty", "empty-pass-1")
    conn.user_id = mine["id"]
    plan.save_settings(conn, {"exam_date": clock.iso(clock.today() + 30)})
    conn.close()
    status, _, _ = login(base, "planner", "planner-pass-1")
    assert status == 200
    assert call(base, "POST", "/api/login", {"username": "planner", "password": "planner-pass-1"})[1]["has_plan"] is True
    assert call(base, "POST", "/api/login", {"username": "empty", "password": "empty-pass-1"})[1]["has_plan"] is False   # 계획이 없으면 로그인 화면이 /start 로 보낸다
    assert "/start" in (STATIC / "login.html").read_text(encoding="utf-8") and PAGES["/start"] == "start.html"


def test_start_overview_uses_bank_numbers_and_roadmap(db):
    data = start.overview(db)
    assert data["has_plan"] is False and len(data["top"]) <= 8 and data["basis"]
    ranks = [r["rank"] for r in data["top"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert [r["unit"] for r in data["top"]] == [r["unit"] for r in study.roadmap(db)[: len(ranks)]]   # roadmap 그대로
    by_subject = {s["subject"]: s for s in data["scope"]}
    assert by_subject["세무회계"]["units"] == db.execute("SELECT COUNT(DISTINCT unit) AS n FROM questions WHERE subject = '세무회계'").fetchone()["n"]
    assert {t["tax"] for t in by_subject["세무회계"]["taxes"]} == {r["tax"] for r in db.execute("SELECT DISTINCT tax FROM questions WHERE subject = '세무회계' AND tax != ''")}
    assert all(s["points_per_round"] > 0 for s in data["scope"])
    status, body = dispatch("GET", "/api/start", {}, {}, db)
    assert status == 200 and body["top"] == data["top"]


def test_start_is_per_user_for_has_plan(db):
    setup_plan(db)
    assert start.overview(db)["has_plan"] is True
    user(db)
    assert start.overview(db)["has_plan"] is False


# ------------------------------------------------------------------ 오늘의 공부 카드
def test_card_order_note_ox_quiz_and_reasons(db):
    card = daily.today_plan(db)
    kinds = [t["kind"] for t in card["tasks"]]
    assert kinds == sorted(kinds, key=daily.ORDER.index) and kinds[0] == "note"
    assert {t["kind"]: t["reason"] for t in card["tasks"]} == {"note": "오늘 단원의 개념을 먼저 읽는다", "ox": "읽은 개념을 제대로 이해했는지 확인한다", "quiz": "실제 시험 문제에 적용한다"}
    assert card["units"] and card["units"][0]["unit"] == card["tasks"][0]["unit"] and card["units"][0]["subject"]


def test_review_row_only_when_something_to_review_and_last(db):
    assert not [t for t in daily.today_plan(db)["tasks"] if t["kind"] == "review"]
    records.save(db, "12-2", "1", False, now=clock.now())
    clock.set_offset(1)
    card = daily.today_plan(db)
    assert card["tasks"][-1]["kind"] == "review" and card["tasks"][-1]["reason"] == "예전에 틀린 문제를 다시 푼다"
    assert [t["kind"] for t in card["tasks"][:-1]] == ["note", "ox", "quiz"]


def test_review_zero_is_not_counted_for_completion(db):
    card = daily.today_plan(db)
    assert card["complete"] is False
    for t in card["tasks"]:
        t["done"] = True
    assert daily.arrange({**card, "tasks": card["tasks"]})["complete"] is True       # 복습이 없어도(0개) 나머지만으로 완료 판단


def test_next_task_is_first_unfinished_and_order_is_not_forced(db):
    card = daily.today_plan(db)
    nxt = [t for t in card["tasks"] if t["next"]]
    assert len(nxt) == 1 and nxt[0] is card["tasks"][0]                          # 아직 아무것도 안 했으면 첫 줄
    study.save_progress(db, card["tasks"][0]["unit"], "read")                  # 노트를 읽으면 다음 줄(O/X)로 넘어간다
    again = daily.today_plan(db)
    assert [t["kind"] for t in again["tasks"] if t["next"]] == ["ox"] and again["tasks"][0]["done"]
    ox_task = next(t for t in again["tasks"] if t["kind"] == "ox")             # 순서를 강제하지 않는다: 기출을 먼저 풀어도 기록되고, 다음 할 일은 첫 미완료 줄 그대로
    for n, row in enumerate(db.execute("SELECT id FROM questions WHERE unit = ?", (ox_task["unit"],)).fetchall()):
        records.save(db, row["id"], str(n + 1), True, source="quiz")
    after = daily.today_plan(db)
    assert next(t for t in after["tasks"] if t["kind"] == "quiz")["done"] and [t["kind"] for t in after["tasks"] if t["next"]] == ["ox"]


def test_planned_card_also_ordered_with_next(db):
    setup_plan(db, rest_days=[])
    plan.generate(db)
    card = daily.today_plan(db)
    kinds = [t["kind"] for t in card["tasks"]]
    assert kinds == sorted(kinds, key=daily.ORDER.index) and sum(t["next"] for t in card["tasks"]) == 1
    assert all(t["need"] > 0 for t in card["tasks"] if t["kind"] == "review")


def test_home_hides_question_box_but_keeps_it_at_ask_tab():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="askBox" hidden' in html and 'id="q"' in html and 'id="ask"' in html          # 기능은 남아 있다
    assert 'name !== "ask"' in html
