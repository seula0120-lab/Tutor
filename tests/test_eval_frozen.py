"""동결 평가셋(data/search_eval_frozen.jsonl)의 형식을 지킨다. 점수는 검색을 고칠 때 전·후 비교용이며 목표를 강제하지 않는다."""
import json
from pathlib import Path

from tutor.db import connect

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    return [json.loads(l) for l in (DATA / name).read_text(encoding="utf-8").splitlines() if l.strip()]


def test_frozen_set_shape_and_no_overlap():
    frozen, level1 = _load("search_eval_frozen.jsonl"), _load("search_eval_level1.jsonl")
    assert len(frozen) == 30
    assert len({c["id"] for c in frozen}) == 30
    assert not {c["query"] for c in frozen} & {c["query"] for c in level1}
    known = {r["id"] for r in connect().execute("SELECT id FROM questions")}
    for case in frozen:
        assert case["query"] and case["expected"]
        assert set(case["expected"]) <= known, case["id"]
