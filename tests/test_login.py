"""로그인·계정별 기록 분리: 두 사람의 기록이 섞이지 않고, 틀린 비밀번호는 막히며, 로그인 없이는 API 가 401 이고, 옛 기록은 첫 관리자에게 남는다."""
import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tutor import auth, favorites, records
from tutor.db import BACKUP_SUFFIX, PERSONAL, connect
from tutor.web import Handler

PERSONAL_TABLES = ("records", "favorites", "study_progress", "study_review", "settings", "daily_plan", "mock_results", "plans", "plan_settings")


@pytest.fixture(autouse=True)
def fresh_throttle():
    auth.reset_throttle()


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def as_user(conn, user):
    conn.user_id = user["id"]
    return conn


def put_question(conn, qid="q1"):
    conn.execute("INSERT OR IGNORE INTO questions(id, round, number, subject, tax, unit, points, question, choices, answer, explanation) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (qid, 1, 1, "재무회계", "", "단원", 5, "문제", "[]", "1", ""))
    conn.commit()


def save_wrong(conn, qid):
    conn.execute(
        "INSERT INTO records(user_id, question_id, choice, correct, seen_only, source, ts) VALUES (?,?,?,?,?,?,?)",
        (conn.user_id, qid, "2", 0, 0, "quiz", 1.0))
    conn.commit()


# ------------------------------------------------------------------ 비밀번호·계정
def test_password_is_hashed_with_salt_and_checked(conn):
    user = auth.create_user(conn, "Alice", "correct-horse", "앨리스")
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert "correct-horse" not in stored and stored.startswith("scrypt$")
    auth.create_user(conn, "bob", "correct-horse")
    hashes = [r[0] for r in conn.execute("SELECT password_hash FROM users")]
    assert hashes[0] != hashes[1]                       # 소금이 달라 같은 비밀번호도 다른 값
    assert user["username"] == "alice"                  # 아이디는 소문자로 저장
    assert auth.authenticate(conn, "ALICE", "correct-horse")["name"] == "앨리스"


def test_wrong_password_and_unknown_user_fail_the_same_way(conn):
    auth.create_user(conn, "alice", "correct-horse")
    for username, password in (("alice", "wrong-password"), ("nobody", "correct-horse"), ("alice", None)):
        with pytest.raises(auth.LoginError) as err:
            auth.authenticate(conn, username, password)
        assert "아이디 또는 비밀번호" in str(err.value)


def test_repeated_failures_lock_the_username_for_a_while(conn):
    auth.create_user(conn, "alice", "correct-horse")
    for n in range(auth.THROTTLE_FAILS):
        with pytest.raises(auth.LoginError):
            auth.authenticate(conn, "alice", "bad", now=1000 + n)
    with pytest.raises(auth.LoginError) as err:
        auth.authenticate(conn, "alice", "correct-horse", now=1010)   # 맞는 비밀번호도 잠시 막힌다
    assert "잠시" in str(err.value)
    assert auth.authenticate(conn, "alice", "correct-horse", now=1000 + auth.THROTTLE_SECONDS + 10)


@pytest.mark.parametrize("username,password", [("ab", "longenough"), ("has space", "longenough"), ("alice", "short")])
def test_bad_account_input_is_rejected(conn, username, password):
    with pytest.raises(ValueError):
        auth.create_user(conn, username, password)


def test_duplicate_username_rejected_and_first_admin_only_once(conn):
    auth.create_first_admin(conn, "admin", "admin-pass-1")
    with pytest.raises(ValueError):
        auth.create_first_admin(conn, "other", "other-pass-1")
    with pytest.raises(ValueError):
        auth.create_user(conn, "ADMIN", "another-pass-1")


def test_session_token_stored_only_as_hash_and_expires(conn):
    user = auth.create_user(conn, "alice", "correct-horse")
    token = auth.create_session(conn, user["id"], now=100)
    assert token not in conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert auth.user_for_token(conn, token, now=200)["username"] == "alice"
    assert auth.user_for_token(conn, token + "x", now=200) is None
    assert auth.user_for_token(conn, token, now=100 + auth.SESSION_SECONDS + 1) is None
    auth.delete_session(conn, token)
    assert auth.user_for_token(conn, token, now=200) is None


# ------------------------------------------------------------------ 계정별 기록 분리
def test_two_users_records_are_isolated(conn):
    put_question(conn)
    alice = auth.create_user(conn, "alice", "correct-horse")
    bob = auth.create_user(conn, "bob", "correct-horse")
    as_user(conn, alice)
    save_wrong(conn, "q1")
    favorites.add(conn, "감가상각", "all")
    assert len(records.notebook(conn)) == 1 and len(favorites.list_all(conn)) == 1
    as_user(conn, bob)
    assert records.notebook(conn) == [] and favorites.list_all(conn) == []
    assert records.unit_stats(conn) == {} and records.correct_ids(conn) == set()
    favorites.add(conn, "감가상각", "all")           # 같은 검색어도 사람마다 따로
    as_user(conn, alice)
    favorites.remove(conn, "감가상각")
    assert favorites.list_all(conn) == []
    as_user(conn, bob)
    assert len(favorites.list_all(conn)) == 1


# ------------------------------------------------------------------ 옛 기록 옮기기
def make_legacy_db(path):
    """로그인 기능 이전의 DB(user_id 열이 없다)를 흉내 낸다."""
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT NOT NULL, choice TEXT NOT NULL,
        correct INTEGER, seen_only INTEGER NOT NULL, source TEXT NOT NULL, ts REAL NOT NULL);
    CREATE TABLE favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, created_at REAL NOT NULL);
    CREATE TABLE study_progress (unit TEXT PRIMARY KEY, status TEXT NOT NULL, updated REAL NOT NULL);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
    INSERT INTO records(question_id, choice, correct, seen_only, source, ts) VALUES ('q1','2',0,0,'quiz',1.0),('q2','1',1,0,'quiz',2.0);
    INSERT INTO favorites(query, scope, created_at) VALUES ('감가상각','all',1.0);
    INSERT INTO study_progress VALUES ('유형자산','read',1.0);
    INSERT INTO settings VALUES ('daily_ox', 30);
    """)
    c.commit()
    c.close()


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in PERSONAL_TABLES}


def test_legacy_rows_survive_migration_and_go_to_first_admin(tmp_path):
    path = tmp_path / "legacy.db"
    make_legacy_db(path)
    conn = connect(path)
    assert counts(conn)["records"] == 2 and counts(conn)["favorites"] == 1 and counts(conn)["settings"] == 1
    assert conn.execute("SELECT DISTINCT user_id FROM records").fetchall()[0][0] == 0
    assert (tmp_path / ("legacy.db" + BACKUP_SUFFIX)).exists()            # 옮기기 전 백업
    before = counts(conn)
    admin = auth.create_first_admin(conn, "admin", "admin-pass-1")
    assert [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM records")] == [admin["id"]]
    assert counts(conn) == before                                          # 한 줄도 잃지 않는다
    as_user(conn, admin)
    assert len(favorites.list_all(conn)) == 1
    assert conn.execute("SELECT value FROM settings WHERE user_id = ? AND key = 'daily_ox'", (admin["id"],)).fetchone()[0] == 30
    # 새 사람은 그 기록을 보지 못한다
    other = auth.create_user(conn, "bob", "bob-password")
    assert favorites.list_all(as_user(conn, other)) == []
    conn.close()
    again = connect(path)                                                  # 다시 열어 옮겨도 같다(멱등)
    assert counts(again) == before
    assert auth.claim_legacy(again, admin["id"]) == {t: 0 for t in PERSONAL_TABLES}
    again.close()


def test_every_personal_table_has_user_id(conn):
    for table in PERSONAL:
        assert "user_id" in [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    assert set(PERSONAL) == set(PERSONAL_TABLES)


# ------------------------------------------------------------------ 실제 서버로 확인
@pytest.fixture
def server(tmp_path):
    path = tmp_path / "web.db"
    connect(path).close()
    handler = type("H", (Handler,), {"db_path": path, "log_message": lambda *a: None})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", path
    httpd.shutdown()
    httpd.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def call(base, method, path, body=None, cookie=""):
    request = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Cookie": cookie})
    try:
        response = urllib.request.build_opener(NoRedirect).open(request)
    except urllib.error.HTTPError as err:
        response = err
    raw = response.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    return response.status, data, response.headers


def login(base, username, password):
    status, data, headers = call(base, "POST", "/api/login", {"username": username, "password": password})
    return status, (headers.get("Set-Cookie") or "").split(";")[0], headers.get("Set-Cookie") or ""


def test_api_requires_login_and_pages_redirect(server):
    base, _ = server
    for path in ("/api/notebook", "/api/today", "/api/favorites", "/api/users"):
        assert call(base, "GET", path)[0] == 401
    assert call(base, "POST", "/api/ox/answer", {})[0] == 401
    for page in ("/", "/study", "/ox", "/toc", "/admin"):
        status, _, headers = call(base, "GET", page)
        assert status == 302 and headers["Location"] == "/login"
    assert call(base, "GET", "/login")[0] == 200
    assert call(base, "GET", "/static/theme.css")[0] == 200


def test_setup_login_isolation_and_admin_only_over_http(server):
    base, path = server
    assert call(base, "GET", "/api/me")[1] == {"user": None, "needs_setup": True}
    status, data, headers = call(base, "POST", "/api/setup", {"username": "admin", "password": "admin-pass-1", "name": "관리자"})
    assert status == 200
    cookie_header = headers["Set-Cookie"]
    assert "HttpOnly" in cookie_header and "SameSite=Lax" in cookie_header
    admin_cookie = cookie_header.split(";")[0]
    assert call(base, "POST", "/api/setup", {"username": "x1x", "password": "password-1"})[0] == 403     # 두 번째 관리자는 못 만든다
    assert call(base, "GET", "/", cookie=admin_cookie)[0] == 200
    assert call(base, "GET", "/admin", cookie=admin_cookie)[0] == 200
    assert call(base, "GET", "/login", cookie=admin_cookie)[0] == 302

    assert call(base, "POST", "/api/users", {"username": "bob", "password": "bob-password", "name": "밥"}, admin_cookie)[0] == 200
    assert call(base, "POST", "/api/users", {"username": "bob", "password": "bob-password"}, admin_cookie)[0] == 400
    assert login(base, "bob", "wrong-password")[0] == 401
    status, bob_cookie, _ = login(base, "bob", "bob-password")
    assert status == 200
    assert call(base, "GET", "/api/users", cookie=bob_cookie)[0] == 403         # 관리자만
    assert call(base, "POST", "/api/users", {"username": "eve", "password": "eve-password"}, bob_cookie)[0] == 403
    assert call(base, "GET", "/admin", cookie=bob_cookie)[0] == 302

    c = connect(path)
    put_question(c)
    admin_id = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    c.execute("INSERT INTO records(user_id, question_id, choice, correct, seen_only, source, ts) VALUES (?,?,?,?,?,?,?)", (admin_id, "q1", "2", 0, 0, "quiz", 1.0))
    c.commit()
    c.close()
    assert len(call(base, "GET", "/api/notebook", cookie=admin_cookie)[1]["items"]) == 1
    assert call(base, "GET", "/api/notebook", cookie=bob_cookie)[1]["items"] == []

    assert call(base, "POST", "/api/logout", {}, bob_cookie)[0] == 200
    assert call(base, "GET", "/api/notebook", cookie=bob_cookie)[0] == 401         # 로그아웃하면 그 쿠키는 쓸 수 없다


def test_password_change_and_reset_over_http(server):
    base, _ = server
    _, _, headers = call(base, "POST", "/api/setup", {"username": "admin", "password": "admin-pass-1", "name": "관리자"})
    admin_cookie = headers["Set-Cookie"].split(";")[0]
    call(base, "POST", "/api/users", {"username": "bob", "password": "bob-password"}, admin_cookie)
    _, bob_cookie, _ = login(base, "bob", "bob-password")
    _, bob_cookie2, _ = login(base, "bob", "bob-password")                       # 다른 기기
    assert call(base, "POST", "/api/password", {"current": "wrong-password", "new": "new-password-1"})[0] == 401   # 로그인 없이
    assert call(base, "POST", "/api/password", {"current": "wrong-password", "new": "new-password-1"}, bob_cookie)[0] == 403
    assert call(base, "POST", "/api/password", {"current": "bob-password", "new": "short"}, bob_cookie)[0] == 400
    assert call(base, "POST", "/api/password", {"current": "bob-password", "new": "new-password-1"}, bob_cookie)[0] == 200
    assert call(base, "GET", "/api/notebook", cookie=bob_cookie)[0] == 200          # 지금 세션은 유지
    assert call(base, "GET", "/api/notebook", cookie=bob_cookie2)[0] == 401         # 다른 기기는 로그아웃
    assert login(base, "bob", "bob-password")[0] == 401 and login(base, "bob", "new-password-1")[0] == 200
    bob_id = next(u["id"] for u in call(base, "GET", "/api/users", cookie=admin_cookie)[1]["users"] if u["username"] == "bob")
    assert call(base, "POST", "/api/users/password", {"user_id": bob_id, "password": "reset-password-1"}, bob_cookie)[0] == 403
    assert call(base, "POST", "/api/users/password", {"user_id": bob_id, "password": "reset-password-1"}, admin_cookie)[0] == 200
    assert call(base, "GET", "/api/notebook", cookie=bob_cookie)[0] == 401
    assert login(base, "bob", "reset-password-1")[0] == 200
