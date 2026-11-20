"""로컬 웹 화면(127.0.0.1:8000)과 JSON API. 외부에는 열지 않는다.

실행: .venv/bin/python -m tutor.web [--port 8000]
dispatch() 는 소켓 없이 (상태코드, 내용) 만 돌려주는 함수라 테스트에서 그대로 부른다.
"""
import argparse
import json
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import auth, clock, daily, favorites, glossary_review, mock, ox, quiz, records, review, study
from .toc import build_toc
from .ai import explain
from .analysis import study_order, unit_profile
from .db import connect
from .glossary import annotate, load_glossary
from .search import DEFAULT_ROUNDS, LATEST_ROUNDS, RESULT_LIMIT, search_theory
from .summary import build_summary, covers_core_terms
from .sync import format_report, sync_raw

STATIC_DIR = Path(__file__).resolve().parent / "static"
HOST = "127.0.0.1"
# 주소 → (static 폴더의 파일, 내용 종류). 이 목록에 있는 파일만 내보낸다.
STATIC_FILES = {"/static/quizcard.js": ("quizcard.js", "text/javascript; charset=utf-8"),
                "/static/theme.css": ("theme.css", "text/css; charset=utf-8")}
FONT_FILES = {"PretendardVariable.woff2", "NotoSerifKR-600.woff2", "NotoSerifKR-latin-600.woff2"}   # /static/fonts/<이름> 으로만 내려 준다
# 화면(HTML) 주소 → static 폴더의 파일
PAGES = {"/": "index.html", "/index.html": "index.html", "/toc": "toc.html", "/glossary-review": "glossary_review.html", "/study": "study.html", "/study-changes": "tax_changes.html", "/ox": "ox.html", "/admin": "admin.html"}
LOGIN_PAGE = "login.html"          # 로그인 없이 볼 수 있는 화면은 이것 하나(/login)
COOKIE = "session"
ADMIN_PAGES = {"/admin"}
LOCAL_ADDRESSES = ("127.0.0.1", "::1")
SUMMARY_LIMIT = 20  # 요약 카드가 '관련 기출'로 보는 검색 상위 후보 수


def parse_scope(value, default=DEFAULT_ROUNDS):
    """'all' 이면 전체 회차(None), 숫자면 최신 그 회차 수, 비어 있으면 default(검색은 전체 회차)."""
    if value in (None, ""):
        return default
    if value == "all":
        return None
    number = int(value)
    if number < 1:
        raise ValueError("범위는 1 이상이어야 합니다.")
    return number


def api_annotated(conn, params):
    """문항의 질문과 보기에 용어 밑줄 주석을 단다. 정답·해설은 넣지 않는다."""
    question = quiz.find_question(conn, params["round"], params["number"])
    if question is None:
        return 404, {"error": "해당 회차·번호의 문항이 없습니다."}
    entries = load_glossary()
    meanings = {e["term"]: e["meaning"] for e in entries}
    return 200, {
        "id": question["id"], "meta": question,
        "question": annotate(question["question"], entries),
        "choices": [annotate(c, entries) for c in question["choices"]],
        "meanings": meanings,
    }


def api_glossary(conn, params):
    """용어 사전 목록. q 가 있으면 용어·뜻·일상어에 그 글자가 든 항목만."""
    needle = (params.get("q") or "").strip()
    entries = load_glossary()
    if needle:
        entries = [e for e in entries
                   if needle in e["term"] or needle in e["meaning"] or any(needle in s for s in e["synonyms"])]
    return 200, {"terms": [{"term": e["term"], "meaning": e["meaning"]} for e in entries]}


def api_ask(conn, body):
    """질문창: 검색 결과 + 요약 카드(항상) + AI 설명(키가 있을 때). AI 가 실패해도 앞의 둘은 항상 준다."""
    query = (body.get("q") or "").strip()
    if not query:
        return 400, {"error": "질문을 입력해 주세요."}
    found = search_theory(query, conn, round_limit=parse_scope(body.get("scope")), limit=SUMMARY_LIMIT)
    summary = build_summary(conn, found["results"], found["terms"])        # 요약은 더 넓은 후보(상위 SUMMARY_LIMIT)에서 만든다
    shown = {**found, "results": found["results"][:RESULT_LIMIT]}   # 목록은 상위 RESULT_LIMIT 개만 보여 준다
    return 200, {"search": shown, "summary": summary,
                 "no_direct": not covers_core_terms(conn, found["results"], found["terms"]), "ai": explain(query, summary)}


NOT_FOUND_QUESTION = {"error": "해당 회차·번호의 문항이 없습니다."}
NOT_FOUND_QUIZ = {"error": "조건에 맞는 문항이 없습니다."}


def _scope(params):
    """분석 화면용 범위: 비어 있으면 최신 10회분."""
    return parse_scope(params.get("scope"), LATEST_ROUNDS)


def api_quiz_set(conn, params, body):
    ids = quiz.pick_set(conn, params.get("subject"), params.get("tax"), params.get("unit"), int(params.get("count") or 5))
    return (200, {"ids": ids}) if ids else (404, NOT_FOUND_QUIZ)


def api_question(conn, params, body):
    """회차·번호 또는 id('128-12')로 문항 하나를 찾는다(정답·해설 없음)."""
    if params.get("id"):
        row = quiz.get_row(conn, params["id"])
        found = quiz.public_question(row) if row else None
    else:
        found = quiz.find_question(conn, params["round"], params["number"])
    return (200, found) if found else (404, NOT_FOUND_QUESTION)


def api_quiz(conn, params, body):
    exclude = [x for x in (params.get("exclude") or "").split(",") if x]
    picked = quiz.pick_quiz_question(conn, params.get("subject"), params.get("tax"), params.get("unit"), exclude)
    return (200, picked) if picked else (404, NOT_FOUND_QUIZ)


def api_mock_new(conn, params, body):
    questions = mock.pick_exam(conn)
    if len(questions) != mock.EXAM_SIZE:
        return 404, {"error": f"모의고사를 만들 문항이 {mock.EXAM_SIZE}개보다 적습니다."}
    return 200, {"questions": questions}


def api_notebook(conn, params, body):
    return 200, {"items": records.notebook(conn, params.get("subject"), params.get("unit")),
                 "unit_counts": records.unit_wrong_counts(conn)}


def api_answer(conn, params, body):
    """보기를 고르면 채점하고 풀이 기록을 남긴다(같은 기록 연타는 한 번만)."""
    result = quiz.check_answer(conn, body.get("id", ""), body.get("choice", ""))
    if "error" in result:
        return 404, result
    records.save(conn, result["id"], body.get("choice", ""), result["correct"])
    return 200, result


def api_reveal(conn, params, body):
    """정답·해설 바로 보기: 확인만 함으로 기록하고 정답으로 세지 않는다."""
    result = quiz.reveal(conn, body.get("id", ""))
    if "error" in result:
        return 404, result
    records.save(conn, result["id"], "", None, seen_only=True)
    return 200, result


def api_study_note(conn, params, body):
    return 200, study.get_note(conn, params.get("unit", ""))


def api_study_progress(conn, params, body):
    return 200, {"status": study.save_progress(conn, body.get("unit", ""), body.get("status", "")), "cards": study.curriculum(conn)}


def api_study_review(conn, params, body):
    return 200, {"reviewed": study.set_review(conn, body.get("unit", ""), body.get("section", ""), bool(body.get("reviewed")))}


def api_ox_set(conn, params, body):
    items = ox.pick(conn, params.get("subject"), params.get("tax"), params.get("unit"), int(params.get("count") or 20))
    return (200, {"items": items}) if items else (404, {"error": "조건에 맞는 O/X 문장이 없습니다."})


def api_ox_answer(conn, params, body):
    result = ox.answer(conn, body.get("key", ""), body.get("choice", ""))
    return (404 if "error" in result else 200), result


def api_settings_save(conn, params, body):
    return 200, {"settings": daily.save_settings(conn, body)}


def api_test_clock(conn, params, body):
    """화면 점검용: 시계를 앞당긴다. TUTOR_TEST_CLOCK=1 로 띄운 점검 서버에서만 열린다."""
    if not clock.test_clock_enabled():
        return 404, {"error": "없는 주소입니다."}
    clock.set_offset(int(body.get("days", 0)))
    return 200, {"offset": clock.offset(), "date": clock.iso(clock.today())}


def _admin_only(conn):
    return conn.user is not None and conn.user["is_admin"]


def api_users(conn, params, body):
    """계정 관리(관리자만): 목록 보기·계정 만들기. 공개 회원가입은 없다."""
    if not _admin_only(conn):
        return 403, {"error": "관리자만 할 수 있습니다."}
    return 200, {"users": auth.list_users(conn)}


def api_users_create(conn, params, body):
    if not _admin_only(conn):
        return 403, {"error": "관리자만 할 수 있습니다."}
    user = auth.create_user(conn, body.get("username"), body.get("password"), body.get("name", ""), is_admin=bool(body.get("is_admin")))
    return 200, {"user": user, "users": auth.list_users(conn)}


def auth_dispatch(method, path, body, conn, token, local):
    """로그인 없이 부를 수 있는 길(상태, 내용, 쿠키 동작). 쿠키 동작: None | ('set', 토큰) | ('clear',). 로그인 길이 아니면 None."""
    if (method, path) == ("GET", "/api/me"):
        return 200, {"user": auth.user_for_token(conn, token), "needs_setup": not auth.has_users(conn)}, None
    if (method, path) == ("POST", "/api/login"):
        try:
            user = auth.authenticate(conn, body.get("username"), body.get("password"))
        except auth.LoginError as err:
            return 401, {"error": str(err)}, None
        return 200, {"user": user}, ("set", auth.create_session(conn, user["id"]))
    if (method, path) == ("POST", "/api/setup"):
        if auth.has_users(conn):
            return 403, {"error": "이미 계정이 있습니다."}, None
        if not local:
            return 403, {"error": "첫 관리자 계정은 서버가 있는 컴퓨터에서 만들어야 합니다."}, None
        try:
            user = auth.create_first_admin(conn, body.get("username"), body.get("password"), body.get("name", ""))
        except ValueError as err:
            return 400, {"error": str(err)}, None
        return 200, {"user": user}, ("set", auth.create_session(conn, user["id"]))
    if (method, path) == ("POST", "/api/logout"):
        auth.delete_session(conn, token)
        return 200, {"ok": True}, ("clear",)
    return None


def api_glossary_review_save(conn, params, body):
    """용어 하나의 검토 상태·메모·수정 제안을 저장한다(사전 원본은 바꾸지 않는다)."""
    glossary_review.save_review(conn, body.get("term", ""), body.get("status", ""), body.get("memo") or "",
                                body.get("proposed_meaning") or "")
    return 200, {"saved": True}


# (방법, 주소) → 처리 함수(conn, params, body) → (상태코드, JSON 내용)
ROUTES = {
    ("GET", "/api/analysis"): lambda conn, params, body: (200, unit_profile(conn, _scope(params))),
    ("GET", "/api/study_order"): lambda conn, params, body: (200, study_order(conn, _scope(params))),
    ("GET", "/api/quiz_set"): api_quiz_set,
    ("GET", "/api/units"): lambda conn, params, body: (200, {"units": quiz.list_units(conn)}),
    ("GET", "/api/question"): api_question,
    ("GET", "/api/quiz"): api_quiz,
    ("GET", "/api/favorites"): lambda conn, params, body: (200, {"favorites": favorites.list_all(conn)}),
    ("GET", "/api/toc"): lambda conn, params, body: (200, {"toc": build_toc(conn)}),
    ("GET", "/api/mock/new"): api_mock_new,
    ("GET", "/api/mock/history"): lambda conn, params, body: (200, {"history": mock.history(conn)}),
    ("GET", "/api/notebook"): api_notebook,
    ("GET", "/api/annotated"): lambda conn, params, body: api_annotated(conn, params),
    ("GET", "/api/glossary"): lambda conn, params, body: api_glossary(conn, params),
    ("POST", "/api/answer"): api_answer,
    ("POST", "/api/reveal"): api_reveal,
    ("POST", "/api/favorites"): lambda conn, params, body: (200, {"favorites": favorites.add(conn, body.get("q"), body.get("scope", "all"))}),
    ("POST", "/api/favorites/delete"): lambda conn, params, body: (200, {"favorites": favorites.remove(conn, body.get("q"))}),
    ("POST", "/api/mock/submit"): lambda conn, params, body: (200, mock.grade(conn, body.get("ids") or [], body.get("answers") or {})),
    ("GET", "/api/study"): lambda conn, params, body: (200, {"cards": study.curriculum(conn), "roadmap": study.roadmap(conn)}),
    ("GET", "/api/study/note"): api_study_note,
    ("GET", "/api/study/changes"): lambda conn, params, body: (200, study.changes_overview(conn)),
    ("POST", "/api/study/progress"): api_study_progress,
    ("POST", "/api/study/review"): api_study_review,
    ("GET", "/api/ox/set"): api_ox_set,
    ("GET", "/api/ox/stats"): lambda conn, params, body: (200, ox.stats(conn)),
    ("POST", "/api/ox/answer"): api_ox_answer,
    ("GET", "/api/review"): lambda conn, params, body: (200, review.summary(conn)),
    ("GET", "/api/today"): lambda conn, params, body: (200, daily.today_card(conn)),
    ("POST", "/api/settings"): api_settings_save,
    ("POST", "/api/test/clock"): api_test_clock,
    ("GET", "/api/users"): api_users,
    ("POST", "/api/users"): api_users_create,
    ("GET", "/api/glossary_review"): lambda conn, params, body: (200, {"rows": glossary_review.list_rows(conn)}),
    ("POST", "/api/glossary_review"): api_glossary_review_save,
    ("POST", "/api/ask"): lambda conn, params, body: api_ask(conn, body),
}


def dispatch(method, path, params, body, conn):
    """요청 하나를 처리해 (상태코드, JSON 내용) 을 돌려준다. 알 수 없는 길은 404."""
    handler = ROUTES.get((method, path))
    if handler is None:
        return 404, {"error": "없는 주소입니다."}
    try:
        return handler(conn, params, body)
    except (KeyError, ValueError) as err:
        return 400, {"error": f"요청이 올바르지 않습니다: {err}"}


class Handler(BaseHTTPRequestHandler):
    db_path = None  # 테스트에서 임시 DB 를 쓰려고 바꿔 끼울 수 있다

    def _token(self):
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        return cookie[COOKIE].value if COOKIE in cookie else ""

    def _redirect(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        """글꼴·스타일은 누구나, 화면은 로그인한 사람만(아니면 /login 으로), 나머지는 dispatch 로 보낸다."""
        url = urlparse(self.path)
        path = unquote(url.path)
        if url.path.startswith("/static/fonts/") and url.path.rsplit("/", 1)[1] in FONT_FILES:
            return self._send_bytes(200, (STATIC_DIR / "fonts" / url.path.rsplit("/", 1)[1]).read_bytes(), "font/woff2")
        if url.path in STATIC_FILES:
            return self._send_bytes(200, (STATIC_DIR / STATIC_FILES[url.path][0]).read_bytes(), STATIC_FILES[url.path][1])
        if path.startswith("/study/"):                       # /study/<단원>: 같은 화면이 주소의 단원 이름을 읽는다
            path = "/study"
        if path == "/login" or path in PAGES:
            conn = connect(self.db_path)
            try:
                user = auth.user_for_token(conn, self._token())
                setup = not auth.has_users(conn)
            finally:
                conn.close()
            if path == "/login":
                return self._redirect("/") if user else self._send_bytes(200, (STATIC_DIR / LOGIN_PAGE).read_bytes(), "text/html; charset=utf-8")
            if user is None:
                return self._redirect("/login")
            if path in ADMIN_PAGES and not user["is_admin"]:
                return self._redirect("/")
            return self._send_bytes(200, (STATIC_DIR / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
        if not url.path.startswith("/api/"):
            return self._send_json(404, {"error": "없는 주소입니다."})
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self._reply("GET", url.path, params, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "JSON 이 올바르지 않습니다."})
        self._reply("POST", urlparse(self.path).path, {}, body)

    def _reply(self, method, path, params, body):
        conn = connect(self.db_path)
        cookie = None
        try:
            token = self._token()
            routed = auth_dispatch(method, path, body if isinstance(body, dict) else {}, conn, token, self.client_address[0] in LOCAL_ADDRESSES)
            if routed is not None:
                status, payload, cookie = routed
            else:
                user = auth.user_for_token(conn, token)
                if user is None:
                    status, payload = 401, {"error": "로그인이 필요합니다."}
                else:
                    conn.user_id, conn.user = user["id"], user
                    status, payload = dispatch(method, path, params, body, conn)
        finally:
            conn.close()
        self._send_json(status, payload, cookie)

    def _send_json(self, status, payload, cookie=None):
        self._send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8", cookie)

    def _send_bytes(self, status, data, content_type, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if cookie:
            value, age = (cookie[1], auth.SESSION_SECONDS) if cookie[0] == "set" else ("", 0)
            self.send_header("Set-Cookie", f"{COOKIE}={value}; HttpOnly; SameSite=Lax; Path=/; Max-Age={age}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # 터미널을 어지럽히지 않는다
        pass


def startup_sync():
    """서버 시작 때 data/raw 의 새 회차를 한 번 반영한다. 실패해도 서버는 기존 DB 로 계속 뜬다."""
    conn = connect()
    try:
        print("\n".join(format_report(sync_raw(conn))))
    except Exception as err:
        print(f"원본 동기화 실패({type(err).__name__}: {err}). 기존 DB 로 계속합니다.")
    finally:
        conn.close()


def warm_up():
    """O/X 문장 은행은 처음 만들 때 몇 초 걸려서, 서버를 켜면 미리 만들어 둔다."""
    conn = connect()
    try:
        ox.pool(conn)
    finally:
        conn.close()


def main():
    """서버를 켠다(시작할 때 새 회차를 한 번 반영)."""
    parser = argparse.ArgumentParser(description="전산세무 1급 이론 튜터 (로컬 웹)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default=HOST, help="기본은 이 컴퓨터만(127.0.0.1). 같은 공유기의 다른 기기에서도 쓰려면 0.0.0.0")
    args = parser.parse_args()
    startup_sync()
    threading.Thread(target=warm_up, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"http://{args.host}:{args.port}/ 에서 실행 중입니다. 끝내려면 Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
