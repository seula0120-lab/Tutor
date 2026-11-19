import json
import re
import shutil
import subprocess

import pytest

from conftest import item
from tutor.bank import load_bank
from tutor.db import connect
from tutor.export import export_data, render_html, safe_json

C4 = ["첫째 문장이다.", "둘째 문장이다.", "셋째 문장이다.", "넷째 문장이다."]
EVIL = "다음 중 </script><script>alert(1)</script> <!-- 재고자산 --> 설명으로 옳은 것은?"


def data_block(html):
    return re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)


def test_closing_script_tag_in_text_cannot_break_the_page(tmp_path):
    conn = connect(tmp_path / "e.db")
    load_bank(conn, [(1, [item(1, EVIL, C4, "2", "해설 </script>")])])
    html = render_html(conn)
    assert "</script><script>alert(1)" not in html                 # 데이터 속 닫는 태그가 이스케이프됨
    assert "<!--" not in data_block(html)
    assert html.count("</script>") == 2                             # 데이터 블록·코드 블록의 진짜 닫는 태그뿐
    parsed = json.loads(data_block(html))                           # 이스케이프해도 원래 글이 그대로 복원된다
    assert parsed[0]["units"][0]["questions"][0]["question"] == EVIL


def test_safe_json_round_trips_and_escapes_only_dangerous_sequences():
    value = {"a": "x</b></script> <!-- y", "k": "한글 ① 보기"}
    text = safe_json(value)
    assert "</" not in text and "<!--" not in text
    assert json.loads(text) == value
    assert "한글" in text                                           # 한글은 이스케이프하지 않는다(UTF-8 그대로)


def test_export_has_no_answers_or_explanations(conn):
    html = render_html(conn)
    for secret in ("순실현가능가치가 원가보다 낮으면", "자기주식은 자본조정이다", '"answer"', '"explanation"'):
        assert secret not in html
    questions = [q for s in export_data(conn) for u in s["units"] for q in u["questions"]]
    assert len(questions) == 8 and all("answer" not in q and "explanation" not in q for q in questions)
    assert "채점·풀이 기록·정답 확인 기능은 없습니다" in html


def test_export_is_self_contained(conn):
    html = render_html(conn)
    assert "http://" not in html and "https://" not in html
    assert not re.search(r'<(script|link)[^>]+(src|href)=', html)    # 외부 파일을 부르지 않는다


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_embedded_script_is_valid_javascript(conn, tmp_path):
    html = render_html(conn)
    code = re.findall(r"<script>(.*?)</script>", html, re.S)[0]
    path = tmp_path / "off.js"
    path.write_text(code, encoding="utf-8")
    assert subprocess.run(["node", "--check", str(path)], capture_output=True).returncode == 0
