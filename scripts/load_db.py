"""data/bank 의 이론 기출을 data/tutor.db 에 적재한다. 몇 번 돌려도 결과가 같다.

사용법: .venv/bin/python scripts/load_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tutor.bank import load_bank, read_bank_files  # noqa: E402
from tutor.db import connect  # noqa: E402


def main():
    conn = connect()
    count = load_bank(conn, read_bank_files())
    rounds = conn.execute("SELECT COUNT(DISTINCT round) FROM questions").fetchone()[0]
    print(f"적재 완료: {rounds}회차, 이론 {count}문항")
    conn.close()


if __name__ == "__main__":
    main()
