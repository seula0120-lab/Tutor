// 화면 자동 점검(수동 실행): 임시 서버 + 로컬 Chrome(--headless=new, CDP)으로 주요 화면을 눌러 보고 통과/실패를 출력한다.
// 사용법: node scripts/check_ui.mjs      (Chrome 위치가 다르면 CHROME_PATH 환경변수)
// 새 npm 패키지 없음: Node 내장 WebSocket·fetch 로 CDP 를 직접 다룬다. 스크린샷은 scratch/screens/ (Git 제외).
// 진짜 DB·API 키는 쓰지 않는다(임시 DB scratch/check.db, ANTHROPIC_API_KEY 제거).
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { inflateSync } from "node:zlib";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// PNG(8비트 RGB/RGBA, 비인터레이스)를 풀어 {width, height, px(x, y) → [r, g, b]} 로 돌려준다. 화면 조각의 색을 직접 비교하는 검사용.
function decodePng(buf) {
  let pos = 8, width = 0, height = 0, channels = 4; const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos), type = buf.toString("latin1", pos + 4, pos + 8), body = buf.subarray(pos + 8, pos + 8 + len);
    if (type === "IHDR") { width = body.readUInt32BE(0); height = body.readUInt32BE(4); channels = body[9] === 2 ? 3 : 4; }
    if (type === "IDAT") idat.push(body);
    pos += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat)), stride = width * channels, out = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)], line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let i = 0; i < stride; i++) {
      const a = i >= channels ? out[y * stride + i - channels] : 0, b = y ? out[(y - 1) * stride + i] : 0, c = y && i >= channels ? out[(y - 1) * stride + i - channels] : 0;
      const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      const pred = [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][filter];
      out[y * stride + i] = (line[i] + pred) & 255;
    }
  }
  return { width, height, px: (x, y) => [out[y * stride + x * channels], out[y * stride + x * channels + 1], out[y * stride + x * channels + 2]] };
}

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SHOTS = join(ROOT, "scratch", "screens");
const DESIGN_SHOTS = join(SHOTS, "design");
const STUDY_SHOTS = join(SHOTS, "study");
const OX_SHOTS = join(SHOTS, "ox");
const CAL_SHOTS = join(SHOTS, "calendar");
const CARRY_SHOTS = join(SHOTS, "carry");
const START_SHOTS = join(SHOTS, "start");
const NUM_SHOTS = join(SHOTS, "numbers");
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PYTHON = join(ROOT, ".venv", "bin", "python");
mkdirSync(SHOTS, { recursive: true });
mkdirSync(DESIGN_SHOTS, { recursive: true });
mkdirSync(STUDY_SHOTS, { recursive: true });
mkdirSync(OX_SHOTS, { recursive: true });
mkdirSync(CAL_SHOTS, { recursive: true });
mkdirSync(CARRY_SHOTS, { recursive: true });
mkdirSync(START_SHOTS, { recursive: true });
mkdirSync(NUM_SHOTS, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const procs = [];
let profile;
async function cleanup() {
  for (const p of procs) p.kill();
  await sleep(1000);                                                // Chrome 이 프로필 폴더 쓰기를 끝낼 때까지
  if (profile) { try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }); } catch { /* 임시 폴더라 남아도 무해 */ } }
}

async function startServer() {
  const p = spawn(PYTHON, [join(ROOT, "scripts", "check_server.py")], { cwd: ROOT, env: { ...process.env, ANTHROPIC_API_KEY: "" } });
  procs.push(p);
  p.stderr.on("data", (d) => process.stderr.write(d));
  return await new Promise((ok, fail) => {
    let buf = "";
    p.stdout.on("data", (d) => { buf += d; const m = buf.match(/PORT (\d+)/); if (m) ok(Number(m[1])); });
    p.on("exit", (c) => fail(new Error("서버가 종료됨: " + c)));
    setTimeout(() => fail(new Error("서버 시작 시간 초과")), 60000);
  });
}

async function startChrome() {
  profile = mkdtempSync(join(tmpdir(), "tutor-chrome-"));
  const p = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-gpu", "about:blank"], { stdio: "ignore" });
  procs.push(p);
  for (let i = 0; i < 100; i++) {                                   // DevToolsActivePort 파일에 실제 포트가 적힌다
    try { return Number(readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0]); } catch { await sleep(100); }
  }
  throw new Error("Chrome 디버깅 포트를 찾지 못함");
}

async function connectPage(port) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((ok, fail) => { ws.onopen = ok; ws.onerror = () => fail(new Error("CDP 연결 실패")); });
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { const { ok, fail } = pending.get(msg.id); pending.delete(msg.id); msg.error ? fail(new Error(msg.error.message)) : ok(msg.result); return; }
    if (msg.method === "Runtime.exceptionThrown") errors.push("예외: " + (msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text));
    if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") errors.push("console.error: " + msg.params.args.map((a) => a.value ?? a.description).join(" "));
    if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error" && !String(msg.params.entry.url || "").includes("favicon")) errors.push("로그: " + msg.params.entry.text + " " + (msg.params.entry.url || ""));
  };
  const send = (method, params = {}) => new Promise((ok, fail) => { const n = ++id; pending.set(n, { ok, fail }); ws.send(JSON.stringify({ id: n, method, params })); });
  await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable");
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (expression, label, timeout = 15000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) { try { if (await evaluate(expression)) return; } catch { /* 페이지 이동 중 */ } await sleep(150); }
    throw new Error(`기다리던 것이 나타나지 않음: ${label}`);
  };
  const goto = async (url) => { await send("Page.navigate", { url }); await sleep(300); await waitFor("document.readyState === 'complete'", "페이지 로드"); };
  let shot = 0;
  const screenshot = async (name) => {
    const r = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(SHOTS, `${String(++shot).padStart(2, "0")}-${name}.png`), Buffer.from(r.data, "base64"));
  };
  const pixels = async (x, y, width, height) => decodePng(Buffer.from((await send("Page.captureScreenshot", { format: "png", clip: { x, y, width, height, scale: 1 } })).data, "base64"));
  const shotTo = async (name, dir = DESIGN_SHOTS) => {              // 디자인 스크린샷: scratch/screens/design/<이름>.png (dir 로 폴더 변경)
    const r = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(dir, `${name}.png`), Buffer.from(r.data, "base64"));
    return `${name}.png`;
  };
  const key = async (name) => { for (const type of ["rawKeyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key: name, code: name, windowsVirtualKeyCode: ({ Escape: 27, Enter: 13, Tab: 9 })[name] || 9 }); };
  const emulate = (features) => send("Emulation.setEmulatedMedia", { features });      // 예: [{name:"prefers-color-scheme", value:"dark"}]
  const viewport = (width, height, mobile) => send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  return { evaluate, waitFor, goto, screenshot, pixels, shotTo, emulate, key, studyDir: STUDY_SHOTS, oxDir: OX_SHOTS, viewport, errors };
}

// 128회 1번 같은 문항의 정답 번호(들): 로컬 기출 파일에서 읽는다(화면에는 풀기 전에 정답이 없으므로 점검 스크립트만 안다).
function answersOf(round, number) {
  const data = JSON.parse(readFileSync(join(ROOT, "data", "bank", `${round}.json`), "utf8"));
  const q = data.theory.find((x) => x.number === number);
  return { right: q.answer.split(/\D+/).filter(Boolean).map(Number), count: q.choices.length };
}

const results = [];
async function scenario(name, fn) {
  try { await fn(); results.push([name, true, ""]); console.log(`통과  ${name}`); }
  catch (err) { results.push([name, false, err.message]); console.log(`실패  ${name} — ${err.message}`); }
}
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };

async function lookup(page, round, number) {
  await page.evaluate(`document.querySelector('.tab[data-tab="answers"]').click();
    document.getElementById('lkRound').value = '${round}'; document.getElementById('lkNumber').value = '${number}';
    document.getElementById('lkGo').click(); true`);
  await page.waitFor(`document.querySelectorAll('#card .choice').length > 0 && document.getElementById('card').textContent.includes('${round}회 ${number}번')`, `${round}회 ${number}번 카드`);
}

async function main() {
  const port = await startServer();
  const base = `http://127.0.0.1:${port}`;
  const page = await connectPage(await startChrome());
  await page.viewport(1100, 900, false);

  // 로그인 화면에서 아이디·비밀번호를 넣고 들어간다(화면 점검 서버가 admin 계정을 미리 만들어 둔다).
  const logIn = async (username, password) => {
    await page.goto(base + "/login");
    await page.waitFor(`document.getElementById('username') && document.getElementById('loginBtn').textContent === '로그인'`, "로그인 화면");
    await page.evaluate(`document.getElementById('username').value = ${JSON.stringify(username)}; document.getElementById('password').value = ${JSON.stringify(password)}; document.getElementById('loginBtn').click(); true`);
    await page.waitFor(`(location.pathname === '/' || location.pathname === '/start') && document.getElementById('userName')`, "로그인 뒤 첫 화면");
    if (await page.evaluate(`location.pathname`) === "/start") await page.goto(base + "/");     // 계획 없는 사용자는 /start 로 오지만, 대부분의 점검은 홈에서 시작한다(/start 는 아래 전용 시나리오)
  };
  await logIn("admin", "admin-pass-1");

  await scenario("질문하면 요약 카드가 나온다", async () => {
    await page.evaluate(`document.getElementById('q').value = '정상공손 비정상공손 처리'; document.getElementById('ask').click(); true`);
    await page.waitFor(`document.getElementById('answer').textContent.includes('주제 요약 카드')`, "요약 카드");
    await page.screenshot("summary-card");
  });

  const wrongInfo = answersOf(128, 1);
  let wrongId = "";
  let rightId = "";
  await scenario("128회 1번 오답 → 보기 잠김, 해설 없음", async () => {
    await lookup(page, 128, 1);
    const wrong = [...Array(wrongInfo.count).keys()].map((i) => i + 1).find((n) => !wrongInfo.right.includes(n));
    wrongId = await page.evaluate(`document.querySelector('#card .meta').textContent.split(' ')[0]`);
    await page.evaluate(`document.querySelectorAll('#card .choice')[${wrong - 1}].click(); true`);
    await page.waitFor(`document.getElementById('card').textContent.includes('오답입니다.')`, "오답 표시");
    assert(await page.evaluate(`[...document.querySelectorAll('#card .choice')].every((b) => b.disabled)`), "보기가 잠기지 않음");
    assert(await page.evaluate(`!document.querySelector('#card .explain')`), "오답인데 해설이 보임");
    await page.screenshot("wrong-answer");
  });

  await scenario("정답 → 해설이 나온다", async () => {
    const info = answersOf(128, 2);
    await lookup(page, 128, 2);
    rightId = await page.evaluate(`document.querySelector('#card .meta').textContent.split(' ')[0]`);
    await page.evaluate(`document.querySelectorAll('#card .choice')[${info.right[0] - 1}].click(); true`);
    await page.waitFor(`document.querySelector('#card .explain') && document.getElementById('card').textContent.includes('정답입니다')`, "정답·해설");
    await page.screenshot("correct-answer");
  });

  await scenario("단어 주석을 누르면 쉬운 풀이가 나온다", async () => {
    await page.evaluate(`document.querySelector('.tab[data-tab="words"]').click();
      document.getElementById('wdRound').value = '128'; document.getElementById('wdNumber').value = '1';
      document.getElementById('wdGo').click(); true`);
    await page.waitFor(`document.querySelector('#wdCard .term')`, "밑줄 친 용어");
    await page.evaluate(`document.querySelector('#wdCard .term').click(); true`);
    await page.waitFor(`getComputedStyle(document.getElementById('wdMeaning')).display !== 'none' && document.getElementById('wdMeaning').textContent.length > 3`, "용어 풀이");
    await page.screenshot("word-meaning");
  });

  await scenario("오답노트에 방금 틀린 128회 1번이 보인다", async () => {
    await page.evaluate(`document.querySelector('.tab[data-tab="notebook"]').click(); true`);
    await page.waitFor(`document.getElementById('nbList').textContent.includes(${JSON.stringify(wrongId)})`, "오답노트 목록");
    assert(await page.evaluate(`!document.getElementById('nbList').textContent.includes(${JSON.stringify(rightId)})`), "맞힌 문항이 오답노트에 있음");
    await page.screenshot("notebook");
  });

  await scenario("모의고사 제출 → 점수가 나온다", async () => {
    await page.evaluate(`document.querySelector('.tab[data-tab="mock"]').click(); document.getElementById('mockStart').click(); true`);
    await page.waitFor(`document.querySelectorAll('#mockBody .hit').length === 15`, "15문항");
    await page.evaluate(`document.querySelectorAll('#mockBody .hit').forEach((h) => h.querySelector('.choice').click()); document.getElementById('mockSubmit').click(); true`);
    await page.waitFor(`document.getElementById('mockResult') && /점수 \\d+ \\/ 30점/.test(document.getElementById('mockResult').textContent)`, "점수");
    await page.screenshot("mock-result");
  });

  await scenario("/toc 가 열리고 문항을 누르면 카드가 열린다", async () => {
    await page.goto(base + "/toc");
    await page.waitFor(`document.querySelectorAll('details.subject').length === 3`, "과목 3개");
    await page.evaluate(`document.querySelector('details.subject').open = true; document.querySelector('details.subject details').open = true; true`);
    await page.evaluate(`document.querySelector('details.subject details .qrow').click(); true`);
    await page.waitFor(`document.querySelector('details.subject details .slot .choice')`, "인라인 퀴즈 카드");
    await page.screenshot("toc");
  });

  await scenario("오프라인 파일(file://): 오답 잠금·해설 없음, 정답 해설", async () => {
    const out = spawn(PYTHON, [join(ROOT, "scripts", "export_offline.py")], { cwd: ROOT });
    await new Promise((ok) => out.on("exit", ok));
    await page.goto("file://" + join(ROOT, "data", "export", "회계튜터_목차.html"));
    await page.evaluate(`document.querySelector('details.subject').open = true; document.querySelector('details.subject details').open = true; true`);
    const info = await page.evaluate(`(() => { const q = JSON.parse(document.getElementById('data').textContent)[0].units[0].questions[0];
      return { answer: q.answer, count: q.choices.length }; })()`);
    const right = info.answer.split(",").map(Number);
    const wrong = [...Array(info.count).keys()].map((i) => i + 1).find((n) => !right.includes(n));
    await page.evaluate(`document.querySelector('details.subject details .qrow').click(); document.querySelectorAll('details.subject details .slot .choice')[${wrong - 1}].click(); true`);
    assert(await page.evaluate(`document.querySelector('details.subject details .slot').textContent.includes('오답입니다.')`), "오답 문구 없음");
    assert(await page.evaluate(`[...document.querySelectorAll('details.subject details .slot .choice')].every((b) => b.disabled) && !document.querySelector('details.subject details .slot .explain')`), "잠금 안 됨 또는 해설 노출");
    await page.evaluate(`document.querySelectorAll('details.subject details .qrow')[1].click(); true`);
    const info2 = await page.evaluate(`(() => { const q = JSON.parse(document.getElementById('data').textContent)[0].units[0].questions[1]; return q.answer; })()`);
    await page.evaluate(`document.querySelectorAll('details.subject details')[0].querySelectorAll('.slot')[1].querySelectorAll('.choice')[${Number(info2.split(",")[0]) - 1}].click(); true`);
    assert(await page.evaluate(`!!document.querySelectorAll('details.subject details')[0].querySelectorAll('.slot')[1].querySelector('.explain')`), "정답인데 해설 없음");
    await page.screenshot("offline");
  });

  await scenario("390px 폭에서 가로 스크롤이 없다", async () => {
    await page.viewport(390, 844, true);
    const overflow = async () => page.evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
    const bad = [];
    if ((await overflow()) > 0) bad.push("/toc");
    await page.screenshot("mobile-toc");
    await page.goto(base + "/");
    for (const tab of ["ask", "analysis", "answers", "words", "notebook", "mock"]) {
      await page.evaluate(`document.querySelector('.tab[data-tab="${tab}"]').click(); true`);
      await sleep(400);
      if ((await overflow()) > 0) bad.push(`홈/${tab}`);
    }
    await page.evaluate(`document.querySelector('.tab[data-tab="ask"]').click(); document.getElementById('q').value = '정상공손 비정상공손 처리'; document.getElementById('ask').click(); true`);
    await page.waitFor(`document.getElementById('answer').textContent.includes('주제 요약 카드')`, "요약 카드(모바일)");
    if ((await overflow()) > 0) bad.push("홈/요약 카드");
    await page.screenshot("mobile-summary");
    assert(!bad.length, "가로로 넘치는 화면: " + bad.join(", "));
  });


  // ---- 디자인 점검: 토큰·접근성·화면별 스크린샷(라이트/다크/모바일) ----
  const contrast = (a, b) => {
    const lum = (hex) => { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const tokens = () => page.evaluate(`(() => { const s = getComputedStyle(document.documentElement); const o = {};
    for (const n of ["bg","surface","paper","note","text","muted","accent","on-accent","ok","ok-soft","bad","bad-soft","warn","warn-soft","accent-soft","mark","mark-text"]) o[n] = s.getPropertyValue("--" + n).trim(); return o; })()`);
  const bodyBg = () => page.evaluate(`getComputedStyle(document.body).backgroundColor`);
  const tab = (name) => page.evaluate(`document.querySelector('.tab[data-tab="${name}"]').click(); true`);

  await scenario("theme.css 토큰: 라이트·다크 팔레트와 글 대비 AA(4.5:1)", async () => {
    await page.viewport(1100, 900, false);
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.goto(base + "/");
    const light = await tokens();
    assert(light.bg.toUpperCase() === "#F5F6F8" && light.accent.toUpperCase() === "#4F46E5", "라이트 팔레트 값이 다름");
    assert((await bodyBg()) === "rgb(245, 246, 248)", "라이트 바탕색이 적용되지 않음");
    await page.emulate([{ name: "prefers-color-scheme", value: "dark" }]);
    const dark = await tokens();
    assert(dark.bg.toUpperCase() === "#0F1115" && dark.accent.toUpperCase() === "#8B87FF", "다크 팔레트 값이 다름");
    assert((await bodyBg()) === "rgb(15, 17, 21)", "다크 바탕색이 적용되지 않음");
    const bad = [];
    for (const [label, t] of [["라이트", light], ["다크", dark]]) {
      for (const [fg, bg] of [["text", "bg"], ["text", "surface"], ["text", "paper"], ["text", "note"], ["muted", "bg"], ["muted", "surface"], ["accent", "surface"], ["accent", "bg"], ["on-accent", "accent"],
                              ["ok", "ok-soft"], ["bad", "bad-soft"], ["warn", "warn-soft"], ["text", "accent-soft"], ["mark-text", "mark"], ["ok", "surface"], ["bad", "surface"]]) {
        const ratio = contrast(t[fg], t[bg]);
        if (ratio < 4.5) bad.push(`${label} ${fg}/${bg} ${ratio.toFixed(2)}`);
      }
    }
    assert(!bad.length, "대비 부족: " + bad.join(", "));
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
  });

  await scenario("공통 구조: 고정 상단 바·알약 탭 순서·글꼴·세 화면이 theme.css 사용", async () => {
    await page.goto(base + "/");
    assert((await page.evaluate(`getComputedStyle(document.querySelector('.topbar')).position`)) === "sticky", "상단 바가 sticky 가 아님");
    const labels = await page.evaluate(`[...document.querySelectorAll('.topbar .tabs > *')].map((n) => n.textContent.trim())`);
    const order = ["질문", "기출 답안", "오답노트", "모의고사", "문제 분석"];
    assert(order.every((l, i) => labels[i] === l) && labels[labels.length - 1] === "목차" && labels[labels.length - 2] === "캘린더", "탭 순서가 다름: " + labels.join(" · "));
    assert((await page.evaluate(`getComputedStyle(document.querySelector('.tab')).borderRadius`)) === "999px", "알약 모양이 아님");
    await page.waitFor(`Promise.all([document.fonts.load('16px Pretendard', '가'), document.fonts.load('600 16px "Noto Serif KR"', '가')]).then((r) => r.every((x) => x.length > 0))`, "번들 글꼴 로드");
    for (const path of ["/", "/toc", "/glossary-review"]) {
      await page.goto(base + path);
      assert(await page.evaluate(`!!document.querySelector('link[href="/static/theme.css"]') && !!document.querySelector('.topbar')`), `${path} 가 theme.css·상단 바를 쓰지 않음`);
    }
    const css = await (await fetch(base + "/static/fonts/PretendardVariable.woff2")).arrayBuffer();
    assert(css.byteLength > 100000, "글꼴 파일을 받지 못함");
  });

  await scenario("시험지 카드: OMR 보기·오답 잠금 표시·주황 개정 배지", async () => {
    await page.goto(base + "/");
    await lookup(page, 128, 3);
    const style = await page.evaluate(`(() => { const o = document.querySelector('#card .omr'); const stem = document.querySelector('#card .stem');
      return { radius: getComputedStyle(o).borderRadius, serif: getComputedStyle(stem).fontFamily, paper: document.getElementById('card').classList.contains('paper') }; })()`);
    assert(style.paper && style.radius === "50%" && style.serif.includes("Noto Serif KR"), "시험지 카드/OMR 모양이 아님: " + JSON.stringify(style));
    await page.evaluate(`const flag = document.createElement('span'); flag.className = 'taxflag'; flag.id = 'probe'; flag.textContent = '테스트'; document.getElementById('card').append(flag); true`);
    const orange = await page.evaluate(`(() => { const c = getComputedStyle(document.getElementById('probe')).color.match(/\\d+/g).map(Number); return c[0] > c[2] + 60 && c[0] > 120; })()`);
    assert(orange, "세법 개정 배지가 주황 계열이 아님");
  });

  await scenario("모의고사 2단: 넓은 화면은 문제지+고정 OMR, 좁은 화면은 하단 바", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/"); await tab("mock");
    await tab("mock");
    await page.evaluate(`document.getElementById('mockStart').click(); true`);
    await page.waitFor(`document.querySelectorAll('#mockBody .hit').length === 15 && document.querySelectorAll('.omr-table tr').length === 15`, "문제지·OMR");
    const wide = await page.evaluate(`(() => { const a = document.querySelector('.sheet').getBoundingClientRect(), b = document.querySelector('.omr-panel').getBoundingClientRect();
      return { side: b.left > a.right - 1, sticky: getComputedStyle(document.querySelector('.omr-panel')).position }; })()`);
    assert(wide.side && wide.sticky === "sticky", "2단/고정 OMR 아님: " + JSON.stringify(wide));
    await page.evaluate(`document.querySelectorAll('.omr-table tr')[2].querySelectorAll('button')[1].click(); true`);
    assert(await page.evaluate(`document.querySelectorAll('#mockBody .hit')[2].querySelectorAll('.choice')[1].classList.contains('picked') && document.querySelector('.omr-progress').textContent.startsWith('1 / 15')`), "OMR 칸을 눌러도 문제지에 반영되지 않음");
    await page.viewport(390, 844, true);
    const narrow = await page.evaluate(`(() => { const p = document.querySelector('.omr-panel'); const r = p.getBoundingClientRect();
      return { fixed: getComputedStyle(p).position, bottom: Math.round(innerHeight - r.bottom), submit: document.getElementById('mockSubmit').getBoundingClientRect().height > 0 }; })()`);
    assert(narrow.fixed === "fixed" && narrow.bottom === 0 && narrow.submit, "하단 바가 아님: " + JSON.stringify(narrow));
    assert((await page.evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)) <= 0, "모의고사 화면이 가로로 넘침");
    await page.viewport(1100, 900, false);
  });

  await scenario("요약 카드: ✔/✘ 묶음과 형광펜", async () => {
    await page.goto(base + "/");
    await page.evaluate(`document.getElementById('q').value = '정상공손 비정상공손 처리'; document.getElementById('ask').click(); true`);
    await page.waitFor(`document.querySelector('#answer .card mark')`, "형광펜 칠한 핵심어");
    const marks = await page.evaluate(`({ ok: getComputedStyle(document.querySelector('.okc h3'), '::before').content, trap: getComputedStyle(document.querySelector('.trap h3'), '::before').content,
      bg: getComputedStyle(document.querySelector('#answer .card mark')).backgroundColor, note: getComputedStyle(document.querySelector('#answer .card')).borderLeftWidth })`);
    assert(marks.ok.includes("✔") && marks.trap.includes("✘") && marks.bg !== "rgba(0, 0, 0, 0)" && marks.note === "6px", "요약 카드 모양이 다름: " + JSON.stringify(marks));
  });

  await scenario("접근성: 키보드 초점 링·움직임 줄이기·다크에서도 가로 스크롤 없음", async () => {
    await page.goto(base + "/");
    await page.evaluate(`document.getElementById('q').focus(); true`);
    await page.key("Tab");                                              // 진짜 키보드 입력이어야 :focus-visible 이 켜진다
    const ring = await page.evaluate(`(() => { const b = document.activeElement; const s = getComputedStyle(b); return { tag: b.id, width: s.outlineWidth, style: s.outlineStyle }; })()`);
    assert(ring.style !== "none" && parseFloat(ring.width) >= 2, "초점 링이 보이지 않음: " + JSON.stringify(ring));
    await page.emulate([{ name: "prefers-reduced-motion", value: "reduce" }]);
    assert((await page.evaluate(`getComputedStyle(document.querySelector('.tab')).transitionDuration`)).split(",").every((v) => parseFloat(v) === 0), "움직임 줄이기에서 전환이 남아 있음");
    await page.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }, { name: "prefers-color-scheme", value: "dark" }]);
    await page.viewport(390, 844, true);
    const bad = [];
    for (const path of ["/", "/toc", "/glossary-review"]) {
      await page.goto(base + path);
      await sleep(300);
      if ((await page.evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)) > 0) bad.push(path);
    }
    assert(!bad.length, "다크 390px 에서 가로로 넘치는 화면: " + bad.join(", "));
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(1100, 900, false);
  });

  await scenario("모바일 탭 줄: 오른쪽 그라데이션·현재 탭 자동 스크롤", async () => {
    await page.viewport(390, 844, true);
    await page.goto(base + "/");
    const more = () => page.evaluate(`document.querySelector('.tabs-wrap').classList.contains('more')`);
    await page.waitFor(`document.querySelector('.tabs').scrollWidth > document.querySelector('.tabs').clientWidth`, "탭 줄이 가로로 넘침");
    assert(await more(), "처음에는 오른쪽에 더 있다는 그라데이션이 켜져야 함");
    assert((await page.evaluate(`getComputedStyle(document.querySelector('.tabs')).webkitMaskImage`)).includes("linear-gradient"), "오른쪽 가장자리 페이드(마스크) 없음");
    await tab("words");
    const visible = `(() => { const n = document.querySelector('.tabs').getBoundingClientRect(), a = document.querySelector('.tab.active').getBoundingClientRect(); return a.left >= n.left - 1 && a.right <= n.right + 1; })()`;
    await page.waitFor(visible, "현재 탭(단어 주석)이 보이도록 스크롤");
    await page.waitFor(`!document.querySelector('.tabs-wrap').classList.contains('more') || document.querySelector('.tabs').scrollLeft > 0`, "스크롤 후 상태 갱신");
    await page.waitFor(`document.querySelector('.tabs-wrap').classList.contains('more-left') === (document.querySelector('.tabs').scrollLeft > 2)`, "스크롤하면 왼쪽 그라데이션도 켜짐");
    assert(await page.evaluate(`document.querySelector('.tabs').scrollLeft > 2 ? getComputedStyle(document.querySelector('.tabs')).webkitMaskImage.includes('linear-gradient') : true`), "왼쪽 가장자리 페이드(마스크)가 없음");
    assert(await page.evaluate(`(() => { const brand = document.querySelector('.brand').getBoundingClientRect(), w = document.querySelector('.tabs-wrap').getBoundingClientRect(); return w.left >= brand.right - 1 && getComputedStyle(document.querySelector('.tabs-wrap')).overflowX === 'hidden'; })()`), "탭 줄이 로고 영역을 침범함");
    await page.evaluate(`document.querySelector('.tabs').scrollLeft = 0; true`);
    await page.waitFor(`!document.querySelector('.tabs-wrap').classList.contains('more-left')`, "맨 왼쪽에서는 왼쪽 그라데이션이 꺼짐");
    await page.goto(base + "/toc");                                       // 목차 화면: 목차 탭이 활성이고 보여야 한다
    await page.waitFor(`(() => { const n = document.querySelector('.tabs').getBoundingClientRect(), a = document.querySelector('.tab-link.active').getBoundingClientRect(); return a.right <= n.right + 1 && a.left >= n.left - 1; })()`, "목차 탭이 보임");
    await page.goto(base + "/#mock");
    await page.waitFor(`document.querySelector('.tab.active').dataset.tab === 'mock'`, "해시 링크로 모의고사 탭 열림");
    await page.viewport(1100, 900, false);
  });

  await scenario("공부: 탭 → 재무 단원 노트 → 읽음 체크 → 진도율 반영 → 5문제 풀기", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/");
    await page.evaluate(`document.querySelector('.topbar .tab-link[href="/study"]').click(); true`);
    await page.waitFor(`location.pathname === '/study' && document.querySelectorAll('#subjects .subject-card').length === 3`, "과목 카드 3개");
    const cardText = (subject) => `(document.querySelector('.subject-card[data-subject="${subject}"] .progress-text') || {}).textContent || ''`;
    const labels = await page.evaluate(`[...document.querySelectorAll('.subject-card h2')].map((h) => h.textContent)`);
    assert(labels.join() === "재무회계,원가관리회계,세무회계", "과목 카드 이름: " + labels.join());
    assert((await page.evaluate(cardText("재무회계"))).includes("진도율 0% · 읽음·이해함 0/12"), "처음 진도율이 0 이 아님: " + await page.evaluate(cardText("재무회계")));
    assert(await page.evaluate(`document.querySelectorAll('#roadmap .road-row').length >= 8 && !!document.querySelector('#roadmap .road-row .btn')`), "복귀 로드맵 줄/노트 열기 버튼 없음");
    await page.evaluate(`[...document.querySelectorAll('.subject-card[data-subject="재무회계"] .unit-link')].find((a) => a.textContent === '재고자산').click(); true`);
    await page.waitFor(`location.pathname.startsWith('/study/') && document.getElementById('sec-check')`, "단원 노트");
    const sections = await page.evaluate(`[...document.querySelectorAll('.study-section')].map((s) => s.dataset.section).join()`);
    assert(sections === "glance,concept,practice,sentences,formula,changes,ox,quiz,check", "노트 칸 구성: " + sections);
    assert(await page.evaluate(`document.querySelectorAll('#sec-glance .stat').length === 4 && document.querySelectorAll('#sec-concept .concept-list li').length >= 5 && document.querySelectorAll('#sec-sentences .src-badge').length > 0`), "한눈에/개념/기출 문장 칸이 비어 있음");
    assert(await page.evaluate(`['concept','practice','formula'].every((k) => document.querySelector('#sec-' + k + ' .draft-badge'))`), "AI 초안 배지 없음");
    await page.evaluate(`document.querySelector('#sec-concept .term-chip').click(); true`);
    await page.waitFor(`!document.getElementById('termMeaning').hidden && document.getElementById('termMeaning').textContent.length > 5`, "용어 뜻 표시");
    await page.evaluate(`document.querySelector('#sec-concept .small-btn').click(); true`);
    await page.waitFor(`!document.querySelector('#sec-concept .draft-badge') && document.querySelector('#sec-concept .reviewed-badge')`, "검토 완료 후 배지 사라짐");
    await page.evaluate(`document.getElementById('check-read').click(); true`);
    await page.waitFor(`document.getElementById('checkInfo').textContent.includes('읽음') && /진도율 [1-9]\\d*%/.test(document.getElementById('checkInfo').textContent)`, "읽음 체크 후 진도율");
    await page.goto(base + "/study");
    await page.waitFor(`document.querySelectorAll('#subjects .subject-card').length === 3`, "목록 다시 열기");
    assert((await page.evaluate(cardText("재무회계"))).includes("읽음·이해함 1/12"), "진도율이 목록에 반영되지 않음: " + await page.evaluate(cardText("재무회계")));
    await page.goto(base + "/study/" + encodeURIComponent("재고자산"));
    await page.waitFor(`document.getElementById('unitQuizGo') && !document.querySelector('#sec-concept .draft-badge')`, "검토 완료 상태 유지");
    await page.evaluate(`document.getElementById('unitQuizGo').click(); true`);
    await page.waitFor(`document.querySelectorAll('#unitRun .choice').length >= 2`, "5문제 풀기 열림");
    assert(await page.evaluate(`document.getElementById('unitRun').textContent.includes('1 / 5')`), "5문제 진행 표시 없음");
  });

  await scenario("공부: 원가관리회계 단원 노트 → 공식·풀이 순서·자주 틀리는 지점·대표 기출 → 5문제 풀기", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/study");
    await page.waitFor(`document.querySelectorAll('#subjects .subject-card').length === 3`, "과목 카드");
    const units = await page.evaluate(`[...document.querySelectorAll('.subject-card[data-subject="원가회계"] .unit-link')].map((a) => a.textContent).join()`);
    assert(units.split(",").length === 7, "원가관리회계 단원이 7개가 아님: " + units);
    assert(!(await page.evaluate(`document.querySelector('.subject-card[data-subject="원가회계"]').textContent.includes('노트 준비 중')`)), "원가 단원에 '노트 준비 중'이 남아 있음");
    await page.evaluate(`[...document.querySelectorAll('.subject-card[data-subject="원가회계"] .unit-link')].find((a) => a.textContent === '개별원가계산').click(); true`);
    await page.waitFor(`location.pathname.startsWith('/study/') && document.getElementById('sec-formula') && document.querySelector('#sec-formula .choice')`, "원가 노트와 대표 기출");
    const checks = await page.evaluate(`({
      sub: document.querySelector('.sub').textContent,
      formulas: document.querySelectorAll('#sec-formula .formula-list li').length,
      steps: document.querySelectorAll('#sec-formula ol li').length,
      pitfalls: document.querySelectorAll('#formulaPitfalls li').length,
      badges: ['concept','practice','formula'].every((k) => document.querySelector('#sec-' + k + ' .draft-badge')),
      confirm: document.getElementById('sec-practice').textContent.includes('확인 필요'),
    })`);
    assert(checks.sub.includes("원가회계") || checks.sub.includes("원가관리회계"), "과목 표시: " + checks.sub);
    assert(checks.formulas >= 4 && checks.steps >= 3, `공식/풀이 순서가 적음: ${JSON.stringify(checks)}`);
    assert(checks.pitfalls >= 1 && checks.pitfalls <= 2, "자주 틀리는 지점이 1~2개가 아님: " + checks.pitfalls);
    assert(checks.badges && checks.confirm, "AI 초안 배지 또는 '확인 필요' 표시 없음");
    await page.evaluate(`document.getElementById('unitQuizGo').click(); true`);
    await page.waitFor(`document.querySelectorAll('#unitRun .choice').length >= 2 && document.getElementById('unitRun').textContent.includes('1 / 5')`, "5문제 풀기 열림");
  });

  await scenario("공부: 세무회계 단원 노트 → ⑥ 바뀐 것(쪽수 출처)·개념 줄 표시 → 바뀐 세법 모아 보기", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/study");
    await page.waitFor(`document.querySelectorAll('#subjects .subject-card').length === 3 && document.getElementById('taxChangesLink')`, "과목 카드와 모아 보기 링크");
    const units = await page.evaluate(`[...document.querySelectorAll('.subject-card[data-subject="세무회계"] .unit-link')].map((a) => a.textContent).join()`);
    assert(units.split(",").length === 15, "세무회계 단원이 15개가 아님: " + units);
    assert(!(await page.evaluate(`document.querySelector('.subject-card[data-subject="세무회계"]').textContent.includes('노트 준비 중')`)), "세무 단원에 '노트 준비 중'이 남아 있음");
    await page.evaluate(`[...document.querySelectorAll('.subject-card[data-subject="세무회계"] .unit-link')].find((a) => a.textContent === '세금계산서').click(); true`);
    await page.waitFor(`location.pathname.startsWith('/study/') && document.getElementById('sec-changes') && document.querySelector('#sec-changes .change-item')`, "세무 노트의 ⑥ 칸");
    const checks = await page.evaluate(`({
      sub: document.querySelector('.sub').textContent,
      concept: document.querySelectorAll('#sec-concept .concept-list li').length,
      diff: document.querySelectorAll('#sec-concept .diff-badge').length,
      check: document.querySelectorAll('#sec-concept .check-badge').length,
      page: (document.querySelector('#sec-changes .pdf-badge') || {}).textContent,
      gap: (document.querySelector('#sec-changes .taxflag-gap') || {}).textContent,
      link: (document.getElementById('allChangesLink') || {}).textContent,
    })`);
    assert(checks.sub.includes("부가가치세"), "세목 표시: " + checks.sub);
    assert(checks.concept >= 5 && checks.diff >= 1 && checks.check >= 1, `개념 줄/옛 기출과 다름/확인 필요 표시: ${JSON.stringify(checks)}`);
    assert(/2025 개정세법 p\.\d+/.test(checks.page || ""), "개정세법 쪽수 표시 없음: " + checks.page);
    assert(checks.gap === "2023·2024·2026 개정 자료 없음 — 확인 필요", "자료 없는 해 안내: " + checks.gap);
    await page.evaluate(`document.getElementById('allChangesLink').click(); true`);
    await page.waitFor(`location.pathname === '/study-changes' && document.querySelectorAll('.change-group').length === 3`, "모아 보기 화면의 세목 3개");
    const all = await page.evaluate(`({
      taxes: [...document.querySelectorAll('.change-group')].map((g) => g.dataset.tax).join(),
      items: document.querySelectorAll('.change-item').length,
      pages: [...document.querySelectorAll('.change-item .pdf-badge')].every((b) => /2025 개정세법 p[.]\\d+/.test(b.textContent)),
      gap: document.querySelector('.taxflag-gap').textContent,
      concept: !!document.querySelector('.concept-list'),
    })`);
    assert(all.taxes === "법인세,부가가치세,소득세", "세목 순서: " + all.taxes);
    assert(all.items >= 25 && all.pages, `개정 항목/쪽수 출처: ${JSON.stringify(all)}`);
    assert(all.gap.includes("확인 필요") && !all.concept, "자료 없는 해 안내 또는 ⑥ 밖 내용이 섞임");
  });

  await scenario("공부 화면 스크린샷 21장(라이트·다크·모바일)이 scratch/screens/study/ 에 저장된다", async () => {
    const files = [];
    const shots = {
      "공부-목록": async () => { await page.goto(base + "/study"); await page.waitFor(`document.querySelectorAll('#subjects .subject-card').length === 3`, "목록"); },
      "노트-개념": async () => { await page.goto(base + "/study/" + encodeURIComponent("재고자산")); await page.waitFor(`document.getElementById('sec-check')`, "노트"); },
      "노트-공식": async () => { await page.goto(base + "/study/" + encodeURIComponent("재고자산")); await page.waitFor(`document.getElementById('sec-formula') && document.querySelector('#sec-formula .choice')`, "공식"); await page.evaluate(`document.getElementById('sec-formula').scrollIntoView(); true`); },
      "원가노트-공식": async () => { await page.goto(base + "/study/" + encodeURIComponent("종합원가계산")); await page.waitFor(`document.getElementById('formulaPitfalls') && document.querySelector('#sec-formula .choice')`, "원가 공식"); await page.evaluate(`document.getElementById('sec-formula').scrollIntoView(); true`); },
      "세무노트-바뀐것": async () => { await page.goto(base + "/study/" + encodeURIComponent("세금계산서")); await page.waitFor(`document.querySelector('#sec-changes .change-item')`, "세무 ⑥"); await page.evaluate(`document.getElementById('sec-changes').scrollIntoView(); true`); },
      "바뀐세법-모아보기": async () => { await page.goto(base + "/study-changes"); await page.waitFor(`document.querySelectorAll('.change-group').length === 3`, "모아 보기"); },
      "노트-5문제": async () => { await page.goto(base + "/study/" + encodeURIComponent("자본")); await page.waitFor(`document.getElementById('unitQuizGo')`, "노트"); await page.evaluate(`document.getElementById('unitQuizGo').click(); true`); await page.waitFor(`document.querySelectorAll('#unitRun .choice').length >= 2`, "5문제"); await page.evaluate(`document.getElementById('sec-quiz').scrollIntoView(); true`); },
    };
    for (const [variant, scheme, width, height, mobile] of [["light", "light", 1100, 900, false], ["dark", "dark", 1100, 900, false], ["mobile", "light", 390, 844, true]]) {
      await page.viewport(width, height, mobile);
      await page.emulate([{ name: "prefers-color-scheme", value: scheme }]);
      for (const [name, setup] of Object.entries(shots)) {
        await setup();
        await sleep(300);
        if ((await page.evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)) > 0) throw new Error(`${name}-${variant}: 가로 스크롤 생김`);
        files.push(await page.shotTo(`${name}-${variant}`, page.studyDir));
      }
    }
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(1100, 900, false);
    assert(files.length === 21, "스크린샷 21장이 아님");
  });

  // ---- O/X · 간격 복습 · 오늘의 공부. 서버 시계를 /api/test/clock 으로 하루씩 넘긴다(점검 서버만 열려 있음).
  const setDay = (days) => page.evaluate(`fetch('/api/test/clock', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ days: ${days} }) }).then((r) => r.json())`);
  const getJson = (path) => page.evaluate(`fetch(${JSON.stringify(path)}).then((r) => r.json())`);
  const postJson = (path, body) => page.evaluate(`fetch(${JSON.stringify(path)}, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(${JSON.stringify(body)}) }).then((r) => r.json())`);
  let wrongSentences = [];
  await scenario("O/X: 노트의 '이 단원 O/X 20개' → 20문장 풀기 → 정오·출처 → 틀린 문장 목록", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/study/" + encodeURIComponent("자본"));
    await page.waitFor(`document.getElementById('unitOxGo')`, "O/X 버튼");
    assert((await page.evaluate(`document.getElementById('unitOxGo').textContent`)) === "이 단원 O/X 20개", "버튼 글자");
    await page.evaluate(`document.getElementById('unitOxGo').click(); true`);
    await page.waitFor(`location.pathname === '/ox' && document.querySelector('#runBox .ox-btn')`, "O/X 첫 문장");
    for (let i = 1; i <= 20; i++) {
      await page.waitFor(`document.getElementById('oxProgress') && document.getElementById('oxProgress').textContent === '${i} / 20'`, `${i}번째 문장`);
      assert(await page.evaluate(`!document.querySelector('#runBox .ox-result').textContent`), "풀기 전에 정오가 보임");
      await page.evaluate(`document.querySelector('#runBox .ox-o').click(); true`);                       // 일부러 늘 O: X 문장은 틀리게 된다
      await page.waitFor(`document.querySelector('#runBox .ox-result .result-right, #runBox .ox-result .result-wrong')`, "정오 표시");
      assert(await page.evaluate(`document.querySelectorAll('#runBox .ox-result .src-badge').length > 0 && /\\d+-\\d+/.test(document.querySelector('#runBox .ox-result .src-badge').textContent)`), "출처(회차-번호)가 없음");
      assert(await page.evaluate(`[...document.querySelectorAll('#runBox .ox-btn')].every((b) => b.disabled)`), "정오 뒤에도 버튼이 열려 있음");
      await page.evaluate(`document.getElementById('oxNext').click(); true`);
    }
    await page.waitFor(`document.getElementById('oxScore')`, "결과");
    const score = await page.evaluate(`document.getElementById('oxScore').textContent`);
    const right = Number(score.match(/20문장 중 (\d+)문장/)[1]);
    wrongSentences = await page.evaluate(`[...document.querySelectorAll('#oxWrongList li')].map((li) => li.firstChild.textContent)`);
    assert(wrongSentences.length === 20 - right && wrongSentences.length >= 5, `틀린 문장 목록이 맞지 않음: ${score} / ${wrongSentences.length}`);
    const review = await getJson("/api/review");
    assert(review.due_count === 0 && review.waiting >= wrongSentences.length, "틀린 문장이 복습 대기에 들어가지 않음: " + JSON.stringify([review.due_count, review.waiting]));
  });

  await scenario("간격 복습: 하루 넘기면 복습 목록에 나타나고, 풀면 오늘의 공부가 '오늘 완료'가 된다", async () => {
    const day = await setDay(1);
    assert(day.offset === 1, "시계를 넘기지 못함");
    await page.goto(base + "/ox");
    await page.waitFor(`document.getElementById('reviewInfo')`, "복습 칸");
    const due = await getJson("/api/review");
    const dueTexts = due.due.filter((d) => d.kind === "ox").map((d) => d.text);
    assert(wrongSentences.every((t) => dueTexts.includes(t)), "틀린 O/X 문장이 하루 뒤 복습 목록에 없음");
    assert((await page.evaluate(`document.getElementById('reviewInfo').textContent`)).includes(`오늘 복습할 것 ${due.due_count}개`), "복습 개수 표시가 다름");
    await page.evaluate(`document.getElementById('reviewStart').click(); true`);
    await page.waitFor(`document.getElementById('reviewProgress')`, "복습 첫 항목");
    const total = Number(await page.evaluate(`document.getElementById('reviewProgress').textContent.split(' / ')[1]`));
    assert(total === due.due_count, "복습 항목 수가 다름");
    for (let i = 1; i <= total; i++) {
      await page.waitFor(`document.getElementById('reviewProgress') && document.getElementById('reviewProgress').textContent.startsWith('${i} / ')`, `복습 ${i}번째`);
      await page.waitFor(`document.querySelector('#reviewRun .ox-btn, #reviewRun .choice')`, "복습 보기");
      await page.evaluate(`(document.querySelector('#reviewRun .ox-o') || document.querySelector('#reviewRun .choice')).click(); true`);
      await page.waitFor(`document.getElementById('reviewNext')`, "복습 정오");
      await page.evaluate(`document.getElementById('reviewNext').click(); true`);
    }
    await page.waitFor(`document.getElementById('reviewScore')`, "복습 결과");
    assert((await getJson("/api/review")).due_count === 0, "복습을 끝냈는데 오늘 복습할 것이 남음");

    await page.goto(base + "/");
    await page.waitFor(`document.querySelectorAll('#todayList .today-row').length === 3`, "오늘의 공부 3줄(복습을 다 하면 복습 줄이 사라짐)");
    assert(await page.evaluate(`document.getElementById('todayStatus').textContent !== '오늘 완료' && !document.querySelector('#todayList [data-task="review"]')`), "복습만 끝난 상태가 아님(복습 줄이 없어야 함)");
    assert((await page.evaluate(`document.getElementById('todayMeta').textContent`)).includes("예정된 복습") && (await page.evaluate(`document.getElementById('todayMeta').textContent`)).includes("아직 날짜 안 됨"), "예정된 복습 표시 없음");
    assert(await page.evaluate(`document.getElementById('weekTable').querySelectorAll('tbody tr').length === 7 && /\\d+일/.test(document.getElementById('streakDays').textContent)`), "지난 7일·연속 일수 표시 없음");
    await page.evaluate(`document.querySelector('.today-settings summary').click(); document.getElementById('set-daily_ox').value = '5'; document.getElementById('set-daily_questions').value = '2'; document.getElementById('settingsSave').click(); true`);
    await page.waitFor(`document.getElementById('todayMsg').textContent.includes('저장')`, "설정 저장");
    assert(await page.evaluate(`document.querySelector('#todayList [data-task^="ox:"]').textContent.includes('O/X 5개') && document.querySelector('#todayList [data-task^="quiz:"]').textContent.includes('2문제')`), "바꾼 하루 분량이 카드에 반영되지 않음");
    const card = await getJson("/api/today");
    const unit = card.tasks.find((t) => t.kind === "note").unit;
    const task = (kind) => card.tasks.find((t) => t.kind === kind);
    await postJson("/api/study/progress", { unit, status: "read" });
    const set = await getJson("/api/ox/set?" + new URLSearchParams({ unit, count: String(task("ox").need) }));
    for (const it of set.items) await postJson("/api/ox/answer", { key: it.key, choice: "O" });
    const ids = (await getJson("/api/quiz_set?" + new URLSearchParams({ unit, count: String(task("quiz").need) }))).ids;
    for (const id of ids) await postJson("/api/answer", { id, choice: "1" });
    await page.goto(base + "/");
    await page.waitFor(`document.getElementById('todayStatus') && document.getElementById('todayStatus').textContent === '오늘 완료'`, "오늘 완료");
    assert(await page.evaluate(`[...document.querySelectorAll('#todayList .today-row')].every((r) => r.classList.contains('done'))`), "완료 표시가 빠진 줄이 있음");
    assert(await page.evaluate(`Number(document.getElementById('streakDays').textContent.replace('일', '')) >= 2`), "연속 공부 일수가 2일 이상이어야 함");
  });

  await scenario("O/X·복습·오늘의 공부 스크린샷 15장(라이트·다크·모바일)이 scratch/screens/ox/ 에 저장된다", async () => {
    await setDay(2);                                                           // 하루 더: 어제 푼 틀린 문항이 다시 복습에 나오고, 오늘의 공부는 새로 시작
    const files = [];
    const shots = {
      "오늘의공부": async () => { await page.goto(base + "/"); await page.waitFor(`document.querySelectorAll('#todayList .today-row').length === 4`, "카드"); },
      "OX-고르기": async () => { await page.goto(base + "/ox"); await page.waitFor(`document.getElementById('oxStart')`, "고르기"); },
      "OX-문장": async () => { await page.goto(base + "/ox?unit=" + encodeURIComponent("자본") + "&count=20"); await page.waitFor(`document.querySelector('#runBox .ox-btn')`, "문장"); },
      "OX-정오": async () => { await page.goto(base + "/ox?unit=" + encodeURIComponent("자본") + "&count=20"); await page.waitFor(`document.querySelector('#runBox .ox-btn')`, "문장"); await page.evaluate(`document.querySelector('#runBox .ox-x').click(); true`); await page.waitFor(`document.querySelector('#runBox .ox-result .src-badge')`, "정오"); },
      "복습": async () => { await page.goto(base + "/ox?mode=review"); await page.waitFor(`document.getElementById('reviewProgress')`, "복습"); await page.waitFor(`document.querySelector('#reviewRun .ox-btn, #reviewRun .choice')`, "복습 보기"); },
    };
    try {
      for (const [variant, scheme, width, height, mobile] of [["light", "light", 1100, 900, false], ["dark", "dark", 1100, 900, false], ["mobile", "light", 390, 844, true]]) {
        await page.viewport(width, height, mobile);
        await page.emulate([{ name: "prefers-color-scheme", value: scheme }]);
        for (const [name, setup] of Object.entries(shots)) {
          await setup();
          await sleep(300);
          if ((await page.evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)) > 0) throw new Error(`${name}-${variant}: 가로 스크롤 생김`);
          files.push(await page.shotTo(`${name}-${variant}`, page.oxDir));
        }
      }
    } finally {
      await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
      await page.viewport(1100, 900, false);
      await setDay(0);                                                         // 뒤의 점검은 실제 오늘 기준
    }
    assert(files.length === 15, "스크린샷 15장이 아님");
  });

  const designFiles = [];
  const screens = {
    "질문-요약카드": async () => { await page.goto(base + "/"); await page.evaluate(`document.getElementById('q').value = '정상공손 비정상공손 처리'; document.getElementById('ask').click(); true`); await page.waitFor(`document.querySelector('#answer .card mark')`, "요약 카드"); },
    "기출답안-오답잠금": async () => { await page.goto(base + "/"); await lookup(page, 128, 4); await page.evaluate(`document.querySelector('#card .choice').click(); true`); await page.waitFor(`document.getElementById('card').textContent.includes('오답입니다.') || document.querySelector('#card .explain')`, "채점 결과"); },
    "오답노트": async () => { await page.goto(base + "/"); await tab("notebook"); await page.waitFor(`document.querySelectorAll('#nbList .hit').length > 0`, "오답노트 목록").catch(async (e) => { throw new Error(e.message + " " + await page.evaluate(`location.href + ' | ' + document.querySelector('.tab.active').textContent + ' | ' + document.getElementById('nbList').textContent.slice(0, 80)`)); }); },
    "모의고사-OMR": async () => { await page.goto(base + "/"); await tab("mock"); await page.evaluate(`document.getElementById('mockStart').click(); true`); await page.waitFor(`document.querySelectorAll('#mockBody .hit').length === 15`, "모의고사");
      await page.evaluate(`document.querySelectorAll('#mockBody .hit').forEach((h, i) => { if (i < 6) h.querySelectorAll('.choice')[i % 4].click(); }); true`); },
    "문제분석": async () => { await page.goto(base + "/"); await tab("analysis"); await page.waitFor(`document.querySelectorAll('#anTable tr').length > 3`, "분석 표"); },
    "단어주석": async () => { await page.goto(base + "/"); await tab("words"); await page.evaluate(`document.getElementById('wdRound').value = '128'; document.getElementById('wdNumber').value = '1'; document.getElementById('wdGo').click(); true`); await page.waitFor(`document.querySelector('#wdCard .term')`, "용어"); await page.evaluate(`document.querySelector('#wdCard .term').click(); true`); await sleep(200); },
    "목차": async () => { await page.goto(base + "/toc"); await page.waitFor(`document.querySelectorAll('details.subject').length === 3`, "목차"); await page.evaluate(`document.querySelector('details.subject').open = true; document.querySelector('details.subject details').open = true; document.querySelector('details.subject details .qrow').click(); true`); await page.waitFor(`document.querySelector('details.subject details .slot .choice')`, "카드"); },
    "용어검토": async () => { await page.goto(base + "/glossary-review"); await page.waitFor(`document.querySelectorAll('#rows tr').length > 10`, "용어 표"); },
  };
  await scenario("화면별 스크린샷(라이트·다크·모바일)이 저장된다", async () => {
    for (const [variant, scheme, width, height, mobile] of [["light", "light", 1100, 900, false], ["dark", "dark", 1100, 900, false], ["mobile", "light", 390, 844, true]]) {
      await page.viewport(width, height, mobile);
      await page.emulate([{ name: "prefers-color-scheme", value: scheme }]);
      for (const [name, setup] of Object.entries(screens)) {
        await setup();
        await sleep(250);
        designFiles.push(await page.shotTo(`${name}-${variant}`));
      }
    }
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(1100, 900, false);
    assert(designFiles.length === 24, "스크린샷 24장이 아님");
  });

  await scenario("계정 만들기 → 다른 계정으로 로그인 → 오답노트가 비어 있다", async () => {
    // 지금까지의 점검에서 admin 은 틀린 문항을 쌓았다.
    await page.goto(base + "/#notebook");
    assert(await page.evaluate(`(async () => (await (await fetch('/api/notebook')).json()).items.length)()`) > 0, "admin 오답노트가 비어 있음");
    await page.goto(base + "/admin");
    await page.waitFor(`document.querySelectorAll('#userTable tbody tr').length === 1`, "계정 표");
    await page.evaluate(`document.getElementById('newUsername').value = 'student1'; document.getElementById('newName').value = '학생1'; document.getElementById('newPassword').value = 'student-pass-1'; document.getElementById('createBtn').click(); true`);
    await page.waitFor(`document.querySelectorAll('#userTable tbody tr').length === 2 && document.getElementById('createMsg').textContent.includes('student1')`, "계정 만들어짐");
    await page.screenshot("account-admin");
    await page.evaluate(`document.getElementById('logoutBtn').click(); true`);
    await page.waitFor(`location.pathname === '/login'`, "로그아웃");
    await page.goto(base + "/study");                                       // 로그아웃 상태에서는 로그인 화면으로 돌려보낸다
    await page.waitFor(`location.pathname === '/login'`, "로그인으로 이동");
    await logIn("student1", "student-pass-1");
    assert(await page.evaluate(`document.getElementById('userName').textContent === '학생1' && !document.getElementById('adminLink')`), "학생 계정 표시/관리자 링크");
    await page.evaluate(`document.querySelector('.tab[data-tab="notebook"]').click(); true`);
    await page.waitFor(`document.getElementById('nbList').textContent.includes('오답노트가 비어 있습니다.')`, "새 계정 오답노트 비어 있음");
    await page.screenshot("account-student-notebook");
    await page.goto(base + "/admin");                                       // 관리자 화면은 관리자만
    await page.waitFor(`location.pathname === '/'`, "관리자 화면 막힘");
    await page.evaluate(`document.getElementById('logoutBtn').click(); true`);
    await page.waitFor(`location.pathname === '/login'`, "로그아웃");
    await logIn("admin", "admin-pass-1");
  });

  // ---- 계획 세우기 · 캘린더. planner 계정(오늘 기록 없음)으로: 계획 생성 → 일부(부분) → 나머지(완료) → 날짜 넘기면 어제는 완료, 오늘은 새 계획.
  const logOut = async () => {
    await page.evaluate(`document.getElementById('logoutBtn').click(); true`);
    await page.waitFor(`location.pathname === '/login'`, "로그아웃");
  };
  const cellState = (date) => page.evaluate(`(document.querySelector('.cal-cell[data-date="${date}"]') || {}).dataset?.state`);
  await scenario("계획 → 캘린더: 계획 생성 → 오늘 일부 수행(부분) → 나머지(완료) → 다음 날 새 계획", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/");
    await page.waitFor(`document.getElementById('logoutBtn')`, "관리자 화면");
    assert(await page.evaluate(`api('/api/users', { username: 'planner', name: '계획', password: 'planner-pass-1' }).then((r) => r.ok)`), "planner 계정 만들기");
    await logOut();
    await logIn("planner", "planner-pass-1");

    await page.goto(base + "/plan");
    await page.waitFor(`document.getElementById('examDate') && document.querySelectorAll('#restDays input').length === 7`, "계획 화면");
    const info = await page.evaluate(`(() => { const d = new Date(); const e = new Date(); e.setDate(d.getDate() + 14); return { exam: e.toLocaleDateString('sv-SE'), rest: ((d.getDay() + 6) % 7 + 3) % 7 }; })()`);
    await page.evaluate(`document.getElementById('examDate').value = ${JSON.stringify(info.exam)}; document.querySelectorAll('#restDays input')[${info.rest}].checked = true; document.getElementById('generate').click(); true`);
    await page.waitFor(`document.getElementById('planMsg').textContent.includes('공부일')`, "계획 생성 결과");
    assert(await page.evaluate(`document.querySelectorAll('#planDays tbody tr').length >= 10`), "날짜별 계획 표");
    await sleep(200);
    await page.shotTo("계획-light", CAL_SHOTS);

    await page.goto(base + "/calendar");
    await page.waitFor(`document.querySelector('.cal-cell.today')`, "달력");
    assert((await page.evaluate(`document.getElementById('dday').textContent`)) === "D-14", "D-day");
    const today = await page.evaluate(`document.getElementById('todayDate').textContent`);
    assert((await cellState(today)) === "future", "오늘(아직 안 함)은 예정 색");
    await page.evaluate(`document.querySelector('.cal-cell.today').click(); true`);
    await page.waitFor(`document.querySelectorAll('#planTable tbody tr').length >= 3`, "날짜 상세 계획 표");
    await page.evaluate(`document.querySelector('#dayPanel').scrollIntoView(); true`);
    await sleep(200);
    await page.shotTo("날짜상세-light", CAL_SHOTS);

    // 오늘 계획 중 노트만 한다 → 부분
    const doIt = (kinds) => page.evaluate(`(async () => {
      const tasks = (await api('/api/today')).data.tasks;
      for (const t of tasks) {
        if (!${JSON.stringify(kinds)}.includes(t.kind)) continue;
        if (t.kind === 'note') await api('/api/study/progress', { unit: t.unit, status: 'read' });
        if (t.kind === 'ox') { const set = (await api('/api/ox/set?' + query({ subject: t.subject, tax: t.tax, unit: t.unit, count: t.need }))).data.items; for (const i of set) await api('/api/ox/answer', { key: i.key, choice: 'O' }); }
        if (t.kind === 'quiz') { const ids = (await api('/api/quiz_set?' + query({ subject: t.subject, tax: t.tax, unit: t.unit, count: t.need }))).data.ids; for (const id of ids) await api('/api/answer', { id, choice: '1' }); }
      }
      return tasks.length;
    })()`);
    assert((await doIt(["note"])) >= 3, "오늘 계획 항목이 3개 이상");
    await page.goto(base + "/calendar");
    await page.waitFor(`document.querySelector('.cal-cell.today')`, "달력");
    assert((await cellState(today)) === "partial", "오늘 부분: " + (await cellState(today)));
    await page.goto(base + "/");
    await page.waitFor(`document.querySelectorAll('#todayList .today-row').length >= 3`, "오늘의 공부 카드(계획 기준)");
    assert(await page.evaluate(`document.querySelector('#todayList .today-row.done') && document.querySelector('#todayList .today-row:not(.done)') && document.getElementById('calendarLink').textContent.includes('캘린더')`), "카드: 일부 완료");

    await doIt(["ox", "quiz"]);
    await page.goto(base + "/calendar");
    await page.waitFor(`document.querySelector('.cal-cell.today')`, "달력");
    assert((await cellState(today)) === "done", "오늘 완료: " + (await cellState(today)));
    await page.evaluate(`document.querySelector('.cal-cell.today').click(); true`);
    await page.waitFor(`document.getElementById('dayState').textContent.includes('완료') && document.getElementById('actualList').textContent.includes('O/X')`, "상세: 완료·실제 기록");

    // 사람이 고친 날은 다시 만들어도 남는다: 모레를 '쉬기' 로 저장 → 계획 다시 만들기 → 그대로 쉬는 날
    const plus2 = await page.evaluate(`(() => { const d = new Date(); d.setDate(d.getDate() + 2); return d.toLocaleDateString('sv-SE'); })()`);
    await page.evaluate(`document.querySelector('.cal-cell[data-date="${plus2}"]').click(); true`);
    await page.waitFor(`document.getElementById('editBox') && document.getElementById('dayTitle').textContent.startsWith('${plus2}')`, "고치기 상자");
    await page.evaluate(`document.getElementById('editBox').open = true; document.getElementById('restCheck').click(); document.getElementById('saveDay').click(); true`);
    await page.waitFor(`document.querySelector('.cal-cell[data-date="${plus2}"]').dataset.state === 'rest'`, "쉬는 날로 저장");
    await page.goto(base + "/plan");
    await page.waitFor(`document.getElementById('generate')`, "계획 화면");
    await page.evaluate(`document.getElementById('generate').click(); true`);
    await page.waitFor(`document.getElementById('planMsg').textContent.includes('직접 고친 날 1일 유지')`, "다시 만들기: 고친 날 유지");
    await page.goto(base + "/calendar");
    await page.waitFor(`document.querySelector('.cal-cell.today')`, "달력");
    assert((await cellState(plus2)) === "rest", "고친 날은 다시 만든 뒤에도 쉬는 날");
    assert((await cellState(today)) === "done", "오늘은 다시 만든 뒤에도 완료(한 일이 있는 오늘은 건드리지 않음)");

    // 스크린샷: 라이트·다크·모바일
    await page.evaluate(`document.querySelector('.cal-cell.today').click(); true`);
    await page.waitFor(`document.getElementById('dayState')`, "상세");
    await sleep(200);
    await page.shotTo("캘린더-light", CAL_SHOTS);
    await page.emulate([{ name: "prefers-color-scheme", value: "dark" }]);
    await sleep(250);
    await page.shotTo("캘린더-dark", CAL_SHOTS);
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(390, 844, true);
    await page.goto(base + "/calendar");
    await page.waitFor(`document.querySelectorAll('#weekList .week-row').length === 7`, "모바일 주간 목록");
    assert(await page.evaluate(`getComputedStyle(document.getElementById('calGrid')).display === 'none' && getComputedStyle(document.getElementById('weekList')).display === 'block'`), "모바일은 주간 목록");
    assert(await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`), "모바일 가로 스크롤");
    await page.evaluate(`document.getElementById('nextWeek').click(); true`);
    await sleep(250);
    await page.shotTo("캘린더-mobile", CAL_SHOTS);
    await page.viewport(1100, 900, false);

    // 다음 날로 넘기기: 어제는 완료, 오늘은 새 계획
    await setDay(1);
    await page.goto(base + "/calendar");
    await page.waitFor(`document.querySelector('.cal-cell.today')`, "달력");
    assert((await page.evaluate(`document.getElementById('dday').textContent`)) === "D-13", "D-day 하루 줄어듦");
    assert((await cellState(today)) === "done", "어제는 완료");
    const nextToday = await page.evaluate(`document.getElementById('todayDate').textContent`);
    assert(nextToday !== today && (await cellState(nextToday)) === "future", "오늘은 새 계획(예정)");
    const card = await page.evaluate(`api('/api/today').then((r) => ({ plan: r.data.plan, n: r.data.tasks.length, complete: r.data.complete, date: r.data.date }))`);
    assert(card.plan && card.n > 0 && !card.complete && card.date === nextToday, "오늘의 공부 카드가 새 날 계획");
    await setDay(0);
    await logOut();
    await logIn("admin", "admin-pass-1");
  });

  await scenario("계정: 내 비밀번호 바꾸기 · 관리자 비밀번호 초기화", async () => {
    await logOut();
    await logIn("planner", "planner-pass-1");
    await page.goto(base + "/account");
    await page.waitFor(`document.getElementById('pwForm')`, "계정 화면");
    await page.evaluate(`document.getElementById('curPw').value = 'planner-pass-1'; document.getElementById('newPw').value = 'planner-pass-2'; document.getElementById('newPw2').value = 'planner-pass-2'; document.getElementById('pwBtn').click(); true`);
    await page.waitFor(`document.getElementById('pwMsg').textContent.includes('바꿨습니다')`, "비밀번호 변경");
    await logOut();
    await logIn("planner", "planner-pass-2");
    await logOut();
    await logIn("admin", "admin-pass-1");
    await page.goto(base + "/admin");
    await page.waitFor(`document.querySelectorAll('#resetUser option').length >= 3`, "관리자 화면");
    await page.evaluate(`[...document.querySelectorAll('#resetUser option')].find((o) => o.textContent.startsWith('planner')).selected = true; document.getElementById('resetPassword').value = 'planner-pass-3'; document.getElementById('resetBtn').click(); true`);
    await page.waitFor(`document.getElementById('resetMsg').textContent.includes('초기화했습니다')`, "비밀번호 초기화");
    await logOut();
    await logIn("planner", "planner-pass-3");
    await logOut();
    await logIn("admin", "admin-pass-1");
  });

  // 상단 바 구성(로고·탭 줄·계정 버튼)이 어떻게 바뀌어도 잡는 검사: ① 로고·탭 줄·계정 버튼 영역이 서로 겹치지 않고
  // ② 탭 줄 안팎의 빈틈(로고~탭 줄, 탭 줄~계정 버튼)과 잘린 가장자리 안쪽 8px 에 글자 조각이 비치지 않는다(화면 조각의 색이 배경과 같다).
  // 예전 검사는 '탭 줄 왼쪽 >= 로고 오른쪽' 좌표만 봤기 때문에, 탭 줄 안에서 잘려 비치는 글자 조각은 통과했다.
  await scenario("상단 바: 로고·탭·계정 버튼이 겹치지 않고 잘린 탭 글자 조각이 비치지 않는다(모바일·데스크톱·라이트·다크, 스크롤 위치별)", async () => {
    const colorDiff = (a, b) => Math.max(...a.map((v, i) => Math.abs(v - b[i])));
    const problems = [];
    const probe = async (label) => {
      const g = await page.evaluate(`(() => {
        const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect(); return { l: b.left, r: b.right, t: b.top, b: b.bottom }; };
        const nav = document.querySelector('.tabs'), wrap = document.querySelector('.tabs-wrap');
        return { brand: r(document.querySelector('.topbar .brand')), wrap: r(wrap), user: r(document.querySelector('.topbar .userbox')), bar: r(document.querySelector('.topbar')),
                 overflow: getComputedStyle(wrap).overflowX, left: nav.scrollLeft > 2, right: nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 2 };
      })()`);
      const narrow = await page.evaluate(`window.innerWidth <= 560`);
      if (narrow && g.overflow !== "hidden") problems.push(`${label}: 모바일은 탭 줄 바깥을 잘라야 함`);
      if (!narrow && (g.overflow !== "visible" || g.left || g.right)) problems.push(`${label}: 데스크톱 폭에서는 탭이 잘리지 않고 줄바꿈되어야 함`);
      if (g.brand.r > g.wrap.l + 0.5) problems.push(`${label}: 로고와 탭 줄이 겹침`);
      if (g.user && g.wrap.r > g.user.l + 0.5) problems.push(`${label}: 탭 줄과 계정 버튼이 겹침`);
      const top = Math.ceil(g.bar.t) + 6, height = Math.max(8, Math.floor(g.bar.b - g.bar.t) - 14);
      const regions = [["로고~탭 줄 빈틈과 왼쪽 가장자리", g.brand.r + 1, g.wrap.l + (g.left ? 8 : 0)]];
      if (g.right) regions.push(["탭 줄 오른쪽 가장자리~계정 버튼", g.wrap.r - 8, g.user ? g.user.l - 1 : g.wrap.r]);
      else if (g.user) regions.push(["탭 줄~계정 버튼 빈틈", g.wrap.r + 1, g.user.l - 1]);
      for (const [name, from, to] of regions) {
        const x = Math.ceil(from), width = Math.floor(to) - x;
        if (width < 2) continue;
        const img = await page.pixels(x, top, width, height), ref = img.px(0, 0);
        let worst = 0;
        for (let yy = 0; yy < img.height; yy++) for (let xx = 0; xx < img.width; xx++) worst = Math.max(worst, colorDiff(img.px(xx, yy), ref));
        if (worst > 12) problems.push(`${label}: ${name}에 글자 조각이 비침(색 차이 ${worst})`);
      }
    };
    const pages = ["/", "/study", "/toc", "/calendar", "/plan", "/account", "/admin"];
    const variants = [[390, 844, true, "light", "모바일"], [1100, 900, false, "light", "데스크톱"], [390, 844, true, "dark", "모바일 다크"], [320, 640, true, "light", "아주 좁은 모바일"]];
    for (const [w, h, mobile, scheme, name] of variants) {
      await page.viewport(w, h, mobile);
      await page.emulate([{ name: "prefers-color-scheme", value: scheme }]);
      for (const path of pages) {
        await page.goto(base + path);
        await page.waitFor(`document.querySelector('.topbar .tabs') && document.querySelector('.topbar .userbox')`, "상단 바 계정 버튼");
        await sleep(500);
        for (const pos of ["0", "mid", "max"]) {
          await page.evaluate(`(() => { const n = document.querySelector('.tabs'); n.style.scrollBehavior = 'auto'; n.scrollLeft = ${pos === "0" ? 0 : pos === "mid" ? "(n.scrollWidth - n.clientWidth) / 2" : "n.scrollWidth"}; return true; })()`);
          await sleep(250);
          await probe(`${name} ${path} 스크롤 ${pos}`);
        }
      }
    }
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(1100, 900, false);
    assert(!problems.length, problems.slice(0, 6).join(" | ") + (problems.length > 6 ? ` … 외 ${problems.length - 6}건` : ""));
  });

  // ---- 강사님 피드백 ②: 표가 표로 보이고, 세무 문장에 시행일 기준·수치 대상/기준일·개정 전 배지가 보인다.
  await scenario("표가 있는 문항이 표로 보임(머리글·칸 병합 유지, 문제 화면·O/X 데이터)", async () => {
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(1100, 900, false);
    await page.goto(base + "/");
    await page.waitFor(`typeof loadQuestion === 'function'`, "문제 화면");
    await page.evaluate(`showTab('answers'); loadQuestion(123, 8); true`);
    await page.waitFor(`document.querySelector('.paper .qtable')`, "문제 카드 안의 표");
    const shape = await page.evaluate(`(() => {
      const t = document.querySelector('.paper .qtable');
      const th = [...t.querySelectorAll('thead th')].map((c) => ({ text: c.textContent, col: c.colSpan, row: c.rowSpan, scope: c.getAttribute('scope') }));
      const rowHead = [...t.querySelectorAll('tbody th')].map((c) => c.textContent);
      return { rows: t.rows.length, th, rowHead, cell: t.querySelector('tbody tr:last-child td:last-child').textContent, tag: document.querySelector('.paper .stem').nextElementSibling.className };
    })()`);
    assert(shape.rows === 4 && shape.th.some((c) => c.text === "보조부문" && c.col === 2) && shape.th.some((c) => c.text === "배분대상원가" && c.row === 2), "병합된 머리글이 그대로 보여야 함: " + JSON.stringify(shape.th));
    assert(shape.th.every((c) => c.scope === "col") && shape.rowHead.includes("수선부문") && shape.rowHead.includes("전력부문"), "열·행 머리글 연결(scope)");
    assert(shape.cell === "100,000원" && shape.tag === "qtable-wrap", "표 칸 값/위치: " + JSON.stringify(shape));
    const dup = await page.evaluate(`(() => {
      const card = document.querySelector('.paper');
      const body = card.querySelector('.stem').textContent, all = card.textContent;
      return { stemHas: /사용부문 제공부문|200,000원|전력부문/.test(body), stem: body, count: (all.match(/200,000원/g) || []).length, tableHas: card.querySelector('.qtable').textContent.includes('200,000원'), question: /단계배분법/.test(body) };
    })()`);
    assert(!dup.stemHas && dup.question, "123-8 본문에서 표 글자가 숨겨지고 물음은 남아야 함: " + dup.stem);
    assert(dup.count === 1 && dup.tableHas, "표 글자('200,000원')가 화면에 한 번만 보임: " + dup.count);
    assert(await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`), "표가 화면을 넘치지 않음");
    await sleep(200);
    await page.shotTo("표-문항-light", NUM_SHOTS);
    await page.emulate([{ name: "prefers-color-scheme", value: "dark" }]);
    await sleep(250);
    await page.shotTo("표-문항-dark", NUM_SHOTS);
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(390, 844, true);
    await page.goto(base + "/");
    await page.waitFor(`typeof loadQuestion === 'function'`, "문제 화면(모바일)");
    await page.evaluate(`showTab('answers'); loadQuestion(123, 8); true`);
    await page.waitFor(`document.querySelector('.paper .qtable')`, "모바일 표");
    assert(await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`), "모바일에서 표 때문에 화면이 가로로 밀리지 않음(표 칸 안에서 스크롤)");
    await sleep(200);
    await page.shotTo("표-문항-mobile", NUM_SHOTS);
    await page.viewport(1100, 900, false);
  });

  await scenario("세무 문장에 시행일·개정 전 배지, 숫자 말풍선(본문엔 숫자만·점선 밑줄, 누르거나 키보드로 열림)", async () => {
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(1100, 900, false);
    await page.goto(base + "/study/" + encodeURIComponent("근로소득·연말정산"));
    await page.waitFor(`document.querySelector('.concept-list li')`, "노트");
    const note = await page.evaluate(`({
      basis: [...document.querySelectorAll('.concept-list .basis')].map((e) => e.textContent),
      pre: [...document.querySelectorAll('.concept-list .preamend')].map((e) => e.textContent),
      preNote: [...document.querySelectorAll('.concept-list .preamend-note')].map((e) => e.textContent),
      nums: document.querySelectorAll('.concept-list .num-tag').length,
      plain: [...document.querySelectorAll('.concept-list .num-tag')].every((e) => !e.querySelector('*') && /^\\d/.test(e.textContent)),
      underline: [...document.querySelectorAll('.concept-list .num-tag')].every((e) => getComputedStyle(e).textDecorationLine === 'underline' && getComputedStyle(e).textDecorationStyle === 'dotted'),
      focusable: [...document.querySelectorAll('.concept-list .num-tag')].every((e) => e.tabIndex === 0 && e.getAttribute('role') === 'button'),
      leaked: document.querySelector('.concept-list').textContent.includes('시행 시험) 기준'),
    })`);
    assert(note.basis.length >= 3 && note.basis.every((t) => /^\d{4}년 \d{1,2}월 시행 시험 기준$/.test(t)), "문장 끝 시험 기준 문구 'YYYY년 M월 시행 시험 기준': " + JSON.stringify(note.basis));
    assert(note.pre.length >= 1 && note.pre.every((t) => t === "개정 전 기준") && note.preNote.every((t) => /’26\.\d+\.\d+/.test(t) && /p\d+/.test(t)), "개정 전 기준 배지에 적용일·쪽 표시: " + JSON.stringify(note.preNote));
    assert(note.nums >= 5 && note.plain && note.underline && note.focusable && !note.leaked, "본문에는 숫자만(점선 밑줄·키보드 포커스), 기준 문구가 끼어들지 않음: " + JSON.stringify(note));
    // 누르면 말풍선
    await page.evaluate(`document.querySelector('.concept-list .num-tag').click(); true`);
    await page.waitFor(`document.getElementById('numPop')`, "숫자 말풍선(클릭)");
    const pop = await page.evaluate(`(() => { const p = document.getElementById('numPop'), t = document.querySelector('.concept-list .num-tag'); const r = p.getBoundingClientRect(); return { text: p.textContent, open: t.getAttribute('aria-expanded'), inView: r.left >= 0 && r.right <= window.innerWidth && r.top >= 0 && r.bottom <= window.innerHeight }; })()`);
    assert(/적용 대상.+기준일.+예외 조건.+출처/.test(pop.text) && pop.open === "true" && pop.inView, "말풍선에 적용 대상·기준일·예외 조건·출처: " + JSON.stringify(pop));
    await sleep(150);
    await page.shotTo("숫자말풍선-light", NUM_SHOTS);
    await page.key("Escape");
    await page.waitFor(`!document.getElementById('numPop')`, "Esc 로 닫힘");
    // 키보드: 포커스 후 Enter
    await page.evaluate(`document.querySelectorAll('.concept-list .num-tag')[1].focus(); true`);
    await page.key("Enter");
    await page.waitFor(`document.getElementById('numPop') && document.activeElement.getAttribute('aria-expanded') === 'true'`, "숫자 말풍선(키보드 Enter)");
    await page.key("Escape");
    await page.waitFor(`!document.getElementById('numPop')`, "Esc 로 닫힘(키보드)");
    const changes = await page.evaluate(`[...document.querySelectorAll('.change-list .num-tag')].length`);
    assert(changes >= 3, "개정 항목에도 숫자 말풍선: " + changes);
    await page.emulate([{ name: "prefers-color-scheme", value: "dark" }]);
    await page.evaluate(`document.querySelector('.concept-list .num-tag').click(); true`);
    await page.waitFor(`document.getElementById('numPop')`, "다크 말풍선");
    await sleep(250);
    await page.shotTo("숫자말풍선-dark", NUM_SHOTS);
    await page.key("Escape");
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await sleep(150);
    await page.shotTo("세무문장-배지-light", NUM_SHOTS);
    await page.viewport(390, 844, true);
    await page.goto(base + "/study/" + encodeURIComponent("근로소득·연말정산"));
    await page.waitFor(`document.querySelector('.concept-list .num-tag')`, "모바일 노트");
    assert(await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`), "모바일 가로 스크롤 없음");
    await page.evaluate(`document.querySelector('.concept-list .num-tag').click(); true`);
    await page.waitFor(`document.getElementById('numPop')`, "모바일 말풍선");
    assert(await page.evaluate(`(() => { const r = document.getElementById('numPop').getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth; })()`), "모바일 말풍선이 화면 안");
    await sleep(200);
    await page.shotTo("숫자말풍선-mobile", NUM_SHOTS);
    await page.key("Escape");
    await page.viewport(1100, 900, false);
    const q = await page.evaluate(`api('/api/question?round=127&number=12').then((r) => r.data)`);
    assert(q.subject === "세무회계" && q.exam_basis === "2026년 8월 시행 시험 기준", "세무 문항에 시험 기준 문구: " + JSON.stringify([q.subject, q.exam_basis]));
  });

  await scenario("노트북·데스크톱 폭에서 모든 탭(계획·캘린더·목차 포함)이 화면 안에 보이고, 계획 없는 오늘의 공부 카드 링크는 /plan", async () => {
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    for (const width of [1000, 1280]) {
      await page.viewport(width, 800, false);
      for (const path of ["/", "/study", "/calendar", "/plan", "/ox", "/toc"]) {
        await page.goto(base + path);
        await page.waitFor(`document.querySelectorAll('.topbar .tab, .topbar .tab-link').length >= 10`, `탭 ${path}`);
        const r = await page.evaluate(`(() => {
          const tabs = [...document.querySelectorAll('.topbar .tab, .topbar .tab-link')];
          const labels = tabs.map((t) => t.textContent.trim());
          const out = tabs.filter((t) => { const b = t.getBoundingClientRect(); return b.width === 0 || b.left < 0 || b.right > window.innerWidth || b.top < 0 || b.bottom > document.querySelector('.topbar').getBoundingClientRect().bottom + 1; }).map((t) => t.textContent.trim());
          const plan = tabs.find((t) => t.textContent.trim() === '계획');
          return { labels, out, planHref: plan && plan.getAttribute('href'), scroll: document.documentElement.scrollWidth <= window.innerWidth + 1 };
        })()`);
        for (const need of ["계획", "캘린더", "목차", "공부"]) assert(r.labels.includes(need), `${width}px ${path}: '${need}' 탭이 없음 ${JSON.stringify(r.labels)}`);
        assert(r.out.length === 0, `${width}px ${path}: 화면 밖으로 잘린 탭 ${JSON.stringify(r.out)}`);
        assert(r.planHref === "/plan" && r.scroll, `${width}px ${path}: 계획 탭 링크/가로 스크롤 ${JSON.stringify(r)}`);
      }
    }
    await page.viewport(1000, 800, false);
    await page.goto(base + "/");
    await page.shotTo("탭-1000", NUM_SHOTS);
    await page.waitFor(`document.getElementById('calendarLink')`, "오늘의 공부 카드 링크");
    const link = await page.evaluate(`({ text: document.getElementById('calendarLink').textContent, href: document.getElementById('calendarLink').getAttribute('href') })`);
    assert(link.text === "계획 세우기" && link.href === "/plan", "계획이 없으면 카드 링크가 /plan: " + JSON.stringify(link));
    await page.viewport(1100, 900, false);
  });

  await scenario("이월: 이틀 공부 안 함 → 밀린 것 표시 → 넘기기 → 캘린더·오늘 카드 → 주간 돌아보기 약한 단원 → 복습 추가", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/");
    await page.waitFor(`document.getElementById('logoutBtn')`, "관리자 화면");
    assert(await page.evaluate(`api('/api/users', { username: 'carrier', name: '이월', password: 'carrier-pass-1' }).then((r) => r.ok)`), "carrier 계정 만들기");
    await logOut();
    await logIn("carrier", "carrier-pass-1");
    const exam = await page.evaluate(`(() => { const e = new Date(); e.setDate(e.getDate() + 20); return e.toLocaleDateString('sv-SE'); })()`);
    await page.evaluate(`api('/api/plan/settings', { exam_date: ${JSON.stringify(exam)}, rest_days: [], final_days: 5 }).then(() => api('/api/plan/generate', {}))`);
    // 약한 단원 재료: 5문제 이상 푼 단원을 만든다(정답 여부는 상관없다)
    const solved = await page.evaluate(`(async () => {
      const units = (await api('/api/plan')).data.units;
      for (const u of units) {
        const ids = (await api('/api/quiz_set?' + query({ subject: u.subject, tax: u.tax, unit: u.unit, count: 6 }))).data.ids || [];
        if (ids.length >= 5) { for (const id of ids) await api('/api/answer', { id, choice: '1' }); return { unit: u.unit, n: ids.length }; }
      }
      return null;
    })()`);
    assert(solved && solved.n >= 5, "5문제 이상 푼 단원: " + JSON.stringify(solved));
    await setDay(2);                                                             // 이틀 동안 공부하지 않음
    await page.goto(base + "/calendar");
    await page.waitFor(`document.getElementById('carryCount')`, "밀린 것 표시");
    const count = await page.evaluate(`document.getElementById('carryCount').textContent`);
    assert(/^밀린 것 [1-9]\d*개$/.test(count), "밀린 것 N개: " + count);
    await page.shotTo("밀린것-light", CARRY_SHOTS);
    await page.evaluate(`document.getElementById('carryBtn').click(); true`);
    await page.waitFor(`document.getElementById('carryMsg').textContent.includes('넘겼습니다')`, "넘기기 결과");
    const left = await page.evaluate(`document.getElementById('carryCount') ? Number(document.getElementById('carryCount').textContent.match(/\\d+/)[0]) : 0`);
    assert(left < Number(count.match(/\d+/)[0]), `넘긴 뒤 밀린 것이 줄어듦: ${count} → ${left}`);
    await page.evaluate(`document.querySelector('.cal-cell.today').click(); true`);
    await page.waitFor(`document.querySelectorAll('#planTable .carry-badge').length >= 1`, "캘린더 상세에 이월 표시");
    await page.evaluate(`document.querySelector('#dayPanel').scrollIntoView(); true`);
    await sleep(200);
    assert(await page.evaluate(`![...document.querySelectorAll('#planTable tbody tr')].some((tr) => tr.textContent.startsWith('복습') && tr.querySelector('.carry-badge'))`), "복습 이월 없음(캘린더)");
    await page.shotTo("넘긴뒤-캘린더", CARRY_SHOTS);
    await page.goto(base + "/");
    await page.waitFor(`document.querySelectorAll('#todayList .carry-badge').length >= 1`, "오늘 카드 이월 표시");
    const note = await page.evaluate(`document.querySelector('#todayList .carry-badge').textContent`);
    assert(note.endsWith("에서 넘어옴"), "카드 표시: " + note);
    assert(await page.evaluate(`![...document.querySelectorAll('#todayList .today-row')].some((r) => r.textContent.startsWith('복습') && r.querySelector('.carry-badge'))`), "복습 이월 없음(오늘 카드)");
    await page.shotTo("오늘카드-이월", CARRY_SHOTS);
    await page.goto(base + "/calendar");
    await page.waitFor(`document.getElementById('weekLink')`, "주간 돌아보기 링크");
    await page.evaluate(`document.getElementById('weekLink').click(); true`);
    await page.waitFor(`location.pathname === '/review-week' && document.querySelectorAll('.week-card').length === 2`, "주간 돌아보기 화면");
    await page.waitFor(`document.querySelector('.weak-card .addReview')`, "약한 단원");
    const weak = await page.evaluate(`document.querySelector('.weak-card b').textContent`);
    assert(weak === solved.unit, `약한 단원 = 푼 단원: ${weak} / ${solved.unit}`);
    await page.shotTo("주간-light", CARRY_SHOTS);
    await page.evaluate(`document.querySelector('.addReview').click(); true`);
    await page.waitFor(`document.querySelector('.weak-card .small') && document.querySelector('.weak-card .small').textContent.includes('더했습니다')`, "복습 추가 결과");
    await page.shotTo("복습추가-light", CARRY_SHOTS);
    await page.viewport(390, 844, true);
    await page.goto(base + "/review-week");
    await page.waitFor(`document.querySelectorAll('.week-card').length === 2`, "모바일 주간");
    assert(await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`), "모바일 가로 스크롤(주간)");
    await page.shotTo("주간-mobile", CARRY_SHOTS);
    await page.viewport(1100, 900, false);
    await setDay(0);
    await logOut();
    await logIn("admin", "admin-pass-1");
  });

  await scenario("첫 화면 흐름: 계획 없는 사용자 로그인 → 시작하기 → 계획 세우기 → 홈(오늘의 공부 순서·다음 할 일), 계획 있는 사용자는 바로 홈", async () => {
    await page.viewport(1100, 900, false);
    await page.goto(base + "/");
    await page.waitFor(`document.getElementById('logoutBtn')`, "관리자 화면");
    assert(await page.evaluate(`api('/api/users', { username: 'starter', name: '시작', password: 'starter-pass-1' }).then((r) => r.ok)`), "starter 계정 만들기");
    await logOut();
    await page.evaluate(`document.getElementById('username').value = 'starter'; document.getElementById('password').value = 'starter-pass-1'; document.getElementById('loginBtn').click(); true`);
    await page.waitFor(`location.pathname === '/start' && document.querySelectorAll('#topList li').length > 0`, "로그인 → /start");
    const scope = await page.evaluate(`[...document.querySelectorAll('#scopeTable tbody tr')].map((r) => r.textContent)`);
    for (const need of ["재무회계", "원가회계", "세무회계", "부가가치세", "소득세", "법인세"]) assert(scope.some((t) => t.includes(need)), "이론 범위에 없음: " + need);
    assert((await page.evaluate(`document.querySelectorAll('#topList li').length`)) === 8, "추천 순서 8개");
    assert((await page.evaluate(`document.getElementById('basis').textContent`)).startsWith("기준:"), "기준 설명 한 줄");
    assert((await page.evaluate(`document.getElementById('skipLink').getAttribute('href')`)) === "/", "건너뛰기 링크");
    await page.shotTo("시작하기-light", START_SHOTS);
    await page.viewport(390, 844, true);
    await page.goto(base + "/start");
    await page.waitFor(`document.querySelectorAll('#topList li').length === 8`, "모바일 /start");
    assert(await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`), "모바일 가로 스크롤(/start)");
    await page.shotTo("시작하기-mobile", START_SHOTS);
    await page.viewport(1100, 900, false);
    await page.goto(base + "/start");
    await page.waitFor(`document.getElementById('goPlan')`, "계획 세우기 버튼");
    await page.evaluate(`document.getElementById('goPlan').click(); true`);
    await page.waitFor(`location.pathname === '/plan' && document.getElementById('generate') && document.getElementById('dailyNotes').value !== ''`, "/plan(설정 불러오기 끝)");
    const exam = await page.evaluate(`(() => { const e = new Date(); e.setDate(e.getDate() + 20); return e.toLocaleDateString('sv-SE'); })()`);
    await page.evaluate(`document.getElementById('examDate').value = ${JSON.stringify(exam)}; document.getElementById('generate').click(); true`);
    await page.waitFor(`location.pathname === '/' && document.getElementById('todayList')`, "계획 만들기 → 홈");
    await page.waitFor(`document.querySelectorAll('#todayList .today-row').length >= 3`, "오늘의 공부 줄");
    const kinds = await page.evaluate(`[...document.querySelectorAll('#todayList .today-row')].map((r) => r.dataset.task.split(':')[0])`);
    const order = ["note", "ox", "quiz", "mock", "review"];
    assert(kinds.every((k, i) => i === 0 || order.indexOf(kinds[i - 1]) <= order.indexOf(k)) && kinds[0] === "note", "카드 순서: " + kinds.join(","));
    assert(!kinds.includes("review"), "복습할 것이 0개면 복습 줄이 없음");
    const rows = await page.evaluate(`[...document.querySelectorAll('#todayList .today-row')].map((r) => ({ next: r.classList.contains('next'), reason: r.querySelector('.today-reason').textContent, done: r.classList.contains('done') }))`);
    assert(rows.every((r) => r.reason.length > 5), "줄마다 이유 한 줄");
    assert(rows.filter((r) => r.next).length === 1 && rows[rows.findIndex((r) => !r.done)].next, "다음 할 일 = 첫 미완료 줄");
    assert((await page.evaluate(`document.getElementById('todayUnits').textContent`)).startsWith("오늘 단원:"), "카드 맨 위 오늘 단원·과목");
    assert(await page.evaluate(`document.getElementById('askBox').hidden && document.getElementById('today').getBoundingClientRect().top < 300`), "홈: 질문창은 숨기고 오늘의 공부가 맨 위");
    await page.shotTo("홈-오늘의공부-light", START_SHOTS);
    await page.emulate([{ name: "prefers-color-scheme", value: "dark" }]);
    await sleep(250);
    await page.shotTo("홈-오늘의공부-dark", START_SHOTS);
    await page.emulate([{ name: "prefers-color-scheme", value: "light" }]);
    await page.viewport(390, 844, true);
    await page.goto(base + "/");
    await page.waitFor(`document.querySelectorAll('#todayList .today-row').length >= 3`, "모바일 홈");
    assert(await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`), "모바일 가로 스크롤(홈)");
    await page.shotTo("홈-오늘의공부-mobile", START_SHOTS);
    await page.viewport(1100, 900, false);
    await page.goto(base + "/#ask");                                           // 질문 기능은 /#ask 로 그대로 남아 있다
    await page.waitFor(`!document.getElementById('askBox').hidden && document.getElementById('q')`, "질문창(/#ask)");
    // 계획이 있는 사용자는 로그인하면 바로 홈
    await logOut();
    await page.evaluate(`document.getElementById('username').value = 'starter'; document.getElementById('password').value = 'starter-pass-1'; document.getElementById('loginBtn').click(); true`);
    await page.waitFor(`location.pathname === '/' && document.getElementById('todayList')`, "계획 있는 사용자 → 바로 홈");
    await logOut();
    await logIn("admin", "admin-pass-1");
  });

  await scenario("콘솔 오류가 없다", async () => {
    assert(!page.errors.length, page.errors.slice(0, 5).join(" | "));
  });
}

let code = 0;
try { await main(); } catch (err) { console.log("실패  점검 시작 중 오류 — " + err.message); code = 1; }
await cleanup();
const failed = results.filter((r) => !r[1]).length;
console.log(`\n화면 점검: ${results.length - failed} 통과 / ${failed} 실패 (스크린샷: scratch/screens/)`);
process.exit(code || (failed ? 1 : 0));
