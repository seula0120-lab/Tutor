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
  return { ok: response.ok, data: await response.json() };
}
const query = (obj) => new URLSearchParams(Object.entries(obj).filter(([, v]) => v !== "" && v != null)).toString();
const CIRCLES = ["①", "②", "③", "④"];
const pathOf = (q) => [q.subject, q.tax, q.unit].filter(Boolean).join(" › ");

// q: 공개용 문항(정답 없음). container: 카드를 그릴 요소. onResult({kind: "correct"|"wrong"|"seen", id}): 결과가 나왔을 때 부른다.
function renderCard(q, container, onResult = () => {}) {
  container.replaceChildren();
  container.append(el("div", { className: "meta", textContent: `${q.id} (${q.round}회 ${q.number}번) · ${pathOf(q)} · ${q.points}점` }),
                   el("div", { style: "margin:6px 0;font-weight:600", textContent: q.question }));
  for (const note of q.tax_notes || (q.tax_notice ? [q.tax_notice] : [])) container.append(el("div", {}, el("span", { className: "taxflag", textContent: note })));
  if (q.multi) container.append(el("div", { className: "notice", textContent: "복수정답 문항입니다. 정답 중 하나를 고르면 정답으로 처리합니다." }));
  const result = el("div");
  const buttons = q.choices.map((text, i) => {
    const b = el("button", { className: "choice", textContent: `${CIRCLES[i] || i + 1} ${text}` });
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
        result.replaceChildren(el("div", { className: "result-wrong", textContent: "오답입니다." }));
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
