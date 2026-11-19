import json

from tutor.bank import load_bank
from tutor.db import connect
from tutor.question_type import (CALCULATION, COMBINATION, IDENTIFY, NEGATIVE, POSITIVE, UNKNOWN, classify,
                                 stem_of, strong_polarity)
from tutor.summary import ALL_CORRECT_KIND, build_summary
from conftest import item

C4 = ["첫째 문장이다.", "둘째 문장이다.", "셋째 문장이다.", "넷째 문장이다."]
NOUNS = ["보험료 세액공제", "의료비 세액공제", "교육비 세액공제", "월세 세액공제"]


def test_last_marker_in_the_question_wins():
    q = "수익적 지출을 자본적 지출로 잘못 회계처리 한 경우 재무제표에 미치는 영향으로 옳은 것은?"
    assert classify(q, C4) == POSITIVE
    assert classify("광고선전비를 제조원가로 잘못 회계처리한 경우 재무제표에 미치는 영향으로 옳은 것은?", C4) == POSITIVE
    assert classify("다음 중 잘못 표시된 것은?", C4) == NEGATIVE                 # '잘못' 뿐이면 그대로 부정
    assert classify("다음 중 옳은 설명을 고르되 그 중 틀린 것은?", C4) == NEGATIVE


def test_data_lines_after_the_question_are_not_read():
    q = "다음 중 옳은 것은? ㆍ자료: 이 금액은 잘못 처리되었다"
    assert stem_of(q) == "다음 중 옳은 것은?" and classify(q, C4) == POSITIVE


def test_word_amount_alone_is_not_calculation():
    assert classify("액면 금액은 1,000,000원이다. 세무조정에 대한 설명으로 틀린 것은?", C4) == NEGATIVE
    assert classify("장부금액을 결정할 수 있는 사유로 옳지 않은 것은?", C4) == NEGATIVE
    assert classify("당기순이익은 얼마인가?", C4) == CALCULATION
    assert classify("차입원가 자본화 금액을 구하시오.", C4) == CALCULATION


def test_combination_comes_before_numeric_choices_and_count_questions():
    assert classify("옳은 것만 고른 것은? 가. 금액을 나. ...", ["가, 나", "가, 다", "나, 다", "다, 라"]) == COMBINATION
    assert classify("틀린 것은 모두 몇 개인가?", ["1개", "2개", "3개", "4개"]) == COMBINATION
    assert classify("수량을 구하면 각각 몇 개인가?", ["10개", "20개", "30개", "40개"]) == CALCULATION


def test_noun_phrase_choices_without_strong_marker_are_identify():
    assert classify("조업도의 변동에 관련없이 그 단위당원가가 일정한 원가는?", ["변동원가", "고정원가", "준변동원가", "기초원가"]) == IDENTIFY
    assert classify("다음 중 면세대상에 해당 하는 것은?", NOUNS) == IDENTIFY
    assert classify("다음 중 개별원가계산에 대한 설명은?", C4) == POSITIVE                   # 문장 보기는 식별형이 아니다


def test_previously_undetermined_negative_meaning_questions():
    cases = {
        "108-13": ("다음 중 소득세법상 성실신고확인서 제출사업자가 적용받을 수 없는 세액공제는 무엇인가?", NOUNS),
        "113-6": ("다음 중 제조원가명세서상 당기제품제조원가에 영향을 미치지 않는 거래는 무엇인가?",
                  ["당기에 투입된 직접노무원가를 과대계상하였다.", "기초 제품 원가를 과소계상하였다.",
                   "당기에 투입된 원재료를 과소계상하였다.", "생산공장에서 사용된 소모품을 과대계상하였다."]),
        "115-12": ("다음 중 소득세법상 원천징수의무자가 간이지급명세서를 제출하지 않아도 되는 소득은?",
                   ["원천징수대상 사업소득", "인적용역 관련 기타소득", "일용직 근로소득", "상용직 근로소득"]),
    }
    for qid, (q, choices) in cases.items():
        assert strong_polarity(q) == NEGATIVE, qid
        assert classify(q, choices) == NEGATIVE, qid


def test_unknown_remains_for_questions_without_any_marker():
    assert classify("공손품에 대하여 서술하시오", C4) == UNKNOWN


def test_all_correct_question_is_excluded_from_card_sentences(tmp_path):
    conn = connect(tmp_path / "ac.db")
    load_bank(conn, [(1, [item(1, "다음 중 공손에 대한 설명으로 틀린 것은?", C4, "1,2,3,4"),
                          item(2, "다음 중 공손에 대한 설명으로 틀린 것은?", ["정상공손은 원가다.", "비정상공손은 기간비용이다.",
                                                                  "공손품은 불량품이다.", "공손은 폐기한다."], "4")])])
    from tutor.search import search_theory
    found = search_theory("공손", conn, entries=[], limit=10)
    summary = build_summary(conn, found["results"], found["terms"])
    kinds = {e["id"]: e["kind"] for e in summary["excluded"]}
    assert kinds == {"1-1": ALL_CORRECT_KIND}
    sources = sum((s["sources"] for s in summary["right"] + summary["traps"]), [])
    assert "1-1" not in sources and "1-2" in sources


def test_real_bank_examples_and_distribution(tmp_path):
    from tutor.bank import BANK_DIR, read_bank_files
    conn = connect(tmp_path / "real.db")
    load_bank(conn, read_bank_files(BANK_DIR))
    kind = {r["id"]: classify(r["question"], json.loads(r["choices"])) for r in conn.execute("SELECT * FROM questions")}
    assert kind["127-2"] == POSITIVE and kind["112-9"] == POSITIVE
    assert kind["72-13"] == NEGATIVE and kind["124-1"] == NEGATIVE
    assert {kind[i] for i in ("108-13", "113-6", "115-12")} == {NEGATIVE}
    assert {kind[i] for i in ("82-5", "83-14", "125-4", "75-6")} == {COMBINATION}
    assert kind["66-15"] == IDENTIFY and kind["68-9"] == IDENTIFY
    assert sum(1 for v in kind.values() if v == UNKNOWN) <= 10
    assert len(kind) == 540
