"""data/raw 의 새 회차 원본을 변환하고 DB 에 반영한다. 여러 번 돌려도 결과가 같다.

사용법: .venv/bin/python scripts/sync_raw.py
원본 위치: data/raw/<회차>/answer.pdf (또는 answer.hwp)
검사에 걸린 회차는 적재하지 않고 이유를 출력한다. 실패한 회차가 있으면 종료 코드 1.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tutor.db import connect  # noqa: E402
from tutor.sync import FAILED, format_report, sync_raw  # noqa: E402


def main():
    conn = connect()
    try:
        report = sync_raw(conn)
    finally:
        conn.close()
    print("\n".join(format_report(report)))
    sys.exit(1 if any(r["status"] == FAILED for r in report["rounds"]) else 0)


if __name__ == "__main__":
    main()
