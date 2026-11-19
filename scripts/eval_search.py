"""이론 기출 검색 품질을 질문셋으로 잰다(hit@3). API 를 쓰지 않는다.

사용법: .venv/bin/python scripts/eval_search.py [질문셋.jsonl] [--latest]
- 기본 질문셋은 data/search_eval_level1.jsonl(1급 수준 질문: 요건·예외·처리 차이·소득처분).
- 한 줄 = {"id", "type", "query", "expected": [정답 문항 id 목록]}.
- hit@3 = 검색 결과 상위 3개 안에 expected 중 하나라도 있는 질문의 비율. 제안 목표는 80%.
- 기본 검색 범위는 앱 기본값(전체 회차)이다. --latest 이면 최신 10회분만.
질문과 정답 문항은 사람이(또는 Claude 가) 정하는 것이며, 검색 결과를 보고 고치지 않는다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tutor.db import connect  # noqa: E402
from tutor.search import DEFAULT_ROUNDS, LATEST_ROUNDS, search_theory  # noqa: E402

DEFAULT_SET = ROOT / "data" / "search_eval_level1.jsonl"
TOP_K = 3
TARGET = 0.8


def load_cases(path):
    """질문셋 파일을 읽어 사례 목록으로 돌려준다(빈 줄은 건너뜀)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def judge_case(case, conn, round_limit):
    """사례 하나를 채점한다: 정답이 처음 나온 순위(없으면 None)와 상위 결과 id 를 돌려준다."""
    found = search_theory(case["query"], conn, round_limit=round_limit)
    ids = [r["id"] for r in found["results"]]
    rank = next((i + 1 for i, qid in enumerate(ids) if qid in case["expected"]), None)
    return {"id": case["id"], "type": case["type"], "query": case["query"], "rank": rank,
            "hit": rank is not None and rank <= TOP_K, "ids": ids, "expected": case["expected"]}


def evaluate(path, conn, round_limit=DEFAULT_ROUNDS):
    """질문셋 전체를 채점해 {"cases": [...], "hits": 맞은 수, "total": 전체 수} 로 돌려준다."""
    cases = [judge_case(c, conn, round_limit) for c in load_cases(path)]
    return {"cases": cases, "hits": sum(c["hit"] for c in cases), "total": len(cases)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    round_limit = LATEST_ROUNDS if "--latest" in sys.argv else DEFAULT_ROUNDS
    conn = connect()
    outcome = evaluate(args[0] if args else DEFAULT_SET, conn, round_limit)
    for c in outcome["cases"]:
        rank = c["rank"] or "-"
        print(f"{c['id']} {'통과' if c['hit'] else '실패'} 순위={rank} | {c['query']}")
        print(f"      결과 {c['ids']} / 정답 {c['expected']}")
    rate = outcome["hits"] / outcome["total"]
    scope = "전체 회차" if round_limit is None else f"최신 {round_limit}회분"
    print(f"hit@{TOP_K}: {outcome['hits']}/{outcome['total']} = {rate:.0%} (목표 {TARGET:.0%}, 범위 {scope})")


if __name__ == "__main__":
    main()
