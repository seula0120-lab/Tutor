from pathlib import Path

ROOT_PAGE = Path(__file__).resolve().parent.parent / "tutor" / "static" / "index.html"
import json
import random
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tutor import quiz
from tutor.analysis import unit_profile
from tutor.web import Handler, dispatch, parse_scope


# ---- 문제 분석 ----
def test_unit_profile_counts_share_and_points_per_round(conn):
    profile = unit_profile(conn, None)
    assert profile["rounds"] == 2 and profile["total_questions"] == 8
    by_unit = {r["unit"]: r for r in profile["rows"]}
    vat = by_unit["영세율·면세"]
    assert vat["questions"] == 1 and vat["rounds"] == 1
    assert vat["appear_rate"] == 0.5 and vat["share"] == 0.125
    assert vat["points_per_round"] == 1.0          # 2점 1문항 ÷ 2회차
    assert abs(sum(r["share"] for r in profile["rows"]) - 1) < 0.01


def test_unit_profile_respects_round_scope(conn):
    latest = unit_profile(conn, 1)
    assert latest["rounds"] == 1 and latest["total_questions"] == 2


def test_unit_profile_orders_by_points_per_round(conn):
    points = [r["points_per_round"] for r in unit_profile(conn, None)["rows"]]
    assert points == sorted(points, reverse=True)


# ---- 기출 답안: 공개 규칙 ----
def test_public_question_hides_answer_and_explanation(conn):
    shown = quiz.find_question(conn, 1, 1)
    assert "answer" not in shown and "explanation" not in shown
    assert shown["id"] == "1-1" and len(shown["choices"]) == 4 and shown["multi"] is False
    assert quiz.find_question(conn, 1, 3)["multi"] is True
    assert quiz.find_question(conn, 9, 9) is None


def test_correct_choice_reveals_answer_and_official_explanation(conn):
    result = quiz.check_answer(conn, "1-1", "2")
    assert result["correct"] is True and result["answer"] == "2"
    assert "순실현가능가치" in result["explanation"]


def test_wrong_choice_shows_only_wrongness(conn):
    result = quiz.check_answer(conn, "1-1", "4")
    assert result == {"id": "1-1", "correct": False}  # 정답·해설 어느 것도 새지 않는다


def test_multi_answer_accepts_any_listed_answer(conn):
    assert quiz.check_answer(conn, "1-3", "1")["correct"] is True
    assert quiz.check_answer(conn, "1-3", "3")["correct"] is True
    assert quiz.check_answer(conn, "1-3", "2")["correct"] is False


def test_reveal_returns_answer_without_grading(conn):
    result = quiz.reveal(conn, "1-7")
    assert result["answer"] == "4" and "상호배분법" in result["explanation"]
    assert "error" in quiz.reveal(conn, "9-9")


def test_quiz_pick_filters_unit_and_excludes_solved(conn):
    picked = quiz.pick_quiz_question(conn, unit="영세율·면세", rng=random.Random(0))
    assert picked["id"] == "1-11" and "answer" not in picked
    assert quiz.pick_quiz_question(conn, unit="영세율·면세", exclude=["1-11"]) is None
    assert quiz.pick_quiz_question(conn, subject="세무회계", tax="소득세")["id"] == "1-12"


# ---- 요청 처리 ----
def test_dispatch_routes_and_errors(conn):
    status, payload = dispatch("GET", "/api/question", {"round": "1", "number": "1"}, {}, conn)
    assert status == 200 and "answer" not in payload
    assert dispatch("GET", "/api/question", {"round": "9", "number": "9"}, {}, conn)[0] == 404
    assert dispatch("GET", "/api/question", {}, {}, conn)[0] == 400           # 인자 빠짐
    assert dispatch("GET", "/api/question", {"round": "x", "number": "1"}, {}, conn)[0] == 400
    assert dispatch("GET", "/api/nothing", {}, {}, conn)[0] == 404
    assert dispatch("POST", "/api/ask", {}, {"q": "  "}, conn)[0] == 400


def test_dispatch_answer_flow_matches_rules(conn):
    status, wrong = dispatch("POST", "/api/answer", {}, {"id": "1-1", "choice": "1"}, conn)
    assert status == 200 and wrong == {"id": "1-1", "correct": False}
    status, right = dispatch("POST", "/api/answer", {}, {"id": "1-1", "choice": "2"}, conn)
    assert right["correct"] and right["explanation"]
    assert dispatch("POST", "/api/answer", {}, {"id": "9-9", "choice": "1"}, conn)[0] == 404


def test_annotated_has_no_answer_and_marks_terms(conn):
    status, payload = dispatch("GET", "/api/annotated", {"round": "1", "number": "1"}, {}, conn)
    assert status == 200
    assert "explanation" not in payload and "explanation" not in payload["meta"]
    joined = "".join(p["text"] for p in payload["question"])
    assert joined == payload["meta"]["question"]
    terms = [p["term"] for p in payload["question"] if p["term"]]
    assert "저가법" in terms and "저가법" in payload["meanings"]
    assert "answer" not in payload["meta"]


def test_glossary_endpoint_filters(conn):
    status, everything = dispatch("GET", "/api/glossary", {}, {}, conn)
    status, filtered = dispatch("GET", "/api/glossary", {"q": "영세율"}, {}, conn)
    assert 0 < len(filtered["terms"]) < len(everything["terms"])


def test_parse_scope():
    assert parse_scope(None) is None and parse_scope("") is None      # 검색 기본은 전체 회차
    assert parse_scope(None, 10) == 10 and parse_scope("all", 10) is None and parse_scope("3") == 3
    with pytest.raises(ValueError):
        parse_scope("0")


# ---- 실제 HTTP ----
def test_http_server_serves_page_and_api(tmp_path, conn):
    from tutor.bank import load_bank
    from tutor.db import connect
    from conftest import ROUND_ONE
    db_file = tmp_path / "http.db"
    http_conn = connect(db_file)
    load_bank(http_conn, [(1, ROUND_ONE)])
    http_conn.close()

    handler = type("TestHandler", (Handler,), {"db_path": db_file})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    from conftest import login_opener
    opener = login_opener(base, None)
    try:
        page = opener.open(base + "/").read().decode("utf-8")
        assert "문제 분석" in page and "기출 답안" in page and "단어 주석" in page
        req = urllib.request.Request(base + "/api/ask", data=json.dumps({"q": "저가법"}).encode(),
                                     headers={"Content-Type": "application/json"})
        data = json.loads(opener.open(req).read())
        assert data["search"]["results"][0]["id"] == "1-1"
        assert data["ai"]["status"] == "no_key"  # 키가 없으면 검색 결과만 쓴다
        with pytest.raises(urllib.error.HTTPError) as err:
            opener.open(base + "/api/question?round=7&number=7")
        assert err.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_quiz_card_has_tax_notice_only_for_tax_questions(conn):
    assert quiz.find_question(conn, 1, 11)["tax_notice"] == "1회 · 세법 개정 확인 필요"
    assert quiz.find_question(conn, 1, 1)["tax_notice"] is None


def test_ask_returns_summary_card_without_api_key(conn):
    status, payload = dispatch("POST", "/api/ask", {}, {"q": "저가법"}, conn)
    assert status == 200
    assert set(payload["summary"]) == {"coverage", "right", "traps", "excluded", "related_ids", "tax_notice"}
    assert payload["summary"]["coverage"]["questions"] >= 1
    assert payload["ai"]["status"] == "no_key"                       # 키가 없어도 카드는 나온다
    assert len(payload["search"]["results"]) <= 5


def test_quiz_page_locks_choices_after_wrong_answer():
    # 퀴즈 카드 코드는 공용 static/quizcard.js 로 옮겼다(같은 검사를 그 파일에 한다).
    page = ROOT_PAGE.read_text(encoding="utf-8") + (ROOT_PAGE.parent / "ask.js").read_text(encoding="utf-8")
    card = (ROOT_PAGE.parent / "quizcard.js").read_text(encoding="utf-8")
    assert "다시 골라" not in page + card                            # 재시도 안내 문구 없음
    wrong_branch = card[card.index('b.classList.add("wrong")'):][:260]
    assert "오답입니다." in wrong_branch
    assert "buttons.forEach((x) => (x.disabled = true))" in card[:card.index('b.classList.add("wrong")')]   # 클릭 즉시 모두 잠금
    assert "정답·해설 바로 보기" in card
    assert "이 주제를 직접 다룬 기출을 찾지 못했습니다" in page
