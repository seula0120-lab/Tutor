"""상단 메뉴(5개 그룹): 공용 nav.js, 활성 그룹 판정, /calendar 리다이렉트, 계획 화면에 캘린더 합침."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_login import call, login, server  # noqa: F401
from tutor import auth
from tutor.db import connect
from tutor.web import PAGES, REDIRECTS, STATIC_DIR

STATIC = Path(STATIC_DIR)
NAV = (STATIC / "nav.js").read_text(encoding="utf-8")
PAGE_FILES = sorted(set(PAGES.values()))


def evaluate(expr):
    """nav.js 의 최상위 선언(그룹 표·판정 함수)만 node 로 실행해 값을 얻는다(DOM 부분은 제외)."""
    if not shutil.which("node"):
        pytest.skip("node 가 없어 nav.js 의 판정 함수를 실행하지 못함")
    head = NAV.split("(function () {")[0]
    script = head + f"\nconsole.log(JSON.stringify({expr}));"
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


def test_every_page_uses_the_shared_nav_script_and_no_own_menu():
    for name in PAGE_FILES:
        html = (STATIC / name).read_text(encoding="utf-8")
        assert 'id="topbar"' in html, name
        assert '<script src="/static/nav.js"></script>' in html, name
        assert html.index("/static/quizcard.js") < html.index("/static/nav.js"), name          # nav.js 는 quizcard.js(el·api) 뒤
        assert "<header" not in html and "tab-link" not in html and "mountTopbar" not in html, name
    assert "calendar.html" not in PAGES.values() and "/calendar" in REDIRECTS


def test_six_groups_and_their_items():
    groups = evaluate("NAV_GROUPS.map((g) => [g.label, g.items.map((i) => [i.label, i.href])])")
    assert groups == [["홈", [["홈", "/"]]], ["질문", [["질문", "/#ask"]]],
                      ["배우기", [["공부", "/study"], ["단어 주석", "/#words"]]],
                      ["풀기", [["O/X", "/ox"], ["기출 답안", "/#answers"], ["모의고사", "/#mock"], ["목차", "/toc"]]],
                      ["복습", [["오답노트", "/#notebook"], ["주간 돌아보기", "/review-week"]]],
                      ["계획", [["계획·캘린더", "/plan"], ["문제 분석", "/#analysis"]]]]


@pytest.mark.parametrize("path,hash_,group", [
    ("/", "", "home"), ("/", "#ask", "ask"), ("/", "#words", "learn"), ("/", "#answers", "solve"), ("/", "#mock", "solve"),
    ("/", "#notebook", "review"), ("/", "#analysis", "plan"), ("/study", "", "learn"), ("/study/자본", "", "learn"), ("/study-changes", "", "learn"),
    ("/ox", "", "solve"), ("/toc", "", "solve"), ("/review-week", "", "review"), ("/plan", "", "plan"), ("/plan", "#calendar", "plan"),
    ("/account", "", ""), ("/admin", "", ""), ("/start", "", ""), ("/glossary-review", "", "")])
def test_active_group_for_each_address(path, hash_, group):
    assert evaluate(f"navGroupOf({json.dumps(path)}, {json.dumps(hash_)})") == group


def test_every_menu_item_belongs_to_its_own_group_and_is_the_current_item():
    pairs = evaluate("NAV_GROUPS.flatMap((g) => g.items.map((i) => { const [p, h = ''] = i.href.split('#'); return [g.key, navGroupOf(p, h ? '#' + h : ''), i.href, (navItemOf(p, h ? '#' + h : '') || {}).href]; }))")
    assert pairs and all(own == found and href == current for own, found, href, current in pairs)


def test_dropdown_opens_only_by_click_or_keyboard_not_hover():
    assert not re.search(r"mouseenter|mouseover|pointerenter", NAV)
    assert "aria-expanded" in NAV and "Escape" in NAV and "focusout" in NAV and 'aria-haspopup' in NAV
    css = (STATIC / "theme.css").read_text(encoding="utf-8")
    assert not re.search(r"\.nav-group:hover\s*>?\s*\.nav-menu|\.nav-drop:hover\s*>?\s*\.nav-menu", css)


def test_plan_page_has_plan_calendar_week_link_and_daily_settings():
    html = (STATIC / "plan.html").read_text(encoding="utf-8")
    assert html.index('id="examDate"') < html.index('id="calendar"') < html.index('id="calGrid"')
    assert html.index('id="weekLink"') < html.index('id="calGrid"') and 'id="dailyOx"' in html and 'id="dailyNotes"' in html
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id: "settingsLink"' in index and "분량 설정은 계획에서" in index and "settingsSave" not in index and "set-daily" not in index


def test_calendar_redirects_to_plan_calendar_after_login(server):
    base, path = server
    conn = connect(path)
    auth.create_first_admin(conn, "admin", "admin-pass-1")
    conn.close()
    status, _, headers = call(base, "GET", "/calendar")
    assert status == 302 and headers["Location"] == "/login"                     # 로그인 안 했으면 지금처럼 /login 먼저
    _, cookie, _ = login(base, "admin", "admin-pass-1")
    status, _, headers = call(base, "GET", "/calendar", cookie=cookie)
    assert status == 302 and headers["Location"] == "/plan#calendar"
    status, _, headers = call(base, "GET", "/calendar?date=2026-11-23", cookie=cookie)
    assert headers["Location"] == "/plan?date=2026-11-23#calendar"
    assert call(base, "GET", "/plan", cookie=cookie)[0] == 200 and call(base, "GET", "/static/nav.js")[0] == 200
