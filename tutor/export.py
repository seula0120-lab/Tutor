"""오프라인 목차 내보내기: 서버 없이 더블클릭으로 열리는 HTML 한 파일(CSS·JS·문항 데이터 포함)을 만든다.

- 문항은 문제 글·보기·세법 표시만 넣고 정답·해설은 넣지 않는다. 화면에서 채점·기록은 하지 않는다고 알린다.
- 데이터는 <script type="application/json"> 안에 JSON 으로 넣는다. 글 속의 '</'(스크립트 닫힘)와 '<!--' 는 JSON 이스케이프로 바꿔
  HTML 이 중간에 끊기거나 데이터가 마크업으로 해석되지 않게 한다.
"""
import json

from .quiz import public_question
from .toc import SUBJECT_ORDER

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
  body { font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; max-width: 920px; margin: 24px auto; padding: 0 16px; color: #1d2433; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .small { font-size: 12px; color: #5b6577; }
  .offline { background: #fff6d6; color: #6b5200; border-radius: 6px; padding: 8px 10px; margin: 8px 0; font-size: 13px; }
  details { border: 1px solid #d5dae3; border-radius: 8px; margin: 6px 0; padding: 6px 10px; }
  details.subject > summary { font-weight: 700; font-size: 16px; }
  summary { cursor: pointer; }
  .qrow { display: block; width: 100%; text-align: left; background: #fff; color: #1d2433; border: none; border-bottom: 1px solid #eef1f6; padding: 6px 2px; font: inherit; cursor: pointer; overflow-wrap: anywhere; }
  .slot { border-left: 3px solid #2b5fd9; margin: 4px 0 8px 8px; padding: 6px 10px; background: #f9fbff; }
  .choice { margin: 4px 0; padding: 6px 8px; border: 1px solid #b9c1d0; border-radius: 6px; }
  .taxflag { display: inline-block; font-size: 12px; color: #8a4b00; background: #ffe9cc; border-radius: 4px; padding: 1px 6px; }
</style>
</head>
<body>
<h1>회계튜터 문제 목차</h1>
<div class="offline">서버 없이 열린 오프라인 화면입니다. 채점·풀이 기록·정답 확인 기능은 없습니다(정답·해설은 이 파일에 들어 있지 않습니다). 풀이는 로컬 서버 화면에서 하세요.</div>
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
            q.choices.forEach(function (c, i) { slot.appendChild(el("div", "①②③④".charAt(i) + " " + c, "choice")); });
            slot.appendChild(el("div", "오프라인 화면: 채점·기록 없음", "small"));
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
    return PAGE.replace("__DATA__", safe_json(export_data(conn)))
