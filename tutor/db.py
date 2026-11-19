"""SQLite 연결과 테이블 정의. 문제은행(questions)과 검색 색인(theory_fts) 두 개뿐이다."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tutor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id          TEXT PRIMARY KEY,   -- 예: 128-12 (회차-문항번호)
    round       INTEGER NOT NULL,
    number      INTEGER NOT NULL,
    subject     TEXT NOT NULL,      -- 재무회계 / 원가회계 / 세무회계
    tax         TEXT NOT NULL,      -- 세무회계만: 부가가치세 / 소득세 / 법인세, 나머지는 ''
    unit        TEXT NOT NULL,
    points      INTEGER NOT NULL,
    question    TEXT NOT NULL,
    choices     TEXT NOT NULL,      -- JSON 문자열 목록
    answer      TEXT NOT NULL,      -- '3' 또는 복수정답 '1,3'
    explanation TEXT NOT NULL
);
-- 3글자 이상 낱말 검색용 trigram 색인. 내용은 load_db 가 questions 와 함께 한 번에 채운다.
CREATE VIRTUAL TABLE IF NOT EXISTS theory_fts USING fts5(
    question_id UNINDEXED, content, tokenize='trigram'
);
"""


def connect(path=None):
    """DB 에 연결하고 테이블을 만든 뒤 돌려준다. 행은 이름으로 읽는다(row['id'])."""
    path = Path(path) if path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
