import json

import pytest

from tutor import glossary_review as gr
from tutor.glossary import GLOSSARY_PATH
from tutor.web import dispatch

ENTRIES = [{"term": "리스", "meaning": "빌려 쓰는 계약", "synonyms": ["임차"]},
           {"term": "충당부채", "meaning": "미래 지출", "synonyms": []},
           {"term": "없는말", "meaning": "x", "synonyms": []}]


def test_rows_sorted_by_question_text_count_desc(conn):
    rows = gr.list_rows(conn, ENTRIES)
    counts = [r["count"] for r in rows]
    assert counts == sorted(counts, reverse=True)
    assert [r["term"] for r in rows if r["count"] == 0] == ["없는말"] or rows[-1]["count"] == 0
    expected = sum(1 for r in conn.execute("SELECT question FROM questions") if "리스" in r["question"].replace(" ", ""))
    assert next(r for r in rows if r["term"] == "리스")["count"] == expected


def test_save_persists_to_db_and_review_file_only(conn, tmp_path):
    glossary_path = GLOSSARY_PATH
    before = glossary_path.read_text(encoding="utf-8")
    target = tmp_path / "review.json"
    gr.save_review(conn, "리스", "수정 필요", "  뜻이 어렵다 ", "더 쉬운 풀이", ENTRIES, target)
    row = next(r for r in gr.list_rows(conn, ENTRIES) if r["term"] == "리스")
    assert (row["status"], row["memo"], row["proposed_meaning"]) == ("수정 필요", "뜻이 어렵다", "더 쉬운 풀이")
    saved = json.loads(target.read_text(encoding="utf-8"))["reviews"]
    assert saved[0]["term"] == "리스" and saved[0]["original_meaning"] == "빌려 쓰는 계약"
    assert glossary_path.read_text(encoding="utf-8") == before      # 사전 원본은 그대로


def test_save_overwrites_and_rejects_bad_input(conn, tmp_path):
    target = tmp_path / "review.json"
    gr.save_review(conn, "리스", "수정 필요", "a", "", ENTRIES, target)
    gr.save_review(conn, "리스", "검토 완료", "b", "", ENTRIES, target)
    assert [r["status"] for r in json.loads(target.read_text(encoding="utf-8"))["reviews"]] == ["검토 완료"]
    with pytest.raises(ValueError):
        gr.save_review(conn, "모르는용어", "검토 완료", "", "", ENTRIES, target)
    with pytest.raises(ValueError):
        gr.save_review(conn, "리스", "아무거나", "", "", ENTRIES, target)


def test_web_routes_save_and_list(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "REVIEW_PATH", tmp_path / "review.json")
    status, payload = dispatch("GET", "/api/glossary_review", {}, {}, conn)
    assert status == 200 and payload["rows"][0]["count"] >= payload["rows"][-1]["count"]
    term = payload["rows"][0]["term"]
    assert dispatch("POST", "/api/glossary_review", {}, {"term": term, "status": "검토 완료", "memo": "ok"}, conn)[0] == 200
    assert next(r for r in dispatch("GET", "/api/glossary_review", {}, {}, conn)[1]["rows"] if r["term"] == term)["status"] == "검토 완료"
    assert dispatch("POST", "/api/glossary_review", {}, {"term": "없는용어", "status": "검토 완료"}, conn)[0] == 400
    assert (tmp_path / "review.json").exists()
