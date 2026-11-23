// 질문(기출 검색·RAG) 패널(모든 화면 공용). 오른쪽 아래 둥근 '질문' 버튼 → 오른쪽에서 열리는 패널(모바일은 전체 화면).
// 검색·AI 설명은 /api/ask 그대로 쓴다. 열고 닫아도 주소는 바뀌지 않는다(/#ask 로 들어오면 열린 채로 시작).
// quizcard.js(el·api·highlight·basisBadges·runSession)를 먼저 불러온 뒤 이 파일을 불러온다.
// ---- 질문창 ----
let lastAsk = { q: "", scope: "all" };
async function runAsk(q, scope) {
  q = q.trim();
  if (!q) return;
  $("ask").disabled = true;
  $("answer").replaceChildren(el("div", { className: "small", textContent: "찾는 중…" }));
  const { data } = await api("/api/ask", { q, scope });
  $("ask").disabled = false;
  lastAsk = { q, scope };
  if (!data.error) rememberQuery(q);
  renderAnswer(data);
}

// ---- 최근 질문(브라우저 localStorage, 쓸 수 없어도 정상 동작) ----
const RECENT_KEY = "tutorRecentQueries";
function readRecent() {
  try { const v = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 10) : []; }
  catch (e) { return []; }
}
function rememberQuery(q) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify([q, ...readRecent().filter((x) => x !== q)].slice(0, 10))); } catch (e) { /* 저장 실패는 무시 */ }
  renderRecent();
}
function renderRecent() {
  const box = $("recent");
  const items = readRecent();
  box.replaceChildren(el("b", { textContent: "최근 질문 " }), ...(items.length ? items.map((q) => {
    const b = el("button", { className: "ghost chip", textContent: q });
    b.addEventListener("click", () => { $("q").value = q; runAsk(q, $("scope").value); });
    return b;
  }) : [el("span", { textContent: "(없음)" })]));
}

// ---- 즐겨찾기(서버 DB) ----
async function loadFavorites() {
  const { data } = await api("/api/favorites");
  const box = $("favs");
  box.replaceChildren(el("b", { textContent: "즐겨찾기 " }), ...(data.favorites.length ? data.favorites.map((f) => {
    const open = el("button", { className: "ghost chip", textContent: "★ " + f.query });
    open.addEventListener("click", () => { $("q").value = f.query; $("scope").value = f.scope; runAsk(f.query, f.scope); });
    const del = el("button", { className: "ghost chip", textContent: "삭제", title: "즐겨찾기에서 삭제" });
    del.addEventListener("click", async () => { await api("/api/favorites/delete", { q: f.query }); loadFavorites(); updateStar(); });
    return el("span", { style: "white-space:nowrap" }, open, del, " ");
  }) : [el("span", { textContent: "(없음)" })]));
  window.favoriteQueries = new Set(data.favorites.map((f) => f.query));
}
async function updateStar() {
  const star = $("starBtn");
  if (!star) return;
  star.textContent = window.favoriteQueries.has(lastAsk.q) ? "★ 즐겨찾기 해제" : "☆ 즐겨찾기";
}

function renderAnswer(data) {
  const box = $("answer");
  box.replaceChildren();
  if (data.error) { box.append(el("div", { className: "result-wrong", textContent: data.error })); return; }
  if (data.no_direct) box.append(el("div", { className: "notice", textContent: "이 주제를 직접 다룬 기출을 찾지 못했습니다. 아래는 일부 낱말만 겹치는 문항일 수 있습니다." }));
  box.append(renderSummary(data.summary));
  const ai = data.ai;
  if (ai && ai.status === "ok") {
    box.append(el("div", { className: "small", textContent: "AI 설명 (요약 카드의 문장만 근거로, 출처는 회차-문항)" }),
               el("div", { className: "ai", textContent: ai.text }));
    if (ai.ungrounded.length) box.append(el("div", { className: "notice", textContent: "주의: 검색 근거에 없는 출처가 인용됐습니다: " + ai.ungrounded.join(", ") }));
    box.append(el("div", { className: "small", textContent: ai.message }));
  } else if (ai && ai.message) {
    box.append(el("div", { className: "notice", textContent: ai.message }));
  }
  const s = data.search;
  const info = `검색 범위: ${s.scope} · 검색어: ${s.terms.join(", ") || "-"}` + (s.expanded.length ? ` · 일상어 확장: ${s.expanded.join(", ")}` : "");
  box.append(el("div", { className: "small", style: "margin-top:8px", textContent: info }));
  if (s.note) box.append(el("div", { className: "notice", textContent: s.note }));
  for (const r of s.results) {
    const row = el("div", { className: "hit" });
    row.append(el("div", { className: "meta", textContent: `출처 ${r.id} (${r.round}회 ${r.number}번) · ${[r.subject, r.tax, r.unit].filter(Boolean).join(" › ")}` }),
               ...(r.tax_notice ? [el("span", { className: "taxflag", textContent: r.tax_notice })] : []), ...basisBadges(r),
               el("div", { textContent: r.question }));
    const open = el("button", { className: "ghost", textContent: "문제·해설 열기" });
    open.style.marginTop = "4px";
    open.addEventListener("click", () => openQuestion(r.round, r.number));
    row.append(open);
    box.append(row);
  }
}

function sentenceList(items) {
  if (!items.length) return el("div", { className: "small", textContent: "해당 문장이 없습니다." });
  const ul = el("ul");
  for (const it of items) {
    const li = el("li", {}, ...highlight(it.text, it.matched), " ", el("span", { className: "src", textContent: `(${it.sources.join(", ")}${it.count > 1 ? ` · ${it.count}회 출제` : ""} · 핵심어 ${it.matched.join(", ")})` }));
    if (it.tax_notice) li.append(" ", el("span", { className: "taxflag", textContent: it.tax_notice }));
    li.append(" ", ...basisBadges(it));
    ul.append(li);
  }
  return ul;
}
function renderSummary(sm) {
  const card = el("div", { className: "card" });
  const cv = sm.coverage;
  card.append(el("b", { textContent: "주제 요약 카드 " }));
  const star = el("button", { id: "starBtn", className: "ghost chip" });
  star.addEventListener("click", async () => {
    const saved = window.favoriteQueries.has(lastAsk.q);
    await api(saved ? "/api/favorites/delete" : "/api/favorites", { q: lastAsk.q, scope: lastAsk.scope });
    await loadFavorites();
    updateStar();
  });
  card.append(star);
  setTimeout(updateStar, 0);
  if (!cv.questions) { card.append(el("div", { className: "small", textContent: "요약할 관련 기출이 없습니다." })); return card; }
  card.append(el("div", { className: "small", textContent: `출제 현황: 관련 기출 ${cv.questions}문항 · ${cv.round_count}개 회차(${cv.rounds.join(", ")}회) · 가장 최근 ${cv.latest_round}회` }));
  if (sm.tax_notice) card.append(el("div", {}, el("span", { className: "taxflag", textContent: sm.tax_notice })));
  const ok = el("div", { className: "okc" }, el("h3", { textContent: "맞는 문장 (시험에서 옳다고 인정된 내용)" }), sentenceList(sm.right));
  const trap = el("div", { className: "trap" }, el("h3", { textContent: "자주 나온 함정 (틀린 문장으로 출제된 내용)" }), sentenceList(sm.traps));
  card.append(ok, trap);
  if (sm.excluded.length) {
    const ul = el("ul");
    for (const e of sm.excluded) ul.append(el("li", {}, `${e.id} [${e.kind}] ${e.question.slice(0, 60)}${e.question.length > 60 ? "…" : ""}`));
    card.append(el("h3", { textContent: "문장 요약에서 제외한 문항 (계산·조합·식별형·전항 정답 처리)" }), ul);
  }
  const run = el("div", { id: "topicRun", style: "margin-top:8px" });
  const go = el("button", { id: "topicGo", textContent: `이 주제 기출 풀기 (${sm.related_ids.length}문제)` });
  go.addEventListener("click", () => runSession(sm.related_ids, run, "이 주제 기출"));
  card.append(el("div", { className: "row" }, go), run);
  card.append(el("div", { className: "small", textContent: "문항 유형(옳은/옳지 않은 것)은 문제 글의 낱말로 자동 판별하므로 틀릴 수 있습니다. 시험 판단은 공식 해설을 따르세요." }));
  return card;
}


// '문제·해설 열기': 홈이면 기출 답안 패널로, 다른 화면이면 홈의 /#answers 로 가서 연다.
function openQuestion(round, number) {
  if (typeof loadQuestion === "function") { closeAsk(); showTab("answers"); loadQuestion(round, number); return; }
  try { sessionStorage.setItem("openQuestion", JSON.stringify([round, number])); } catch (e) { /* 저장 실패면 홈만 연다 */ }
  location.href = "/#answers";
}

function askIsOpen() { const d = $("askDrawer"); return !!d && !d.hidden; }
function openAsk() {
  $("askDrawer").hidden = false;
  document.body.classList.add("ask-open");
  $("askFab").setAttribute("aria-expanded", "true");
  $("q").focus();
}
function closeAsk() {
  if (!askIsOpen()) return;
  $("askDrawer").hidden = true;
  document.body.classList.remove("ask-open");
  $("askFab").setAttribute("aria-expanded", "false");
}

(function () {
  const fab = el("button", { type: "button", id: "askFab", className: "ask-fab", textContent: "질문", title: "궁금한 것을 물어보세요" });
  fab.setAttribute("aria-controls", "askDrawer");
  fab.setAttribute("aria-expanded", "false");
  const drawer = el("aside", { id: "askDrawer", className: "ask-drawer", hidden: true, ariaLabel: "질문" });
  drawer.setAttribute("role", "dialog");
  const close = el("button", { type: "button", id: "askClose", className: "ghost", textContent: "닫기" });
  const q = el("textarea", { id: "q", placeholder: "궁금한 것을 물어보세요. 예: 자기주식은 어떻게 처리해?" });
  q.setAttribute("aria-label", "질문");
  const scope = el("select", { id: "scope" }, el("option", { value: "all", textContent: "전체 회차" }), el("option", { value: "10", textContent: "최신 10회분" }));
  const go = el("button", { type: "button", id: "ask", textContent: "질문하기" });
  drawer.append(
    el("div", { className: "ask-head" }, el("h2", { textContent: "질문 · 기출 검색" }), close),
    el("div", { className: "small" }, "이론 30점 영역 · 기출 문항 검색과 공식 해설 · ", el("a", { id: "glossaryReviewLink", href: "/glossary-review", textContent: "용어 사전 검토" })),
    q,
    el("div", { className: "row" }, go, el("label", { className: "small" }, "검색 범위 ", scope)),
    el("div", { id: "recent", className: "small", style: "margin-top:8px" }),
    el("div", { id: "favs", className: "small", style: "margin-top:4px" }),
    el("div", { className: "small", style: "margin-top:6px", textContent: "요약 카드는 API 키 없이 동작합니다. API 키가 있으면 카드의 문장 모음이 Anthropic API 로 전송되어 3~5줄 설명이 덧붙고, 사용량에 따라 비용이 듭니다." }),
    el("div", { id: "answer" }));
  document.body.append(drawer, fab);
  fab.addEventListener("click", (e) => { e.stopPropagation(); askIsOpen() ? closeAsk() : openAsk(); });
  close.addEventListener("click", () => { closeAsk(); fab.focus(); });
  go.addEventListener("click", () => runAsk($("q").value, $("scope").value));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && askIsOpen() && !document.querySelector(".topbar [aria-expanded='true']")) { closeAsk(); fab.focus(); } });
  const fromHash = () => { if (location.pathname === "/" && location.hash === "#ask" && !askIsOpen()) openAsk(); };
  addEventListener("hashchange", fromHash);
  renderRecent();
  loadFavorites();
  fromHash();
})();
