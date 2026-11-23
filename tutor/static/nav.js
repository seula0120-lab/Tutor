// 화면 틀(모든 화면 공용): 왼쪽 사이드바(항상 펼침) + 상단 바(☰·다크 모드·사용자 메뉴). #topbar 자리에 넣는다.
// quizcard.js(el·api)를 먼저 불러온 뒤 이 파일을 불러온다. 화면마다 따로 메뉴를 쓰지 않는다.
// 900px 이하에서는 사이드바가 숨고 ☰ 로 여는 서랍이 된다(Esc·바깥 클릭으로 닫힘). 사용자 메뉴는 클릭/Enter/Space 로만 열린다(hover 없음).
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
  const THEME_KEY = "tutorTheme";
  const savedTheme = () => { try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; } };
  const isDark = () => (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  if (savedTheme()) document.documentElement.dataset.theme = savedTheme();

  const closeMenu = () => {
    document.querySelectorAll(".topbar [aria-expanded='true']").forEach((b) => { b.setAttribute("aria-expanded", "false"); b.nextElementSibling.hidden = true; });
  };
  const setDrawer = (open) => {
    document.querySelector(".sidebar").classList.toggle("open", open);
    document.querySelector(".side-backdrop").hidden = !open;
    document.getElementById("sideToggle").setAttribute("aria-expanded", String(open));
  };

  function sidebar() {
    const link = (it) => el("li", {}, el("a", { className: "side-link", href: it.href, textContent: it.label }));
    const parts = [];
    for (const g of NAV_GROUPS) {
      if (g.items.length === 1 && g.key === "home") parts.push(el("ul", { className: "side-list" }, link(g.items[0])));
      else parts.push(el("div", { className: "side-group", id: "side-" + g.key }, el("div", { className: "side-title", textContent: g.label }), el("ul", { className: "side-list" }, ...g.items.map(link))));
    }
    const out = el("button", { type: "button", id: "sideLogout", className: "side-logout", textContent: "로그아웃" });
    out.addEventListener("click", async () => { await api("/api/logout", {}); location.href = "/login"; });
    return el("aside", { className: "sidebar", id: "sidebar", ariaLabel: "화면 이동" },
      el("a", { className: "brand", href: "/", textContent: "회계튜터" }),
      el("nav", { className: "side-nav" }, ...parts), out);
  }

  // 지금 주소에 맞는 항목(보라색)과 그룹 제목을 다시 칠한다.
  function mark() {
    const group = navGroupOf(location.pathname, location.hash), item = navItemOf(location.pathname, location.hash);
    document.querySelectorAll(".sidebar .side-link").forEach((a) => {
      const here = !!item && item.href === a.getAttribute("href");
      a.classList.toggle("active", here);
      if (here) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.querySelectorAll(".sidebar .side-group").forEach((g) => g.classList.toggle("on", g.id === "side-" + group));
  }

  function topbar() {
    const toggle = el("button", { type: "button", id: "sideToggle", className: "side-toggle", textContent: "☰", title: "메뉴", ariaLabel: "메뉴 열기" });
    toggle.setAttribute("aria-controls", "sidebar");
    toggle.setAttribute("aria-expanded", "false");
    toggle.addEventListener("click", (e) => { e.stopPropagation(); setDrawer(!document.querySelector(".sidebar").classList.contains("open")); });
    const theme = el("button", { type: "button", id: "themeBtn", className: "theme-btn" });
    const paint = () => { theme.textContent = isDark() ? "라이트 모드" : "다크 모드"; theme.setAttribute("aria-pressed", String(isDark())); };
    theme.addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* 저장 실패는 무시 */ }
      paint();
    });
    paint();
    return el("header", { className: "topbar" }, el("div", { className: "topbar-inner" },
      toggle, el("a", { className: "brand brand-top", href: "/", textContent: "회계튜터" }), el("span", { className: "topbar-gap" }), theme));
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
    menu.hidden = true;
    button.setAttribute("aria-controls", "menu-account");
    button.setAttribute("aria-haspopup", "true");
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = button.getAttribute("aria-expanded") === "true";
      closeMenu();
      button.setAttribute("aria-expanded", String(!open));
      menu.hidden = open;
    });
    button.addEventListener("keydown", (e) => { if (e.key === "ArrowDown") { e.preventDefault(); if (menu.hidden) button.click(); menu.querySelector("a, button").focus(); } });
    const wrap = el("div", { className: "nav-drop" }, button, menu);
    wrap.addEventListener("focusout", (e) => { if (!wrap.contains(e.relatedTarget)) closeMenu(); });
    menu.addEventListener("click", closeMenu);
    bar.append(el("div", { id: "userbox", className: "userbox" }, wrap));
    if (location.pathname === "/account") button.classList.add("active");
  }

  function mount() {
    const slot = document.getElementById("topbar");
    if (!slot) return;
    const header = topbar();
    slot.replaceWith(header);
    document.body.classList.add("has-side");
    document.body.prepend(el("div", { className: "side-backdrop", hidden: true }), sidebar());
    document.querySelector(".side-backdrop").addEventListener("click", () => setDrawer(false));
    document.querySelector(".sidebar").addEventListener("click", (e) => { if (e.target.closest("a")) setDrawer(false); });
    mark();
    addAccount(header.querySelector(".topbar-inner"));
    addEventListener("hashchange", mark);
    document.addEventListener("click", closeMenu);
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      const open = document.querySelector(".topbar [aria-expanded='true']");
      if (open) { closeMenu(); open.focus(); return; }
      if (document.querySelector(".sidebar.open")) { setDrawer(false); document.getElementById("sideToggle").focus(); }
    });
    addEventListener("resize", () => { if (innerWidth > 900) setDrawer(false); });
  }
  mount();
})();
