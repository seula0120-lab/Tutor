"""로컬 웹 화면(127.0.0.1:8000)과 JSON API. 외부에는 열지 않는다.

실행: .venv/bin/python -m tutor.web [--port 8000]
dispatch() 는 소켓 없이 (상태코드, 내용) 만 돌려주는 함수라 테스트에서 그대로 부른다.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import quiz
from .analysis import unit_profile
from .db import connect
from .glossary import annotate, load_glossary
from .search import DEFAULT_ROUNDS, search_theory

STATIC_DIR = Path(__file__).resolve().parent / "static"
HOST = "127.0.0.1"


def parse_scope(value):
    """'all' 이면 전체 회차(None), 숫자면 최신 그 회차 수, 비어 있으면 기본 10회분."""
    if value in (None, ""):
        return DEFAULT_ROUNDS
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
    """질문창: 검색 결과를 돌려준다."""
    query = (body.get("q") or "").strip()
    if not query:
        return 400, {"error": "질문을 입력해 주세요."}
    search = search_theory(query, conn, round_limit=parse_scope(body.get("scope")))
    return 200, {"search": search}


def dispatch(method, path, params, body, conn):
    """요청 하나를 처리해 (상태코드, JSON 내용) 을 돌려준다. 알 수 없는 길은 404."""
    try:
        if method == "GET":
            if path == "/api/analysis":
                return 200, unit_profile(conn, parse_scope(params.get("scope")))
            if path == "/api/units":
                return 200, {"units": quiz.list_units(conn)}
            if path == "/api/question":
                found = quiz.find_question(conn, params["round"], params["number"])
                return (200, found) if found else (404, {"error": "해당 회차·번호의 문항이 없습니다."})
            if path == "/api/quiz":
                exclude = [x for x in (params.get("exclude") or "").split(",") if x]
                picked = quiz.pick_quiz_question(conn, params.get("subject"), params.get("tax"),
                                                 params.get("unit"), exclude)
                return (200, picked) if picked else (404, {"error": "조건에 맞는 문항이 없습니다."})
            if path == "/api/annotated":
                return api_annotated(conn, params)
            if path == "/api/glossary":
                return api_glossary(conn, params)
        if method == "POST":
            if path == "/api/answer":
                result = quiz.check_answer(conn, body.get("id", ""), body.get("choice", ""))
                return (404 if "error" in result else 200), result
            if path == "/api/reveal":
                result = quiz.reveal(conn, body.get("id", ""))
                return (404 if "error" in result else 200), result
            if path == "/api/ask":
                return api_ask(conn, body)
    except (KeyError, ValueError) as err:
        return 400, {"error": f"요청이 올바르지 않습니다: {err}"}
    return 404, {"error": "없는 주소입니다."}


class Handler(BaseHTTPRequestHandler):
    db_path = None  # 테스트에서 임시 DB 를 쓰려고 바꿔 끼울 수 있다

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send_bytes(200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
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
        try:
            status, payload = dispatch(method, path, params, body, conn)
        finally:
            conn.close()
        self._send_json(status, payload)

    def _send_json(self, status, payload):
        self._send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8")

    def _send_bytes(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # 터미널을 어지럽히지 않는다
        pass


def main():
    parser = argparse.ArgumentParser(description="전산세무 1급 이론 튜터 (로컬 웹)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((HOST, args.port), Handler)
    print(f"http://{HOST}:{args.port}/ 에서 실행 중입니다. 끝내려면 Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
