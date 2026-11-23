from tutor import records
from tutor.bank import load_bank
from tutor.db import connect
from tutor.web import dispatch
from conftest import ROUND_ONE


def answer(conn, qid, choice):
    return dispatch("POST", "/api/answer", {}, {"id": qid, "choice": choice}, conn)[1]


def rows(conn):
    return [tuple(r) for r in conn.execute("SELECT question_id, choice, correct, seen_only FROM records ORDER BY id")]


def test_choice_creates_record_with_correctness(conn):
    answer(conn, "1-1", "4")      # 오답
    answer(conn, "1-1", "2")      # 정답
    assert rows(conn) == [("1-1", "4", 0, 0), ("1-1", "2", 1, 0)]


def test_reveal_is_seen_only_and_not_counted_as_correct(conn):
    dispatch("POST", "/api/reveal", {}, {"id": "1-1"}, conn)
    assert rows(conn) == [("1-1", "", None, 0 + 1)]
    assert records.correct_ids(conn) == set()                      # 정답으로 세지 않는다
    assert records.unit_stats(conn) == {}                          # 풀이 통계에도 안 들어간다
    assert records.notebook(conn) == []                            # 오답노트에도 안 들어간다


def test_double_click_does_not_duplicate_but_later_repeat_does(conn):
    assert records.save(conn, "1-1", "4", False, now=100.0) is True
    assert records.save(conn, "1-1", "4", False, now=101.0) is False       # 3초 안의 같은 기록
    assert records.save(conn, "1-1", "3", False, now=101.5) is True        # 다른 보기는 별개
    assert records.save(conn, "1-1", "3", False, now=110.0) is True        # 시간이 지난 뒤의 같은 선택은 새 기록
    assert len(rows(conn)) == 3
    assert records.save(conn, "1-2", "1", False, now=110.5) is True        # 다른 문항은 영향 없음


def test_records_survive_reload_of_question_bank(tmp_path):
    db = tmp_path / "keep.db"
    c = connect(db)
    load_bank(c, [(1, ROUND_ONE)])
    answer(c, "1-1", "4")
    load_bank(c, [(1, ROUND_ONE)])                                  # 문제은행 다시 적재
    load_bank(c, [])                                                # 비워도 기록은 남는다
    assert rows(c) == [("1-1", "4", 0, 0)]
    c.close()
    assert rows(connect(db)) == [("1-1", "4", 0, 0)]                # 다시 연결해도 그대로


def test_notebook_lists_wrong_then_drops_when_answered_correctly(conn):
    answer(conn, "1-1", "4")
    answer(conn, "1-7", "1")
    assert [i["id"] for i in records.notebook(conn)] == ["1-7", "1-1"]      # 최근에 틀린 순
    answer(conn, "1-1", "2")                                                # 다시 풀어 맞힘
    assert [i["id"] for i in records.notebook(conn)] == ["1-7"]
    answer(conn, "1-1", "4")                                                # 또 틀리면 다시 들어온다
    assert "1-1" in [i["id"] for i in records.notebook(conn)]


def test_notebook_filters_and_has_no_answer_fields(conn):
    answer(conn, "1-1", "4")
    answer(conn, "1-7", "1")
    only_cost = records.notebook(conn, subject="원가회계")
    assert [i["id"] for i in only_cost] == ["1-7"]
    assert [i["id"] for i in records.notebook(conn, unit="재고자산")] == ["1-1"]
    assert records.notebook(conn, unit="없는단원") == []
    item = records.notebook(conn)[0]
    assert not {"answer", "explanation", "choices"} & set(item) and item["first_line"]


def test_seen_after_wrong_keeps_question_in_notebook(conn):
    answer(conn, "1-1", "4")
    dispatch("POST", "/api/reveal", {}, {"id": "1-1"}, conn)
    assert [i["id"] for i in records.notebook(conn)] == ["1-1"]     # 확인만으로는 빠지지 않는다


def test_unit_wrong_counts_and_open_questions(conn):
    answer(conn, "1-1", "4")
    answer(conn, "1-1", "3")
    answer(conn, "1-1", "2")        # 맞혀서 노트에서는 빠짐
    answer(conn, "1-7", "1")
    counts = {r["unit"]: r for r in records.unit_wrong_counts(conn)}
    assert counts["재고자산"]["wrong_total"] == 2 and counts["재고자산"]["open_questions"] == 0
    assert counts["보조부문원가 배분"]["wrong_total"] == 1 and counts["보조부문원가 배분"]["open_questions"] == 1


def test_notebook_api_shape(conn):
    answer(conn, "1-1", "4")
    status, payload = dispatch("GET", "/api/notebook", {"subject": "재무회계"}, {}, conn)
    assert status == 200 and [i["id"] for i in payload["items"]] == ["1-1"]
    assert payload["unit_counts"][0]["wrong_total"] == 1


def test_question_by_id_and_static_script_and_notebook_tab(tmp_path):
    from pathlib import Path
    from conftest import ROUND_ONE
    status, found = dispatch("GET", "/api/question", {"id": "1-1"}, {}, connect(tmp_path / "x.db"))
    assert status == 404
    c = connect(tmp_path / "y.db")
    load_bank(c, [(1, ROUND_ONE)])
    status, found = dispatch("GET", "/api/question", {"id": "1-1"}, {}, c)
    assert status == 200 and found["id"] == "1-1" and "answer" not in found
    static = Path(__file__).resolve().parent.parent / "tutor" / "static"
    page = (static / "index.html").read_text(encoding="utf-8")
    assert "/#notebook" in (static / "nav.js").read_text(encoding="utf-8") and 'id="notebook"' in page and "/static/quizcard.js" in page
    assert "오답입니다." in (static / "quizcard.js").read_text(encoding="utf-8")


def test_shared_card_script_served_over_http(tmp_path):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from tutor.web import Handler
    handler = type("H", (Handler,), {"db_path": tmp_path / "z.db"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        body = urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/static/quizcard.js").read().decode()
        assert "function renderCard" in body
    finally:
        server.shutdown()
        server.server_close()
