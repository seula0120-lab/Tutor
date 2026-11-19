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
