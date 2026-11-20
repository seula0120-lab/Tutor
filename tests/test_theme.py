import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from tutor.bank import load_bank
from tutor.db import connect
from tutor.export import inline_theme, render_html
from tutor.web import FONT_FILES, STATIC_DIR, Handler

THEME = (STATIC_DIR / "theme.css").read_text(encoding="utf-8")


def test_theme_defines_both_palettes_with_spec_values():
    assert "--bg: #F5F6F8" in THEME and "--accent: #4F46E5" in THEME           # 라이트
    dark = THEME.split("prefers-color-scheme: dark")[1]
    assert "--bg: #0F1115" in dark and "--accent: #8B87FF" in dark              # 다크
    assert "--radius: 12px" in THEME and "prefers-reduced-motion" in THEME and ":focus-visible" in THEME


def test_pages_use_theme_only_and_no_inline_style_blocks():
    for name in ("index.html", "toc.html", "glossary_review.html"):
        html = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert '/static/theme.css' in html and "<style" not in html, name


def test_spacing_values_are_multiples_of_4():
    for px in re.findall(r"--s\d: (\d+)px", THEME):
        assert int(px) % 4 == 0


def test_bundled_fonts_exist_and_are_served(tmp_path):
    for name in FONT_FILES:
        assert (STATIC_DIR / "fonts" / name).stat().st_size > 10000
    db = tmp_path / "t.db"
    connect(db).close()
    server = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (Handler,), {"db_path": db}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert urllib.request.urlopen(base + "/static/theme.css").headers["Content-Type"].startswith("text/css")
        assert urllib.request.urlopen(base + "/static/fonts/PretendardVariable.woff2").headers["Content-Type"] == "font/woff2"
        try:
            urllib.request.urlopen(base + "/static/fonts/../theme.css%00")
            assert False
        except Exception as err:
            assert getattr(err, "code", 404) == 404                              # 목록 밖 파일은 내려 주지 않는다
    finally:
        server.shutdown()
        server.server_close()


def test_offline_export_inlines_theme_without_font_files(conn):
    html = render_html(conn)
    assert "--accent: #4F46E5" in html and "@font-face" not in html and "/static/" not in html
    assert "@font-face" not in inline_theme()


def test_tab_row_overflow_hint_and_hash_links_are_wired():
    js = (STATIC_DIR / "quizcard.js").read_text(encoding="utf-8")
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert ".tabs-wrap.more::after" in THEME and "linear-gradient(to right, transparent" in THEME
    assert ".tabs-wrap.more-left::before" in THEME and "overflow: hidden" in THEME.split(".tabs-wrap {")[1].split("}")[0] and "more-left" in js
    assert "scrollTabIntoView" in js and "watchTabOverflow" in js and "mountTopbar" in js
    # 해시 링크 처리는 스크립트 맨 아래(최상위)에서 실행돼야 한다: 다른 이벤트 처리기 안에 들어가면 /#answers 링크가 동작하지 않는다
    tail = index.split("loadFavorites();\n")[-1]
    assert "tabFromHash();" in tail and 'addEventListener("hashchange"' in tail
    for page in ("toc.html", "glossary_review.html"):
        assert "mountTopbar(" in (STATIC_DIR / page).read_text(encoding="utf-8")
