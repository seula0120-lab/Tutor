"""SQLite 연결과 테이블 정의.

문제은행(questions)·검색 색인(theory_fts)은 bank JSON 에서 다시 만드는 '파생 데이터'라 적재 때 비운다.
풀이 기록(records)·즐겨찾기(favorites)·모의고사 결과(mock_results)는 사용자가 만든 데이터라
적재가 건드리지 않는다(문항 id 는 외래키로 묶지 않는다: 문제은행을 다시 채워도 기록이 남게 하려는 것).
"""
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

CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    choice      TEXT NOT NULL,      -- 고른 보기 번호. '정답 보기로 확인'이면 '' , 모의고사 미응답도 ''
    correct     INTEGER,            -- 1 정답 / 0 오답 / NULL 확인만 함(정오 판단 없음)
    seen_only   INTEGER NOT NULL,   -- 1 이면 '정답·해설 바로 보기'로 확인만 한 기록(정답으로 세지 않는다)
    source      TEXT NOT NULL,      -- quiz / mock
    ts          REAL NOT NULL       -- 푼 시각(epoch 초)
);
CREATE INDEX IF NOT EXISTS records_question ON records(question_id);
CREATE TABLE IF NOT EXISTS favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query      TEXT NOT NULL UNIQUE,
    scope      TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS glossary_review (
    term             TEXT PRIMARY KEY,
    status           TEXT NOT NULL,     -- '' / 검토 완료 / 수정 필요
    memo             TEXT NOT NULL,
    proposed_meaning TEXT NOT NULL,     -- 고쳐 쓰자고 제안한 풀이(없으면 '')
    updated          REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS study_progress (
    unit    TEXT PRIMARY KEY,
    status  TEXT NOT NULL,              -- '' / read(읽음) / understood(이해함)
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS study_review (
    unit    TEXT NOT NULL,
    section TEXT NOT NULL,              -- concept / practice / formula: 사람이 '검토 완료' 로 바꾼 AI 초안 칸
    updated REAL NOT NULL,
    PRIMARY KEY (unit, section)
);
CREATE TABLE IF NOT EXISTS mock_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at   REAL NOT NULL,
    score      INTEGER NOT NULL,
    max_score  INTEGER NOT NULL,
    by_subject TEXT NOT NULL,       -- JSON {과목: {score, max}}
    wrong_ids  TEXT NOT NULL        -- JSON 목록
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
