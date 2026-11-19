// 화면 자동 점검(수동 실행): 임시 서버 + 로컬 Chrome(--headless=new, CDP)으로 주요 화면을 눌러 보고 통과/실패를 출력한다.
// 사용법: node scripts/check_ui.mjs      (Chrome 위치가 다르면 CHROME_PATH 환경변수)
// 새 npm 패키지 없음: Node 내장 WebSocket·fetch 로 CDP 를 직접 다룬다. 스크린샷은 scratch/screens/ (Git 제외).
// 진짜 DB·API 키는 쓰지 않는다(임시 DB scratch/check.db, ANTHROPIC_API_KEY 제거).
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SHOTS = join(ROOT, "scratch", "screens");
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PYTHON = join(ROOT, ".venv", "bin", "python");
mkdirSync(SHOTS, { recursive: true });

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
  const viewport = (width, height, mobile) => send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  return { evaluate, waitFor, goto, screenshot, viewport, errors };
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
  await page.goto(base + "/");

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

  await scenario("390px 폭에서 가로 스크롤이 없다", async () => {
    await page.viewport(390, 844, true);
    const overflow = async () => page.evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
    const bad = [];
    if ((await overflow()) > 0) bad.push("/toc");
    await page.screenshot("mobile-toc");
    await page.goto(base + "/");
    for (const tab of ["analysis", "answers", "words", "notebook", "mock"]) {
      await page.evaluate(`document.querySelector('.tab[data-tab="${tab}"]').click(); true`);
      await sleep(400);
      if ((await overflow()) > 0) bad.push(`홈/${tab}`);
    }
    await page.evaluate(`document.getElementById('q').value = '정상공손 비정상공손 처리'; document.getElementById('ask').click(); true`);
    await page.waitFor(`document.getElementById('answer').textContent.includes('주제 요약 카드')`, "요약 카드(모바일)");
    if ((await overflow()) > 0) bad.push("홈/요약 카드");
    await page.screenshot("mobile-summary");
    assert(!bad.length, "가로로 넘치는 화면: " + bad.join(", "));
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
