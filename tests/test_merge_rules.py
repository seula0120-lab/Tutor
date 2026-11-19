"""요약 카드 문장 합치기: 뜻이 반대이거나 숫자가 다른 문장은 합치지 않는다."""
import pytest

from tutor.summary import is_similar, merge_sentences


@pytest.mark.parametrize("a,b", [
    ("당기순이익이 증가하고 자본이 증가한다.", "당기순이익이 증가하고 자본이 감소한다."),
    ("당사는 주식을 할인발행하였다.", "당사는 주식을 할증발행하였다."),
    ("해당 지출은 취득원가에 포함한다.", "해당 지출은 취득원가에서 제외한다."),
    ("매입세액공제가 가능하다.", "매입세액공제가 불가능하다."),
    ("손금산입하여야 한다.", "손금불산입하여야 한다."),
    ("1,000,000원을 지급하였다.", "6,000,000원을 지급하였다."),
    ("재고가 있으면 총이익이 달라진다.", "재고가 없으면 총이익이 달라진다."),
])
def test_opposite_or_different_number_sentences_are_not_similar(a, b):
    assert not is_similar(a, b)


def test_same_meaning_wording_variants_still_merge():
    assert is_similar("표준원가와 실제원가의 차이를 분석하여 예외에 의한 관리가 가능하다.",
                      "표준원가와 실제원가의 차이를 분석하여 예외에 의한 관리를 가능하게 한다.")


def test_choices_of_the_same_question_are_never_merged():
    entries = [("과대계상 과대계상 과소계상", "1-1", 1, False), ("과대계상 과소계상 과소계상", "1-1", 1, False)]
    assert len(merge_sentences(entries)) == 2


def test_same_sentence_from_two_questions_merges_with_both_sources():
    entries = [("정액법은 매년 같은 금액을 상각한다.", "1-1", 1, False), ("정액법은 매년 같은 금액을 상각한다.", "2-1", 2, False)]
    groups = merge_sentences(entries)
    assert len(groups) == 1 and groups[0]["count"] == 2
