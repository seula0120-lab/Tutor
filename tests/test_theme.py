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
