// 상단 메뉴(모든 화면 공용). 5개 그룹(홈·배우기·풀기·복습·계획)과 오른쪽 계정 메뉴를 만들어 #topbar 자리에 넣는다.
// quizcard.js(el·api)를 먼저 불러온 뒤 이 파일을 불러온다. 화면마다 따로 메뉴를 쓰지 않는다.
// 드롭다운은 클릭/Enter/Space 로만 열린다(hover 로 열지 않음). Esc·바깥 클릭·다른 그룹 클릭·포커스가 밖으로 나가면 닫힌다.
const NAV_GROUPS = [
  { key: "home", label: "홈", items: [{ label: "홈", href: "/" }] },
  { key: "learn", label: "배우기", items: [{ label: "공부", href: "/study" }, { label: "단어 주석", href: "/#words" }] },
  { key: "solve", label: "풀기", items: [{ label: "O/X", href: "/ox" }, { label: "기출 답안", href: "/#answers" }, { label: "모의고사", href: "/#mock" }, { label: "목차", href: "/toc" }] },
  { key: "review", label: "복습", items: [{ label: "오답노트", href: "/#notebook" }, { label: "주간 돌아보기", href: "/review-week" }] },
  { key: "plan", label: "계획", items: [{ label: "계획·캘린더", href: "/plan" }, { label: "문제 분석", href: "/#analysis" }] },
];
const HASH_GROUP = { "": "home", "#ask": "home", "#words": "learn", "#answers": "solve", "#mock": "solve", "#notebook": "review", "#analysis": "plan" };
const PATH_GROUP = { "/study": "learn", "/study-changes": "learn", "/ox": "solve", "/toc": "solve", "/review-week": "review", "/plan": "plan", "/calendar": "plan" };

// 지금 보고 있는 주소(경로+해시)가 속한 그룹 키. 어느 그룹에도 안 속하면 "" (/account, /start 등).
function navGroupOf(path, hash) {
  if (path === "/" || path === "/index.html") return HASH_GROUP[hash] || "";
  const base = path.startsWith("/study/") ? "/study" : path;
  return PATH_GROUP[base] || "";
}
// 세부 메뉴 중 지금 주소와 같은 항목(없으면 null).
function navItemOf(path, hash) {
  const here = path === "/index.html" ? "/" : path.startsWith("/study/") ? "/study" : path;
  for (const g of NAV_GROUPS) for (const it of g.items) {
    const [p, h = ""] = it.href.split("#");
    if (p === here && (p !== "/" || (h ? "#" + h : "") === (hash === "#ask" ? "" : hash))) return it;
  }
  return null;
}

(function () {
  const closeAll = (except) => {
    document.querySelectorAll(".topbar [aria-expanded='true']").forEach((b) => { if (b !== except) { b.setAttribute("aria-expanded", "false"); b.nextElementSibling.hidden = true; } });
  };
  // 메뉴가 화면 오른쪽 밖으로 나가면 안쪽으로 당긴다.
  const keepInside = (menu) => {
    if (menu.classList.contains("nav-menu-right")) { menu.style.left = "auto"; menu.style.right = "0px"; return; }      // 계정 메뉴는 오른쪽 끝에 맞춘다
    menu.style.left = "0px";
    const r = menu.getBoundingClientRect();
    const shift = Math.min(0, document.documentElement.clientWidth - 8 - r.right);
    menu.style.left = Math.max(shift, 8 - r.left) + "px";
  };
  const dropdown = (button, menu) => {
    const wrap = el("div", { className: "nav-drop" }, button, menu);
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-haspopup", "true");
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = button.getAttribute("aria-expanded") === "true";
      closeAll(open ? null : button);
      button.setAttribute("aria-expanded", String(!open));
      menu.hidden = open;
      if (!open) keepInside(menu);
    });
    button.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); if (menu.hidden) button.click(); menu.querySelector("a, button").focus(); }
    });
    wrap.addEventListener("focusout", (e) => { if (!wrap.contains(e.relatedTarget)) { button.setAttribute("aria-expanded", "false"); menu.hidden = true; } });
    menu.addEventListener("click", () => { button.setAttribute("aria-expanded", "false"); menu.hidden = true; });
    return wrap;
  };

  function build() {
    const groups = NAV_GROUPS.map((g) => {
      if (g.items.length === 1) return el("li", { className: "nav-group" }, el("a", { className: "nav-btn", href: g.items[0].href, textContent: g.label }));
      const button = el("button", { type: "button", className: "nav-btn", textContent: g.label });
      const menu = el("ul", { className: "nav-menu" }, ...g.items.map((it) => el("li", {}, el("a", { href: it.href, textContent: it.label }))));
      button.dataset.group = g.key;
      menu.id = "menu-" + g.key;
      button.setAttribute("aria-controls", menu.id);
      return el("li", { className: "nav-group" }, dropdown(button, menu));
    });
    groups.forEach((li, i) => { li.dataset.group = NAV_GROUPS[i].key; });
    return el("header", { className: "topbar" }, el("div", { className: "topbar-inner" },
      el("a", { className: "brand", href: "/", textContent: "회계튜터" }, el("small", { textContent: " 전산세무 1급 이론" })),
      el("nav", { className: "nav-groups", ariaLabel: "화면 이동" }, el("ul", {}, ...groups))));
  }

  // 지금 주소에 맞게 활성 그룹(보라색 pill)과 현재 항목 표시를 다시 칠한다.
  function mark() {
    const group = navGroupOf(location.pathname, location.hash), item = navItemOf(location.pathname, location.hash);
    document.querySelectorAll(".topbar .nav-group").forEach((li) => {
      const on = li.dataset.group === group;
      const btn = li.querySelector(".nav-btn");
      btn.classList.toggle("active", on);
      if (on) btn.setAttribute("aria-current", "page"); else btn.removeAttribute("aria-current");
    });
    document.querySelectorAll(".topbar .nav-menu a").forEach((a) => {
      const [p, h = ""] = a.getAttribute("href").split("#");
      const here = item && item.href === a.getAttribute("href");
      a.classList.toggle("current", !!here);
      if (here) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }

  async function addAccount(bar) {
    const { ok, data } = await api("/api/me");
    if (!ok || !data.user) return;
    const button = el("button", { type: "button", id: "userName", className: "nav-btn user-btn", textContent: data.user.name, title: "계정 메뉴" });
    const logout = el("button", { type: "button", id: "logoutBtn", textContent: "로그아웃" });
    logout.addEventListener("click", async () => { await api("/api/logout", {}); location.href = "/login"; });
    const menu = el("ul", { className: "nav-menu nav-menu-right", id: "menu-account" },
      el("li", {}, el("a", { id: "accountLink", href: "/account", textContent: "내 계정" })),
      ...(data.user.is_admin ? [el("li", {}, el("a", { id: "adminLink", href: "/admin", textContent: "계정 관리" }))] : []),
      el("li", {}, logout));
    button.setAttribute("aria-controls", "menu-account");
    const box = el("div", { id: "userbox", className: "userbox" }, dropdown(button, menu));
    bar.append(box);
    if (location.pathname === "/account") button.classList.add("active");
  }

  function mount() {
    const slot = document.getElementById("topbar");
    if (!slot) return;
    const header = build();
    slot.replaceWith(header);
    mark();
    addAccount(header.querySelector(".topbar-inner"));
    addEventListener("hashchange", mark);
    document.addEventListener("click", () => closeAll());
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      const open = document.querySelector(".topbar [aria-expanded='true']");
      if (!open) return;
      closeAll();
      open.focus();
    });
    addEventListener("resize", () => { const o = document.querySelector(".topbar [aria-expanded='true']"); if (o) keepInside(o.nextElementSibling); });
  }
  mount();
})();
