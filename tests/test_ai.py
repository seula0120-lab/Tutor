from types import SimpleNamespace

import anthropic

from tutor.ai import build_context, cited_ids, explain
from tutor.search import search_theory


class FakeClient:
    """messages.create 를 흉내 내는 가짜 클라이언트. 받은 인자를 기록한다."""

    def __init__(self, text=None, error=None):
        self.calls, self._text, self._error = [], text, error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


def make_error(cls, status):
    """anthropic 오류 객체를 만든다. 응답 객체는 오류 클래스가 읽는 속성만 가진 가짜다."""
    response = SimpleNamespace(status_code=status, headers={}, request=SimpleNamespace(), text="", json=lambda: {})
    return cls("error", response=response, body=None)


def test_no_key_skips_call_and_says_so(conn):
    search = search_theory("저가법", conn, entries=[])
    result = explain("저가법", search, conn)
    assert result["status"] == "no_key" and result["text"] == ""
    assert result["sources"] == ["1-1"]  # 검색 결과는 그대로 쓸 수 있다


def test_no_results_does_not_call_model(conn):
    client = FakeClient(text="x")
    result = explain("zzzz없는말", {"results": []}, conn, client=client)
    assert result["status"] == "no_results" and client.calls == []


def test_ok_answer_includes_context_and_flags_ungrounded_citation(conn):
    client = FakeClient(text="저가법은 재고 평가 방법입니다 (1-1). 다른 근거 (99-9).")
    search = search_theory("저가법", conn, entries=[])
    result = explain("저가법이 뭐야", search, conn, client=client)
    assert result["status"] == "ok" and result["ungrounded"] == ["99-9"]
    prompt = client.calls[0]["messages"][0]["content"]
    assert "순실현가능가치" in prompt and "저가법이 뭐야" in prompt   # 공식 해설과 질문이 전달됨
    assert "Anthropic API" in result["message"]


def test_auth_failure_falls_back_without_raising(conn):
    client = FakeClient(error=make_error(anthropic.AuthenticationError, 401))
    result = explain("저가법", search_theory("저가법", conn, entries=[]), conn, client=client)
    assert result["status"] == "auth_failed" and "401" in result["message"] and result["text"] == ""


def test_other_api_error_falls_back(conn):
    client = FakeClient(error=make_error(anthropic.InternalServerError, 500))
    result = explain("저가법", search_theory("저가법", conn, entries=[]), conn, client=client)
    assert result["status"] == "error"


def test_cited_ids_and_context():
    assert cited_ids("(128-12) 그리고 (128-12), (7-3). 2026-11") == ["128-12", "7-3"]


def test_context_has_answer_and_explanation(conn):
    text = build_context(conn, ["1-7"])
    assert 'id="1-7"' in text and "정답: 4" in text and "상호배분법" in text
