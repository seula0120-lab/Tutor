"""서버 없이 열리는 문제 목차 HTML 한 파일을 만든다: data/export/회계튜터_목차.html

사용법: .venv/bin/python scripts/export_offline.py
열기:   Finder 에서 파일을 더블클릭하거나, 브라우저 주소창에 file:///Users/<사용자>/Desktop/회계튜터/data/export/회계튜터_목차.html
정답·해설이 파일에 들어 있다(화면에서 보기를 고르면 채점하고 풀이 기록은 남기지 않는다). 파일을 남에게 보내면 정답도 전달된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tutor.db import ROOT, connect  # noqa: E402
from tutor.export import EXPORT_NAME, render_html  # noqa: E402

EXPORT_DIR = ROOT / "data" / "export"


def main():
    """오프라인 목차 HTML 을 만든다."""
    conn = connect()
    try:
        html = render_html(conn)
    finally:
        conn.close()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = EXPORT_DIR / EXPORT_NAME
    target.write_text(html, encoding="utf-8")
    print(f"만들었습니다: {target} ({target.stat().st_size // 1024} KB)")
    print(f"열기: {target.as_uri()}")


if __name__ == "__main__":
    main()
