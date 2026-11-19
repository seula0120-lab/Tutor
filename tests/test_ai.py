from types import SimpleNamespace

import anthropic

from tutor.ai import build_context, cited_ids, explain, sentence_ids


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


SUMMARY = {
    "right": [{"text": "정상공손은 제조원가에 포함한다.", "sources": ["128-6", "117-10"]}],
    "traps": [{"text": "비정상공손도 제조원가에 포함한다.", "sources": ["120-9"]}],
}
EMPTY = {"right": [], "traps": []}


def test_no_key_skips_call_and_says_so():
    result = explain("정상공손", SUMMARY)
    assert result["status"] == "no_key" and result["text"] == ""
    assert result["sources"] == ["128-6", "117-10", "120-9"]


def test_no_sentences_does_not_call_model():
    client = FakeClient(text="x")
    result = explain("zzzz", EMPTY, client=client)
    assert result["status"] == "no_sentences" and client.calls == []


def test_prompt_contains_only_the_sentence_collection_and_flags_ungrounded():
    client = FakeClient(text="정상공손은 원가에 포함합니다 (128-6). 다른 근거 (99-9).")
    result = explain("정상공손이 뭐야", SUMMARY, client=client)
    assert result["status"] == "ok" and result["ungrounded"] == ["99-9"]
    prompt = client.calls[0]["messages"][0]["content"]
    assert "정상공손은 제조원가에 포함한다. (128-6, 117-10)" in prompt and "정상공손이 뭐야" in prompt
    assert "함정(틀린 문장)" in prompt and "공식 해설" not in prompt            # 문제 원문·해설은 보내지 않는다
    assert "3~5줄" in client.calls[0]["system"] and "Anthropic API" in result["message"]


def test_auth_failure_falls_back_without_raising():
    client = FakeClient(error=make_error(anthropic.AuthenticationError, 401))
    result = explain("정상공손", SUMMARY, client=client)
    assert result["status"] == "auth_failed" and "401" in result["message"] and result["text"] == ""


def test_other_api_error_falls_back():
    client = FakeClient(error=make_error(anthropic.InternalServerError, 500))
    assert explain("정상공손", SUMMARY, client=client)["status"] == "error"


def test_cited_ids_and_context():
    assert cited_ids("(128-12) 그리고 (128-12), (7-3). 2026-11") == ["128-12", "7-3"]
    assert sentence_ids(SUMMARY) == ["128-6", "117-10", "120-9"]
    assert "(없음)" in build_context(EMPTY)
