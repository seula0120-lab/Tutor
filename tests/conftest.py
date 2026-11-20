"""테스트 공용 준비물: 실제 기출 대신 직접 만든 작은 문항으로 임시 DB 를 만든다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tutor.bank import load_bank  # noqa: E402
from tutor.db import connect  # noqa: E402


def item(number, question, choices, answer, explanation="해설."):
    return {"number": number, "question": question, "choices": choices,
            "answer": answer, "explanation": explanation, "points": 2}


C4 = ["첫째 문장이다.", "둘째 문장이다.", "셋째 문장이다.", "넷째 문장이다."]

# 회차 두 개(1회·2회)에 서로 다른 단원·세목 문항을 둔다.
ROUND_ONE = [
    item(1, "다음 중 재고자산의 저가법 평가에 대한 설명으로 옳은 것은?",
         ["저가법은 원가가 낮을 때 쓴다.", "저가법은 순실현가능가치가 원가보다 낮을 때 쓴다.",
          "저가법 평가손실은 이익잉여금으로 처리한다.", "저가법은 유형자산에만 쓴다."], "2",
         "순실현가능가치가 원가보다 낮으면 저가법으로 평가손실을 인식한다."),
    item(3, "다음 중 자기주식에 대한 설명으로 옳은 것은?", C4, "1,3", "자기주식은 자본조정이다."),
    item(7, "다음 중 보조부문원가 배분 방법에 대한 설명으로 틀린 것은?", C4, "4",
         "상호배분법은 보조부문 간 용역 수수를 모두 반영한다."),
    item(11, "다음 중 부가가치세법상 영세율에 대한 설명으로 옳지 않은 것은?", C4, "3",
         "수출하는 재화에는 영세율을 적용한다."),
    item(12, "다음 중 소득세법상 근로소득에 대한 설명으로 옳은 것은?", C4, "1", "연말정산 때 정산한다."),
    item(13, "다음 중 법인세법상 접대비 한도에 대한 설명으로 옳은 것은?", C4, "2", "한도 초과액은 손금불산입한다."),
]
ROUND_TWO = [
    item(1, "다음 중 유형자산의 감가상각에 대한 설명으로 옳은 것은?", C4, "1", "정액법은 매년 같은 금액."),
    item(11, "다음 중 세금계산서 발급에 대한 설명으로 옳은 것은?", C4, "4", "수정세금계산서를 발급한다."),
]


@pytest.fixture
def conn(tmp_path):
    """회차 1·2 의 문항 8개가 적재된 임시 DB 연결."""
    connection = connect(tmp_path / "test.db")
    load_bank(connection, [(1, ROUND_ONE), (2, ROUND_TWO)])
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def no_real_api_key(monkeypatch):
    """테스트가 실제 API 를 부르지 않도록 키 환경변수를 지운다(키가 필요한 경우는 가짜 클라이언트를 쓴다)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def login_opener(base, db_path):
    """웹 서버 시험용: 관리자 계정을 하나 만들고 로그인한 urllib opener(쿠키 보관)를 돌려준다. 화면·API 는 로그인이 필요하다."""
    import http.cookiejar
    import json
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request = urllib.request.Request(base + "/api/setup", data=json.dumps({"username": "tester", "password": "tester-pass-1"}).encode(),
                                     headers={"Content-Type": "application/json"})
    opener.open(request).read()
    return opener
