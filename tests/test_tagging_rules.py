"""단원 태그: 문제 글 → 보기 → 해설 순서와 '기타' 제거를 실제 문제은행으로 확인한다."""
from tutor.db import connect
from tutor.tagging import tag_question

MERGED_AWAY = {"기타", "리스", "결산·발생주의", "현금흐름표", "금융소득", "퇴직·연금·기타소득"}


def test_question_text_wins_over_choices_and_explanation():
    _, _, unit = tag_question(1, "재고자산에 대한 설명으로 옳은 것은?", ["유형자산 감가상각"], "")
    assert unit == "재고자산"


def test_choices_used_only_when_question_has_no_unit_word():
    _, _, unit = tag_question(1, "다음 설명으로 옳은 것은?", ["재고자산의 저가법"], "유형자산")
    assert unit == "재고자산"


def test_real_bank_has_no_other_or_tiny_units():
    rows = connect().execute("SELECT id, unit FROM questions").fetchall()
    assert rows
    assert not [r["id"] for r in rows if r["unit"] in MERGED_AWAY]


def test_audit_misclassified_questions_moved():
    got = {r["id"]: r["unit"] for r in connect().execute("SELECT id, unit FROM questions")}
    assert got["124-3"] == "재무제표·개념체계"
    assert got["114-7"] == "종합원가계산"
    assert got["74-3"] == "무형자산"
    assert got["126-5"] == "자본"


def test_deferred_tax_and_financial_retirement_units_are_separate():
    got = {r["id"]: r["unit"] for r in connect().execute("SELECT id, unit FROM questions")}
    assert {got[i] for i in ("115-5", "121-5", "128-2")} == {"법인세회계"}
    assert {got[i] for i in ("70-12", "120-13", "122-12", "123-15")} == {"금융·퇴직·기타소득"}
