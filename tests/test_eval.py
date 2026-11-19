import json

from scripts.eval_search import TOP_K, evaluate, judge_case, load_cases
from tutor.tagging import tag_question


def write_cases(tmp_path, cases):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n\n", encoding="utf-8")
    return path


def test_hit_requires_expected_within_top_k(conn, tmp_path):
    path = write_cases(tmp_path, [
        {"id": "A", "type": "t", "query": "저가법", "expected": ["1-1"]},
        {"id": "B", "type": "t", "query": "저가법", "expected": ["1-13"]},   # 결과에 없는 문항
    ])
    outcome = evaluate(path, conn)
    assert outcome["total"] == 2 and outcome["hits"] == 1
    assert outcome["cases"][0]["rank"] == 1 and outcome["cases"][1]["rank"] is None


def test_rank_beyond_top_k_is_not_a_hit(conn):
    case = {"id": "C", "type": "t", "query": "다음 중 설명으로 옳은 것은", "expected": ["2-11"]}
    result = judge_case(case, conn, None)
    assert result["hit"] == (result["rank"] is not None and result["rank"] <= TOP_K)


def test_blank_lines_skipped_and_real_set_is_well_formed():
    from scripts.eval_search import DEFAULT_SET
    cases = load_cases(DEFAULT_SET)
    assert len(cases) >= 10
    for case in cases:
        assert case["query"] and case["expected"] and all("-" in e for e in case["expected"])
    assert len({c["id"] for c in cases}) == len(cases)


def test_spaced_capital_expenditure_is_property_plant():
    _, _, unit = tag_question(2, "수익적 지출을 자본적 지출로 잘못 처리한 경우 영향은?", ["가"], "")
    assert unit == "유형자산"
