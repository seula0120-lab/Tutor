"""SQLite 연결과 테이블 정의.

문제은행(questions)·검색 색인(theory_fts)은 bank JSON 에서 다시 만드는 '파생 데이터'라 적재 때 비운다.
풀이 기록(records)·즐겨찾기(favorites)·모의고사 결과(mock_results)는 사용자가 만든 데이터라
적재가 건드리지 않는다(문항 id 는 외래키로 묶지 않는다: 문제은행을 다시 채워도 기록이 남게 하려는 것).
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tutor.db"

"""SQLite 연결과 테이블 정의.

문제은행(questions)·검색 색인(theory_fts)은 bank JSON 에서 다시 만드는 '파생 데이터'라 적재 때 비운다. 모두가 같이 쓴다(용어 사전 검토 glossary_review 도 같이 쓴다).
개인 기록 표(PERSONAL)는 사람마다 따로 쓴다: 모든 줄에 user_id 가 있고, 조회·저장은 연결의 user_id(conn.user_id)만 다룬다.
  records·favorites·study_progress·study_review·settings·daily_plan·mock_results·plans·plan_settings
적재가 건드리지 않는다(문항 id 는 외래키로 묶지 않는다: 문제은행을 다시 채워도 기록이 남게 하려는 것).

로그인 이전 DB 는 connect 때 자동으로 옮긴다(migrate): user_id 열이 없는 표에 user_id 를 넣고 기존 줄은 user_id = 0('주인 없음')으로 둔다.
첫 관리자 계정을 만들 때 auth.create_first_admin 이 user_id = 0 인 줄을 모두 그 계정으로 넘긴다. 몇 번을 돌려도 결과가 같다.
conn.user_id 가 0 인 연결은 '주인 없음' 줄을 본다(로그인 전 기록을 다루는 도구·테스트용). 웹 서버는 로그인한 사람의 id 만 넣는다.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tutor.db"

SHARED_SCHEMA = """
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

CREATE TABLE IF NOT EXISTS glossary_review (
    term             TEXT PRIMARY KEY,
    status           TEXT NOT NULL,     -- '' / 검토 완료 / 수정 필요
    memo             TEXT NOT NULL,
    proposed_meaning TEXT NOT NULL,     -- 고쳐 쓰자고 제안한 풀이(없으면 '')
    updated          REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,   -- 로그인 아이디(소문자로 저장)
    password_hash TEXT NOT NULL,          -- scrypt$n$r$p$소금$해시 (평문은 저장하지 않는다)
    display_name  TEXT NOT NULL,
    is_admin      INTEGER NOT NULL,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,          -- 쿠키 값의 sha256 (쿠키 값 자체는 저장하지 않는다)
    user_id    INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""

# 개인 기록 표의 새 정의. 이미 있는 옛 표는 migrate 가 같은 모양으로 다시 만든다(기본키에 user_id 를 넣으려고).
PERSONAL = {
    "records": """CREATE TABLE records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL DEFAULT 0,
    question_id TEXT NOT NULL,          -- 기출 문항 id 또는 'ox:<문장 키>'
    choice      TEXT NOT NULL,      -- 고른 보기 번호. '정답 보기로 확인'이면 '' , 모의고사 미응답도 ''
    correct     INTEGER,            -- 1 정답 / 0 오답 / NULL 확인만 함(정오 판단 없음)
    seen_only   INTEGER NOT NULL,   -- 1 이면 '정답·해설 바로 보기'로 확인만 한 기록(정답으로 세지 않는다)
    source      TEXT NOT NULL,      -- quiz / mock / ox
    ts          REAL NOT NULL       -- 푼 시각(epoch 초)
)""",
    "favorites": """CREATE TABLE favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL DEFAULT 0,
    query      TEXT NOT NULL,
    scope      TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (user_id, query)
)""",
    "study_progress": """CREATE TABLE study_progress (
    user_id INTEGER NOT NULL DEFAULT 0,
    unit    TEXT NOT NULL,
    status  TEXT NOT NULL,              -- '' / read(읽음) / understood(이해함)
    updated REAL NOT NULL,
    PRIMARY KEY (user_id, unit)
)""",
    "study_review": """CREATE TABLE study_review (
    user_id INTEGER NOT NULL DEFAULT 0,
    unit    TEXT NOT NULL,
    section TEXT NOT NULL,              -- concept / practice / formula: 사람이 '검토 완료' 로 바꾼 AI 초안 칸
    updated REAL NOT NULL,
    PRIMARY KEY (user_id, unit, section)
)""",
    "settings": """CREATE TABLE settings (
    user_id INTEGER NOT NULL DEFAULT 0,
    key     TEXT NOT NULL,              -- 오늘의 공부 하루 분량: daily_notes / daily_ox / daily_questions
    value   INTEGER NOT NULL,
    PRIMARY KEY (user_id, key)
)""",
    "daily_plan": """CREATE TABLE daily_plan (
    user_id INTEGER NOT NULL DEFAULT 0,
    day     INTEGER NOT NULL,           -- clock 의 일 번호
    units   TEXT NOT NULL,              -- JSON 단원 이름 목록(그날 처음 열 때 정해 하루 동안 고정)
    PRIMARY KEY (user_id, day)
)""",
    "plans": """CREATE TABLE plans (
    user_id INTEGER NOT NULL DEFAULT 0,
    day     INTEGER NOT NULL,           -- clock 의 일 번호
    kind    TEXT NOT NULL,              -- note / ox / quiz / review / mock / rest(그날 쉬기)
    unit    TEXT NOT NULL,              -- 단원 이름(복습·모의고사·쉬는 날, 단원 없는 기출은 '')
    target  INTEGER NOT NULL,           -- 목표 수량(노트는 1, 모의고사는 회수)
    edited  INTEGER NOT NULL,           -- 1 이면 사람이 고친 줄: 다시 자동 생성해도 그날은 덮어쓰지 않는다
    PRIMARY KEY (user_id, day, kind, unit)
)""",
    "plan_settings": """CREATE TABLE plan_settings (
    user_id INTEGER NOT NULL DEFAULT 0,
    key     TEXT NOT NULL,              -- exam_day / start_day(일 번호) / rest_days('0,6' 월=0) / final_days / review_per_day
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
)""",
    "mock_results": """CREATE TABLE mock_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL DEFAULT 0,
    taken_at   REAL NOT NULL,
    score      INTEGER NOT NULL,
    max_score  INTEGER NOT NULL,
    by_subject TEXT NOT NULL,       -- JSON {과목: {score, max}}
    wrong_ids  TEXT NOT NULL        -- JSON 목록
)""",
}
INDEXES = """
CREATE INDEX IF NOT EXISTS records_question ON records(user_id, question_id);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
"""
BACKUP_SUFFIX = ".before-login.bak"


class Connection(sqlite3.Connection):
    """user_id: 이 연결이 다루는 사람(0 = 로그인 전 기록). 개인 기록 표의 모든 조회·저장이 이 값을 쓴다."""
    user_id = 0
    token = ''        # 지금 쿠키 토큰(내 비밀번호를 바꿀 때 이 세션만 남기려고)
    user = None       # 로그인한 사람(auth 의 사용자 dict). 관리자 확인에 쓴다.


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def migrate(conn, path=None):
    """로그인 이전 DB 를 새 모양으로 옮긴다. 이미 새 모양이면 아무것도 하지 않는다(여러 번 돌려도 같은 결과).
    옮기기 전에 파일 DB 는 한 번 백업한다(<DB>.before-login.bak)."""
    old = [t for t in PERSONAL if _columns(conn, t) and "user_id" not in _columns(conn, t)]
    if not old:
        return []
    if path is not None and Path(path).exists() and not Path(str(path) + BACKUP_SUFFIX).exists():
        backup = sqlite3.connect(str(path) + BACKUP_SUFFIX)
        conn.backup(backup)
        backup.close()
    with conn:
        for table in old:
            columns = _columns(conn, table)
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
            conn.execute(PERSONAL[table])
            names = ", ".join(columns)
            conn.execute(f"INSERT INTO {table}(user_id, {names}) SELECT 0, {names} FROM {table}_old")
            conn.execute(f"DROP TABLE {table}_old")
    return old


def connect(path=None):
    """DB 에 연결하고 테이블을 만든(또는 옛 모양을 옮긴) 뒤 돌려준다. 행은 이름으로 읽는다(row['id'])."""
    path = Path(path) if path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, factory=Connection)
    conn.row_factory = sqlite3.Row
    conn.executescript(SHARED_SCHEMA)
    migrate(conn, path)
    for table, create in PERSONAL.items():
        if not _columns(conn, table):
            conn.execute(create)
    conn.executescript(INDEXES)
    conn.commit()
    return conn
