"""오프라인 목차 내보내기: 서버 없이 더블클릭으로 열리는 HTML 한 파일(CSS·JS·문항 데이터 포함)을 만든다.

- 문항에 정답·해설을 함께 넣고, 화면에서 보기를 고르면 기존 퀴즈 규칙대로 채점한다(오답이면 보기 전체 잠금·"오답입니다."만,
  정답이면 해설). 풀이 기록은 남기지 않는다고 화면에 알린다. 파일을 받은 사람은 정답을 볼 수 있다는 점에 유의.
- 데이터는 <script type="application/json"> 안에 JSON 으로 넣는다. 글 속의 '</'(스크립트 닫힘)와 '<!--' 는 JSON 이스케이프로 바꿔
  HTML 이 중간에 끊기거나 데이터가 마크업으로 해석되지 않게 한다.
"""
import json
import re
from pathlib import Path

from .quiz import explanation_of, public_question
from .toc import SUBJECT_ORDER

THEME_PATH = Path(__file__).resolve().parent / "static" / "theme.css"


def inline_theme():
    """화면과 같은 theme.css 를 파일 안에 그대로 넣는다. 글꼴 파일은 부를 수 없으니 @font-face 는 빼고 시스템 글꼴로 대체한다."""
    return re.sub(r"@font-face\s*\{[^}]*\}", "", THEME_PATH.read_text(encoding="utf-8"))


EXPORT_NAME = "회계튜터_목차.html"


def safe_json(data):
    """JSON 글자 중 <script> 안에서 위험한 '</' 와 '<!--' 를 같은 뜻의 JSON 이스케이프로 바꾼다."""
    text = json.dumps(data, ensure_ascii=False)
    return text.replace("</", "<\\/").replace("<!--", "\\u003c!--")


def export_data(conn):
    """내보낼 데이터: 과목 › (세목 ›) 단원 묶음과 문항(정답·해설 없음)."""
    rows = conn.execute("SELECT * FROM questions ORDER BY round DESC, number").fetchall()
    grouped = {}
    for row in rows:
        q = public_question(row)
        q["answer"] = row["answer"]
        q["explanation"] = explanation_of(row)
        grouped.setdefault(q["subject"], {}).setdefault((q["tax"], q["unit"]), []).append(q)
    subjects = sorted(grouped, key=lambda s: (SUBJECT_ORDER.index(s) if s in SUBJECT_ORDER else 99, s))
    return [{"subject": s, "units": [{"label": " › ".join(p for p in key if p), "questions": items}
                                      for key, items in sorted(grouped[s].items())]} for s in subjects]


PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>회계튜터 문제 목차 (오프라인)</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
__THEME__
</style>
</head>
<body>
<h1>회계튜터 문제 목차</h1>
<div class="offline">서버 없이 열린 오프라인 화면입니다. 보기를 고르면 채점하고(오답이면 보기가 잠기고 정답이면 해설이 나옵니다), 풀이 기록은 남기지 않습니다. 이 파일에는 정답·해설이 들어 있습니다.</div>
<div id="toc"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  var data = JSON.parse(document.getElementById("data").textContent);
  var root = document.getElementById("toc");
  function el(tag, text, cls) { var n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; }
  data.forEach(function (subject) {
    var count = subject.units.reduce(function (n, u) { return n + u.questions.length; }, 0);
    var box = el("details", null, "subject");
    box.appendChild(el("summary", subject.subject + " · " + count + "문항"));
    subject.units.forEach(function (unit) {
      var rounds = {};
      unit.questions.forEach(function (q) { rounds[q.round] = 1; });
      var d = el("details");
      d.appendChild(el("summary", unit.label + " · " + unit.questions.length + "문항 · " + Object.keys(rounds).length + "개 회차 출제"));
      unit.questions.forEach(function (q) {
        var slot = el("div", null, "slot");
        slot.hidden = true;
        var first = q.question.split("\\n")[0];
        var row = el("button", q.id + "  " + (first.length > 60 ? first.slice(0, 60) + "…" : first), "qrow");
        row.addEventListener("click", function () {
          if (!slot.childElementCount) {
            slot.appendChild(el("div", q.id + " (" + q.round + "회 " + q.number + "번) · " + q.points + "점", "small"));
            if (q.tax_notice) slot.appendChild(el("span", q.tax_notice, "taxflag"));
            slot.appendChild(el("div", q.question)).style.fontWeight = "600";
            var accepted = q.answer.split(",").map(function (a) { return a.trim(); });
            if (accepted.length > 1) slot.appendChild(el("div", "복수정답 문항입니다. 정답 중 하나를 고르면 정답으로 처리합니다.", "small"));
            var result = el("div");
            var buttons = q.choices.map(function (c, i) {
              var b = el("button", null, "choice"); b.appendChild(el("span", "①②③④".charAt(i), "omr")); b.appendChild(el("span", c, "ctext"));
              b.addEventListener("click", function () {
                buttons.forEach(function (x) { x.disabled = true; });          // 누르는 즉시 잠근다(오답이면 그대로 끝)
                result.textContent = "";
                if (accepted.indexOf(String(i + 1)) >= 0) {
                  b.classList.add("right");
                  result.appendChild(el("div", "정답입니다. (정답 " + q.answer + "번)", "ok"));
                  result.appendChild(el("div", q.explanation, "explain"));
                } else {
                  b.classList.add("wrong");
                  result.appendChild(el("div", "오답입니다.", "bad"));
                }
              });
              return b;
            });
            buttons.forEach(function (b) { slot.appendChild(b); });
            var reveal = el("button", "정답·해설 바로 보기", "ghost");
            reveal.addEventListener("click", function () {
              reveal.disabled = true;
              buttons.forEach(function (x) { x.disabled = true; });
              result.textContent = "";
              result.appendChild(el("div", "정답 " + q.answer + "번 (확인만 함)", "ok"));
              result.appendChild(el("div", q.explanation, "explain"));
            });
            slot.appendChild(reveal);
            slot.appendChild(result);
            slot.appendChild(el("div", "오프라인 화면: 풀이 기록은 남지 않습니다", "small"));
          }
          slot.hidden = !slot.hidden;
        });
        d.appendChild(row);
        d.appendChild(slot);
      });
      box.appendChild(d);
    });
    root.appendChild(box);
  });
})();
</script>
</body>
</html>
"""


def render_html(conn):
    return PAGE.replace("__THEME__", inline_theme()).replace("__DATA__", safe_json(export_data(conn)))
