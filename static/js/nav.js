/* 四頁共用的第一排導覽列 —— ⛔ 唯一正本,四頁都吃這一份。

   使用者的需求(2026-09-08):「我按了心智圖、按了待辦事項、按了排行程,他的介面都長得不一樣,
   然後會跳來跳去,他的擺放位置也會跳來跳去,這樣真的很奇怪。我希望你就是都在固定位置
   不要跳來跳去。**你這個心智圖如果它有比較多的功能,你應該把那些功能放在往下面的一排**,
   而不是讓他上面第一排的選擇東西跳來跳去亂七八糟的。」

   ⭐ 在這之前導覽列是**四份各寫各的**(index/board/day/topics 各一段 + 四個 CSS 檔),
   於是同一顆「任務板」按鈕在排行程頁是第 3 個、待辦事項頁是第 2 個、心智圖頁是第 5 個。
   根因不是誰寫歪了,是**沒有共用的那一份** —— 每加一頁就多歪一次。

   兩條規則:
   ① 第一排**只放分頁**,順序固定,⛔ 當前頁不拿掉(拿掉的話剩下幾顆的位置每頁都不同,
      那正是使用者反映的「跳來跳去」),改成亮起來。
   ② 這一頁自己的工具**全部下移到第二排**(各頁原本的 #toolbar / #bar)。

   ⚠️ 這支 MUST 在各頁的主 JS **之前**載入 —— 狀態列 `#status` 是它生出來的,
      晚一步各頁的 getElementById("status") 就會拿到 null。 */

(() => {
  // 順序照「範圍由大到小」:整張圖 → 我還剩什麼 → 哪些在進行 → 今天幾點做。
  // ⛔ 改順序前先想一下:使用者的手已經記住位置了,換順序等於再跳一次。
  const PAGES = [
    { href: "/",        icon: "🧠", name: "心智圖",
      title: "整張圖長怎樣:什麼跟什麼有關、為什麼這樣定" },
    { href: "/topics",  icon: "✅", name: "待辦事項",
      title: "我還剩什麼沒做:按主題收起來,一個主題看得到還剩幾件" },
    { href: "/board",   icon: "📋", name: "任務板",
      title: "哪些在進行中:所有待辦依狀態分四欄" },
    { href: "/day",     icon: "🗓", name: "排行程",
      title: "今天幾點做哪一件:把任務拖進時間軸" },
  ];

  const here = location.pathname.replace(/\/+$/, "") || "/";
  const host = document.getElementById("scnav");
  if (!host) return;                      // 還沒接上這套的頁面,安靜跳過

  PAGES.forEach((p) => {
    const a = document.createElement("a");
    a.className = "np" + (p.href === here ? " cur" : "");
    a.href = p.href;
    a.title = p.title;
    a.innerHTML = `<span class="ni">${p.icon}</span>${p.name}`;
    // 已經在這一頁了就不要再載入一次 —— 按下去整頁重刷,使用者會以為當掉了
    if (p.href === here) a.addEventListener("click", (e) => e.preventDefault());
    host.appendChild(a);
  });

  /* 狀態列由這裡生,放在第一排最右邊 —— 四頁的 #status 位置從此一致。
     ⚠️ 各頁的 JS 都是 getElementById("status"),所以 id 不能改。 */
  const st = document.createElement("span");
  st.id = "status";
  host.appendChild(st);
})();

/* ── 隨手記:每一頁右下角的「＋」(2026-09-17)──────────────────────────
   使用者的需求(2026-09-17):「有時候我突然想到一些任務、一些想要做的事情,
   好像就沒有辦法直接加在我們這個上面。」—— 當時四頁只有待辦事項頁加得了,
   而且只能加在已經存在的主題底下。「還不知道要放哪裡的念頭」沒有地方放。

   設計:
   ① 四頁都在右下角同一個位置(依「第一排只放分頁」這條規範,所以不放第一排)。
   ② 不知道放哪 → 📥 收件匣;知道 → 直接選領域。伺服器只收這兩種,不收任意節點。
   ③ ⛔ 存失敗時字留在框裡。使用者突然想到的東西,弄丟一次就不會再用這顆了。
   ④ ⛔ 用注音/拼音選字時按的 Enter 不算送出(isComposing)。
   ⑤ 心智圖頁:先等它把沒存的改動存完再送,不然它下一次存檔會跳「圖被別人改過了」。
      送完馬上叫它重新載入(它自己每 4 秒也會查一次)。 */
(() => {
  const MAP = window.MM_MAP || "全局總覽圖";   // 伺服器說了算,見 /static/js/config.js
  const fab = document.createElement("button");
  fab.id = "qa-fab";
  fab.type = "button";
  fab.title = "隨手記一件事(不知道放哪就先進收件匣)";
  fab.textContent = "＋";
  const dlg = document.createElement("div");
  dlg.id = "qa-dlg";
  dlg.hidden = true;
  dlg.innerHTML = `
    <div class="qa-h">想到什麼?</div>
    <input id="qa-text" type="text" maxlength="200" autocomplete="off"
           placeholder="例如:問房東押金什麼時候退">
    <div class="qa-row"><span class="qa-l">放哪裡</span>
      <select id="qa-where"><option value="inbox">📥 收件匣,之後再分</option></select></div>
    <div class="qa-row"><span class="qa-l">等級</span>
      <select id="qa-pri"><option>P1</option><option selected>P2</option><option>P3</option><option>P4</option></select>
      <button id="qa-go" type="button">加進去</button></div>
    <div id="qa-msg" aria-live="polite"></div>`;
  document.body.append(fab, dlg);

  const $q = (id) => document.getElementById(id);
  const inp = $q("qa-text"), where = $q("qa-where"), pri = $q("qa-pri");
  const go = $q("qa-go"), msg = $q("qa-msg");
  let loaded = false, busy = false, closer = null;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function loadTargets() {
    if (loaded) return;
    try {
      const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}/quick-targets`);
      const out = await r.json();
      where.innerHTML = "";
      out.targets.forEach((t) => where.appendChild(new Option(t.label, t.id)));
      loaded = true;
    } catch { /* 拿不到清單就只剩收件匣,照樣能用 */ }
  }

  function open() {
    clearTimeout(closer);
    dlg.hidden = false;
    fab.classList.add("on");
    msg.textContent = "";
    msg.className = "";
    loadTargets();
    inp.focus();
  }
  // ⚠️ 關掉不清空:按錯關掉,再打開字還在
  function close() { dlg.hidden = true; fab.classList.remove("on"); }

  /* 心智圖頁才有 isDirty/saveMap。它「正在存」的時候再叫一次會直接返回,
     所以用輪詢等它真的存完,最多等 4 秒。 */
  async function mapSettled() {
    if (typeof window.isDirty !== "function" || typeof window.saveMap !== "function") return true;
    for (let i = 0; i < 14; i++) {
      if (!window.isDirty()) return true;
      window.saveMap();
      await sleep(300);
    }
    return !window.isDirty();
  }

  async function submit() {
    const text = inp.value.trim();
    if (!text || busy) { inp.focus(); return; }
    busy = true;
    go.disabled = true;
    msg.textContent = "存檔中…";
    msg.className = "";
    try {
      if (!(await mapSettled())) {
        throw new Error("心智圖上有還沒存進去的改動,先按「儲存」再加一次");
      }
      const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}/quick-todo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, parent: where.value, pri: pri.value }),
      });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(out.detail || `伺服器回 ${r.status}`);
      inp.value = "";
      msg.textContent = `✅ 加進「${out.parentTopic || "收件匣"}」了`;
      msg.className = "ok";
      document.dispatchEvent(new CustomEvent("sc:todo-added", { detail: out }));
      if (typeof window.pollExternal === "function") window.pollExternal();
      closer = setTimeout(close, 1500);
    } catch (e) {
      msg.textContent = `✘ 沒存進去:${e.message}。字還在框裡,可以再按一次。`;
      msg.className = "err";
    } finally {
      busy = false;
      go.disabled = false;
    }
  }

  fab.addEventListener("click", () => (dlg.hidden ? open() : close()));
  go.addEventListener("click", submit);
  dlg.addEventListener("keydown", (e) => {
    e.stopPropagation();                       // 不讓頁面自己的快捷鍵接走
    if (e.key === "Escape") { close(); return; }
    if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229 && e.target === inp) submit();
  });
})();
