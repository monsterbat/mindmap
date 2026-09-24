/* 待辦事項 — 心智圖的第五個視圖(2026-09-08)。

   使用者的需求(2026-09-08):「我們現在每次處理什麼事情都會產生一大堆待辦事項,但是這些待辦事項
   我到最後其實都不知道我到底還需要做什麼事情,那每次都還要再跑去心智圖那邊去看有缺什麼,
   這樣其實很煩躁…我們沒有一個我自己可以去檢視審查的環境,我這樣很容易漏掉很多事情。」

   當時圖上有 112 件未完成待辦攤成一片 —— 任務板依「狀態」分四欄,回答得了「有哪些事」,
   回答不了「這件事我還剩什麼沒做」。

   ⭐ 一行的欄位順序是使用者當天定案的(第二輪):「優先區 → 分類 → 內容」。
      需求是:「主題像是 Workspace、Blog、Music 這種東西應該是要放最前面的,
      然後他的優先序的應該要排在更前面,就是第一個就是優先區、再來就是分類、再來才是內容,
      然後你還要有辦法讓我去調整排序。」

   設計五條:
   ① 按主題收起來。主題 = 非待辦節點,而且底下(含子孫)有 ≥2 件待辦。使用者選「自動」不選
      「手動標」—— 新開的專案會自己出現,而「忘記標」正是使用者漏東西的成因。
   ② 收起來的時候也要看得到「做到哪」與「下一件是什麼」,不展開就能決定要不要動它。
   ③ 可以直接打勾、也可以直接新增 —— 不然使用者還是得回來叫 AI,那就沒解決原本的問題。
   ④ 順序由使用者自己拖,存進圖上的 `detail.viewOrder`。沒拖過的照「等級 → 死線 → 剩幾件」。
   ⑤ ⛔ 不是另一份資料。讀寫的就是那張圖,跟任務板/排行程/心智圖即時連動。 */

const MAP = window.MM_MAP || "全局總覽圖";   // 伺服器說了算,見 /static/js/config.js
const PRIS = ["P1", "P2", "P3", "P4"];
const MARKS = ["⏳", "🔜", "⏸️", "⏸", "✅", "🎯"];
const $ = (id) => document.getElementById(id);

let raw = null;            // 上一次讀到的整張圖
let topics = [];
const openSet = new Set(); // 展開狀態要跨重新整理留著,不然打一個勾整頁就收起來了
const whySet = new Set();

const stripMark = (t) => {
  let s = (t || "").trim();
  for (const m of MARKS) if (s.startsWith(m)) return s.slice(m.length).trim();
  return s;
};
const markOf = (t) => {
  const s = (t || "").trim();
  for (const m of MARKS) if (s.startsWith(m)) return m === "⏸" ? "⏸️" : m;
  return "⏳";
};
const isDone = (n) => markOf(n.topic) === "✅";
const priOf = (n) => (n.tags || []).find((t) => PRIS.includes(t)) || "";
const det = (n) => n.detail || {};

/* 差幾天用「日期」算不用時間戳 —— 今天到期會被算成「剩 1 天」,
   而「今天」跟「剩一天」在排程上是兩件事。(跟 board.js 同一個理由) */
function daysLeft(due) {
  if (!due) return null;
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const [y, m, d] = due.split("-").map(Number);
  return Math.round((Date.UTC(y, m - 1, d) - today) / 86400000);
}
function dueLabel(due) {
  const n = daysLeft(due);
  if (n === null) return "";
  if (n < 0) return `${due}(過期 ${-n} 天)`;
  if (n === 0) return `${due}(今天)`;
  return `${due}(剩 ${n} 天)`;
}
const dueClass = (due) => {
  const n = daysLeft(due);
  if (n === null) return "";
  if (n <= 3) return "soon";
  if (n <= 14) return "warn";
  return "";
};

// 這一支底下(含自己)有幾件待辦
function countTodos(node) {
  let n = node.todo ? 1 : 0;
  (node.children || []).forEach((c) => (n += countTodos(c)));
  return n;
}

/* 一個主題底下的「層面」。刻意扁平化:巢狀太深使用者會看不完,
   所以子孫層面的名字寫成路徑(「分類 › 子項目」),縮排只有一層。 */
function facetsOf(topicNode) {
  const out = [];
  const direct = (topicNode.children || []).filter((c) => c.todo);
  if (direct.length) out.push({ name: "", parent: topicNode, items: direct });
  const walk = (node, path) => {
    (node.children || []).forEach((c) => {
      if (c.todo) return;
      if (!countTodos(c)) return;
      const here = path.concat(stripMark(c.topic));
      const mine = (c.children || []).filter((x) => x.todo);
      if (mine.length) out.push({ name: here.join(" › "), parent: c, items: mine });
      walk(c, here);
    });
  };
  walk(topicNode, []);
  return out;
}

/* 主題怎麼認定(2026-09-08 定案選「自動」):
   從領域(根的直接子節點)往下走,遇到「非待辦 + 底下有 ≥2 件待辦」就收成一個主題,
   ⛔ 收了就不再往下找 —— 不然同一批事情會在祖先跟後代重複出現兩次。
   ⚠️ 領域本身不當主題,它是分類。零星的(直接掛在領域下、或底下只有 1 件的)
      收進該領域的「零星待辦」,⛔ 不能讓它們無家可歸 —— 那就是使用者現在漏東西的成因。

   `orderNodeId` = 順序寫回哪一顆。零星待辦桶沒有自己的節點,寫在該領域節點上。 */
function collectTopics(root) {
  const out = [];
  (root.children || []).forEach((domain) => {
    const dom = stripMark(domain.topic);
    /* 📥 收件匣(2026-09-17):右下角「＋」隨手記、還不知道放哪的事。
       它掛在根底下,照一般規則會被當成一個「領域」,裡面的事全變成「零星待辦」——
       那個名字會讓使用者以為是別的東西。所以特別處理:自成一包、永遠排第一。 */
    if (domain.id === "inbox") {
      if (countTodos(domain)) {
        out.push({ id: "inbox", name: "隨手記、還沒分類的", domain: dom, node: domain,
                   orderNodeId: domain.id, order: det(domain).viewOrder, isInbox: true });
      }
      return;
    }
    const loose = [];
    const scan = (node) => {
      (node.children || []).forEach((c) => {
        if (c.todo) { loose.push({ node: c, parent: node }); return; }
        const n = countTodos(c);
        if (n >= 2) {
          out.push({
            id: c.id, name: stripMark(c.topic), domain: dom, node: c,
            orderNodeId: c.id, order: det(c).viewOrder,
          });
        } else if (n === 1) scan(c);
      });
    };
    scan(domain);
    if (loose.length) {
      out.push({
        id: `__loose__${domain.id}`, name: "零星待辦(沒有歸到主題)",
        domain: dom, node: null, loose,
        orderNodeId: domain.id, order: det(domain).viewOrder,
      });
    }
  });
  return out;
}

// 這個主題現在最高的等級 = 底下「還沒做完」的裡面最高的那一級
function topPri(items) {
  const idx = items.filter((x) => !isDone(x))
    .map((x) => PRIS.indexOf(priOf(x))).filter((i) => i >= 0);
  return idx.length ? PRIS[Math.min(...idx)] : "";
}

function statsOf(t) {
  const items = t.node ? [] : t.loose.map((x) => x.node);
  if (t.node) facetsOf(t.node).forEach((f) => items.push(...f.items));
  const done = items.filter(isDone).length;
  const open = items.filter((x) => !isDone(x));
  const dues = open.map((x) => det(x).due).filter(Boolean).sort();
  // 「下一件」= 等級最高的,同級取死線最近的。使用者收起來的時候只想知道這一件。
  const next = open.slice().sort((a, b) => {
    const pa = PRIS.indexOf(priOf(a)), pb = PRIS.indexOf(priOf(b));
    if (pa !== pb) return (pa < 0 ? 9 : pa) - (pb < 0 ? 9 : pb);
    const da = det(a).due || "9999", db = det(b).due || "9999";
    return da < db ? -1 : da > db ? 1 : 0;
  })[0];
  return { total: items.length, done, open: open.length,
           due: dues[0] || "", next, pri: topPri(items) };
}

/* 完整順序(不受篩選影響)。拖曳要靠它算插入位置 ——
   只看畫面上那幾張的話,篩了領域再拖就會把被篩掉的主題順序打亂。 */
function sortedAll() {
  return topics.map((t) => ({ t, s: statsOf(t) })).sort((a, b) => {
    // ⓪ 收件匣永遠第一:它的意思就是「還沒處理的」,沉下去就等於沒有
    if (!!a.t.isInbox !== !!b.t.isInbox) return a.t.isInbox ? -1 : 1;
    // ① 使用者自己拖過的,永遠照拖過的順序
    const va = a.t.order, vb = b.t.order;
    if (va != null && vb != null && va !== vb) return va - vb;
    if (va != null && vb == null) return -1;
    if (vb != null && va == null) return 1;
    // ② 沒拖過的:等級 → 死線 → 還剩幾件(艾森豪:重要先於緊急)
    const pa = PRIS.indexOf(a.s.pri), pb = PRIS.indexOf(b.s.pri);
    if (pa !== pb) return (pa < 0 ? 9 : pa) - (pb < 0 ? 9 : pb);
    const da = a.s.due || "", db = b.s.due || "";
    if (da && db && da !== db) return da < db ? -1 : 1;
    if (da && !db) return -1;
    if (db && !da) return 1;
    return b.s.open - a.s.open;
  });
}

async function load() {
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}`);
  if (!r.ok) { $("status").textContent = "✘ 讀不到圖"; return; }
  raw = await r.json();
  topics = collectTopics(raw.data.nodeData);
  fillDomains();
  if (!applyQuery._done) { applyQuery(); applyQuery._done = true; fillDomains(); }
  render();
}

/* 網址可以指定一進來就展開哪個主題:/topics?open=<節點id>&domain=<領域>&q=<關鍵字>
   —— 心智圖或每日排程報告要把使用者直接送到某一個主題時用得到,不然還要自己找。 */
function applyQuery() {
  const p = new URLSearchParams(location.search);
  const dom = p.get("domain");
  if (dom) $("domain").value = dom;
  const q = p.get("q");
  if (q) $("q").value = q;
  (p.get("open") || "").split(",").map((s) => s.trim()).filter(Boolean)
    .forEach((id) => openSet.add(id));
}

function fillDomains() {
  const sel = $("domain"), keep = sel.value;
  const seen = [...new Set(topics.map((t) => t.domain))];
  sel.innerHTML = '<option value="">全部領域</option>'
    + seen.map((d) => `<option>${esc(d)}</option>`).join("");
  sel.value = keep;
}

const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function render() {
  const box = $("topics");
  const domain = $("domain").value;
  const onlyOpen = $("chk-open").checked;
  const q = $("q").value.trim().toLowerCase();
  box.innerHTML = "";

  let rows = sortedAll();
  if (domain) rows = rows.filter((r) => r.t.domain === domain);
  if (onlyOpen) rows = rows.filter((r) => r.s.open > 0);
  if (q) {
    rows = rows.filter((r) => {
      if ((r.t.name + r.t.domain).toLowerCase().includes(q)) return true;
      const items = r.t.node ? facetsOf(r.t.node).flatMap((f) => f.items)
                             : r.t.loose.map((x) => x.node);
      return items.some((i) => (stripMark(i.topic) + (det(i).explain || "")).toLowerCase().includes(q));
    });
  }

  $("empty").hidden = rows.length > 0;
  const totalOpen = topics.reduce((n, t) => n + statsOf(t).open, 0);
  $("status").textContent = `${rows.length} 個主題／全部還有 ${totalOpen} 件沒做完`;
  rows.forEach((r) => box.appendChild(topicCard(r.t, r.s)));
}

function topicCard(t, s) {
  const el = document.createElement("section");
  const soon = s.due && daysLeft(s.due) <= 14;
  el.className = "topic" + (openSet.has(t.id) ? " open" : "") + (soon ? " urgent" : "");
  el.dataset.id = t.id;

  const head = document.createElement("div");
  head.className = "thead";
  // ⭐ 欄位順序是使用者定案的:優先區 → 分類 → 內容(2026-09-08 第二輪)
  head.innerHTML = `<span class="grip" title="按住我上下拖,可以調這一頁的順序">⠿</span>`
    + `<span class="pri ${s.pri || "none"}">${s.pri || "—"}</span>`
    + `<span class="tdomain">${esc(t.domain)}</span>`
    + `<span class="tname"><span class="caret">▶</span>${esc(t.name)}</span>`
    + `<span class="tduecell">${s.due
        ? `<span class="tdue ${dueClass(s.due)}">🗓 ${esc(dueLabel(s.due))}</span>` : ""}</span>`
    + `<span class="prog"><span class="bar"><i style="width:${
        s.total ? Math.round((s.done / s.total) * 100) : 0}%"></i></span>`
    + `<span class="pcount">${s.done}/${s.total}</span></span>`;
  head.addEventListener("click", (e) => {
    if (e.target.closest(".grip")) return;   // 抓把手不是要展開
    openSet.has(t.id) ? openSet.delete(t.id) : openSet.add(t.id);
    el.classList.toggle("open");
  });
  el.appendChild(head);
  wireDrag(el, head, t);

  if (s.next) {
    const nx = document.createElement("div");
    nx.className = "next";
    nx.innerHTML = `↳ 下一件:<b>${esc(stripMark(s.next.topic))}</b>`
      + (priOf(s.next) ? ` <span class="tag pri ${priOf(s.next)}">${priOf(s.next)}</span>` : "");
    el.appendChild(nx);
  }

  const body = document.createElement("div");
  body.className = "tbody";
  const facets = t.node ? facetsOf(t.node)
                        : [{ name: "", parent: null, items: t.loose.map((x) => x.node),
                             parents: t.loose.map((x) => x.parent) }];
  // 全部做完的層面沉到最下面 —— 使用者打開一個主題是要找「還沒做的」,
  // 不是要先看一遍做完的。⛔ 但不隱藏,使用者要看得到自己做過什麼(同 /day 的規則)。
  facets.sort((a, b) => {
    const oa = a.items.some((x) => !isDone(x)) ? 0 : 1;
    const ob = b.items.some((x) => !isDone(x)) ? 0 : 1;
    return oa - ob;
  });
  facets.forEach((f) => body.appendChild(facetBlock(f)));
  if (t.node && !t.isInbox) body.appendChild(addRow(t.node, "直接加在這個主題底下"));
  el.appendChild(body);
  return el;
}

/* 拖曳排順序(2026-09-08 使用者要求)。

   ⛔ 刻意**不用** HTML5 的 drag-and-drop:①手機與平板的瀏覽器完全不支援它
   ②它要先把元素設成 draggable,而那個屬性一設下去,標題文字就選不起來了。
   改用 pointer 事件自己做,滑鼠與觸控同一套。

   ⚠️ 只有把手能起拖:整張卡都能拖的話,使用者想選取標題文字就會變成拖曳。
   ⚠️ 插入位置看滑鼠在目標卡的上半還是下半 —— 不另外畫插入線,邊框亮起來就夠了,
      而且不會在拖到一半時抖動。 */
function wireDrag(el, head, t) {
  const grip = head.querySelector(".grip");
  const clearMarks = () => document.querySelectorAll(".topic")
    .forEach((x) => x.classList.remove("drop-before", "drop-after"));

  grip.addEventListener("pointerdown", (e) => {
    e.preventDefault();          // 不要順便選到文字
    grip.setPointerCapture(e.pointerId);
    const startY = e.clientY;
    let moved = false, target = null, after = false;

    const onMove = (ev) => {
      // 5px 的容差:手指與滑鼠都會抖,不設容差的話點一下就被當成拖曳
      if (!moved && Math.abs(ev.clientY - startY) < 5) return;
      if (!moved) { moved = true; el.classList.add("dragging"); }
      clearMarks();
      target = null;
      for (const card of document.querySelectorAll(".topic")) {
        if (card === el) continue;
        const r = card.getBoundingClientRect();
        if (ev.clientY >= r.top && ev.clientY <= r.bottom) {
          target = card;
          after = ev.clientY - r.top > r.height / 2;
          card.classList.add(after ? "drop-after" : "drop-before");
          break;
        }
      }
    };
    const onUp = () => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onUp);
      el.classList.remove("dragging");
      clearMarks();
      if (moved && target) reorder(t.id, target.dataset.id, after);
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onUp);
  });
}

/* 把被拖的那張插到目標的前/後,然後把「全部主題」重新編號送回去。
   ⛔ 只送畫面上那幾張是不夠的 —— 使用者篩了領域再拖的話,被篩掉的那些順序會被打亂。 */
async function reorder(srcId, dstId, after) {
  const ids = sortedAll().map((r) => r.t.id);
  const i = ids.indexOf(srcId);
  if (i < 0) return;
  ids.splice(i, 1);
  const j = ids.indexOf(dstId);
  if (j < 0) return;
  ids.splice(after ? j + 1 : j, 0, srcId);

  const order = ids.map((id) => (topics.find((t) => t.id === id) || {}).orderNodeId).filter(Boolean);
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}/view-order`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order }),
  });
  if (!r.ok) { toast("順序沒存起來,重新整理再試"); return; }
  const out = await r.json();
  toast(out.missing && out.missing.length
    ? `順序存好了(有 ${out.missing.length} 個找不到,可能剛被歸檔)`
    : "順序存好了");
  await load();
}

function facetBlock(f) {
  const wrap = document.createElement("div");
  wrap.className = "facet";
  const items = f.items.slice().sort((a, b) => {
    const da = isDone(a) ? 1 : 0, db = isDone(b) ? 1 : 0;
    if (da !== db) return da - db;               // 沒做完的在上面
    const pa = PRIS.indexOf(priOf(a)), pb = PRIS.indexOf(priOf(b));
    return (pa < 0 ? 9 : pa) - (pb < 0 ? 9 : pb);
  });
  const done = items.filter(isDone).length;
  if (f.name) {
    const h = document.createElement("div");
    h.className = "fname";
    h.innerHTML = `<span>${esc(f.name)}</span>`
      + `<span class="fn">${done}/${items.length}</span>`
      + (done === items.length && items.length ? `<span class="fdone">✓ 都做完了</span>` : "");
    wrap.appendChild(h);
  }
  items.forEach((n, i) => wrap.appendChild(itemRow(n, (f.parents || [])[i] || f.parent)));
  if (f.parent) wrap.appendChild(addRow(f.parent, `加進「${f.name || "這一組"}」`));
  return wrap;
}

function itemRow(n, parent) {
  const row = document.createElement("div");
  const done = isDone(n);
  const pri = priOf(n);
  row.className = `item p-${pri || "P4"}` + (done ? " done" : "");
  row.dataset.id = n.id;   // 對帳與除錯用:畫面上這一條是圖上的哪一顆
  const d = det(n);

  const box = document.createElement("button");
  box.className = "box";
  box.textContent = done ? "✓" : "";
  box.title = done ? "取消完成" : "標成完成";
  box.addEventListener("click", (e) => { e.stopPropagation(); toggleDone(n.id, done); });
  row.appendChild(box);

  const col = document.createElement("div");
  col.className = "icol";
  let meta = "";
  if (pri) meta += `<span class="tag pri ${pri}">${pri}</span>`;
  if (d.due) meta += `<span class="tag due ${dueClass(d.due)}">🗓 ${esc(dueLabel(d.due))}</span>`;
  if (d.hardDue) meta += `<span class="tag lock">🔒 外力死線</span>`;
  // ⚠️ 欄位名是 until 不是 waitUntil(mm.py wait 寫的是 detail.until)。
  //    2026-09-08 第一版寫成 waitUntil,這個標籤從上線那天起一次都沒顯示過 —— 而且不會報錯。
  if (d.until) meta += `<span class="tag wait">⏸ 等「${esc(d.until)}」</span>`;
  if (d.earliest) meta += `<span class="tag">最早 ${esc(d.earliest)}</span>`;
  if (markOf(n.topic) === "🔜") meta += `<span class="tag" style="color:var(--blue)">正在做</span>`;
  if (done && d.doneOn) meta += `<span class="tag">✅ ${esc(d.doneOn)}</span>`;
  col.innerHTML = `<div class="it">${esc(stripMark(n.topic))}</div>`
    + `<div class="imeta">${meta}</div>`;

  if (d.explain) {
    const b = document.createElement("button");
    b.className = "whyb";
    b.type = "button";
    b.title = "這件事是什麼、為什麼要做";
    const sync = () => (b.textContent = whySet.has(n.id) ? "ⓘ 收起" : "ⓘ 為什麼");
    sync();
    const p = document.createElement("div");
    p.className = "why";
    p.textContent = d.explain;
    p.hidden = !whySet.has(n.id);
    b.addEventListener("click", () => {
      whySet.has(n.id) ? whySet.delete(n.id) : whySet.add(n.id);
      p.hidden = !whySet.has(n.id);
      sync();
    });
    col.querySelector(".imeta").appendChild(b);
    col.appendChild(p);
  }
  row.appendChild(col);
  return row;
}

/* 直接在這頁加一條 —— 這是這一頁的重點之一。
   2026-09-08 要解的問題是「想到一件事 → 要回去叫 AI 加 → 沒加 → 忘記」,
   少掉中間那兩步,使用者才有可能真的把腦子裡的東西倒出來。 */
function addRow(parentNode, hint) {
  const row = document.createElement("div");
  row.className = "addrow";
  const inp = document.createElement("input");
  inp.type = "text";
  inp.placeholder = `＋ ${hint}`;
  const sel = document.createElement("select");
  PRIS.forEach((p) => sel.appendChild(new Option(p, p)));
  sel.value = "P2";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "加進去";
  const go = () => {
    const text = inp.value.trim();
    if (!text) return;
    inp.value = "";
    addTodo(parentNode.id, text, sel.value);
  };
  btn.addEventListener("click", go);
  // ⛔ 用注音/拼音選字時按的 Enter 也會觸發 keydown(isComposing=true),不能當成送出 ——
  //    2026-09-17 做「＋」時才發現這裡從第一版就沒擋,使用者打中文會被截斷送出。
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) go();
  });
  row.append(inp, sel, btn);
  return row;
}

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2600);
}

/* 寫回:重讀一次再寫,而且帶 base_mtime ——
   這頁跟心智圖、任務板、排行程、AI 的 mm.py 可能同時在動同一份檔案。 */
async function writeBack(mutate, okMsg, what) {
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}`);
  const out = await r.json();
  const byId = {};
  const index = (n) => { byId[n.id] = n; (n.children || []).forEach(index); };
  index(out.data.nodeData);
  const touched = mutate(byId, out.data.nodeData);
  if (touched === false) return false;
  const put = await fetch(`/api/maps/${encodeURIComponent(MAP)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: out.data, base_mtime: out.mtime }),
  });
  if (!put.ok) {
    toast(put.status === 409 ? "圖被別人改過了,重新整理再試" : "存檔失敗");
    return false;
  }
  toast(okMsg);
  await load();
  return true;
}

const today = () => new Date().toLocaleDateString("sv-SE");

async function toggleDone(id, wasDone) {
  await writeBack((byId) => {
    const n = byId[id];
    if (!n) { toast("那條已經不在圖上了"); return false; }
    const body = stripMark(n.topic);
    n.topic = wasDone ? `⏳ ${body}` : `✅ ${body}`;
    const d = (n.detail = n.detail || {});
    /* 完成的事放 7 天後自動歸檔,靠 detail.doneOn 算。
       ⛔ 完成日一定要在按下去的當下寫 —— 2026-08-24 出過的問題:/day 標完成沒寫 doneOn,
       等 7 天後 janitor 補一個「今天」,那個日期最多錯 7 天而且看不出是補的。 */
    if (wasDone) delete d.doneOn;
    else d.doneOn = today();
    // ⛔ 這是使用者自己按的,不要標成 AI 改的 —— 圈圈是「AI 動過、你還沒看」的意思。
    delete n.aiEdited;
    n.scEdited = `${today()} 在待辦事項頁${wasDone ? "取消完成" : "打勾完成"}`;
    return true;
  }, wasDone ? "改回還沒做完" : "✅ 打勾了", "改狀態");
}

async function addTodo(parentId, text, pri) {
  const id = "sc-" + Date.now().toString(36);
  await writeBack((byId) => {
    const p = byId[parentId];
    if (!p) { toast("找不到要掛的地方,重新整理再試"); return false; }
    (p.children = p.children || []).push({
      id, topic: `⏳ ${text}`, todo: true, tags: [pri],
      detail: { explain: `${today()} 自己在待辦事項頁加的(還沒寫為什麼要做)。` },
      scEdited: `${today()} 在待辦事項頁新增`,
    });
    openSet.add(parentId);
    return true;
  }, "＋ 加好了", "新增");
}

$("domain").addEventListener("change", render);
$("chk-open").addEventListener("change", render);
$("q").addEventListener("input", render);
$("expand-all").addEventListener("click", () => {
  topics.forEach((t) => openSet.add(t.id));
  render();
});
$("collapse-all").addEventListener("click", () => { openSet.clear(); render(); });
$("reset-order").addEventListener("click", resetOrder);
document.addEventListener("sc:todo-added", (e) => {
  if (e.detail && e.detail.parent) openSet.add(e.detail.parent === "inbox" ? "inbox" : e.detail.parent);
  load();
});
load();

/* 排順序反悔的出口 —— ⛔ 一個「只進不出」的排序使用者不敢亂拖。
   清掉所有 viewOrder,回到「等級 → 死線 → 剩幾件」。 */
async function resetOrder() {
  if (!window.confirm("要把順序改回自動排嗎?\n\n（自動排 = 等級高的在前，同級死線近的在前）\n你拖過的順序會清掉，事情本身不會動。")) return;
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}/view-order`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order: [], reset: true }),
  });
  if (!r.ok) { toast("清不掉,重新整理再試"); return; }
  toast("已經改回自動排");
  await load();
}
