"""하나의 검증 명령: 단위 테스트와 검색 평가를 돌려 통과/실패/미실행으로 보고한다.

사용법: .venv/bin/python scripts/verify.py
- 단위 테스트(pytest): 통과 / 실패
- 검색 평가(hit@3): data/tutor.db 가 없으면 미실행. 있으면 목표(80%) 이상이면 통과, 아니면 실패.
- 실제 Claude 호출 검증은 API 키가 필요해 이 명령에 넣지 않는다(미실행으로 표시).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_search import DEFAULT_SET, TARGET, evaluate  # noqa: E402
from tutor.db import DB_PATH, connect  # noqa: E402


def run_unit_tests():
    """pytest 를 돌려 '통과' 또는 '실패' 와 요약 줄을 돌려준다."""
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True)
    summary = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr.strip()[-200:]
    return ("통과" if proc.returncode == 0 else "실패"), summary


def run_search_eval():
    """검색 평가를 돌려 (상태, 설명) 을 돌려준다. DB 가 없으면 미실행."""
    if not DB_PATH.exists():
        return "미실행", "data/tutor.db 없음 (scripts/load_db.py 먼저)"
    conn = connect()
    try:
        outcome = evaluate(DEFAULT_SET, conn)
    finally:
        conn.close()
    rate = outcome["hits"] / outcome["total"]
    status = "통과" if rate >= TARGET else "실패"
    return status, f"hit@3 {outcome['hits']}/{outcome['total']} = {rate:.0%} (목표 {TARGET:.0%})"


def main():
    """단위 테스트와 검색 평가를 돌려 결과를 보고한다."""
    results = [
        ("단위 테스트", *run_unit_tests()),
        ("검색 평가", *run_search_eval()),
        ("화면 자동 점검", "미실행(수동)", "필요할 때 node scripts/check_ui.mjs (Chrome 필요)"),
        ("Claude 실제 호출", "미실행", "API 키가 필요한 검증은 이 명령에 포함하지 않음"),
    ]
    for name, status, detail in results:
        print(f"{name}: {status} - {detail}")
    failed = any(status == "실패" for _, status, _ in results)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
