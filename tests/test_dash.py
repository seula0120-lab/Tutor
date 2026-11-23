"""LMS 대시보드 틀: 왼쪽 사이드바(nav.js)·상단 바·다크 모드 버튼·질문 버튼/패널(ask.js)·홈 대시보드 배치."""
import re
from pathlib import Path

from tutor.web import PAGES, STATIC_DIR, STATIC_FILES

STATIC = Path(STATIC_DIR)
NAV = (STATIC / "nav.js").read_text(encoding="utf-8")
ASK = (STATIC / "ask.js").read_text(encoding="utf-8")
CSS = (STATIC / "theme.css").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_sidebar_is_always_expanded_with_every_item_and_no_dropdown_for_groups():
    assert 'className: "sidebar"' in NAV and "side-title" in NAV and "side-link" in NAV
    assert "sideLogout" in NAV and "nav-menu-right" in NAV            # 맨 아래 로그아웃, 상단 오른쪽은 사용자 메뉴만 드롭다운
    assert "aria-haspopup" not in NAV.split("function sidebar")[1].split("function mark")[0]
    assert re.search(r"body\.has-side \{ padding-left: 220px", CSS) and re.search(r"\.sidebar \{[^}]*width: 220px", CSS)


def test_sidebar_becomes_a_drawer_at_900px_closed_by_esc_and_backdrop():
    assert "@media (max-width: 900px)" in CSS and "translateX(-100%)" in CSS
    assert 'id: "sideToggle"' in NAV and "side-backdrop" in NAV and "Escape" in NAV


def test_topbar_has_only_theme_button_and_user_menu_and_dark_mode_toggles_data_theme():
    assert 'id: "themeBtn"' in NAV and "dataset.theme" in NAV and "tutorTheme" in NAV
    assert ':root[data-theme="dark"]' in CSS and ':root:not([data-theme="light"])' in CSS


def test_main_uses_wide_body_and_only_reading_pages_keep_960px():
    assert re.search(r"main, \.page \{ max-width: 1400px", CSS) and "main.reading { max-width: 960px; }" in CSS
    for name in ("study", "ox", "toc"):
        assert 'class="reading"' in (STATIC / f"{name}.html").read_text(encoding="utf-8")
    assert 'class="reading"' not in INDEX and 'class="reading"' not in (STATIC / "plan.html").read_text(encoding="utf-8")


def test_ask_button_and_panel_exist_on_every_page_that_has_the_nav_and_dont_navigate():
    for name in sorted(set(PAGES.values())):
        html = (STATIC / name).read_text(encoding="utf-8")
        if "/static/nav.js" in html:
            assert "/static/ask.js" in html and html.index("/static/nav.js") < html.index("/static/ask.js"), name
    assert "/static/ask.js" in STATIC_FILES
    open_close = ASK.split("function askIsOpen")[1].split("(function")[0]
    assert "location" not in open_close and "history" not in open_close      # 열고 닫아도 주소는 그대로
    assert "자기주식은 어떻게 처리해?" in ASK and 'location.hash === "#ask"' in ASK and "role" in ASK
    assert 'fetch(' not in ASK and "/api/ask" in ASK                          # 검색 API 는 그대로


def test_home_dashboard_layout_and_dash_values_come_from_existing_apis_with_dash_for_empty():
    for marker in ('id="today"', 'id="examCard"', 'id="stats"', 'id="weekPlan"', 'id="weekLog"'):
        assert marker in INDEX
    assert INDEX.index('id="today"') < INDEX.index('id="examCard"') < INDEX.index('id="stats"') < INDEX.index('id="weekPlan"')
    assert '"/api/calendar"' in INDEX and '"/api/review-week"' in INDEX and '"시험일 미정"' in INDEX and '"계획 세우기"' in INDEX and '"계획 보기"' in INDEX
    assert '? Math.round' in INDEX and ': "-"' in INDEX
    for key in ("streak", "planPct", "oxRate", "quizRate", "dueCount"):
        assert f'"{key}"' in INDEX
    assert "#ask" not in INDEX or "askBox" not in INDEX
