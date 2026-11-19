from tutor.glossary import annotate, expand_everyday_words, load_glossary
from tutor.search import extract_terms, scope_rounds, search_theory

ENTRIES = [
    {"term": "저가법", "meaning": "싸게 평가", "synonyms": ["물건 값이 떨어지면", "재고 값이 떨어"]},
    {"term": "자기주식", "meaning": "자사주", "synonyms": ["자기 회사 주식"]},
    {"term": "공손", "meaning": "불량", "synonyms": ["불량품"]},
    {"term": "비정상공손", "meaning": "관리 잘못 불량", "synonyms": []},
]


def ids(result):
    return [r["id"] for r in result["results"]]


def test_extract_terms_strips_particles_and_stopwords():
    assert extract_terms("자기주식의 처리는 어떻게 해?") == ["자기주식", "처리"]
    assert extract_terms("영세율이 뭐야?") == ["영세율"]
    assert extract_terms("a 가 ?") == []


def test_keyword_search_finds_question_by_unit_term(conn):
    result = search_theory("저가법", conn, entries=[])
    assert ids(result)[0] == "1-1"


def test_two_char_term_uses_like_path(conn):
    result = search_theory("손금", conn, entries=[])  # 2글자: FTS trigram 으로는 못 찾는 길이
    assert "1-13" in ids(result)


def test_everyday_words_expand_to_official_term(conn):
    assert expand_everyday_words("물건  값이 떨어지면 재고는?", ENTRIES) == ["저가법"]  # 띄어쓰기 무시
    without = search_theory("물건 값이 떨어지면 어떻게 적어", conn, entries=[])
    with_syn = search_theory("물건 값이 떨어지면 어떻게 적어", conn, entries=ENTRIES)
    assert "1-1" not in ids(without)
    assert ids(with_syn)[0] == "1-1" and with_syn["expanded"] == ["저가법"]


def test_default_scope_is_latest_rounds_and_all_on_request(conn):
    assert scope_rounds(conn, 1) == [2]
    assert scope_rounds(conn, None) == [2, 1]
    latest_only = search_theory("영세율", conn, round_limit=1, entries=[])
    assert latest_only["results"] == [] and "최신 1회분" in latest_only["note"]
    everything = search_theory("영세율", conn, round_limit=None, entries=[])
    assert ids(everything) == ["1-11"] and everything["scope"] == "전체 회차"


def test_no_usable_terms_returns_note(conn):
    result = search_theory("? ! a", conn, entries=[])
    assert result["results"] == [] and result["note"]


def test_query_with_fts_special_characters_does_not_crash(conn):
    assert search_theory('"저가법" OR (재고*) NEAR', conn, entries=[])["results"]


def test_result_carries_source_fields(conn):
    top = search_theory("자기주식", conn, entries=[])["results"][0]
    assert (top["id"], top["round"], top["number"]) == ("1-3", 1, 3)
    assert top["subject"] == "재무회계" and "자기주식" in top["matched"]


def test_annotate_prefers_longest_term_and_keeps_text():
    pieces = annotate("비정상공손과 저가법", ENTRIES)
    assert "".join(p["text"] for p in pieces) == "비정상공손과 저가법"
    assert [p["term"] for p in pieces if p["term"]] == ["비정상공손", "저가법"]


def test_real_glossary_file_loads_with_synonyms():
    entries = load_glossary()
    assert len(entries) >= 100 and all(e["meaning"] for e in entries)
    assert any(e["synonyms"] for e in entries)


def test_default_scope_is_all_rounds(conn):
    # 기본값(전체 회차): 옛 회차(1회)에만 있는 문항도 찾고, 범위 설명이 '전체 회차'다.
    result = search_theory("영세율", conn, entries=[])
    assert result["scope"] == "전체 회차" and ids(result) == ["1-11"]
    assert search_theory("영세율", conn, round_limit=1, entries=[])["results"] == []   # 최신 1회분만 고르면 없음


def test_tax_notice_only_on_tax_subject_with_round(conn):
    vat = search_theory("영세율", conn, entries=[])["results"][0]
    assert vat["tax_notice"] == "1회 · 세법 개정 확인 필요"
    for text in ("저가법", "자기주식", "보조부문"):                       # 재무·원가: 표시 없음
        assert search_theory(text, conn, entries=[])["results"][0]["tax_notice"] is None


def test_same_score_puts_recent_round_first(tmp_path):
    from conftest import item
    from tutor.bank import load_bank
    from tutor.db import connect
    same = dict(question="다음 중 저가법에 대한 설명으로 옳은 것은?", choices=["가", "나", "다", "라"], answer="1")
    c = connect(tmp_path / "tie.db")
    load_bank(c, [(5, [item(1, **same)]), (9, [item(1, **same)]), (7, [item(1, **same)])])
    assert ids(search_theory("저가법", c, entries=[])) == ["9-1", "7-1", "5-1"]
