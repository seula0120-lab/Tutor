from pathlib import Path

import pytest

from tutor import favorites
from tutor.db import connect
from tutor.web import dispatch


def test_add_list_and_remove(conn):
    assert favorites.list_all(conn) == []
    favorites.add(conn, "정상공손 비정상공손 처리", "all", now=1.0)
    favorites.add(conn, "수정세금계산서 발급", "10", now=2.0)
    assert [f["query"] for f in favorites.list_all(conn)] == ["수정세금계산서 발급", "정상공손 비정상공손 처리"]   # 최근 저장이 위
    favorites.remove(conn, "수정세금계산서 발급")
    assert [f["query"] for f in favorites.list_all(conn)] == ["정상공손 비정상공손 처리"]
    assert favorites.remove(conn, "없는 질문") == favorites.list_all(conn)         # 없는 걸 지워도 오류 없음


def test_same_query_is_stored_once_and_scope_updates(conn):
    favorites.add(conn, "자기주식", "all", now=1.0)
    favorites.add(conn, "  자기주식  ", "10", now=2.0)               # 앞뒤 공백은 같은 질문
    items = favorites.list_all(conn)
    assert len(items) == 1 and items[0]["scope"] == "10"


def test_invalid_query_rejected(conn):
    for bad in ("", "   ", None, "가" * 201):
        with pytest.raises(ValueError):
            favorites.add(conn, bad)


def test_favorites_api_and_persistence(tmp_path):
    db = tmp_path / "f.db"
    conn = connect(db)
    assert dispatch("POST", "/api/favorites", {}, {"q": "영세율 면세 차이", "scope": "all"}, conn)[0] == 200
    status, listed = dispatch("GET", "/api/favorites", {}, {}, conn)
    assert status == 200 and listed["favorites"][0]["query"] == "영세율 면세 차이"
    conn.close()
    conn = connect(db)                                              # 서버를 다시 켜도 남아 있다
    assert len(dispatch("GET", "/api/favorites", {}, {}, conn)[1]["favorites"]) == 1
    status, after = dispatch("POST", "/api/favorites/delete", {}, {"q": "영세율 면세 차이"}, conn)
    assert status == 200 and after["favorites"] == []
    assert dispatch("POST", "/api/favorites", {}, {"q": ""}, conn)[0] == 400


def test_favorites_survive_question_bank_reload(conn):
    from tutor.bank import load_bank
    favorites.add(conn, "자기주식")
    load_bank(conn, [])
    assert len(favorites.list_all(conn)) == 1


def test_page_has_recent_queries_that_tolerate_storage_failure():
    page = (Path(__file__).resolve().parent.parent / "tutor" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="recent"' in page and "localStorage" in page
    assert page.count("catch (e)") >= 2                              # 읽기·쓰기 모두 실패해도 화면은 계속 동작
    assert ".slice(0, 10)" in page                                   # 최근 질문은 10개까지
