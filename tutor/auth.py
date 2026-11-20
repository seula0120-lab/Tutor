"""로그인: 사용자 계정·비밀번호·세션.

- 비밀번호는 hashlib.scrypt + 사람마다 다른 소금으로 저장한다(`scrypt$n$r$p$소금$해시`). 평문은 어디에도 남기지 않는다.
- 세션은 무작위 토큰을 쿠키로 주고, DB 에는 토큰의 sha256 만 둔다(DB 가 새도 쿠키를 만들 수 없다).
- 계정 만들기: 첫 실행 때 관리자 한 명을 만들고(create_first_admin, 이때 로그인 전 기록이 그 계정으로 넘어간다), 그다음 계정은 관리자가 만든다(create_user).
  공개 회원가입은 없다.
- 로그인 연속 실패는 아이디마다 잠깐 막는다(같은 네트워크에서 비밀번호를 대입해 보는 것을 늦춘다).
"""
import hashlib
import hmac
import os
import re
import secrets
import time

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
SESSION_SECONDS = 30 * 24 * 3600
USERNAME = re.compile(r"^[\w.\-]{3,30}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 200
THROTTLE_FAILS, THROTTLE_SECONDS = 5, 300
PERSONAL_TABLES = ("records", "favorites", "study_progress", "study_review", "settings", "daily_plan", "mock_results")

_failures = {}   # {아이디: [실패 시각]}


class LoginError(ValueError):
    """로그인할 수 없는 이유(화면에 그대로 보여 줄 수 있는 말)."""


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, bytes.fromhex(digest))


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _public(row):
    return {"id": row["id"], "username": row["username"], "name": row["display_name"], "is_admin": bool(row["is_admin"])}


def has_users(conn):
    return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def _clean(username, password, name):
    username = (username or "").strip().lower()
    name = (name or "").strip() or username
    if not USERNAME.match(username):
        raise ValueError("아이디는 3~30자의 글자·숫자·밑줄(_)·점(.)·하이픈(-)이어야 합니다.")
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise ValueError(f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다.")
    if len(name) > 30:
        raise ValueError("이름은 30자 이하여야 합니다.")
    return username, name


def create_user(conn, username, password, name="", is_admin=False, now=None):
    """계정 하나를 만든다. 아이디가 겹치거나 모양이 틀리면 ValueError."""
    username, name = _clean(username, password, name)
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise ValueError("이미 있는 아이디입니다.")
    with conn:
        cursor = conn.execute("INSERT INTO users(username, password_hash, display_name, is_admin, created_at) VALUES (?,?,?,?,?)",
                              (username, hash_password(password), name, int(bool(is_admin)), time.time() if now is None else now))
    return _public(conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone())


def claim_legacy(conn, user_id):
    """로그인 이전에 쌓인 기록(user_id = 0)을 이 계정으로 넘긴다. 다시 불러도 넘길 것이 없어 결과가 같다."""
    with conn:
        return {table: conn.execute(f"UPDATE {table} SET user_id = ? WHERE user_id = 0", (user_id,)).rowcount for table in PERSONAL_TABLES}


def create_first_admin(conn, username, password, name=""):
    """아직 계정이 하나도 없을 때만 관리자 계정을 만들고, 기존 기록을 그 계정으로 옮긴다."""
    if has_users(conn):
        raise ValueError("이미 계정이 있습니다. 관리자에게 계정을 만들어 달라고 하세요.")
    user = create_user(conn, username, password, name, is_admin=True)
    claim_legacy(conn, user["id"])
    return user


def list_users(conn):
    return [{**_public(r), "created_at": r["created_at"]} for r in conn.execute("SELECT * FROM users ORDER BY id")]


# ------------------------------------------------------------------ 로그인 시도 제한
def _recent_failures(username, now):
    kept = [t for t in _failures.get(username, []) if now - t < THROTTLE_SECONDS]
    _failures[username] = kept
    return kept


def authenticate(conn, username, password, now=None):
    """아이디·비밀번호가 맞으면 사용자 dict, 아니면 LoginError. 어느 쪽이 틀렸는지는 알려 주지 않는다."""
    now = time.time() if now is None else now
    username = (username or "").strip().lower()
    if len(_recent_failures(username, now)) >= THROTTLE_FAILS:
        raise LoginError("로그인에 여러 번 실패했습니다. 잠시 뒤에 다시 해 보세요.")
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    ok = verify_password(password if isinstance(password, str) else "", row["password_hash"] if row else _DUMMY_HASH)
    if not (row and ok):
        _failures.setdefault(username, []).append(now)
        raise LoginError("아이디 또는 비밀번호가 맞지 않습니다.")
    _failures.pop(username, None)
    return _public(row)


def reset_throttle():
    _failures.clear()


# ------------------------------------------------------------------ 세션
def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn, user_id, now=None):
    """세션을 만들고 쿠키에 넣을 토큰을 돌려준다."""
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                     (_token_hash(token), user_id, now, now + SESSION_SECONDS))
    return token


def user_for_token(conn, token, now=None):
    """쿠키 토큰의 주인(사용자 dict). 없거나 만료되었으면 None."""
    if not token:
        return None
    now = time.time() if now is None else now
    row = conn.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                          WHERE s.token_hash = ? AND s.expires_at > ?""", (_token_hash(token), now)).fetchone()
    return _public(row) if row else None


def delete_session(conn, token):
    if token:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
