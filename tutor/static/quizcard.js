// 화면 여러 곳(기출 답안·오답노트·모의고사 결과·/toc·묶음 풀기)이 함께 쓰는 도우미와 퀴즈 카드.
// 퀴즈 규칙은 여기 한 곳에만 있다: 오답이면 보기를 모두 잠그고, 해설은 정답을 골랐을 때만 펼친다.
const $ = (id) => document.getElementById(id);
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const c of children) node.append(c);
  return node;
}
async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  if (response.status === 401 && location.pathname !== "/login") { location.href = "/login"; }   // 로그인이 풀렸다
  return { ok: response.ok, data: await response.json() };
}
const query = (obj) => new URLSearchParams(Object.entries(obj).filter(([, v]) => v !== "" && v != null)).toString();
const CIRCLES = ["①", "②", "③", "④"];
const pathOf = (q) => [q.subject, q.tax, q.unit].filter(Boolean).join(" › ");

// OMR 마킹 모양의 보기 버튼: 동그라미 번호 + 글. 글 전체가 하나의 버튼이다.
function choiceButton(i, text) {
  return el("button", { className: "choice" }, el("span", { className: "omr", ariaHidden: "true", textContent: CIRCLES[i] || String(i + 1) }), el("span", { className: "ctext", textContent: text }));
}

// 글 속의 핵심어를 형광펜(<mark>)으로 칠한 조각들을 돌려준다. 긴 핵심어부터 찾고 겹치는 곳은 칠하지 않는다.
function highlight(text, words) {
  const keys = [...new Set((words || []).filter((w) => w))].sort((a, b) => b.length - a.length);
  if (!keys.length) return [document.createTextNode(text)];
  const spans = [];
  for (const k of keys) {
    for (let at = text.indexOf(k); at !== -1; at = text.indexOf(k, at + k.length)) {
      if (!spans.some(([s, e]) => at < e && at + k.length > s)) spans.push([at, at + k.length]);
    }
  }
  spans.sort((a, b) => a[0] - b[0]);
  const out = [];
  let pos = 0;
  for (const [s, e] of spans) {
    if (s > pos) out.push(document.createTextNode(text.slice(pos, s)));
    out.push(el("mark", { textContent: text.slice(s, e) }));
    pos = e;
  }
  if (pos < text.length) out.push(document.createTextNode(text.slice(pos)));
  return out;
}

// 문제 글 속 표(원본의 행·열 머리글과 칸 병합을 그대로): tables = [{n_rows, header_rows, row_header, cells: [{r, c, rs, cs, text}]}]
function renderTables(tables) {
  return (tables || []).map((t) => {
    const table = el("table", { className: "qtable" });
    table.dataset.rows = t.n_rows;
    const head = el("thead"), body = el("tbody");
    for (let r = 0; r < t.n_rows; r++) {
      const tr = el("tr");
      for (const cell of t.cells.filter((x) => x.r === r)) {
        const isHead = r < t.header_rows || (t.row_header && cell.c === 0);
        const td = el(isHead ? "th" : "td", { textContent: cell.text });
        if (isHead) td.setAttribute("scope", r < t.header_rows ? "col" : "row");
        if (cell.rs > 1) td.rowSpan = cell.rs;
        if (cell.cs > 1) td.colSpan = cell.cs;
        if (!isHead && /^[\d,.\-+% ]+(원|%)?$/.test(cell.text)) td.className = "num";
        tr.append(td);
      }
      (r < t.header_rows ? head : body).append(tr);
    }
    if (head.children.length) table.append(head);
    table.append(body);
    return el("div", { className: "qtable-wrap" }, table);
  });
}

// 구조화한 수치(numbers.py): 본문에는 숫자만 두고 점선 밑줄을 긋는다. 누르거나(Enter·Space 포함) 마우스를 올리면 말풍선으로 적용 대상·기준일·예외 조건·출처를 보인다. Esc·바깥 클릭으로 닫는다.
let numPop = null, numPopOwner = null;
function closeNumPop() {
  if (numPop) numPop.remove();
  if (numPopOwner) numPopOwner.setAttribute("aria-expanded", "false");
  numPop = numPopOwner = null;
}
function openNumPop(tag, n) {
  if (numPopOwner === tag) return;
  closeNumPop();
  const row = (label, value) => el("div", { className: "numpop-row" }, el("b", { textContent: label }), ` ${value || "없음"}`);
  numPop = el("div", { className: "numpop", role: "tooltip", id: "numPop" },
    el("div", { className: "numpop-head", textContent: `${n.token} (${n.unit})` }),
    row("적용 대상", n.applies_to), row("기준일", n.as_of), row("예외 조건", n.exception), row("출처", n.source));
  document.body.append(numPop);
  numPopOwner = tag;
  tag.setAttribute("aria-expanded", "true");
  tag.setAttribute("aria-describedby", "numPop");
  const r = tag.getBoundingClientRect(), w = numPop.offsetWidth;
  numPop.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.left))}px`;
  numPop.style.top = `${r.bottom + 6}px`;
  if (numPop.getBoundingClientRect().bottom > window.innerHeight) numPop.style.top = `${Math.max(8, r.top - numPop.offsetHeight - 6)}px`;
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNumPop(); });
document.addEventListener("click", (e) => { if (numPopOwner && !numPopOwner.contains(e.target) && !(numPop && numPop.contains(e.target))) closeNumPop(); });

function numberedNodes(text, items) {
  const nodes = [];
  let pos = 0;
  for (const n of items || []) {
    const i = text.indexOf(n.token, pos);
    if (i < 0) continue;
    if (i > pos) nodes.push(document.createTextNode(text.slice(pos, i)));
    const tag = el("span", { className: "num-tag", textContent: n.token, tabIndex: 0 });
    tag.setAttribute("role", "button");
    tag.setAttribute("aria-expanded", "false");
    tag.setAttribute("aria-label", `${n.token}, 적용 대상과 기준일 보기`);
    tag.addEventListener("click", (e) => { e.stopPropagation(); numPopOwner === tag ? closeNumPop() : openNumPop(tag, n); });
    tag.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); numPopOwner === tag ? closeNumPop() : openNumPop(tag, n); } });
    tag.addEventListener("mouseenter", () => openNumPop(tag, n));
    tag.addEventListener("mouseleave", (e) => { if (!(numPop && e.relatedTarget && numPop.contains(e.relatedTarget))) closeNumPop(); });
    nodes.push(tag);
    pos = i + n.token.length;
  }
  if (pos < text.length) nodes.push(document.createTextNode(text.slice(pos)));
  return nodes;
}

// 세무 문장 옆 작은 배지: '2026년 10월 시행 시험 기준' + 개정 전 기준(항목마다). obj = {exam_basis, pre_amend: [{label, text}]}
function basisBadges(obj) {
  const out = [];
  if (obj.exam_basis) out.push(el("span", { className: "basis", textContent: obj.exam_basis }));
  for (const b of obj.pre_amend || []) out.push(el("span", { className: "preamend", textContent: b.label, title: b.text }), el("span", { className: "small preamend-note", textContent: b.text.slice(b.label.length + 3) }));
  return out;
}

// q: 공개용 문항(정답 없음). container: 카드를 그릴 요소. onResult({kind: "correct"|"wrong"|"seen", id}): 결과가 나왔을 때 부른다.
function renderCard(q, container, onResult = () => {}) {
  container.replaceChildren();
  container.classList.add("paper");                          // 시험지 카드 모양(theme.css)
  container.classList.remove("locked");
  container.append(el("div", { className: "meta", textContent: `${q.id} (${q.round}회 ${q.number}번) · ${pathOf(q)} · ${q.points}점` }),
                   el("div", { className: "stem", textContent: q.question_view || q.question }));
  container.append(...renderTables(q.tables));
  for (const note of q.tax_notes || (q.tax_notice ? [q.tax_notice] : [])) container.append(el("div", {}, el("span", { className: "taxflag", textContent: note })));
  if (q.exam_basis || (q.pre_amend || []).length) container.append(el("div", { className: "basis-row" }, ...basisBadges(q)));
  if (q.multi) container.append(el("div", { className: "notice", textContent: "복수정답 문항입니다. 정답 중 하나를 고르면 정답으로 처리합니다." }));
  const result = el("div");
  const buttons = q.choices.map((text, i) => {
    const b = choiceButton(i, text);
    b.addEventListener("click", async () => {
      buttons.forEach((x) => (x.disabled = true));        // 누르는 즉시 잠가 연타를 막는다(오답이면 그대로 잠긴 채 끝)
      const { data } = await api("/api/answer", { id: q.id, choice: String(i + 1) });
      if (data.correct) {
        b.classList.add("right");
        result.replaceChildren(el("div", { className: "result-right", textContent: `정답입니다. (정답 ${data.answer}번)` }),
                               el("div", { className: "explain", textContent: data.explanation }));
        onResult({ kind: "correct", id: q.id });
      } else {
        b.classList.add("wrong");
        container.classList.add("locked");                   // 오답: 보기를 모두 잠근다
        result.replaceChildren(el("div", { className: "result-wrong" }, el("span", { className: "lock", ariaHidden: "true", textContent: "🔒" }), "오답입니다."));
        onResult({ kind: "wrong", id: q.id });
      }
    });
    return b;
  });
  const reveal = el("button", { className: "ghost", textContent: "정답·해설 바로 보기" });
  reveal.addEventListener("click", async () => {
    reveal.disabled = true;
    buttons.forEach((x) => (x.disabled = true));
    const { data } = await api("/api/reveal", { id: q.id });
    result.replaceChildren(el("div", { className: "result-right", textContent: `정답 ${data.answer}번 (확인만 함 · 정답으로 세지 않음)` }),
                           el("div", { className: "explain", textContent: data.explanation }));
    onResult({ kind: "seen", id: q.id });
  });
  container.append(...buttons, el("div", { className: "row" }, reveal), result);
}

// 문항 묶음을 차례대로 푸는 진행기(요약 카드의 '이 주제 기출 풀기', 단원 5문제 풀기에서 쓴다).
// ids: 문항 id 목록. container: 그릴 곳. 끝나면 맞힌 수와 틀린 문항 목록을 보여 준다.
async function runSession(ids, container, title) {
  const tally = { correct: 0, wrong: [], seen: [] };
  const head = el("b", { textContent: title });
  const body = el("div");
  container.replaceChildren(head, body);
  async function step(index) {
    if (index >= ids.length) return finish();
    const { ok, data } = await api("/api/question?" + query({ id: ids[index] }));
    const frame = el("div");
    body.replaceChildren(el("div", { className: "small", textContent: `${index + 1} / ${ids.length}` }), frame);
    if (!ok) { frame.append(el("div", { className: "result-wrong", textContent: data.error })); return; }
    renderCard(data, frame, ({ kind, id }) => {
      if (kind === "correct") tally.correct += 1;
      else if (kind === "wrong") tally.wrong.push(id);
      else tally.seen.push(id);
      const next = el("button", { textContent: index + 1 < ids.length ? "다음 문제" : "결과 보기" });
      next.addEventListener("click", () => step(index + 1));
      frame.append(el("div", { className: "row" }, next));
    });
  }
  function finish() {
    const list = (label, items) => items.length ? [el("div", { className: "small", textContent: `${label}: ${items.join(", ")}` })] : [];
    body.replaceChildren(el("div", { className: "result-right", textContent: `${ids.length}문제 중 ${tally.correct}문제 맞힘` }),
      ...list("틀린 문항", tally.wrong), ...list("확인만 한 문항(정답으로 세지 않음)", tally.seen));
  }
  await step(0);
}
