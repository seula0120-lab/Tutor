"""O/X 퀴즈 · 간격 복습 · 오늘의 공부: 문장 고르기 규칙, 채점·기록, 복습 간격, 날짜 바꿔 끼우기, 오늘 완료."""
import json

import pytest

from conftest import item
from tutor import clock, daily, ox, records, review, study
from tutor.bank import load_bank
from tutor.db import connect
from tutor.web import dispatch


def four(prefix):
    return [f"{prefix} 첫째 보기는 이렇게 처리한다.", f"{prefix} 둘째 보기는 저렇게 계산한다.",
            f"{prefix} 셋째 보기는 따로 구분하여 기록한다.", f"{prefix} 넷째 보기는 아예 인식하지 않는다."]


OLD = [  # 1회: 최신(12회)보다 10회 넘게 앞이라 세무 문장은 '옛 회차'
    item(1, "다음 중 자기주식에 대한 설명으로 옳은 것은?", four("자기주식"), "2", "자기주식 해설."),
    item(12, "다음 중 소득세법상 근로소득에 대한 설명으로 옳은 것은?", four("근로소득"), "1", "근로소득 해설."),
]
NEW = [
    item(11, "다음 중 부가가치세법상 영세율에 대한 설명으로 옳지 않은 것은?", four("영세율"), "3", "영세율 정정 해설."),
    item(2, "다음 중 유형자산의 감가상각에 대한 설명으로 옳은 것은?", four("감가상각"), "4", ""),
    item(13, "다음 중 소득세법상 근로소득에 대한 설명으로 옳은 것은?", four("연말정산"), "1", "연말정산 해설."),
    item(4, "다음 중 자기주식 처분손익의 금액을 계산하면 얼마인가?", ["100원", "200원", "300원", "400원"], "2"),
    item(5, "다음 중 자기주식에 대한 설명으로 옳은 것은?", ["자본", "자산", "부채", "수익"], "1"),   # 조각 보기: 문장 아님
]


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "ox.db")
    load_bank(conn, [(1, OLD), (12, NEW)])
    ox._cache.clear()
    yield conn
    conn.close()
    clock.set_offset(0)


def by_text(conn, fragment):
    return next(i for i in ox.pool(conn).values() if fragment in i["text"])


# ---------------------------------------------------------------- O/X 문장 고르기
def test_pool_takes_right_and_trap_sentences_and_skips_fragments_and_calculation(db):
    pool = ox.pool(db)
    assert all(i["text"].endswith("다.") for i in pool.values())
    assert by_text(db, "영세율 셋째")["truth"] is False       # 옳지 않은 것 문항의 정답 보기 = 틀린 문장
    assert by_text(db, "영세율 첫째")["truth"] is True
    assert by_text(db, "자기주식 둘째")["truth"] is True
    assert not any(i["text"] in ("자본", "자산", "부채", "수익") for i in pool.values())
    assert not any("100원" in i["text"] for i in pool.values())       # 계산형 문항은 뺀다


def test_old_tax_sentences_are_flagged_and_recent_ones_are_not(db):
    assert by_text(db, "근로소득 첫째")["old_tax"] is True and "세법 개정 확인 필요" in by_text(db, "근로소득 첫째")["tax_label"]
    assert by_text(db, "연말정산 첫째")["old_tax"] is False and by_text(db, "연말정산 첫째")["tax_label"] == ""
    assert by_text(db, "자기주식 첫째")["old_tax"] is False            # 재무 문장은 옛 회차여도 표시하지 않는다


def test_pick_puts_recent_tax_sentences_first_and_balances_o_and_x(db):
    picked = ox.pick(db, subject="세무회계", count=6)
    old_flags = [p["old_tax"] for p in picked]
    chosen_old = sum(old_flags)
    recent_available = sum(1 for i in ox.pool(db).values() if i["subject"] == "세무회계" and not i["old_tax"])
    assert chosen_old == max(0, 6 - recent_available)                 # 최근 것이 모자랄 때만 옛 회차로 채운다
    both = ox.pick(db, count=8)
    truths = [ox.pool(db)[p["key"]]["truth"] for p in both]
    assert 0 < sum(truths) < len(truths)
    assert all("truth" not in p and "sources" not in p for p in both)   # 정답은 미리 주지 않는다


def test_pick_limits_to_unit(db):
    unit = by_text(db, "영세율 첫째")["unit"]
    picked = ox.pick(db, unit=unit, count=20)
    assert picked and {p["unit"] for p in picked} == {unit} and len(picked) == 4


def test_answer_grades_records_and_gives_explanation_only_for_x(db):
    trap, right = by_text(db, "영세율 셋째"), by_text(db, "영세율 첫째")
    wrong = ox.answer(db, trap["key"], "O")
    assert wrong["correct"] is False and wrong["truth"] is False and wrong["explanation"] == "영세율 정정 해설."
    assert wrong["sources"] == ["12-11"]
    good = ox.answer(db, right["key"], "O")
    assert good["correct"] is True and good["explanation"] == ""
    row = db.execute("SELECT question_id, choice, correct, source FROM records WHERE question_id = ?", (ox.record_id(trap["key"]),)).fetchone()
    assert tuple(row) == ("ox:" + trap["key"], "O", 0, "ox")
    assert "error" in ox.answer(db, "없는키", "O") and "error" in ox.answer(db, right["key"], "예")


def test_x_sentence_without_official_explanation_gives_none(db):
    rows = db.execute("SELECT id FROM questions WHERE id = '12-2'").fetchall()
    assert rows
    trap = next(i for i in ox.pool(db).values() if i["sources"] == ["12-2"] and not i["truth"])
    assert ox.answer(db, trap["key"], "X")["explanation"] == ""      # '공식 해설 없음' 을 지어내지 않고 비운다


def test_ox_records_do_not_enter_the_notebook(db):
    ox.answer(db, by_text(db, "영세율 셋째")["key"], "O")
    assert records.notebook(db) == []


def test_stats_counts_o_and_x_per_subject(db):
    stats = ox.stats(db)
    assert {s["subject"] for s in stats["subjects"]} == {"재무회계", "세무회계"}
    assert all(s["total"] == s["o"] + s["x"] for s in stats["subjects"])


# ---------------------------------------------------------------- 맥락: 물음 보이기·자료 의존 문장 빼기
Q_82_8 = ("종합원가계산 하에서, 평균법에 의한 경우 당기제품 제조원가가 다음과 같을 때 선입선출법을 적용할 경우와 비교한 설명으로 올바른 것은? "
          "ㆍ기초재공품 : 0개 ㆍ당기착수량 : 10,000개 ㆍ완성품 : 7,000개 ㆍ기말재공품 : 3,000개(완성도 50%) ㆍ당기제품제조원가 : 1,050,000원")
Q_81_1 = ("2018년에 개업한 ㈜세무의 기말재고자산 평가와 관련하여 다음 자료로 인하여 재무제표에 미치는 영향에 대한 설명으로 틀린 것은? "
          "1. 기말재고자산 수량을 검토한 결과 감모 손실이 1,000,000원 발생하였으며 감모 손실의 90%는 정상적인 것이다.")


def test_display_stem_hides_the_verdict_but_keeps_the_topic():
    for question, expected in (("다음 중 현금흐름표에 대한 설명으로 옳지 않은 것은?", "다음 중 현금흐름표에 대한 설명으로 …"),
                               ("다음 중 소득세법상 종합소득공제에 대한 설명으로 가장 옳은 것은?", "다음 중 소득세법상 종합소득공제에 대한 설명으로 …"),
                               ("자기주식의 회계처리에 대한 다음의 설명 중 틀린 것은?", "자기주식의 회계처리에 대한 다음의 설명 중 …")):
        assert ox.display_stem(question) == expected
    shown = ox.display_stem(Q_81_1)
    assert shown.startswith("2018년에 개업한 ㈜세무") and "틀린" not in shown and "1,000,000" not in shown     # 물음까지만, 뒤의 자료는 안 붙는다
    assert ox.display_stem("다음 중 감가상각에 대한 설명으로 올바른 것은?").count("올바른") == 0


def test_sentences_that_need_the_given_data_are_dropped_by_a_general_rule():
    assert ox.has_data(Q_82_8) and ox.has_data(Q_81_1) and not ox.has_data("다음 중 현금흐름표에 대한 설명으로 옳지 않은 것은?")
    for sentence in ("당기제품제조원가는 동일하다.", "기말재공품의 완성품환산량은 작아진다.", "가공비 발생액은 800,000원이다."):
        assert ox.depends_on_data(sentence, Q_82_8), sentence
    for sentence in ("손익계산서상 당기순이익은 1,000,000원이 감소한다.", "재무상태표상 재고자산가액이 500,000원 감소된다.", "기말재고자산 수량을 검토한 결과는 감모손실에 반영된다."):
        assert ox.depends_on_data(sentence, Q_81_1), sentence                    # 금액이 있거나 자료에 나온 대상(기말재고자산)을 말한다
    assert not ox.depends_on_data("당기제품제조원가는 동일하다.", "다음 중 원가에 대한 설명으로 옳은 것은?")       # 자료가 없는 문항이면 그대로 쓴다
    assert ox.depends_on_data("생산공장에서 사용된 소모품을 과대계상하였다.", "다음 중 제조원가명세서상 당기제품제조원가에 영향을 미치지 않는 거래는 무엇인가?")   # 보기가 사례
    assert not ox.depends_on_data("정액법은 매년 같은 금액을 상각한다.", Q_82_8)                                 # 자료와 무관한 일반 문장은 남긴다


def test_pool_has_no_data_dependent_sentences_and_shows_stem(db):
    choices = ["재무상태표상 재고자산가액이 500,000원 감소된다.", "손익계산서상 당기순이익은 1,000,000원이 감소한다.",
               "정액법은 내용연수 동안 매년 같은 금액을 상각하는 방법이다.", "기말재고자산 수량이 늘면 매출원가가 줄어드는 경향이 있다."]
    db.execute("UPDATE questions SET question = ?, choices = ?, answer = '1' WHERE id = '12-2'", (Q_81_1, json.dumps(choices, ensure_ascii=False)))
    db.commit()
    ox._cache.clear()
    texts = {i["text"] for i in ox.pool(db).values() if "12-2" in i["sources"]}
    assert texts == {choices[2]}                                               # 숫자가 있거나 자료에 나온 대상(기말재고자산)을 말하는 보기는 빠지고 일반 문장만 남는다
    item = by_text(db, "영세율 셋째")
    assert item["stem"] == "다음 중 부가가치세법상 영세율에 대한 설명으로 …"
    assert ox.public_item(item)["stem"] == item["stem"]
    assert not any(w in i["stem"] for i in ox.pool(db).values() for w in ("옳지 않은", "틀린 것"))


# ---------------------------------------------------------------- 간격 복습
DAY = 86400


def test_advance_follows_1_3_7_14_and_completes():
    state = review.advance(None, 100, False)
    assert state == {"stage": 0, "due": 101, "done": False}
    for day, due, stage in ((101, 104, 1), (104, 111, 2), (111, 125, 3)):
        state = review.advance(state, day, True)
        assert (state["due"], state["stage"], state["done"]) == (due, stage, False)
    state = review.advance(state, 125, True)
    assert state["done"] is True and state["due"] is None


def test_advance_wrong_restarts_at_one_day_and_early_correct_does_not_advance():
    state = review.advance(review.advance(None, 100, False), 101, True)       # 3일 단계
    assert review.advance(state, 102, True) == state                           # 복습일(104) 전에 맞혀도 그대로
    assert review.advance(state, 104, False) == {"stage": 0, "due": 105, "done": False}
    assert review.advance(None, 100, True) is None                             # 틀린 적 없는 문항은 복습 대상이 아니다
    done = review.advance({"stage": 3, "due": 125, "done": False}, 125, True)
    assert review.advance(done, 130, True) == done and review.advance(done, 130, False)["stage"] == 0


def test_wrong_question_and_wrong_ox_enter_review_and_are_due_next_day(db):
    records.save(db, "12-2", "1", False, source="quiz")
    ox.answer(db, by_text(db, "영세율 셋째")["key"], "O")
    ox.answer(db, by_text(db, "자기주식 둘째")["key"], "X")
    today = clock.today()
    assert review.due_items(db, today) == []                                   # 같은 날은 아직
    due = review.due_items(db, today + 1)
    assert {d["kind"] for d in due} == {"question", "ox"} and len(due) == 3
    assert review.summary(db, today)["waiting"] == 3
    assert all("truth" not in d for d in due)


def test_review_dates_follow_clock_and_full_cycle_completes(db):
    records.save(db, "12-2", "1", False, now=clock.now())
    for days, stage in ((1, 1), (4, 2), (11, 3)):
        clock.set_offset(days)
        assert [d["id"] for d in review.due_items(db)] == ["12-2"]
        records.save(db, "12-2", "4", True, now=clock.now())
        assert review.states(db)["12-2"]["stage"] == stage
        assert review.due_items(db) == []
    clock.set_offset(25)
    assert review.due_items(db)[0]["interval"] == 14
    records.save(db, "12-2", "4", True, now=clock.now())
    assert review.summary(db)["done"] == 1 and review.summary(db)["due_count"] == 0


def test_wrong_in_review_goes_back_to_one_day(db):
    records.save(db, "12-2", "1", False, now=clock.now())
    clock.set_offset(1)
    records.save(db, "12-2", "4", True, now=clock.now())                      # 3일 단계
    clock.set_offset(4)
    records.save(db, "12-2", "1", False, now=clock.now())
    assert review.states(db)["12-2"] == {"stage": 0, "due": clock.today() + 1, "done": False}


def test_seen_only_records_do_not_enter_review(db):
    records.save(db, "12-2", "", None, seen_only=True)
    assert review.states(db) == {}


# ---------------------------------------------------------------- 오늘의 공부
def test_settings_validation_and_defaults(db):
    assert daily.get_settings(db) == {"daily_notes": 1, "daily_ox": 20, "daily_questions": 5}
    assert daily.save_settings(db, {"daily_ox": "10", "daily_questions": 3})["daily_ox"] == 10
    for bad in ({"daily_ox": 0}, {"daily_notes": 99}, {"daily_questions": "많이"}):
        with pytest.raises(ValueError):
            daily.save_settings(db, bad)
    assert daily.get_settings(db)["daily_ox"] == 10


def test_today_plan_picks_unit_with_note_that_is_not_understood_and_keeps_it_all_day(db):
    plan = daily.today_plan(db)
    unit = next(t["unit"] for t in plan["tasks"] if t["kind"] == "note")
    assert [t["kind"] for t in plan["tasks"]] == ["note", "ox", "quiz"]          # 순서 변경: 노트 → O/X → 기출 → 복습, 복습할 것이 0개면 줄이 없다
    study.save_progress(db, unit, "understood")
    again = daily.today_plan(db)
    assert next(t["unit"] for t in again["tasks"] if t["kind"] == "note") == unit        # 오늘은 바뀌지 않는다
    clock.set_offset(1)
    tomorrow = daily.today_plan(db)
    assert all(t["unit"] != unit for t in tomorrow["tasks"] if t["kind"] == "note")      # 이해함이면 다음 날은 다른 단원


def test_today_complete_when_every_task_is_done(db, monkeypatch):
    monkeypatch.setattr(study, "load_note", lambda subject, unit, study_dir=None: {"concept": {"lines": []}})   # 시험용 문항 은행의 단원에도 노트가 있는 셈
    daily.save_settings(db, {"daily_ox": 5, "daily_questions": 1})
    plan = daily.today_plan(db)
    assert plan["complete"] is False and not [t for t in plan["tasks"] if t["kind"] == "review"]   # 복습할 것이 없으면 복습 줄이 없다
    unit = plan["tasks"][0]["unit"]
    subject, tax, _ = study.find_unit(db, unit)
    study.save_progress(db, unit, "read")
    for p in ox.pick(db, subject, tax, unit, 5):
        ox.answer(db, p["key"], "O")
    need_ox = next(t for t in daily.today_plan(db)["tasks"] if t["kind"] == "ox")["need"]
    assert next(t for t in daily.today_plan(db)["tasks"] if t["kind"] == "ox")["have"] == need_ox
    qid = db.execute("SELECT id FROM questions WHERE unit = ?", (unit,)).fetchone()["id"]
    records.save(db, qid, "1", True, source="quiz")
    assert daily.today_plan(db)["complete"] is True


def test_wrong_review_item_keeps_today_incomplete_until_reviewed(db, monkeypatch):
    monkeypatch.setattr(study, "load_note", lambda subject, unit, study_dir=None: {"concept": {"lines": []}})
    records.save(db, "12-2", "1", False, now=clock.now())
    clock.set_offset(1)
    review_of = lambda: next(t for t in daily.today_plan(db)["tasks"] if t["kind"] == "review")
    assert review_of()["done"] is False and review_of()["need"] == 1
    records.save(db, "12-2", "4", True, now=clock.now())
    assert not [t for t in daily.today_plan(db)["tasks"] if t["kind"] == "review"]       # 다 복습하면 오늘 복습할 것이 0개 → 줄이 사라진다(완료 계산에서도 빠짐)


def test_streak_counts_consecutive_days_and_week_has_rates(db):
    base = clock.now()
    for back in (0, 1, 2, 4):                                                 # 3일 연속 + 하루 건너뜀
        records.save(db, "12-2", "1", back % 2 == 0, now=base - back * DAY)
    assert daily.streak(db) == 3
    clock.set_offset(1)
    assert daily.streak(db) == 3                                              # 오늘(하루 뒤) 아직 안 했으면 어제까지 센다
    week = daily.week(db)
    assert len(week) == 7 and week[-1]["quiz"]["n"] == 0 and week[-1]["quiz"]["rate"] is None


def test_week_separates_ox_and_quiz_rates(db):
    ox.answer(db, by_text(db, "영세율 셋째")["key"], "X")
    ox.answer(db, by_text(db, "영세율 첫째")["key"], "X")
    records.save(db, "12-2", "4", True, source="quiz")
    today = daily.week(db)[-1]
    assert today["ox"] == {"n": 2, "right": 1, "rate": 0.5} and today["quiz"] == {"n": 1, "right": 1, "rate": 1.0}


# ---------------------------------------------------------------- API
def test_api_routes(db):
    status, data = dispatch("GET", "/api/ox/set", {"subject": "세무회계", "count": "4"}, None, db)
    assert status == 200 and len(data["items"]) == 4
    key = data["items"][0]["key"]
    status, result = dispatch("POST", "/api/ox/answer", {}, {"key": key, "choice": "O"}, db)
    assert status == 200 and "correct" in result
    assert dispatch("POST", "/api/ox/answer", {}, {"key": "없음", "choice": "O"}, db)[0] == 404
    assert dispatch("GET", "/api/ox/set", {"unit": "없는단원"}, None, db)[0] == 404
    status, card = dispatch("GET", "/api/today", {}, None, db)
    assert status == 200 and {"tasks", "streak", "week", "complete", "settings"} <= set(card)
    assert dispatch("POST", "/api/settings", {}, {"daily_ox": 30}, db)[1]["settings"]["daily_ox"] == 30
    assert dispatch("POST", "/api/settings", {}, {"daily_ox": 1}, db)[0] == 400
    assert dispatch("GET", "/api/review", {}, None, db)[1]["intervals"] == [1, 3, 7, 14]


def test_test_clock_route_is_closed_unless_enabled(db, monkeypatch):
    monkeypatch.delenv("TUTOR_TEST_CLOCK", raising=False)
    assert dispatch("POST", "/api/test/clock", {}, {"days": 1}, db)[0] == 404 and clock.offset() == 0
    monkeypatch.setenv("TUTOR_TEST_CLOCK", "1")
    status, data = dispatch("POST", "/api/test/clock", {}, {"days": 2}, db)
    assert status == 200 and data["offset"] == 2 and clock.offset() == 2


def test_pages_and_note_button_exist():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / "tutor" / "static"
    from tutor.web import PAGES
    assert PAGES["/ox"] == "ox.html" and (static / "ox.html").exists()
    assert "이 단원 O/X 20개" in (static / "study.html").read_text(encoding="utf-8")
    index = (static / "index.html").read_text(encoding="utf-8")
    assert 'id="today"' in index and "예정된 복습" in index and "복습 대기" not in index
    assert "예정된 복습" in (static / "ox.html").read_text(encoding="utf-8")
