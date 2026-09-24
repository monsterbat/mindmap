/* mindmap 前端:mind-elixir 當引擎,正本是伺服器上的 JSON 檔。
   共編模型:操作後自動存檔;輪詢偵測外部(AI/另一視窗)修改,乾淨就自動重載,
   有未存改動就亮衝突橫幅,絕不靜默覆蓋。 */

const ZH_TW = {
  addChild: "插入子節點", addParent: "插入父節點", addSibling: "插入同級節點",
  removeNode: "刪除節點", focus: "專注", cancelFocus: "取消專注",
  moveUp: "上移", moveDown: "下移", link: "連接", linkBidirectional: "雙向連接",
  clickTips: "請點擊目標節點", summary: "摘要",
};

/* 沒指定圖名時開哪一張。⛔ 不能用「清單第一張」——那是照檔名排序,
   「_沙盒」的底線永遠排在中文前面,從任務板/行程表按「🧠 心智圖」回來就會掉進沙盒。 */
const DEFAULT_MAP = window.MM_MAP || "全局總覽圖";   // 伺服器說了算,見 /static/js/config.js

const $ = (id) => document.getElementById(id);
const nodeMenu = window["@mind-elixir/node-menu"];
// iife 全域是模組命名空間,建構子在 .default(statics 也掛在上面)
const ME = window.MindElixir.default || window.MindElixir;

let mind = null;
let currentName = null;
let baseMtime = null;     // 上次從伺服器讀到的檔案 mtime
let lastSavedJson = "";   // 上次存檔成功時的資料快照(比對用)
let saveTimer = null;
let saving = false;
let mapNames = []; // 給「連到另一張圖」的下拉用

function setStatus(text, cls) {
  const el = $("status");
  el.textContent = text;
  el.className = cls || "";
}

function showBanner(text) {
  $("banner-text").textContent = text;
  $("banner").hidden = false;
  document.body.classList.add("has-banner");
}

function hideBanner() {
  $("banner").hidden = true;
  document.body.classList.remove("has-banner");
}

function isDirty() {
  if (!mind) return false;
  return JSON.stringify(mind.getData()) !== lastSavedJson;
}

/* 便條樣式:寫成節點自己的 style(真實資料),不是前端自動套的隱形規則。
   ⛔ 2026-08-02 出過的問題:原本做成「topic 開頭是 📏 就自動套 class」,結果
   ①使用者只改個底色,字級/斜體/邊框跟著被改掉(使用者沒要求)
   ②裝飾跑在 3 秒計時器上,清掉幾秒後又自己套回來 → 「怎麼改都跳回去」
   ③介面上完全關不掉。**不要再做任何自動改外觀的隱形規則。看到什麼就是什麼。** */
const NOTE_STYLE = {
  fontStyle: "italic",
  fontSize: "12px",
  border: "1.5px dashed #c4b268",
  borderRadius: "8px",
  padding: "2px 8px",
};

/* ── 節點詳情:每個節點可以掛「📖 說明」與「🔨 要怎麼做」──────────────
   存在節點自己的 `detail: { explain, how }` 裡(正本 JSON 的一部分,AI 直接讀得到)。
   圖上只顯示標題 + 一個 📝 記號,內容在右側抽屜看與編輯。 */
let detailNodeId = null;

/* ⚠️ 一定要走 findEle().nodeObj:那才是「活的」節點物件。
   `mind.getData()` 回的是深拷貝,改它等於改到複製品,存檔時什麼都不會變
   (clearStyle 之所以沒事,是因為它把改過的整份餵回 refresh)。 */
/* ⚠️ findEle 找不到是 **throw**,不是回 null(節點被折疊起來、剛換過圖都會遇到)。
   一律走這個包裝,不然整個面板會停在半路。 */
function eleById(id) {
  try {
    return (mind && mind.findEle(id)) || null;
  } catch {
    return null;
  }
}

function nodeById(id) {
  const el = eleById(id);
  return (el && el.nodeObj) || null;
}

/* 用「資料」查節點,不看畫面 —— 折疊起來的節點在 DOM 裡根本不存在,
   但它還在資料裡,關聯清單照樣要顯示得出它的名字。 */
function nodeDataById(id) {
  if (!mind || !mind.getObjById || !mind.nodeData) return null;
  return mind.getObjById(id, mind.nodeData);
}

/* ── 節點徽章:📝(有詳情)+ 底下還沒做的事,依艾森豪等級分色計數 ─────────
   全部寫進一個 data-badges 屬性,CSS 用 content: attr(...) 畫出來。
   這是「把你填的資料畫出來」,不是改你設的樣式——內容變了記號就跟著變。 */
const PRIORITY = [
  { tag: "P1", dot: "🔴" },
  { tag: "P2", dot: "🟠" },
  { tag: "P3", dot: "🟡" },
  { tag: "P4", dot: "⚪" },
];
/* 狀態寫在標題最前面的圖示裡(圖上一眼看得到);只認這幾個,其他 emoji 不動。
   ⚠️ 節點與待辦共用這一組 —— 使用者 2026-08-02 反映:節點設得了狀態、待辦只有勾選框,
   「這樣子的操作邏輯是不是有點資訊落差」。標 todo 的那幾個待辦也能選。 */
const DONE = "✅";
const WAITING = "⏸️"; // 球不在你身上:分得出「等你」和「等別人」,每日排程報告才排得準
const STATUS = [
  { mark: "", label: "無" },
  { mark: "⏳", label: "待辦", todo: true },
  { mark: "🔜", label: "進行中", todo: true },
  { mark: WAITING, label: "等別人", todo: true },
  { mark: DONE, label: "完成", todo: true },
  { mark: "🎯", label: "目標" },
];
const TODO_STATUS = STATUS.filter((s) => s.todo);

/* 認出標題開頭的狀態圖示,回傳實際前綴長度(⏸️ 有沒有帶 U+FE0F 都要認得,
   不然使用者手打的版本會比對不到)。 */
function statusOf(topic) {
  const t = (topic || "").trim();
  for (const s of STATUS) {
    if (!s.mark) continue;
    const bare = s.mark.replace(/\uFE0F/g, "");
    if (t.startsWith(s.mark)) return { s, len: s.mark.length };
    if (t.startsWith(bare)) return { s, len: bare.length };
  }
  return null;
}

function isUndone(node) {
  const st = statusOf(node.topic);
  return !!(st && st.s.todo && st.s.mark !== DONE);
}

/* 待辦的狀態。舊資料只有 done:true/false,讀的時候就地換算,不動檔案;
   下次這個節點的待辦被編輯到,writeTodos 會寫成 st 順手汰換掉。 */
function todoStatus(t) {
  if (t.st) {
    // 正規化:AI 手寫 JSON 可能漏掉 U+FE0F,不校正下拉選單會對不到選項
    const bare = String(t.st).replace(/\uFE0F/g, "");
    const hit = TODO_STATUS.find((s) => s.mark.replace(/\uFE0F/g, "") === bare);
    return hit ? hit.mark : "⏳";
  }
  return t.done ? DONE : "⏳";
}

function todoDone(t) {
  return todoStatus(t) === DONE;
}

function todoWaiting(t) {
  return todoStatus(t) === WAITING;
}

function nodePriority(node) {
  const tags = node.tags || [];
  const p = PRIORITY.find((x) => tags.includes(x.tag));
  return p ? p.tag : "";
}

/* ⚠️ 舊格式:待辦曾經是節點的欄位 `detail.todos[]`。2026-08-03 起**待辦本身就是節點**
   (`node.todo === true`),因為使用者說躲在面板最下面「沒有這麼的直觀」——
   看不到就等於不存在,而且拉不出關聯線。這個函式只留給統計讀舊資料,不再有寫入端。 */
function todosOf(node) {
  return (node.detail && node.detail.todos) || [];
}

/* ── 待辦節點 ─────────────────────────────────────────────
   一般節點在講**結構**(這東西由哪些部分組成);待辦節點在講**有事情要做**。
   兩者共用全部欄位(狀態/等級/截止日/說明/關聯線),差別只在 `todo` 這個記號,
   以及由它衍生的外觀:文字藍色、連到它的那條線是藍虛線、可以整批開關。 */
function isTodoNode(node) {
  return !!(node && node.todo);
}

function todoChildren(node) {
  return (node.children || []).filter(isTodoNode);
}

/* 統計「還沒做的事」:①這個節點自己的待辦清單 ②子孫節點裡狀態不是 ✅ 的
   ③子孫節點各自的待辦清單。節點與待辦一套規則:**狀態不是 ✅ 就算沒做**。
   回傳 { counts:{P1:n,…,未分類:n}, waiting:n }(waiting=其中在等別人的件數) */
function rollup(node) {
  const counts = {};
  let waiting = 0;
  const add = (p) => {
    const key = p || "未分類";
    counts[key] = (counts[key] || 0) + 1;
  };
  const addTodos = (n) =>
    todosOf(n).forEach((t) => {
      if (todoDone(t)) return;
      add(t.p);
      if (todoWaiting(t)) waiting += 1;
    });
  addTodos(node);
  (node.children || []).forEach((child) =>
    walkNodes(child, (n) => {
      if (isUndone(n)) {
        add(nodePriority(n));
        const st = statusOf(n.topic);
        if (st && st.s.mark === WAITING) waiting += 1;
      }
      addTodos(n);
    }),
  );
  return { counts, waiting };
}

function rollupText(counts) {
  const parts = PRIORITY.filter((p) => counts[p.tag]).map((p) => p.dot + counts[p.tag]);
  if (counts["未分類"]) parts.push("⚫" + counts["未分類"]);
  return parts.join(" ");
}

/* 幫 P1–P4 的標籤加 data-p,CSS 才有辦法把它們換成紅橘黃(引擎預設全是同一種藍底,
   跟徽章的 🔴🟠🟡⚪ 對不起來)。CSS 選不到文字內容,只能在這裡標。
   ⚠️ 這跟被禁的「依內容自動改外觀」不同:①它畫的是「等級」這個系統欄位,不是猜使用者的意圖
   ②不寫進 node.style ③使用者自己設的顏色照樣蓋得過去。自由標籤維持原樣不碰。 */
function markPriorityTags(el) {
  el.querySelectorAll(".tags > span").forEach((span) => {
    const hit = PRIORITY.find((p) => p.tag === span.textContent.trim());
    if (hit) span.setAttribute("data-p", hit.tag);
    else span.removeAttribute("data-p");
  });
}

function hasDetail(node) {
  const d = node && node.detail;
  return !!(d && ((d.explain || "").trim() || (d.how || "").trim()));
}

/* ── 對應的專案資料夾(node.source)────────────────────────────
   使用者的需求(2026-08-03):「我在其他專案更新 TODO/DESIGN,會同步回饋到心智圖嗎?
   會不會又變成文件各自散亂、進度沒辦法對齊?」

   解法是**分層 + 拉**:心智圖記「有哪些事、多重要」,專案 TODO 記「下一步做什麼」,
   兩邊記的**不是同一件事**所以不會衝突;要看進度就即時去問伺服器。
   ⛔ **一個字都不寫進 JSON** —— 一複製就會 drift,而且會跟使用者自己的編輯打架。 */
const projectCache = {}; // source 路徑 → 伺服器算的摘要(純快取,重整就沒了)

function sourceOf(node) {
  return ((node && node.source) || "").trim();
}

async function refreshProjects() {
  if (!mind || !mind.nodeData) return;
  const paths = new Set();
  walkNodes(mind.nodeData, (n) => {
    if (sourceOf(n)) paths.add(sourceOf(n));
  });
  for (const p of paths) {
    try {
      projectCache[p] = await (await fetch(`/api/project?path=${encodeURIComponent(p)}`)).json();
    } catch {
      /* 讀不到就下一輪再說,不要讓整張圖停在這 */
    }
  }
  updateBadges();
  renderDrawer();
}

const SYNC_STALE_DAYS = 7;

function syncStale(st) {
  // 從沒對過帳(null)也算 stale —— 不然新掛的專案會安靜地一直不同步
  return !st || st.synced_days === null || st.synced_days > SYNC_STALE_DAYS;
}

function projectBadge(node) {
  const st = projectCache[sourceOf(node)];
  if (!st || !st.exists) return "";
  const core = st.unreadable ? "⟳?" : st.open ? "⟳" + st.open : "";
  // ⚠️ = 太久沒跟心智圖對帳。AI 忘了跑,使用者掃一眼圖就會發現。
  return syncStale(st) ? (core || "⟳") + "⚠️" : core;
}

function renderSource(node) {
  const input = $("src-input");
  const box = $("src-status");
  input.value = sourceOf(node);
  input.disabled = !node;
  box.textContent = "";
  box.className = "";
  const st = node && projectCache[sourceOf(node)];
  if (!node || !sourceOf(node)) return;
  if (!st) {
    box.textContent = "讀取中…";
    return;
  }
  if (!st.exists) {
    box.textContent = "⚠️ 找不到這個資料夾";
    box.className = "bad";
    return;
  }
  if (st.unreadable) {
    box.textContent = "⚠️ 這個專案的 TODO.md 沒用 `- [ ] / - [x]` 格式,數不出進度";
    box.className = "bad";
    return;
  }

  const bits = [`${st.open} 件未完 / ${st.done} 件完成`];
  if (st.waiting) bits.push(`其中 ${st.waiting} 件等你`);
  bits.push(
    st.synced_days === null
      ? "⚠️ 還沒跟這個專案對過帳"
      : st.synced_days === 0
        ? "今天對過帳"
        : `對帳:${st.synced_days} 天前`,
  );
  if (st.last) bits.push(`最後更新:${st.last}`);
  const line = document.createElement("div");
  line.textContent = bits.join(" · ");
  if (syncStale(st)) line.className = "warn";
  box.appendChild(line);

  /* 這個專案自己的待辦,連內容一起列出來。
     使用者 2026-08-08:「我所有專案都是直接看這個心智圖」——只有數字的話使用者得離開圖去翻檔案。
     ⚠️ 仍然是「拉」:每分鐘即時去讀那個 TODO.md,不寫進圖裡,所以不會 drift。
     ⛔ 也刻意不長成子節點:專案有上百條,長進圖會把圖淹掉。 */
  if (st.items && st.items.length) {
    const list = document.createElement("ul");
    list.className = "src-items";
    st.items.forEach((t) => {
      const li = document.createElement("li");
      li.textContent = t;
      if (t.includes("⏳")) li.className = "waiting";
      list.appendChild(li);
    });
    box.appendChild(list);
    if (st.open > st.items.length) {
      const more = document.createElement("div");
      more.className = "src-more";
      more.textContent = `…還有 ${st.open - st.items.length} 條,在那個專案的 TODO.md 裡`;
      box.appendChild(more);
    }
  }
}

function setSource(value) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  const v = (value || "").trim().replace(/^\/+|\/+$/g, "");
  if (v) node.source = v;
  else delete node.source;
  scheduleSave();
  refreshProjects();
}

/* ── 截止日(detail.due,ISO `YYYY-MM-DD`)────────────────────────────
   使用者的需求(2026-08-03):「這些地方都差了一個時間截止日」。心智圖原本沒有任何日期,
   所以永遠算不出「哪件事快到期」——每日排程報告也就掃不到。
   ⚠️ 沒有明確死線就不填,不逼使用者編假日期(使用者原本的習慣)。
   臨界值照 Workspace 的判準:**剩 ≤3 天 = 緊急**;4–7 天先給個提醒。 */
function dueOf(node) {
  const s = ((node && node.detail && node.detail.due) || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : "";
}

/* ── 排程地基:effort(要花多久)與 window(只能在哪做)─────────────
   甘特圖/自動排程要的三個欄位,due 已有,這是另外兩個。
   window 是 2026-08-04 的修正:有些事只有人在某個地點時才做得了,但條件只寫在
   說明散文裡 → 排程照樣排在人離開之後。條件要成為**欄位**,機器才躲得開。 */
/* 要花多久。使用者 2026-08-08:「只有一小時/四小時/一整天太少了」→ 八檔。
   `hours` 是給排程與甘特圖算的:一天以使用者的實際容量 10 小時計(專案規則文件裡
   定的),一週以 5 個工作天算,不是 24×7。
   ⚠️ 值就是標籤本身(不再用 小/中/大):資料自己看得懂,免得日後要對照表。 */
const EFFORTS = [
  { v: "1h", hours: 1 },
  { v: "2h", hours: 2 },
  { v: "4h", hours: 4 },
  { v: "8h", hours: 8 },
  { v: "12h", hours: 12 },
  { v: "1天", hours: 10 },
  { v: "2天", hours: 20 },
  { v: "1週", hours: 50 },
];

function effortOf(node) {
  const s = ((node && node.detail && node.detail.effort) || "").trim();
  return EFFORTS.some((e) => e.v === s) ? s : "";
}

/* 不能比這天早做。2026-08-11 加:排程本來只認死線,於是把「8/13 當天去機關
   窗口」排到 8/12(合約還沒到期)、把「款項入帳對帳」排到錢還沒進來的日子。
   ⚠️ 這跟 window 不一樣:window 是「條件成不成立只有人知道」→ 交回給使用者自己挑;
   earliest 是「日期上就算得出來」→ 排程自己避開。 */
function earliestOf(node) {
  const s = ((node && node.detail && node.detail.earliest) || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : "";
}

function windowOf(node) {
  return ((node && node.detail && node.detail.window) || "").trim();
}

/* 回傳距今天還剩幾天(負數=已過期)。用當地日期的 00:00 相減,
   不用 Date.now() 直接減 —— 不然「今天下午」跟「今天早上」會算出不同天數。 */
function daysLeft(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const target = new Date(y, m - 1, d);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target - today) / 86400000);
}

function dueState(iso) {
  if (!iso) return "";
  const n = daysLeft(iso);
  if (n <= 3) return "soon"; // 含過期:兩者都要立刻處理
  if (n <= 7) return "near";
  return "far";
}

function dueBadge(iso) {
  if (!iso) return "";
  const n = daysLeft(iso);
  const [, m, d] = iso.split("-");
  const md = `${Number(m)}/${Number(d)}`;
  if (n < 0) return `⏰${md} 逾期${-n}天`;
  if (n === 0) return `⏰${md} 今天`;
  return `⏰${md}`;
}

function updateBadges() {
  if (!mind) return;
  let changed = false;
  document.querySelectorAll("me-tpc").forEach((el) => {
    const node = el.nodeObj;
    if (!node) return;
    markPriorityTags(el);
    // 待辦節點:文字變藍、線變藍虛線、可以整批藏起來(全部由這個屬性驅動)
    if (isTodoNode(node)) el.setAttribute("data-todo", "1");
    else el.removeAttribute("data-todo");
    // AI 動過的節點先圈起來,使用者檢查完自己按「看過了」拆掉(見 clearAiMark)
    if (node.aiEdited) el.setAttribute("data-ai", "1");
    else el.removeAttribute("data-ai");
    // 圖層屬性:✅ 開頭=已完成層;kind=sop/infra 各自一層(hide-* 的 CSS 靠這些認人)
    const st_ = statusOf(node.topic);
    if (st_ && st_.s.mark === DONE) el.setAttribute("data-done", "1");
    else el.removeAttribute("data-done");
    if (["sop", "infra", "tool"].includes(node.kind)) el.setAttribute("data-kind", node.kind);
    else el.removeAttribute("data-kind");
    // 前面的紅牌 = 這個節點連著幾條關聯線;後面 = 有詳情 + 底下還沒做的事。
    // 兩邊刻意分開:前面講「這個節點的身分」,後面講「底下的工作量」。
    // 使用者 2026-08-03 反映:原本混在後面用 🔗n「有點太不顯眼」→ 改成紅底,跟關聯線同色。
    const links = relationCount(node.id);
    const rel = links ? "⇄" + links : "";
    // ⛔ 做完的事不准再喊「逾期」—— 使用者 2026-08-11 回報:兩件標了 ✅ 的還是紅框
    //    「逾期3天」,整排紅色看起來像什麼都沒做,而那正是使用者最焦慮的畫面。
    const iso = (st_ && st_.s.mark === DONE) ? "" : dueOf(node);
    // ⚠️ 比對用的值必須跟「真的會寫進 DOM 的值」一模一樣。
    // 曾經出過的問題:dueState 對遠期回 "far",但 far 不寫屬性 → 比對永遠不相等 → 每次都判定「有變」
    // → 呼叫 linkDiv → 觸發 updateBadges → 無限重畫(實測 6 秒 863 次)。
    const dueMark = ["soon", "near"].includes(dueState(iso)) ? dueState(iso) : "";
    // 📍窗口要印在圖上:它是「過了就做不了」的條件,藏在面板裡就會再出一次
    // 「排程排在人已經離開那個地點之後」的問題(2026-08-04)。
    const win = windowOf(node);
    const badges = [
      dueBadge(iso),
      win ? "📍" + (win.length > 8 ? win.slice(0, 8) + "…" : win) : "",
      hasDetail(node) ? "📝" : "",
      projectBadge(node),
      rollupText(rollup(node).counts),
    ]
      .filter(Boolean)
      .join(" ");
    if (
      (el.getAttribute("data-badges") || "") === badges &&
      (el.getAttribute("data-rel") || "") === rel &&
      (el.getAttribute("data-due") || "") === dueMark
    )
      return;
    changed = true;
    if (badges) el.setAttribute("data-badges", badges);
    else el.removeAttribute("data-badges");
    if (rel) el.setAttribute("data-rel", rel);
    else el.removeAttribute("data-rel");
    // 快到期的整個節點亮框 —— 小小的文字掃不到,框才掃得到
    if (dueMark) el.setAttribute("data-due", dueMark);
    else el.removeAttribute("data-due");
  });
  // 徽章會把節點撐寬,連線是照舊寬度畫的 → 要重畫,不然線跟節點對不上。
  // (只在真的有變時做;linkDiv 會再觸發本函式,那次沒變就停,不會無限迴圈)
  if (changed) mind.linkDiv();
  updateAiBtn(); // 圈圈數是資料算的,跟上面的 DOM 有沒有變無關,一律更新
}

/* 連到待辦節點的那條樹狀線也要看得出來。引擎本身沒給線任何識別,
   是 vendor 補了 `data-nodeid`(見 static/vendor/PATCHES.md)才做得到。
   ⚠️ 每次 linkDiv 都會把 lines 整個重畫,所以要跟著重跑。 */
function applyTodoLines() {
  if (!mind) return;
  document.querySelectorAll("path[data-nodeid]").forEach((p) => {
    const n = nodeDataById(p.dataset.nodeid);
    p.classList.toggle("todo-line", isTodoNode(n));
    // 圖層藏節點時,接到它的樹狀線也要跟著藏(不然留一截接到空氣的線)
    const st = n && statusOf(n.topic);
    p.classList.toggle("done-line", !!(st && st.s.mark === DONE));
    p.classList.toggle("sop-line", !!(n && n.kind === "sop"));
    p.classList.toggle("infra-line", !!(n && n.kind === "infra"));
    p.classList.toggle("tool-line", !!(n && n.kind === "tool"));
  });
}

/* ── 圖層:一張圖裝下任務+腦袋架構+電腦架構,靠開關分流 ─────────────
   使用者的需求(2026-08-04):「拆開我要分三個地方看會更混亂,不如放一起做好分類」,
   但開關不能散裝——「開到最後不知道建立了什麼、哪個新哪個舊」。
   所以統一成一個面板:每層一個勾,面板一眼看完現在藏了什麼。純顯示層,資料不動。 */
const LAYERS = [
  { key: "todos", label: "☑ 待辦節點", cls: "hide-todos", hint: "藍字藍虛線的那些" },
  { key: "done", label: "✅ 已完成", cls: "hide-done", hint: "標題是 ✅ 開頭的(含其子樹)" },
  { key: "sop", label: "📐 規則・工具", cls: "hide-sop", hint: "指向正本檔的路標(紫)與 skill(黃)" },
  { key: "infra", label: "🖥️ 設施・架構", cls: "hide-infra", hint: "機器/系統架構那一掛" },
  { key: "ai", label: "⭕ AI 圈圈", cls: "hide-ai", hint: "只藏紫圈,節點還在" },
];

function layerOn(key) {
  // 舊的單一待辦開關(mm-todos)搬進圖層系統,設定值直接沿用
  const legacy = key === "todos" ? localStorage.getItem("mm-todos") : null;
  return (localStorage.getItem("mm-layer-" + key) ?? legacy) !== "0";
}

function setLayer(key, on) {
  const layer = LAYERS.find((l) => l.key === key);
  if (!layer) return;
  document.body.classList.toggle(layer.cls, !on);
  localStorage.setItem("mm-layer-" + key, on ? "1" : "0");
  renderLayerPanel();
  if (mind && key !== "ai") {
    mind.linkDiv(); // 版面縮了,線要重算
    applyTodoLines();
    // ⛔ 不置中:開關圖層時人正在看某一塊,把圖拉回中間等於叫使用者重找一次
  }
}

function renderLayerPanel() {
  const panel = $("layer-panel");
  panel.innerHTML = "";
  LAYERS.forEach((l) => {
    const row = document.createElement("label");
    row.className = "layer-row";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = layerOn(l.key);
    cb.onchange = () => setLayer(l.key, cb.checked);
    const span = document.createElement("span");
    span.textContent = l.label;
    const small = document.createElement("small");
    small.textContent = l.hint;
    row.append(cb, span, small);
    panel.appendChild(row);
  });
  // 按鈕上直接標「藏了幾層」——不點開也知道現在不是全貌
  const hidden = LAYERS.filter((l) => !layerOn(l.key)).length;
  const btn = $("btn-layers");
  btn.textContent = hidden ? `🗂 圖層（藏${hidden}）` : "🗂 圖層";
  btn.classList.toggle("off", hidden > 0);
}

/* 跳去某個節點之前,把會蓋住它的圖層打開 —— 搜尋到了卻看不到,等於沒搜到。
   只開「這個節點與其祖先」需要的層,不動其他層。 */
function revealLayersFor(id) {
  const need = new Set();
  for (let n = nodeDataById(id); n; n = n.parent) {
    if (isTodoNode(n)) need.add("todos");
    const st = statusOf(n.topic);
    if (st && st.s.mark === DONE) need.add("done");
    if (n.kind === "sop" || n.kind === "tool") need.add("sop");
    if (n.kind === "infra") need.add("infra");
  }
  need.forEach((key) => {
    if (!layerOn(key)) setLayer(key, true);
  });
}

/* 把圖重新置中。⚠️ 只在「剛載入一張圖」時用。
   使用者反映(2026-08-07):「我點詳情或其他東西,原本在看的位置就跳回正中間,很煩」——
   置中對「正在看某個角落」的人是破壞性的,他得重新找回剛才的位置。
   所以版面變動(開面板/開圖層/多一條 bar)一律不置中,只在必要時最小幅度推(nudgeIntoView)。
   要手動置中:引擎原生 F1。 */
function recenter() {
  if (mind) requestAnimationFrame(() => mind.toCenter());
}

/* ── 記住/還原目前的視角(平移 + 縮放)──────────────────────────────
   使用者的需求(2026-08-11):「心智圖只要從行程那邊有改動東西,他就會跳回到正中間,
   能不能讓他不要跳回去啊?」

   原因:偵測到外部修改會整張重載,而重載 = 重新 `mind.init()` + `toCenter()`。
   使用者在 300 個節點的圖上找到位置、正在看某一支,結果一被 /day 或排程的程式改一下
   就彈回正中間 —— 等於要重找一次。
   ⚠️ 平移狀態在 map 的 transform(translate3d + scale),不是捲軸;
   縮放另外記在 `mind.scaleVal`,兩個都要還原,只還原一個會縮放跳掉。 */
function viewState() {
  const map = mind && mind.map;
  return map ? { transform: map.style.transform || "", scale: mind.scaleVal } : null;
}

function applyView(view) {
  const map = mind && mind.map;
  if (!map || !view || !view.transform) return recenter();
  requestAnimationFrame(() => {
    if (view.scale) mind.scaleVal = view.scale;
    map.style.transform = view.transform;
  });
}

/* 平移目前的視角。引擎把平移狀態放在 map 的 transform(translate3d + scale),
   直接改它就等於捲動,不會動到資料也不會重排。 */
function panBy(dx, dy) {
  const map = mind && mind.map;
  if (!map || (!dx && !dy)) return;
  const m = /translate3d\(([-\d.]+)px,\s*([-\d.]+)px/.exec(map.style.transform || "");
  const x = m ? parseFloat(m[1]) : 0;
  const y = m ? parseFloat(m[2]) : 0;
  map.style.transform = `translate3d(${x + dx}px, ${y + dy}px, 0) scale(${mind.scaleVal})`;
}

/* 節點被擠出畫面(例如詳情面板蓋住它)才推,而且只推剛好看得到的距離。
   看得到就完全不動——「我沒叫它動的時候它就不該動」。 */
function nudgeIntoView(el) {
  if (!mind || !el) return;
  const pad = 24;
  const c = mind.container.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  let dx = 0;
  let dy = 0;
  if (r.right > c.right - pad) dx = c.right - pad - r.right;
  if (r.left + dx < c.left + pad) dx = c.left + pad - r.left;
  if (r.bottom > c.bottom - pad) dy = c.bottom - pad - r.bottom;
  if (r.top + dy < c.top + pad) dy = c.top + pad - r.top;
  panBy(dx, dy);
}

function openDrawer(show) {
  $("drawer").hidden = !show;
  localStorage.setItem("mm-drawer", show ? "1" : "0");
  if (show) renderDrawer();
  // 畫布寬度變了,但視角不動;只有「選著的節點被面板蓋住」才推回來
  if (show)
    requestAnimationFrame(() => {
      const el = detailNodeId && eleById(detailNodeId);
      if (el) nudgeIntoView(el);
    });
}

/* 外觀模式:預設關。關著的時候點節點只出詳情,不會跳出顏色/字級面板
   (使用者 2026-08-02:「點一下同時跳出詳情跟一堆設定,很不直覺」)。 */
function setStyleMode(on) {
  document.body.classList.toggle("style-mode", on);
  localStorage.setItem("mm-stylemode", on ? "1" : "0");
  $("btn-style-mode").classList.toggle("on", on);
}

/* ── 關聯線(紅線):資料只有一份=arrows,這裡只管「怎麼顯示」───────────
   三檔循環:全開 / 聚焦(只亮跟選取節點有關的) / 全關。純顯示層,不動資料。

   ⚠️ 為什麼不另外做一套「連結」欄位:使用者 2026-08-03 反映「關聯線拉來拉去會非常的亂,
   有沒有辦法用連結的方式」。線亂的是**畫法**不是資料——同一份 from/to 換個顯示
   方式就解決了。真的開第二套欄位,同一個關係會記在兩個地方,遲早對不起來,
   而且就不能用引擎「拉一下就連好」的原生操作了。 */
const ARROW_MODES = ["all", "focus", "off"];
const ARROW_MODE_UI = {
  all: { text: "🔗 線：全開", title: "所有關聯線都畫出來。點一下切到「聚焦」" },
  focus: { text: "🔗 線：聚焦", title: "只畫跟目前選取節點有關的線。點一下切到「全關」" },
  off: { text: "🔗 線：全關", title: "關聯線全部藏起來（資料還在）。點一下切回「全開」" },
};
let arrowMode = "focus";

function setArrowMode(mode) {
  arrowMode = ARROW_MODES.includes(mode) ? mode : "focus";
  localStorage.setItem("mm-arrow-mode", arrowMode);
  document.body.classList.toggle("arrows-focus", arrowMode === "focus");
  document.body.classList.toggle("arrows-off", arrowMode === "off");
  const btn = $("btn-arrows");
  btn.textContent = ARROW_MODE_UI[arrowMode].text;
  btn.title = ARROW_MODE_UI[arrowMode].title;
  btn.classList.toggle("off", arrowMode === "off");
  btn.classList.toggle("focus", arrowMode === "focus");
  applyArrowFocus();
}

function cycleArrowMode() {
  setArrowMode(ARROW_MODES[(ARROW_MODES.indexOf(arrowMode) + 1) % ARROW_MODES.length]);
}

function allArrows() {
  return (mind && mind.arrows) || [];
}

function relationsOf(id) {
  const arrows = allArrows();
  return {
    incoming: arrows.filter((a) => a.to === id), // ← 誰餵給我
    outgoing: arrows.filter((a) => a.from === id), // → 我餵給誰
  };
}

function relationCount(id) {
  return allArrows().filter((a) => a.from === id || a.to === id).length;
}

/* 聚焦模式:把跟選取節點有關的線標成 .arrow-on,其餘交給 CSS 藏起來。
   ⚠️ 每次 linkDiv 都會把 arrowSvg 整個重畫(引擎的 renderArrow 會清空 innerHTML),
   所以這函式要跟著 linkDiv 與選取事件重跑,不能只在切模式時做一次。 */
function applyArrowFocus() {
  if (!mind) return;
  const on = new Set();
  if (arrowMode === "focus") {
    const ids = selectedIds();
    allArrows().forEach((a) => {
      if (ids.includes(a.from) || ids.includes(a.to)) on.add(a.id);
    });
    // 正在編輯中的那一條一定要留著。引擎在「選取一條線」時會先 clearSelection()
    // 把節點的選取拿掉,不特別處理的話:①剛拉好的新線馬上消失 ②想點線拉彎,
    // 線會在手指底下不見。linkController 顯示中 = 現在確實有一條線被選著。
    const editing = mind.currentArrow;
    if (editing && mind.linkController && mind.linkController.style.display !== "none") {
      on.add(editing.dataset.linkid);
    }
  }
  document.querySelectorAll(".topiclinks g[data-linkid]").forEach((g) => {
    g.classList.toggle("arrow-on", on.has(g.dataset.linkid));
  });
  document.querySelectorAll('.svg-label[data-type="arrow"]').forEach((el) => {
    // 標籤掛的是 data-svg-id="a-<arrowId>"(引擎的命名),去掉前綴才對得上
    el.classList.toggle("arrow-on", on.has((el.dataset.svgId || "").replace(/^a-/, "")));
  });
}

/* ── 連到另一張圖(節點的 hyperLink 欄位)────────────────────────
   引擎只會在標題後面畫一個很小的 🔗,而且介面上設不了(只有改 JSON 一途)。
   使用者反映(2026-08-03):「我哪知道要點後面的🔗」→ ①面板給下拉可以自己設 ②整個節點都點得下去。 */
function renderLinkSelect(node) {
  const sel = $("link-select");
  const cur = (node && node.hyperLink) || "";
  sel.innerHTML = "";
  [{ v: "", t: "（不連結）" }]
    .concat(mapNames.map((n) => ({ v: `/#${n}`, t: `↗ ${n}` })))
    .forEach(({ v, t }) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = t;
      sel.appendChild(o);
    });
  // 連到「不在清單裡」的網址(外部連結)也要顯示得出來,不然一選就被洗掉
  if (cur && !mapNames.some((n) => `/#${n}` === cur)) {
    const o = document.createElement("option");
    o.value = cur;
    o.textContent = `↗ ${cur}`;
    sel.appendChild(o);
  }
  sel.value = cur;
  sel.disabled = !node;
}

function setHyperLink(url) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  if (url) {
    mind.reshapeNode(mind.findEle(node.id), { hyperLink: url });
  } else {
    // reshapeNode 是 Object.assign,清不掉既有欄位 → 動資料 + 整張重繪(跟 clearStyle 同一招)
    delete node.hyperLink;
    mind.refresh(mind.getData());
    const again = mind.findEle(node.id);
    if (again) mind.selectNode(again);
  }
  updateBadges();
  afterContentChange();
}

/* `/#圖名` 或 `#圖名` = 同一頁換圖(hashchange 會去 openMap);其餘當外部網址開新分頁。
   換圖前先存,不然剛打的字會被吃掉。 */
async function followLink(url) {
  const m = /^\/?#(.+)$/.exec(url);
  if (!m) {
    window.open(url, "_blank", "noopener");
    return;
  }
  if (isDirty()) await saveMap();
  const name = decodeURIComponent(m[1]);
  if (name === currentName) return;
  location.hash = encodeURIComponent(name);
}

/* 跳到關聯的另一端:選取它 + 捲到看得見 + 閃一下。
   聚焦模式下對方自己的線會跟著亮出來 → 可以一路點著把整條資料流走完
   (例子:儀表板 → 某專案的資料分析 → 日報)。 */
function jumpTo(id) {
  const obj = nodeDataById(id);
  if (!obj) {
    setStatus("那個節點已經不在圖上了", "dirty");
    return;
  }
  // 對方藏在折疊起來的分支裡 → 由上而下把它的祖先展開,不然畫面上根本沒有那個元素
  const collapsed = [];
  for (let p = obj.parent; p; p = p.parent) if (p.expanded === false) collapsed.push(p);
  collapsed.reverse().forEach((n) => {
    const pe = eleById(n.id);
    if (pe) mind.expandNode(pe, true);
  });
  const el = eleById(id);
  if (!el) {
    setStatus("那個節點被收起來了,先展開它的上層", "dirty");
    return;
  }
  mind.selectNode(el, true);
  renderDrawer();
  applyArrowFocus();
  el.classList.remove("mm-jumped");
  void el.offsetWidth; // 強制重排,不然連跳同一個節點兩次不會再閃
  el.classList.add("mm-jumped");
  setTimeout(() => el.classList.remove("mm-jumped"), 1400);
}

/* ── 就地改關聯線(不必重拉)────────────────────────────────
   使用者 2026-08-03 反映:方向訂錯要全圖對調,「一個一個去重拉很麻煩」。
   三個操作都走引擎的 reshapeArrow:它會就地重畫、記進 undo,並 fire operation
   讓自動存檔接手。⚠️ 它內部用 findEle,對方被折疊起來會 throw,所以要接住。 */
function reshapeArrow_(a, patch) {
  try {
    mind.reshapeArrow(a, patch);
  } catch {
    Object.assign(a, patch); // 畫不出來就先把資料改掉,再整張重畫
    mind.refresh(mind.getData());
    const back = eleById(detailNodeId);
    if (back) mind.selectNode(back);
  }
  scheduleSave();
}

function setArrowLabel(a, text) {
  reshapeArrow_(a, { label: text });
}

/* 調轉:from/to 對調。**兩端的彎度也要跟著換邊**,不然線會扭成奇怪的形狀
   (delta1 是 from 那端的控制點,delta2 是 to 那端的)。 */
function flipArrow(a) {
  reshapeArrow_(a, { from: a.to, to: a.from, delta1: a.delta2, delta2: a.delta1 });
  renderRelations(nodeById(detailNodeId));
  applyArrowFocus();
}

function toggleBidirectional(a) {
  if (a.bidirectional) {
    delete a.bidirectional; // Object.assign 清不掉欄位,只能先動資料再讓它重畫
    reshapeArrow_(a, {});
  } else {
    reshapeArrow_(a, { bidirectional: true });
  }
  renderRelations(nodeById(detailNodeId));
  applyArrowFocus();
}

/* 關聯清單:← 進來的、⇄ 雙向、→ 出去的,各自可以點過去,也可以就地改。
   線關掉的時候這裡就是唯一的入口,所以不能只畫在圖上。 */
function renderRelations(node) {
  const list = $("rel-list");
  list.innerHTML = "";
  const id = node && node.id;
  /* ⚠️ 不能只看 from/to 就判成單向:引擎的「雙向連接」存的是 arrow 的 `bidirectional:true`,
     兩端都該標 ⇄。少判這一項的話,雙向線在面板上會變成一邊「→ 出去」一邊「← 進來」,
     看起來像兩條方向相反的單向線。 */
  const rows = (id ? allArrows() : [])
    .filter((a) => a.from === id || a.to === id)
    .map((a) => {
      const out = a.from === id;
      return { dir: a.bidirectional ? "⇄" : out ? "→" : "←", other: out ? a.to : a.from, a };
    })
    .sort((x, y) => "←⇄→".indexOf(x.dir) - "←⇄→".indexOf(y.dir)); // 進來的 → 雙向 → 出去的
  $("rel-field").hidden = !rows.length;
  rows.forEach(({ dir, other, a }) => {
    const target = nodeDataById(other); // 用資料查:對方被折疊起來時名字也要顯示得出來
    const row = document.createElement("div");
    row.className = "rel-row";

    const go = document.createElement("button");
    go.type = "button";
    go.className = "rel-go";
    go.disabled = !target;
    const d = document.createElement("span");
    d.className = "rel-dir";
    d.textContent = dir;
    const name = document.createElement("span");
    name.className = "rel-name";
    name.textContent = target ? target.topic : "（對方節點已不在圖上）";
    go.append(d, name);
    go.title = target ? `跳到「${target.topic}」` : "這條線指向的節點已經被刪掉了";
    go.onclick = () => jumpTo(other);

    const tools = document.createElement("div");
    tools.className = "rel-tools";

    const lab = document.createElement("input");
    lab.type = "text";
    lab.className = "rel-label";
    lab.value = a.label || "";
    lab.placeholder = "這條線在傳什麼…";
    lab.title = "線上顯示的文字。寫動詞才讀得出方向(餵給／回傳／彙整後進)";
    lab.oninput = () => setArrowLabel(a, lab.value);

    const flip = document.createElement("button");
    flip.type = "button";
    flip.className = "rel-btn";
    flip.textContent = "⇅";
    flip.disabled = !!a.bidirectional; // 雙向線沒有方向可調
    flip.title = a.bidirectional ? "雙向線沒有方向可以調" : "調轉方向(誰指向誰對調)";
    flip.onclick = () => flipArrow(a);

    const both = document.createElement("button");
    both.type = "button";
    both.className = "rel-btn" + (a.bidirectional ? " on" : "");
    both.textContent = "⇄";
    both.title = a.bidirectional
      ? "現在是雙向,點一下改回單向"
      : "改成雙向(兩邊互相給「同一種東西」時才用;送的是不同東西就拉兩條單向)";
    both.onclick = () => toggleBidirectional(a);

    tools.append(lab, flip, both);
    row.append(go, tools);
    list.appendChild(row);
  });
}

/* 「進階」預設收起,但節點已經設了專案資料夾或外部連結時要自動展開 ——
   把「已經有東西的欄位」藏起來,人會以為那個設定不見了。 */
function syncMoreOpen(node) {
  const more = $("drawer-more");
  if (more) more.open = !!(node && (sourceOf(node) || node.hyperLink));
}

function renderDrawer() {
  if ($("drawer").hidden) return;
  const ids = selectedIds();
  detailNodeId = ids.length === 1 ? ids[0] : null;
  const node = detailNodeId ? nodeById(detailNodeId) : null;
  $("drawer-title").textContent = node
    ? node.topic
    : ids.length > 1
      ? "（一次只能編輯一個節點）"
      : "（點一個節點看它的詳情）";

  renderRollupLine(node);
  const d = (node && node.detail) || {};
  $("detail-explain").value = d.explain || "";
  $("detail-explain").disabled = !node;
  $("detail-due").value = dueOf(node);
  $("detail-due").disabled = !node;
  $("detail-earliest").value = earliestOf(node);
  $("detail-earliest").disabled = !node;
  $("earliest-clear").disabled = !earliestOf(node);
  $("due-clear").disabled = !node || !dueOf(node);
  renderEffortChips(node);
  $("window-input").value = windowOf(node);
  $("window-input").disabled = !node;
  $("todo-add").disabled = !node;
  renderChips(node);
  renderTags(node);
  renderLinkSelect(node);
  renderRelations(node);
  renderKind(node);
  renderSource(node);
  syncMoreOpen(node);
  renderAiRow(node);
  $("tag-input").disabled = !node;
  $("tag-input").value = "";
}

/* ── 這個節點本身的狀態與等級 ───────────────────────────────
   狀態=標題最前面的圖示(圖上看得到);等級=tags 裡的 P1–P4(節點下方的小標籤)。
   兩者都是「內容」,所以放在詳情面板,不藏在外觀面板裡。 */
function renderChips(node) {
  const isTodo = !!(node && isTodoNode(node));
  // 待辦:四個進度狀態(⛔ 沒有「無」——待辦一定看得出處在哪一階段,lint 也這樣查)
  // 項目:只有「無 / 🎯 目標」。🎯 本來就是給節點用的,不是任務狀態
  const marks = isTodo ? ["⏳", "🔜", WAITING, DONE] : ["", "🎯"];
  const hint = $("self-hint");
  if (hint) hint.textContent = isTodo ? "狀態＋等級＋標籤" : "項目不設等級，標籤照用";
  const found = node ? statusOf(node.topic) : null;
  const cur = found ? found.s.mark : "";
  $("chips-status").innerHTML = "";
  STATUS.filter((s) => marks.includes(s.mark)).forEach((s) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (cur === s.mark ? " on" : "");
    b.textContent = s.mark ? `${s.mark} ${s.label}` : s.label;
    b.disabled = !node;
    b.onclick = () => setStatus_(s.mark);
    $("chips-status").appendChild(b);
  });

  // 等級只屬於「要做的事」。項目也能設的話,P1 就失去意義(2026-08-07 才清掉 12 個)
  const curP = node ? nodePriority(node) : "";
  $("chips-priority").hidden = !isTodo;
  $("chips-priority").innerHTML = "";
  if (isTodo) {
    [{ tag: "", dot: "", name: "沒等級" }]
      .concat(PRIORITY.map((p) => ({ ...p, name: p.tag })))
      .forEach((p) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "chip" + (curP === p.tag ? " on" : "");
        b.textContent = p.dot ? `${p.dot} ${p.name}` : p.name;
        b.disabled = !node;
        b.onclick = () => setPriority(p.tag);
        $("chips-priority").appendChild(b);
      });
  }
}

function setStatus_(mark) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  let topic = (node.topic || "").trim();
  const old = statusOf(topic);
  if (old) topic = topic.slice(old.len).trim();
  mind.reshapeNode(mind.findEle(node.id), { topic: (mark ? mark + " " : "") + topic });
  afterContentChange();
}

/* 自由標籤(P1–P4 以外的),例如「新需求」「等回覆」。
   ⚠️ 一定要給刪除的地方:2026-08-02 使用者就是被自動加上去的「新需求」卡住,
   圖上看得到卻沒有任何介面能拿掉。 */
function freeTags(node) {
  return (node.tags || []).filter((t) => !PRIORITY.some((p) => p.tag === t));
}

function renderTags(node) {
  const box = $("tag-list");
  box.innerHTML = "";
  if (!node) return;
  freeTags(node).forEach((t) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip tag";
    b.textContent = t + " ✕";
    b.title = "點一下移除這個標籤";
    b.onclick = () => writeTags(node, freeTags(node).filter((x) => x !== t));
    box.appendChild(b);
  });
}

function writeTags(node, free) {
  const p = nodePriority(node);
  const tags = (p ? [p] : []).concat(free);
  mind.reshapeNode(mind.findEle(node.id), { tags: tags.length ? tags : undefined });
  if (!tags.length) delete node.tags;
  renderTags(node);
  afterContentChange();
}

function addTag(text) {
  const node = nodeById(detailNodeId);
  const name = (text || "").trim();
  if (!node || !name) return;
  if (PRIORITY.some((p) => p.tag === name)) {
    setStatus("P1–P4 請用上面那排按鈕設定", "dirty");
    return;
  }
  if (freeTags(node).includes(name)) return;
  writeTags(node, freeTags(node).concat([name]));
}

function setPriority(tag) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  const free = freeTags(node);
  const tags = tag ? [tag, ...free] : free;
  mind.reshapeNode(mind.findEle(node.id), { tags: tags.length ? tags : undefined });
  if (!tags.length) delete node.tags;
  afterContentChange();
}

/* 新增一個待辦子節點。快捷鍵 **Shift+Tab** —— Tab 是「加子節點(結構)」,
   加個修飾鍵就是「加子節點(待辦)」,同一個手勢好記。
   ⚠️ 傳 nodeObj 進 addChild 引擎就不會自己開編輯框,所以要自己叫 editTopic,
   不然新節點會頂著「新待辦」三個字等你去雙擊。 */
function addTodoChild() {
  const id = selectedIds()[0];
  const el = id && eleById(id);
  if (!el) {
    setStatus("先點一個節點,再按 Shift+Tab 加待辦", "dirty");
    return;
  }
  const obj = mind.generateNewObj();
  obj.topic = "⏳ 新待辦";
  obj.todo = true;
  mind.addChild(el, obj);
  const created = eleById(obj.id);
  if (!created) return;
  mind.selectNode(created, true);
  mind.editTopic(created);
  updateBadges();
  applyTodoLines();
  scheduleSave();
}

/* 把既有節點在 結構/待辦/SOP/設施 之間切換。**不是新增,是改記號** ——
   使用者圖上很多節點本來就是任務,只是當初當結構畫的。
   四種互斥:待辦寫 node.todo,SOP/設施寫 node.kind,結構=兩者皆無。
   (留 false/空字串會讓 JSON 多一堆沒意義的欄位,所以一律用 delete) */
function setKindOf(kind) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  delete node.todo;
  delete node.kind;
  if (kind === "todo") node.todo = true;
  else if (kind === "sop" || kind === "infra" || kind === "tool") node.kind = kind;
  updateBadges();
  applyTodoLines();
  renderDrawer();
  scheduleSave();
}

/* AI 動過的節點會被圈起來,使用者檢查完自己拆掉圈圈。
   使用者的需求(2026-08-03):「加個圈把你修正的區塊圈起來,我檢查沒問題就把圈拿掉,
   這樣就不會有我不知道你有改的問題了。」 */
function clearAiMark(all) {
  if (!mind) return;
  if (all) {
    const data = mind.getData();
    walkNodes(data.nodeData, (n) => delete n.aiEdited);
    mind.refresh(data);
    const back = eleById(detailNodeId);
    if (back) mind.selectNode(back);
  } else {
    const node = nodeById(detailNodeId);
    if (!node) return;
    delete node.aiEdited;
  }
  updateBadges();
  applyTodoLines();
  renderDrawer();
  scheduleSave();
}

function countAiMarks() {
  if (!mind || !mind.nodeData) return 0;
  let n = 0;
  walkNodes(mind.nodeData, (x) => {
    if (x.aiEdited) n += 1;
  });
  return n;
}

/* 面板上的「這個節點是什麼」:結構 / 待辦 / 規則SOP / 設施 */
function kindOf(node) {
  if (!node) return "";
  if (isTodoNode(node)) return "todo";
  if (node.kind === "sop" || node.kind === "infra" || node.kind === "tool") return node.kind;
  return "struct";
}

function renderKind(node) {
  const box = $("chips-kind");
  box.innerHTML = "";
  [
    { kind: "struct", label: "🗂 結構", title: "在講「這東西由哪些部分組成」" },
    { kind: "todo", label: "☑ 待辦", title: "有事情要做;字會變藍、線變藍虛線,可以整批開關" },
    { kind: "sop", label: "📐 規則SOP", title: "指向正本檔的路標(紫);內容不抄進圖,點節點開正本" },
    { kind: "infra", label: "🖥️ 設施", title: "機器/系統架構(綠);可以整批開關" },
    { kind: "tool", label: "🛠 工具", title: "skill／指令的路標(黃);跟規則SOP同一個圖層開關" },
  ].forEach((k) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (kindOf(node) === k.kind ? " on" : "");
    b.textContent = k.label;
    b.title = k.title;
    b.disabled = !node;
    b.onclick = () => setKindOf(k.kind);
    box.appendChild(b);
  });
  $("todo-add").disabled = !node;
}

/* AI 改動的圈圈:選到被圈起來的節點時,面板給一顆「看過了」 */
function renderAiRow(node) {
  const el = $("drawer-ai");
  el.innerHTML = "";
  const marked = !!(node && node.aiEdited);
  el.hidden = !marked;
  if (!marked) return;
  const span = document.createElement("span");
  span.textContent = `⭕ 這個節點 AI 改過${typeof node.aiEdited === "string" ? `（${node.aiEdited}）` : ""} —`;
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = "看過了，拆掉圈圈";
  b.onclick = () => clearAiMark(false);
  const all = document.createElement("button");
  all.type = "button";
  all.textContent = `全部拆掉（${countAiMarks()}）`;
  all.onclick = () => clearAiMark(true);
  el.append(span, b, all);
}

/* 寫回 detail 的唯一出口。**三個欄位全空了才把 detail 整個拿掉** ——
   以前這個判斷寫在兩個地方各判一次,加了截止日之後少判一個就會被順手刪掉。 */
function commitDetail(node, detail) {
  delete detail.how; // 舊的自由文字欄位已由待辦清單取代
  if (!(detail.explain || "").trim()) delete detail.explain;
  if (!(detail.todos || []).length) delete detail.todos;
  if (!dueOf({ detail })) delete detail.due;
  if (!effortOf({ detail })) delete detail.effort;
  if (!(detail.window || "").trim()) delete detail.window;
  if (Object.keys(detail).length) node.detail = detail;
  else delete node.detail;
}

function setDue(iso) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  const detail = { ...(node.detail || {}) };
  detail.due = (iso || "").trim();
  commitDetail(node, detail);
  const now = dueOf(node);
  $("detail-due").value = now;
  $("due-clear").disabled = !now; // 設完日期「清除」才按得下去(漏了這行就變成設了拆不掉)
  afterContentChange();
}

function setEarliest(iso) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  const detail = { ...(node.detail || {}) };
  detail.earliest = (iso || "").trim();
  commitDetail(node, detail);
  const now = earliestOf(node);
  $("detail-earliest").value = now;
  $("earliest-clear").disabled = !now;
  afterContentChange();
}

function writeDetail() {
  const node = nodeById(detailNodeId);
  if (!node) return;
  const detail = { ...(node.detail || {}) };
  detail.explain = $("detail-explain").value;
  commitDetail(node, detail);
  afterContentChange();
}

/* effort 用「再點一次同一顆=清掉」——八顆小按鈕再擠一顆「清除」會小到按不準 */
function setEffort(v) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  const detail = { ...(node.detail || {}) };
  detail.effort = effortOf(node) === v ? "" : v;
  commitDetail(node, detail);
  renderEffortChips(node);
  afterContentChange();
}

function setWindow(text) {
  const node = nodeById(detailNodeId);
  if (!node) return;
  const detail = { ...(node.detail || {}) };
  detail.window = (text || "").trim();
  commitDetail(node, detail);
  afterContentChange();
}

function renderEffortChips(node) {
  const box = $("chips-effort");
  box.innerHTML = "";
  const cur = node ? effortOf(node) : "";
  EFFORTS.forEach((e) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip mini" + (cur === e.v ? " on" : "");
    b.textContent = e.v;
    b.title = `約 ${e.hours} 小時（一天以你的實際容量 10 小時計）· 再點一次取消`;
    b.disabled = !node;
    b.onclick = () => setEffort(e.v);
    box.appendChild(b);
  });
}

/* 內容一改,徽章與統計都要跟著更新,然後排存檔 */
function afterContentChange() {
  updateBadges();
  const node = nodeById(detailNodeId);
  if (node) {
    $("drawer-title").textContent = node.topic;
    renderChips(node); // 不重畫的話按鈕會停在舊狀態(曾經出過的問題)
    renderTags(node);
    renderRollupLine(node);
  }
  scheduleSave();
}

function renderRollupLine(node) {
  const r = node ? rollup(node) : { counts: {}, waiting: 0 };
  const counts = r.counts;
  const rows = PRIORITY.filter((p) => counts[p.tag])
    .map((p) => `${p.dot} ${p.tag}:${counts[p.tag]}`)
    .concat(counts["未分類"] ? [`⚫ 沒等級:${counts["未分類"]}`] : []);
  // 「等別人」照算沒做(它確實還沒完成),但另外標出來——球不在你身上的別催自己
  const tail = r.waiting ? `　（其中 ${r.waiting} 件在等別人）` : "";
  $("drawer-rollup").hidden = !rows.length;
  $("drawer-rollup").textContent = rows.length ? "還沒做的事：" + rows.join("　") + tail : "";
  renderSuggest(node);
}

/* 待辦全部 ✅ 了、節點自己卻還掛著未完成狀態 → 提示一下,附一個按鈕。
   ⛔ 只提示不自動改:自動改內容跟自動改外觀是同一種病(設計原則一)。 */
function renderSuggest(node) {
  const el = $("drawer-suggest");
  const kids = node ? todoChildren(node) : [];
  const st = node ? statusOf(node.topic) : null;
  const done = kids.filter((k) => !isUndone(k)).length;
  const show = kids.length > 0 && done === kids.length && (!st || st.s.mark !== DONE);
  el.hidden = !show;
  el.innerHTML = "";
  if (!show) return;
  const span = document.createElement("span");
  span.textContent = `底下 ${kids.length} 條待辦都完成了 —`;
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = "把這個節點標成 ✅";
  b.onclick = () => setStatus_(DONE);
  el.append(span, b);
}

function walkNodes(node, fn) {
  fn(node);
  (node.children || []).forEach((c) => walkNodes(c, fn));
}

function selectedIds() {
  if (!mind) return []; // boot 期間面板可能先渲染,那時地圖還沒建好
  const nodes =
    mind.currentNodes && mind.currentNodes.length
      ? mind.currentNodes
      : mind.currentNode
        ? [mind.currentNode]
        : [];
  return nodes.map((el) => el.nodeObj && el.nodeObj.id).filter(Boolean);
}

/* 清掉選取節點的樣式。引擎的 reshapeNode 只會 Object.assign 合併,清不掉既有值
   (這就是調色盤只能換色、不能回到「無」的原因),所以改成動資料 + 整張重繪。
   keys 省略 = 清掉全部樣式。 */
function clearStyle(keys) {
  const ids = selectedIds();
  if (!ids.length) {
    setStatus("先點一個節點,再清除樣式", "dirty");
    return;
  }
  const data = mind.getData();
  walkNodes(data.nodeData, (n) => {
    if (!ids.includes(n.id) || !n.style) return;
    if (keys) keys.forEach((k) => delete n.style[k]);
    else delete n.style;
    if (n.style && !Object.keys(n.style).length) delete n.style;
  });
  mind.refresh(data);
  updateBadges();
  const el = mind.findEle(ids[0]);
  if (el) mind.selectNode(el);
  clearPanelMarks(); // 面板上舊的選取圈不會自己消,手動清掉才不會誤導
  scheduleSave();
}

/* 把選取節點變成「規則/說明便條」的外觀。寫進節點自己的 style,
   所以之後你要改哪個屬性、要不要清掉,全部由你決定。 */
function applyNoteStyle() {
  const ids = selectedIds();
  if (!ids.length) {
    setStatus("先點一個節點,再套便條樣式", "dirty");
    return;
  }
  ids.forEach((id) => {
    const el = mind.findEle(id);
    if (el) mind.reshapeNode(el, { style: { ...NOTE_STYLE } });
  });
  scheduleSave();
}

/* 面板上的「清除」按鈕列——使用者的手本來就在那個面板上,比工具列好找。
   ⚠️ 刻意不做成「一顆『無』+ 看目前在哪個分頁」:面板剛打開時 Font/Background
   兩個分頁都不是 selected,那時候猜要清哪一個一定會猜錯(曾經出過的問題:想清字色結果清到背景)。
   三顆各做各的,沒有猜的空間。 */
function clearPanelMarks() {
  const nm = document.querySelector(".node-menu");
  if (!nm) return;
  nm.querySelectorAll(".nmenu-selected").forEach((e) => e.classList.remove("nmenu-selected"));
  nm.querySelectorAll(".size-selected").forEach((e) => e.classList.remove("size-selected"));
}

function injectClearRow() {
  const nm = document.querySelector(".node-menu");
  if (!nm || nm.querySelector(".mm-clear-row")) return;
  const rows = nm.querySelector(".nm-fontcolor-container");
  if (!rows) return;
  const row = document.createElement("div");
  row.className = "mm-clear-row";
  [
    ["清除字色", () => clearStyle(["color"]), "把這個節點的字色拿掉"],
    ["清除底色", () => clearStyle(["background"]), "把這個節點的底色拿掉"],
    ["全部清除", () => clearStyle(), "顏色、字級、邊框全部回到預設"],
    ["📏 便條樣式", applyNoteStyle, "套成規則/說明的外觀(虛線框+斜體小字);之後可用「全部清除」拿掉"],
  ].forEach(([label, fn, title]) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = label;
    btn.title = title;
    btn.onclick = (e) => {
      e.stopPropagation();
      fn();
    };
    row.appendChild(btn);
  });
  rows.parentElement.insertBefore(row, rows.nextSibling);
}

function createEditor(data) {
  $("map").innerHTML = "";
  mind = new ME({
    el: "#map",
    direction: ME.SIDE,
    draggable: true,
    toolBar: true,
    keypress: true,
    allowUndo: true,
    contextMenu: { focus: true, link: true, locale: ZH_TW },
  });
  mind.install(nodeMenu);
  mind.init(data);
  injectClearRow();
  window.__mind = mind; // 給 debug / AI 在 console 摸資料用
  mind.bus.addListener("operation", scheduleSave);
  mind.bus.addListener("updateArrowDelta", scheduleSave);
  // 選取一變,聚焦模式要亮的線就跟著換
  ["selectNewNode", "selectNodes", "unselectNodes"].forEach((ev) =>
    mind.bus.addListener(ev, () =>
      setTimeout(() => {
        renderDrawer();
        applyArrowFocus();
      }, 0),
    ),
  );
  // 節點重繪後 data-detail 會掉,補回來(事件驅動,不用計時器輪詢);
  // linkDiv 也會把關聯線整個重畫,.arrow-on 一起沒了,所以要補標回去
  ["operation", "expandNode", "linkDiv"].forEach((ev) =>
    mind.bus.addListener(ev, () =>
      setTimeout(() => {
        updateBadges();
        applyArrowFocus();
        applyTodoLines();
      }, 0),
    ),
  );
  /* 拉新線／刪線之後,面板的關聯清單要跟著更新。
     ⚠️ 只認這兩種 operation:每種都重畫的話,在標籤輸入框打字會被自己打斷。 */
  mind.bus.addListener("operation", (op) => {
    if (!op || (op.name !== "createArrow" && op.name !== "removeArrow")) return;
    setTimeout(() => {
      renderRelations(nodeById(detailNodeId));
      applyArrowFocus();
    }, 0);
  });
  updateBadges();
  applyArrowFocus();
  applyTodoLines();
}

function scheduleSave() {
  setStatus("● 未儲存…", "dirty");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveMap, 1200);
}

async function saveMap(force = false) {
  if (!mind || !currentName || saving) return;
  const json = JSON.stringify(mind.getData());
  if (!force && json === lastSavedJson) return;
  saving = true;
  try {
    const resp = await fetch(`/api/maps/${encodeURIComponent(currentName)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        data: JSON.parse(json),
        base_mtime: force ? null : baseMtime,
      }),
    });
    if (resp.status === 409) {
      showBanner("⚠ 檔案在別處被改過(可能是 AI)。要載入最新、還是用你目前的版本覆蓋?");
      setStatus("⚠ 衝突", "dirty");
      return;
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const out = await resp.json();
    baseMtime = out.mtime;
    lastSavedJson = json;
    hideBanner();
    setStatus(`✔ 已儲存 ${new Date().toLocaleTimeString("zh-TW", { hour12: false })}`, "saved");
  } catch (e) {
    setStatus(`✘ 存檔失敗:${e.message}`, "dirty");
  } finally {
    saving = false;
  }
}

async function fetchList() {
  const resp = await fetch("/api/maps");
  return resp.json();
}

async function refreshList(selected) {
  const maps = await fetchList();
  mapNames = maps.map((m) => m.name);
  const sel = $("map-select");
  sel.innerHTML = "";
  for (const m of maps) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.name;
    sel.appendChild(opt);
  }
  if (selected) sel.value = selected;
  return maps;
}

async function openMap(name, keepView) {
  const view = keepView ? viewState() : null;
  const resp = await fetch(`/api/maps/${encodeURIComponent(name)}`);
  if (!resp.ok) {
    setStatus(`✘ 開不了 ${name}`, "dirty");
    return;
  }
  const out = await resp.json();
  currentName = name;
  baseMtime = out.mtime;
  createEditor(out.data);
  lastSavedJson = JSON.stringify(mind.getData());
  refreshProjects();
  location.hash = encodeURIComponent(name);
  $("map-select").value = name;
  hideBanner();
  setStatus("✔ 已載入", "saved");
  // 徽章已經把節點撐寬,引擎載入時算的置中位置要重算。
  // ⚠️ 但「外部改動自動重載」不算重新開一張圖 —— 那種要留在原本看的地方。
  if (view) applyView(view);
  else recenter();
}

async function newMap() {
  const name = prompt("新圖名稱(中英數字、-、_、空格):");
  if (!name) return;
  const data = ME.new(name);
  const resp = await fetch(`/api/maps/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data, base_mtime: null }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    alert(`建立失敗:${err.detail || resp.status}`);
    return;
  }
  await refreshList(name);
  await openMap(name);
}

/* 這一頁載入時的程式版本。伺服器上的靜態檔一被改動就會對不上,
   代表「你看到的是舊 UI」——分頁開著不重整就會這樣,而且從畫面上完全看不出來。 */
let loadedBuild = null;

async function checkBuild() {
  try {
    const h = await (await fetch("/api/health")).json();
    if (loadedBuild === null) {
      loadedBuild = h.build;
      return;
    }
    if (h.build !== loadedBuild) {
      $("update-bar").hidden = false;
      document.body.classList.add("has-update");
    }
  } catch {
    /* 網路瞬斷就等下一輪 */
  }
}

/* 輪詢外部修改:乾淨→自動重載;髒→衝突橫幅 */
async function pollExternal() {
  checkBuild();
  if (!currentName || saving) return;
  try {
    const maps = await fetchList();
    const me = maps.find((m) => m.name === currentName);
    if (!me || baseMtime === null) return;
    if (me.mtime - baseMtime > 1e-4) {
      if (!isDirty()) {
        await openMap(currentName, true); // ⛔ 別把使用者的視角拉回正中間
        setStatus("🔄 已載入外部修改(視角保持不動)", "saved");
      } else {
        showBanner("⚠ 檔案在別處被改過(可能是 AI),而你也有未存的改動。");
      }
    }
  } catch {
    /* 網路瞬斷就等下一輪 */
  }
}

/* ── 搜尋:232+ 節點的圖,「在同一個地方查找」沒有搜尋撐不住 ─────────
   比對範圍=標題+說明+標籤+窗口(全部小寫包含比對,不做模糊猜測)。
   跳過去之前先把蓋住它的圖層打開 —— 搜到了卻看不到等於沒搜到。 */
let searchItems = [];
let searchIndex = -1;

function searchNodes(q) {
  const needle = q.trim().toLowerCase();
  if (!needle || !mind || !mind.nodeData) return [];
  const out = [];
  const walkP = (n, path) => {
    const hay = [n.topic, (n.detail && n.detail.explain) || "", (n.tags || []).join(" "), windowOf(n)]
      .join(" ")
      .toLowerCase();
    if (hay.includes(needle)) out.push({ id: n.id, topic: (n.topic || "").trim(), path });
    (n.children || []).forEach((c) => walkP(c, path.concat((n.topic || "").trim())));
  };
  walkP(mind.nodeData, []);
  return out.slice(0, 12);
}

function closeSearch() {
  $("search-list").hidden = true;
  searchItems = [];
  searchIndex = -1;
}

function searchGo(i) {
  const it = searchItems[i];
  if (!it) return;
  closeSearch();
  $("search-box").blur();
  revealLayersFor(it.id);
  jumpTo(it.id);
}

function renderSearchList() {
  const box = $("search-list");
  box.innerHTML = "";
  box.hidden = !searchItems.length;
  searchItems.forEach((it, i) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "search-row" + (i === searchIndex ? " active" : "");
    const t = document.createElement("span");
    t.className = "search-topic";
    t.textContent = it.topic;
    const p = document.createElement("small");
    p.textContent = it.path.slice(-2).join(" / "); // 只給最近兩層,夠定位又不會爆版
    row.append(t, p);
    row.onclick = () => searchGo(i);
    box.appendChild(row);
  });
}

/* ── AI 圈圈檢查器:一顆一顆跳,不用自己在 232 個節點裡找紫圈 ─────────
   按鈕上是還剩幾顆;點了跳下一顆(會自動開圖層+展開祖先+閃一下),
   拆圈本身用詳情面板既有的「看過了,拆掉圈圈」。 */
let aiCursor = -1;

function nextAiMark() {
  if (!mind || !mind.nodeData) return;
  const ids = [];
  walkNodes(mind.nodeData, (n) => {
    if (n.aiEdited) ids.push(n.id);
  });
  if (!ids.length) return;
  aiCursor = (aiCursor + 1) % ids.length;
  const id = ids[aiCursor];
  revealLayersFor(id);
  jumpTo(id);
  if ($("drawer").hidden) openDrawer(true); // 拆圈的按鈕在面板上,面板關著會找不到出口
  setStatus(`⭕ 第 ${aiCursor + 1}/${ids.length} 顆 — 右側面板可拆圈`, "saved");
}

function updateAiBtn() {
  const n = countAiMarks();
  const btn = $("btn-ai-next");
  btn.hidden = !n;
  btn.textContent = `⭕ ${n}`;
  btn.title = `還有 ${n} 個 AI 改過的節點沒檢查。點一下跳到下一個（在詳情面板拆圈圈）`;
}

async function boot() {
  $("btn-save").onclick = () => saveMap();
  $("btn-new").onclick = newMap;
  // 清除樣式的入口統一在外觀面板裡(injectClearRow),工具列不重複放
  $("btn-detail").onclick = () => openDrawer($("drawer").hidden);
  $("btn-arrows").onclick = cycleArrowMode;
  $("btn-layers").onclick = (e) => {
    e.stopPropagation(); // 不擋的話下面的「點外面就收起來」會立刻把它關回去
    $("layer-panel").hidden = !$("layer-panel").hidden;
  };
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#layers-wrap")) $("layer-panel").hidden = true;
    if (!e.target.closest || !e.target.closest("#search-wrap")) closeSearch();
  });
  $("btn-ai-next").onclick = nextAiMark;
  $("search-box").oninput = (e) => {
    searchItems = searchNodes(e.target.value);
    searchIndex = searchItems.length ? 0 : -1;
    renderSearchList();
  };
  $("search-box").onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!searchItems.length) return;
      const d = e.key === "ArrowDown" ? 1 : -1;
      searchIndex = (searchIndex + d + searchItems.length) % searchItems.length;
      renderSearchList();
    } else if (e.key === "Enter") {
      e.preventDefault();
      searchGo(searchIndex >= 0 ? searchIndex : 0);
    } else if (e.key === "Escape") {
      closeSearch();
      e.target.value = "";
      e.target.blur();
    }
  };

  /* Shift+Tab = 加一條待辦。⚠️ 要在捕獲階段攔:引擎的 Tab 綁在容器上而且不判 shiftKey,
     不搶先攔下來的話會變成加一個普通子節點。編輯框開著時放行(那是換欄位不是加節點)。 */
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "Tab" || !e.shiftKey || e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.getElementById("input-box")) return;
      if (!mind || !selectedIds().length) return;
      e.preventDefault();
      e.stopPropagation();
      addTodoChild();
    },
    true,
  );
  $("link-select").onchange = (e) => setHyperLink(e.target.value);

  /* 整個節點都可以點去開連結。三種情況都要擋:
     ①**第一次點只能選取,不能跳走** —— 不然這個節點會變成點不到、選不起來,
       連結也拆不掉(每次想選它都被送去別張圖)。所以「已經選起來的」才跳。
       點那顆「開啟 ↗」膠囊則是一下就走,一次到位的入口留著。
     ②雙擊是要改字 → dblclick 進來就取消;編輯框開著時一律不跳。
     ③點膠囊要 preventDefault,不然瀏覽器會照 target="_blank" 另開分頁。 */
  let linkTimer = null;
  let wasSelected = false;
  // 捕獲階段:搶在引擎把節點設成 selected 之前,記下「按下去的當下選了沒」
  $("map").addEventListener(
    "pointerdown",
    (e) => {
      const tpc = e.target.closest && e.target.closest("me-tpc");
      wasSelected = !!(tpc && tpc.classList.contains("selected"));
    },
    true,
  );
  $("map").addEventListener("click", (e) => {
    const tpc = e.target.closest && e.target.closest("me-tpc");
    const url = tpc && tpc.nodeObj && tpc.nodeObj.hyperLink;
    if (!url) return;
    const onPill = !!e.target.closest(".hyper-link");
    if (onPill) e.preventDefault();
    if (!onPill && !wasSelected) return; // 先選起來,再點一下才開
    clearTimeout(linkTimer);
    linkTimer = setTimeout(() => {
      if (document.getElementById("input-box")) return; // 正在改字,別跳走
      followLink(url);
    }, 220);
  });
  $("map").addEventListener("dblclick", () => clearTimeout(linkTimer));
  $("btn-style-mode").onclick = () =>
    setStyleMode(!document.body.classList.contains("style-mode"));
  $("drawer-close").onclick = () => openDrawer(false);
  // 先存再重整:直接 reload 會把還沒存的改動丟掉,不能讓使用者自己記得先按儲存
  $("btn-update").onclick = async () => {
    if (isDirty()) await saveMap();
    location.reload();
  };
  checkBuild(); // 記下這一頁載入的是哪一版
  $("detail-explain").oninput = writeDetail;
  $("src-input").onchange = (e) => setSource(e.target.value);
  $("detail-due").onchange = (e) => setDue(e.target.value);
  $("due-clear").onclick = () => setDue("");
  $("detail-earliest").onchange = (e) => setEarliest(e.target.value);
  $("earliest-clear").onclick = () => setEarliest("");
  $("window-input").onchange = (e) => setWindow(e.target.value);
  $("todo-add").onclick = addTodoChild;
  $("tag-input").onkeydown = (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    addTag(e.target.value);
    e.target.value = "";
  };
  $("detail-clear").onclick = () => {
    const node = nodeById(detailNodeId);
    if (!node) return;
    delete node.detail;
    renderDrawer();
    afterContentChange();
  };
  $("btn-reload").onclick = () => openMap(currentName);
  $("btn-force").onclick = () => saveMap(true);
  $("map-select").onchange = (e) => openMap(e.target.value);
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") {
      e.preventDefault();
      saveMap();
    }
    // ⌘F 交給圖內搜尋:圖是 DOM 不是文字流,瀏覽器原生搜尋在這頁本來就沒用
    if ((e.metaKey || e.ctrlKey) && e.key === "f") {
      e.preventDefault();
      $("search-box").focus();
      $("search-box").select();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && isDirty()) saveMap();
  });
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(recenter, 200);
  });
  // 任務板的「在圖上看 ↗」會帶 ?focus=<id> 過來 —— 載完圖之後跳過去並圈出來
  const focusId = new URLSearchParams(location.search).get("focus");
  if (focusId) {
    setTimeout(() => {
      revealLayersFor(focusId);
      jumpTo(focusId);
      history.replaceState(null, "", location.pathname + location.hash);
    }, 900);
  }

  window.addEventListener("hashchange", () => {
    const name = decodeURIComponent(location.hash.slice(1));
    if (name && name !== currentName) openMap(name);
  });
  setInterval(pollExternal, 4000);
  setInterval(refreshProjects, 60000); // 專案進度一分鐘拉一次就夠,它不會每秒變
  // 兜底:node-menu 等不走 operation 事件的修改,靠定時比對抓髒
  setInterval(() => {
    if (isDirty() && !saving) scheduleSave();
  }, 3000);

  openDrawer(localStorage.getItem("mm-drawer") !== "0"); // 詳情面板預設開著,版面才固定
  setStyleMode(localStorage.getItem("mm-stylemode") === "1"); // 外觀模式預設關
  localStorage.removeItem("mm-arrows"); // 舊的兩態開關,已被三檔取代
  setArrowMode(localStorage.getItem("mm-arrow-mode") || "focus"); // 預設聚焦:點到才亮
  // 圖層(預設全開;舊的 mm-todos 開關設定值在 layerOn 裡沿用)
  LAYERS.forEach((l) => document.body.classList.toggle(l.cls, !layerOn(l.key)));
  renderLayerPanel();

  const maps = await refreshList();
  const fromHash = decodeURIComponent(location.hash.slice(1));
  if (fromHash && maps.some((m) => m.name === fromHash)) {
    await openMap(fromHash);
  } else if (maps.some((m) => m.name === DEFAULT_MAP)) {
    await openMap(DEFAULT_MAP); // ⛔ 不要退回 maps[0]:那是照檔名排序,「_沙盒」永遠排第一
  } else if (maps.length) {
    await openMap(maps[0].name);
  } else {
    setStatus("還沒有圖,按「➕ 新圖」開始");
  }
}

boot();
