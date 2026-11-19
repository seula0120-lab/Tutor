import json

from conftest import ROUND_ONE, ROUND_TWO
from tutor.bank import load_bank
from tutor.tagging import tag_question, tax_of


def test_subject_follows_question_number():
    assert tag_question(1, "재고자산 저가법", ["가"], "")[0] == "재무회계"
    assert tag_question(5, "재고자산 저가법", ["가"], "")[0] == "재무회계"
    assert tag_question(6, "표준원가 차이", ["가"], "")[0] == "원가회계"
    assert tag_question(10, "표준원가 차이", ["가"], "")[0] == "원가회계"
    assert tag_question(11, "영세율", ["가"], "")[0] == "세무회계"
    assert tag_question(15, "영세율", ["가"], "")[0] == "세무회계"


def test_law_name_in_stem_decides_tax_over_choice_words():
    # 보기에 부가가치세 낱말이 많아도 질문 문장의 법 이름이 우선이다.
    stem = "다음 중 법인세법상 손금에 대한 설명으로 옳은 것은?"
    body = stem + " 세금계산서 영세율 매입세액 면세"
    assert tax_of(stem, body) == "법인세"


def test_tax_falls_back_to_keyword_score_without_law_name():
    stem = "다음 중 세금계산서 발급에 대한 설명으로 옳은 것은?"
    assert tax_of(stem, stem + " 수정세금계산서") == "부가가치세"
    stem = "다음 중 연말정산에 대한 설명으로 옳은 것은?"
    assert tax_of(stem, stem + " 근로소득") == "소득세"


def test_unit_prefers_stem_over_choices():
    # 질문은 재고자산인데 보기에 '자본' 낱말이 먼저 나와도 재고자산이어야 한다.
    _, _, unit = tag_question(1, "재고자산의 저가법에 대한 설명으로 옳은 것은?",
                              ["자본금 증자", "나", "다", "라"], "")
    assert unit == "재고자산"


def test_capitalized_expenditure_is_not_equity():
    # '자본적지출'·'차입원가 자본화' 는 자본 단원이 아니라 유형자산이다.
    _, _, unit = tag_question(1, "자본적지출과 수익적지출에 대한 설명으로 옳은 것은?", ["가"], "")
    assert unit == "유형자산"
    _, _, unit = tag_question(2, "차입원가 자본화에 대한 설명으로 옳은 것은?", ["가"], "")
    assert unit == "유형자산"


def test_unmatched_question_gets_default_unit():
    _, _, unit = tag_question(1, "전혀 상관없는 문장", ["가"], "")
    assert unit == "기타"


def test_load_stores_tagged_rows(conn):
    row = conn.execute("SELECT * FROM questions WHERE id='1-11'").fetchone()
    assert (row["round"], row["number"]) == (1, 11)
    assert (row["subject"], row["tax"], row["unit"]) == ("세무회계", "부가가치세", "영세율·면세")
    assert row["answer"] == "3" and len(json.loads(row["choices"])) == 4
    multi = conn.execute("SELECT answer FROM questions WHERE id='1-3'").fetchone()
    assert multi["answer"] == "1,3"


def test_reload_keeps_row_and_index_counts_equal(conn):
    total = len(ROUND_ONE) + len(ROUND_TWO)
    for _ in range(3):
        assert load_bank(conn, [(1, ROUND_ONE), (2, ROUND_TWO)]) == total
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == total
    assert conn.execute("SELECT COUNT(*) FROM theory_fts").fetchone()[0] == total


def test_load_does_not_modify_source_items():
    before = json.dumps(ROUND_ONE, ensure_ascii=False)
    from tutor.bank import question_row
    question_row(1, ROUND_ONE[0])
    assert json.dumps(ROUND_ONE, ensure_ascii=False) == before
