import json

import pytest

from conftest import item
from tutor.bank import load_bank
from tutor.db import connect
from tutor.question_type import (CALCULATION, COMBINATION, NEGATIVE, POSITIVE, UNKNOWN, classify)
from tutor.search import search_theory
from tutor.summary import build_summary, is_similar, merge_sentences, split_sentences

C4 = ["첫째 문장이다.", "둘째 문장이다.", "셋째 문장이다.", "넷째 문장이다."]   # 기호가 아닌 일반 문장 보기


# ---- 유형 판별 ----
@pytest.mark.parametrize("question", [
    "다음 중 공손에 대한 설명으로 옳지 않은 것은?",
    "다음 중 자기주식에 대한 설명으로 틀린 것은?",
    "다음 중 영세율 적용대상이 아닌 것은?",
    "다음 중 설명으로 가장 적절하지 않은 것은?",
    "다음 중 법인세법상 해당하지 않는 것은?",
    "다음 중 맞지 않는 것은?",
])
def test_negative_stems(question):
    assert classify(question, C4) == NEGATIVE


@pytest.mark.parametrize("question", [
    "다음 중 퇴직급여에 대한 설명으로 옳은 것은?",
    "다음 중 재고자산에 대한 설명으로 맞는 것은?",
    "다음 중 부가가치세법상 면세에 해당하는 것은?",
    "다음 중 가장 적절한 것은?",
])
def test_positive_stems(question):
    assert classify(question, C4) == POSITIVE


@pytest.mark.parametrize("question,choices", [
    ("다음 중 옳은 것만 모두 고른 것은? 가. 나. 다.", C4),
    ("다음 중 옳은 것으로만 짝지어진 것은?", C4),
    ("다음 중 면세에 해당하는 것은 몇 개인가?", C4),
    ("다음 중 올바른 설명은?", ["가, 나", "가, 다", "나, 다", "가, 나, 다"]),    # 보기가 기호 나열
    ("다음 중 옳은 설명은?", ["㉠, ㉡", "㉠, ㉢", "㉡, ㉢", "㉠, ㉡, ㉢"]),
])
def test_combination_questions(question, choices):
    assert classify(question, choices) == COMBINATION


@pytest.mark.parametrize("question,choices", [
    ("기말재공품 원가는 얼마인가?", C4),
    ("종합소득금액을 계산하면 얼마인가?", C4),
    ("다음 중 설명으로 옳은 것은?", ["1,000,000원", "2,000,000원", "3,000,000원", "4,500,000원"]),  # 보기가 전부 숫자
    ("정상공손의 수량을 구하면 각각 몇 개인가?", C4),
])
def test_calculation_questions(question, choices):
    assert classify(question, choices) == CALCULATION


def test_combination_wins_over_positive_and_unknown_is_flagged():
    assert classify("다음 중 옳은 것만 고른 것은?", C4) == COMBINATION      # '옳은 것' 이 들어 있어도 조합형
    assert classify("공손품에 대하여 서술하시오", C4) == UNKNOWN


# ---- 문장 나누기 ----
def make_conn(tmp_path, *rounds):
    conn = connect(tmp_path / "s.db")
    load_bank(conn, list(rounds))
    return conn


def row_of(conn, qid):
    return conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()


def test_negative_question_answer_is_the_false_sentence(tmp_path):
    conn = make_conn(tmp_path, (1, [item(1, "다음 중 공손에 대한 설명으로 옳지 않은 것은?", ["A문장", "B문장", "C문장", "D문장"], "2")]))
    right, wrong = split_sentences(row_of(conn, "1-1"), NEGATIVE)
    assert wrong == ["B문장"] and right == ["A문장", "C문장", "D문장"]


def test_positive_question_answer_is_the_true_sentence(tmp_path):
    conn = make_conn(tmp_path, (1, [item(1, "다음 중 공손에 대한 설명으로 옳은 것은?", ["A문장", "B문장", "C문장", "D문장"], "3")]))
    right, wrong = split_sentences(row_of(conn, "1-1"), POSITIVE)
    assert right == ["C문장"] and wrong == ["A문장", "B문장", "D문장"]


def test_multi_answer_sentences_are_all_counted(tmp_path):
    conn = make_conn(tmp_path, (1, [item(1, "다음 중 설명으로 옳지 않은 것은?", ["A문장", "B문장", "C문장", "D문장"], "1,3")]))
    right, wrong = split_sentences(row_of(conn, "1-1"), NEGATIVE)
    assert wrong == ["A문장", "C문장"] and right == ["B문장", "D문장"]


# ---- 문장 합치기 ----
def test_similar_sentences_merge_with_all_sources_latest_text_first():
    entries = [("정상공손은 제조원가에 포함한다.", "5-1", 5, False),
               ("정상공손은 제조원가에 포함한다", "9-2", 9, False),            # 문장부호만 다름
               ("비정상공손은 기간비용으로 처리한다.", "7-3", 7, False)]
    merged = merge_sentences(entries)
    assert merged[0]["count"] == 2 and merged[0]["sources"] == ["9-2", "5-1"]   # 최근 회차 대표, 출처 모두
    assert merged[1]["sources"] == ["7-3"]


def test_negation_difference_is_never_merged():
    a = "정상공손원가는 제품원가에 포함하여 처리하는 것이 원칙이다."
    b = "정상공손원가는 제품원가에 포함하여 처리하지 않는 것이 원칙이다."
    assert not is_similar(a, b)
    assert len(merge_sentences([(a, "1-1", 1, False), (b, "2-1", 2, False)])) == 2


def test_merge_orders_by_frequency_then_recency():
    entries = [("자주 나온 문장입니다 그렇습니다", "1-1", 1, False), ("자주 나온 문장입니다 그렇습니다.", "2-1", 2, False),
               ("전혀 다른 최근 문장 하나뿐이다", "9-1", 9, False), ("또 다른 옛날 문장 하나뿐이다", "3-1", 3, False)]
    merged = merge_sentences(entries)
    assert [g["count"] for g in merged] == [2, 1, 1]
    assert merged[1]["sources"] == ["9-1"]                                   # 같은 빈도면 최근 회차 먼저


# ---- 요약 카드 전체 ----
SAME = ["정상공손은 제품원가에 포함한다.", "비정상공손은 기간비용이다.", "공손품은 불량품이다.", "공손은 폐기한다."]
BANK = [
    (3, [item(6, "다음 중 공손에 대한 설명으로 옳지 않은 것은?", SAME, "4"),
         item(7, "다음 중 공손과 관련하여 옳은 것만 모두 고른 것은?", C4, "1"),
         item(8, "공손품 수량을 구하면 각각 몇 개인가?", C4, "2"),
         item(11, "다음 중 부가가치세법상 공손 관련 설명으로 옳은 것은?", ["세A공손", "세B공손", "세C공손", "세D공손"], "1")]),
    (8, [item(6, "다음 중 공손에 대한 설명으로 옳지 않은 것은?",
              ["정상공손은 제품원가에 포함한다", "비정상공손은 기간비용이다", "공손품은 불량품이다", "공손은 매각한다."], "4")]),
]


def card(tmp_path, query="공손"):
    conn = make_conn(tmp_path, *BANK)
    found = search_theory(query, conn, entries=[], limit=20)
    return build_summary(conn, found["results"])


def test_summary_collects_merged_right_and_trap_sentences_with_sources(tmp_path):
    summary = card(tmp_path)
    right = {s["text"]: s for s in summary["right"]}
    merged = right["정상공손은 제품원가에 포함한다"]            # 3회·8회가 한 문장으로 합쳐짐(최근 회차 글이 대표)
    assert merged["count"] == 2 and merged["sources"] == ["8-6", "3-6"]
    assert {s["text"] for s in summary["traps"]} == {"공손은 폐기한다.", "공손은 매각한다.", "세B공손", "세C공손", "세D공손"}
    assert "세A공손" in right                                      # 긍정형 문항의 정답 보기는 맞는 문장
    assert all(s["sources"] for s in summary["right"] + summary["traps"])


def test_combination_and_calculation_questions_only_listed(tmp_path):
    summary = card(tmp_path)
    kinds = {e["id"]: e["kind"] for e in summary["excluded"]}
    assert kinds == {"3-7": "조합형", "3-8": "계산형"}
    texts = " ".join(s["text"] for s in summary["right"] + summary["traps"])
    assert "가" not in texts.split() and "3-7" not in sum((s["sources"] for s in summary["right"] + summary["traps"]), [])


def test_coverage_counts_rounds_and_latest(tmp_path):
    cov = card(tmp_path)["coverage"]
    assert cov["rounds"] == [8, 3] and cov["round_count"] == 2 and cov["latest_round"] == 8
    assert cov["questions"] == 5


def test_tax_notice_only_when_tax_question_involved(tmp_path):
    summary = card(tmp_path)
    assert summary["tax_notice"] == "3회 · 세법 개정 확인 필요"
    taxed = [s for s in summary["right"] + summary["traps"] if "세" in s["text"][:1]]
    assert all(s["tax_notice"] == "3회 · 세법 개정 확인 필요" for s in taxed) and taxed
    plain = [s for s in summary["right"] + summary["traps"] if s["text"] == "공손은 폐기한다."]
    assert plain[0]["tax_notice"] is None                       # 원가회계 문장은 표시 없음


def test_summary_without_results_is_empty_card(tmp_path):
    conn = make_conn(tmp_path, *BANK)
    empty = build_summary(conn, [])
    assert empty["right"] == [] and empty["traps"] == [] and empty["coverage"]["questions"] == 0
    assert empty["tax_notice"] is None


def test_summary_does_not_mutate_database(tmp_path):
    conn = make_conn(tmp_path, *BANK)
    before = json.dumps([tuple(r) for r in conn.execute("SELECT * FROM questions ORDER BY id")], ensure_ascii=False)
    build_summary(conn, search_theory("공손", conn, entries=[], limit=20)["results"])
    after = json.dumps([tuple(r) for r in conn.execute("SELECT * FROM questions ORDER BY id")], ensure_ascii=False)
    assert before == after
