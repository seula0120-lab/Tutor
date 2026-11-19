"""확정답안 원본(PDF·HWP)을 '줄 목록'으로 읽는다. 해석은 answer_parser.py 가 맡는다.

줄 하나 = {"page", "x", "x1", "y", "text"}. PDF 는 글 상자 좌표를 그대로 쓰고,
HWP 는 좌표가 없어서 줄 순서를 y 로, x 는 0 으로 둔다(한 줄 여러 보기는 파서가 나눈다).
회차별 파일 위치는 find_answer_file 한 곳에서만 정한다(PDF 가 있으면 PDF, 없으면 HWP).
"""
import html
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pymupdf

# 쪽 머리글·쪽 번호: '[제128회 전산세무1급 확정답안]', '1/33(뒷면 계속)', 옛 형식 '-1/19-'
PAGE_HEADER = re.compile(r"^\[제\d+회 전산세무\s*1급 (확정)?답안\]$|^\d+/\d+\(|^-\d*/\d+-$")
HWP_CHAR_WIDTH = 7  # HWP 줄 안의 보기 위치를 어림할 때 쓰는 글자 폭(임의 단위)


def find_answer_file(round_dir):
    """회차 폴더의 확정답안 파일 경로. PDF 를 먼저, 없으면 HWP. 둘 다 없으면 None."""
    for name in ("answer.pdf", "answer.hwp"):
        path = Path(round_dir) / name
        if path.is_file():
            return path
    return None


def read_answer_lines(path):
    """파일 확장자에 맞게 줄 목록을 읽는다."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)
    if path.suffix.lower() == ".hwp":
        return _read_hwp(path)
    raise ValueError(f"지원하지 않는 형식입니다: {path.name}")


# ── PDF ────────────────────────────────────────────────

def _pdf_line(page_no, raw):
    # 옛 원본에 ① 대신 모양이 비슷한 'ⓛ'(원 안 소문자 l)이 찍힌 곳이 있어 바로잡는다.
    text = "".join(span["text"] for span in raw["spans"]).strip().replace("ⓛ", "①")
    x0, y0, x1, _ = raw["bbox"]
    return {"page": page_no, "x": round(x0, 1), "x1": round(x1, 1), "y": round(y0, 1), "text": text}


def _read_pdf(path):
    lines = []
    with pymupdf.open(path) as doc:
        for page_no, page in enumerate(doc):
            for block in page.get_text("dict")["blocks"]:
                lines.extend(_pdf_line(page_no, raw) for raw in block.get("lines", []))
    return [line for line in lines if line["text"] and not PAGE_HEADER.match(line["text"])]


# ── HWP ────────────────────────────────────────────────

class _HtmlLines(HTMLParser):
    """HTML 에서 문단(<p>) 하나, 표 칸(<td>) 하나를 각각 한 줄로 모은다. 표 칸 안의 문단은 칸 하나로 합친다."""

    def __init__(self):
        super().__init__()
        self.lines, self.parts, self.cell_depth = [], [], 0

    def _flush(self):
        text = " ".join(html.unescape("".join(self.parts)).split())
        if text:
            self.lines.append(text)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self._flush()
            self.cell_depth += 1
        elif tag == "br" and not self.cell_depth:
            self._flush()

    def handle_endtag(self, tag):
        if tag == "td":
            self.cell_depth -= 1
            self._flush()
        elif tag == "p" and not self.cell_depth:
            self._flush()
        elif tag == "p":
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)

    def finish(self):
        self._flush()
        return self.lines


def _hwp_to_html(path, out_dir):
    """이 가상환경의 hwp5html 로 HTML 을 만든다. 표(정답표)를 살리려고 txt 가 아니라 HTML 을 거친다."""
    tool = Path(sys.executable).parent / "hwp5html"
    run = subprocess.run([str(tool), "--output", str(out_dir), str(path)], capture_output=True, text=True)
    page = Path(out_dir) / "index.xhtml"
    if run.returncode != 0 or not page.exists():
        raise RuntimeError(f"hwp5html 변환 실패: {run.stderr.strip()[-200:]}")
    return page.read_text(encoding="utf-8")


def _read_hwp(path):
    with tempfile.TemporaryDirectory() as tmp:
        page = _hwp_to_html(path, Path(tmp) / "out")
    parser = _HtmlLines()
    parser.feed(page[page.find("<body"):])
    texts = parser.finish()
    return [{"page": 0, "x": 0, "x1": len(t) * HWP_CHAR_WIDTH, "y": i * 10, "text": t.replace("ⓛ", "①")}
            for i, t in enumerate(texts)]
