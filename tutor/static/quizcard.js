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

// 위쪽 고정 바와 알약 탭. 홈 화면은 자체 탭(button)을 쓰고, 다른 화면은 이 함수가 링크 탭을 그린다. active: 켜 둘 탭 이름.
const TABS = [["ask", "질문"], ["answers", "기출 답안"], ["notebook", "오답노트"], ["mock", "모의고사"], ["analysis", "문제 분석"], ["words", "단어 주석"], ["study", "공부"], ["calendar", "캘린더"], ["toc", "목차"]];
function renderTopbar(active) {
  const links = TABS.map(([name, label]) => el("a", { className: "tab-link" + (name === active ? " active" : ""), href: name === "toc" ? "/toc" : name === "study" ? "/study" : name === "calendar" ? "/calendar" : `/#${name}`, textContent: label }));
  return el("header", { className: "topbar" }, el("div", { className: "topbar-inner" },
    el("a", { className: "brand", href: "/", textContent: "회계튜터" }, el("small", { textContent: " 전산세무 1급 이론" })), el("div", { className: "tabs-wrap" }, el("nav", { className: "tabs", ariaLabel: "화면 이동" }, ...links))));
}
// 탭 줄이 가로로 넘칠 때: 현재 탭을 보이는 가운데로 스크롤하고, 양쪽에 더 있으면 가장자리를 옅게 가린다(.more, .more-left).
function scrollTabIntoView(nav) {
  const active = nav && nav.querySelector(".active");
  if (!active) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  nav.scrollTo({ left: Math.max(0, active.offsetLeft - (nav.clientWidth - active.offsetWidth) / 2), behavior: reduce ? "auto" : "smooth" });
}
function watchTabOverflow(nav) {
  const wrap = nav.parentElement;
  const update = () => {
    wrap.classList.toggle("more", nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 2);
    wrap.classList.toggle("more-left", nav.scrollLeft > 2);          // 왼쪽에 가려진 탭이 있을 때
  };
  nav.addEventListener("scroll", update, { passive: true });
  addEventListener("resize", update);
  update();
}

// #topbar 자리에 상단 바를 넣고 탭 줄 동작(현재 탭 보이기·오른쪽 그라데이션)을 연결한다. 홈 이외의 화면용.
function mountTopbar(active) {
  $("topbar").replaceWith(renderTopbar(active));
  const nav = document.querySelector(".tabs");
  watchTabOverflow(nav);
  scrollTabIntoView(nav);
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

// q: 공개용 문항(정답 없음). container: 카드를 그릴 요소. onResult({kind: "correct"|"wrong"|"seen", id}): 결과가 나왔을 때 부른다.
function renderCard(q, container, onResult = () => {}) {
  container.replaceChildren();
  container.classList.add("paper");                          // 시험지 카드 모양(theme.css)
  container.classList.remove("locked");
  container.append(el("div", { className: "meta", textContent: `${q.id} (${q.round}회 ${q.number}번) · ${pathOf(q)} · ${q.points}점` }),
                   el("div", { className: "stem", textContent: q.question }));
  for (const note of q.tax_notes || (q.tax_notice ? [q.tax_notice] : [])) container.append(el("div", {}, el("span", { className: "taxflag", textContent: note })));
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

// 로그인한 사람 표시: 상단 바 오른쪽에 이름·(관리자면) 계정 관리·로그아웃. 모든 화면이 이 파일을 쓰므로 한 곳에서 붙인다.
addEventListener("DOMContentLoaded", async () => {
  const bar = document.querySelector(".topbar-inner");
  if (!bar) return;
  const { ok, data } = await api("/api/me");
  if (!ok || !data.user) return;
  const logout = el("button", { id: "logoutBtn", className: "ghost small", textContent: "로그아웃" });
  logout.addEventListener("click", async () => { await api("/api/logout", {}); location.href = "/login"; });
  bar.append(el("div", { id: "userbox", className: "userbox" },
    el("a", { className: "small", id: "userName", href: "/account", title: "내 비밀번호 바꾸기", textContent: data.user.name }),
    ...(data.user.is_admin ? [el("a", { id: "adminLink", className: "small", href: "/admin", textContent: "계정 관리" })] : []), logout));
  const nav = document.querySelector(".tabs");           // 이름·버튼이 붙어 탭 줄이 좁아졌으니 현재 탭을 다시 보이는 곳으로
  if (nav) { scrollTabIntoView(nav); dispatchEvent(new Event("resize")); }
});
