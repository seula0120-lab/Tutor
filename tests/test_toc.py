import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from tutor.toc import build_toc
from tutor.web import Handler, dispatch


def test_toc_groups_subject_then_unit_with_counts(conn):
    toc = build_toc(conn)
    assert [s["subject"] for s in toc] == ["재무회계", "원가회계", "세무회계"]
    assert sum(s["count"] for s in toc) == 8
    finance = toc[0]
    assert finance["count"] == sum(u["count"] for u in finance["units"])
    inventory = next(u for u in finance["units"] if u["unit"] == "재고자산")
    assert inventory["count"] == 1 and inventory["round_count"] == 1
    tax = toc[2]["units"]
    assert {u["tax"] for u in tax} == {"부가가치세", "소득세", "법인세"}
    vat = next(u for u in tax if u["unit"] == "영세율·면세")
    assert vat["label"] == "부가가치세 › 영세율·면세"


def test_round_count_counts_distinct_rounds(conn):
    toc = build_toc(conn)
    asset_units = [u for s in toc for u in s["units"] if u["unit"] == "유형자산"]
    assert asset_units[0]["count"] == 1
    total_items = sum(len(u["items"]) for s in toc for u in s["units"])
    assert total_items == 8


def test_toc_response_never_contains_answers_choices_or_explanations(conn):
    status, payload = dispatch("GET", "/api/toc", {}, {}, conn)
    assert status == 200
    text = json.dumps(payload, ensure_ascii=False)
    for secret in ("answer", "explanation", "choices", "순실현가능가치가 원가보다 낮으면"):    # 키 이름과 해설 글 모두
        assert secret not in text
    item = payload["toc"][0]["units"][0]["items"][0]
    assert set(item) == {"id", "round", "number", "first_line"}


def test_items_newest_round_first(conn):
    for s in build_toc(conn):
        for u in s["units"]:
            rounds = [i["round"] for i in u["items"]]
            assert rounds == sorted(rounds, reverse=True)


def test_toc_page_and_index_link_over_http(tmp_path, conn):
    from tutor.bank import load_bank
    from tutor.db import connect
    from conftest import ROUND_ONE
    db = tmp_path / "h.db"
    c = connect(db)
    load_bank(c, [(1, ROUND_ONE)])
    c.close()
    handler = type("H", (Handler,), {"db_path": db})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    from conftest import login_opener
    opener = login_opener(base, db)
    try:
        toc_page = opener.open(base + "/toc").read().decode()
        assert "문제 목차" in toc_page and "renderCard" in toc_page and "/static/quizcard.js" in toc_page
        assert 'href="/toc"' in opener.open(base + "/").read().decode()
        data = json.loads(opener.open(base + "/api/toc").read())
        assert data["toc"][0]["subject"] == "재무회계"
    finally:
        server.shutdown()
        server.server_close()
