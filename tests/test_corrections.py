"""데이터 정정(data/corrections.json)과 '공식 해설 없음' 표시."""
import json

import pytest

from tutor.bank import BANK_DIR, read_bank_files
from tutor.corrections import apply_corrections, load_corrections
from tutor.db import connect
from tutor.quiz import NO_EXPLANATION, explanation_of


def _item(**kw):
    base = {"number": 1, "question": "제품원 가 문제", "choices": ["가", "나", "다", "라"], "answer": "1", "explanation": ""}
    return {**base, **kw}


def test_apply_replaces_and_does_not_mutate_input():
    original = [(1, [_item()])]
    fix = [{"id": "1-1", "field": "question", "before": "제품원 가", "after": "제품원가", "reason": "x"}]
    out = apply_corrections(original, fix)
    assert out[0][1][0]["question"] == "제품원가 문제"
    assert original[0][1][0]["question"] == "제품원 가 문제"


def test_apply_choice_field_and_skip_missing_question():
    fix = [{"id": "1-1", "field": "choices[2]", "before": "다", "after": "다음", "reason": "x"},
           {"id": "9-9", "field": "question", "before": "없음", "after": "x", "reason": "x"}]
    assert apply_corrections([(1, [_item()])], fix)[0][1][0]["choices"][2] == "다음"


def test_stale_correction_is_an_error():
    fix = [{"id": "1-1", "field": "question", "before": "없는글", "after": "x", "reason": "x"}]
    with pytest.raises(ValueError):
        apply_corrections([(1, [_item()])], fix)


def test_corrections_file_is_complete_and_applies_to_real_bank():
    entries = load_corrections()
    assert len(entries) >= 26
    for e in entries:
        assert {"id", "field", "before", "after", "reason"} <= set(e) and e["reason"]
    raw = {int(p.stem): json.loads(p.read_text(encoding="utf-8")) for p in BANK_DIR.glob("*.json")}
    assert "제품원 가" in raw[120]["theory"][8]["choices"][1]  # bank 원본은 그대로
    fixed = dict(read_bank_files())
    item = next(i for i in fixed[120] if i["number"] == 9)
    assert "제품원가" in item["choices"][1] and "제품원 가" not in item["choices"][1]


def test_db_has_corrected_text():
    row = connect().execute("SELECT question, choices FROM questions WHERE id='122-14'").fetchone()
    assert "세금계산서 관련" in row["question"]


def test_empty_explanation_shows_notice():
    assert explanation_of({"explanation": ""}) == NO_EXPLANATION == "공식 해설 없음"
    assert explanation_of({"explanation": "  "}) == NO_EXPLANATION
    assert explanation_of({"explanation": "해설"}) == "해설"


def test_73_9_choices_repaired_from_pdf():
    import json as _j
    row = connect().execute("SELECT choices FROM questions WHERE id='73-9'").fetchone()
    c = _j.loads(row["choices"])
    assert c[0].endswith("상대적으로 제조원가의 계산이 부정확함")
    assert "총생산량으로 나누어 단위당제조원가를 계산" in c[1] and "원가에 의하여 제조원가를 계산" in c[1]


def test_pdf_checked_line_wrap_fixes_are_applied():
    c = connect()
    def choice(qid, i):
        return json.loads(c.execute("SELECT choices FROM questions WHERE id=?", (qid,)).fetchone()["choices"])[i]
    assert "경우에는" in choice("120-2", 1) and "경우에 는" not in choice("120-2", 1)
    assert "발급하고" in choice("125-14", 1)
    assert "자본잉여금으로" in choice("114-4", 3)
    assert len([e for e in load_corrections() if "원문 PDF 확인" in e["reason"]]) == 14


def test_original_spacing_confirmed_in_pdf_is_left_alone():
    # 72-2·127-2 의 '회계처리 한' 은 원문 PDF 에도 띄어 쓴 그대로라 정정 목록에 없다
    row = connect().execute("SELECT question FROM questions WHERE id='127-2'").fetchone()
    assert "회계처리 한" in row["question"]
