/* 🗓 排行程(路徑仍是 /day)— 拖拉排程器(心智圖的第四個視圖)。
   ⚠️ 使用者 2026-08-24 改名:「排今天」→「排行程」。要排的本來就不只今天,
   一次看得到一整週。⛔ 路徑不改 —— 改了使用者的書籤跟工具裡寫死的網址全會壞。

   使用者的需求(2026-08-11):「我想設計一個更好讓我去做拖拉行程的工具…右邊區域放目前還沒有
   排進行程的任務,我可以依照優先順序拖拉到左邊的行程裡…固定行程(讀書、語言學習、
   運動、吃飯、通勤)拉到左邊後,右邊的原始區塊不會消失,可以重複拖拉使用。」

   「所以他只能排一天喔,好爛喔…我想要可以一直往後看看到很多天的,不如就設定為
   一個禮拜吧,我看 Google 行事曆好像也都這樣設定的。」
   → 一次畫連續幾天,並排成欄、左右捲;每一欄都能接住拖過來的東西。
   ⚠️ 欄寬給固定的 min-width 而不是等分:等分的話 7 欄擠進畫面 = 每欄 160px,
      字又會被切掉 —— 那正是使用者上一版最不滿的地方。寧可左右捲。

   兩種資料,刻意分開放:
   ① 任務的「哪天幾點做」→ 寫回**心智圖那個節點**的 detail.plannedAt
      (使用者選的:任務板上要看得出來「已經排在 8/12 早上」)。
      ⚠️ 走 PATCH 單節點,不是 PUT 整張圖 —— 300 個節點每拖一下重寫一次,
      使用者同時開著心智圖網頁就會一直跳「圖被別人改過了」。
   ② 日常區塊的實例 → 存在「那一天的行程檔」(排程設定/每日行程/<日期>.json)。
      它們不是待辦,不該變成心智圖節點,不然圖會被吃飯通勤淹掉。

   ⛔ 這一頁不出現「主線/雜項/語言」。使用者反映:「為什麼你要幫我排什麼主線雜項那些東西」。 */

const MAP = window.MM_MAP || "全局總覽圖";   // 伺服器說了算,見 /static/js/config.js
const SNAP = 15;                  // 15 分鐘一格(使用者選的)
const DAY_START_SCROLL = 8 * 60;  // 直向預設捲到 08:00
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

/* 顏色 = 領域。使用者問過「不同的顏色是代表什麼意思」→ 右下角有圖例。
   不在表裡的領域用雜湊挑一個固定色,不會每次重整都換色。 */
const DOMAIN_COLOR = {
  "💼 Work": "#4dabf7",
  "💰 Finance": "#f59f00",
  "✍️ Blog": "#38d9a9",
  Workspace: "#b197fc",
  Personal: "#ff8787",
  Language: "#a9e34b",
  "🎵 Music": "#e599f7",
};
const SPARE = ["#74c0fc", "#ffd8a8", "#63e6be", "#d0bfff", "#ffc9c9", "#c0eb75"];
function colorOf(domain) {
  if (DOMAIN_COLOR[domain]) return DOMAIN_COLOR[domain];
  let h = 0;
  for (const ch of domain || "") h = (h * 31 + ch.charCodeAt(0)) % 9973;
  return SPARE[h % SPARE.length];
}

/* 拖到時間軸上,一塊預設多長。
   使用者 2026-08-30 定案把「這件事要花幾小時」整個從這一頁拿掉:
   「我根本沒有辦法知道我要花幾個小時完成,那就變成會限制我安排時間的長度,
   而且如果今天真的比較長、我想拆兩天的話還沒辦法弄。」
   ⛔ 所以這一頁不再有「總時數」與「還剩多少沒排」——
   任務永遠留在右邊,拖幾塊、每塊多長都由使用者自己決定,按下完成才離開。
   ⚠️ effort 欄位本身刻意留著沒刪(心智圖與任務板還改得到、plan_week 的死線警報還在讀),
   只有這一頁不看它。 */
const DEFAULT_BLOCK_MIN = 60;
const uid = () => "s" + Math.random().toString(36).slice(2, 9);
const fmtMin = (m) => (m % 60 === 0 ? `${m / 60} 小時` : m < 60 ? `${m} 分` : `${(m / 60).toFixed(1)} 小時`);

const pad = (n) => String(n).padStart(2, "0");
const toHHMM = (mins) => `${pad(Math.floor(mins / 60))}:${pad(mins % 60)}`;
const fromHHMM = (s) => {
  const [h, m] = String(s).split(":").map(Number);
  return h * 60 + m;
};
const snap = (mins) => Math.max(0, Math.min(24 * 60 - SNAP, Math.round(mins / SNAP) * SNAP));
const px = (mins) => mins * parseFloat(
  getComputedStyle(document.documentElement).getPropertyValue("--min-px"));

/* 無限往右滑:畫面上永遠只有「已經載入的那一段日子」,捲到邊緣才去要更多。
   使用者的需求(2026-08-11):「它能不能變成可以一直往後滑?不需要單純去選擇看多少,
   我一直往後看就可以了;然後當我選擇『今天』,它就會跳回來。」
   ⚠️ 有上限(MAX_DAYS):滑一整晚也不會把幾百欄堆在 DOM 裡 ——
   超過就從另一頭砍掉,反正那端使用者已經捲離很遠了。 */
const CHUNK = 14;      // 每次補幾天
const BACK = 3;        // 一開始往前留幾天(昨天沒做完的要看得到)
const MAX_DAYS = 120;  // DOM 上最多留幾欄
let state = { date: "", days: [], pool: [], stale: [], repeats: [], waiting: [],
              aiTasks: [], templates: [] };
/* 「顯示已完成」。**預設開**(使用者 2026-08-30 定案,推翻 08-24 的預設關):
   「我覺得其實沒有必要這麼做…我們只要在完成的項目前面畫上一個勾勾並且變成暗暗的
   就好了,這個東西沒有必要把它隱藏起來。」
   ⚠️ 08-24 那次是使用者自己說「重點要關注在還沒做的事情」,照那句設成預設關 ——
   但真正在意的是**版面不要被佔走**,而淡色+劃掉已經解決了那件事,藏起來反而
   讓使用者看不到自己做過什麼。開關留著(關得掉),只是預設反過來。
   ⛔ 這裡只存介面偏好,不存任務也不存時間。 */
let showDone = localStorage.getItem("day.showDone") !== "0";
let busy = false;      // 正在補資料,別重複發
let drag = null;   // { kind:"task"|"tpl"|"move"|"moveBlock", ... }

function toast(text, bad) {
  const t = $("toast");
  t.textContent = text;
  t.style.borderColor = bad ? "var(--p1)" : "var(--blue)";
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 3000);
}

const todayISO = () => new Date().toLocaleDateString("sv-SE");
const shiftDate = (iso, n) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d + n).toLocaleDateString("sv-SE");
};
const dayOf = (iso) => state.days.find((d) => d.date === iso);

/* ── 讀 ─────────────────────────────────────────────────────────── */
async function fetchDays(startISO, n) {
  const r = await fetch(`/api/day?date=${startISO}&days=${n}`);
  if (!r.ok) { $("status").textContent = "✘ 讀不到資料"; return null; }
  return r.json();
}

/* 重載目前畫面上的整段(改過東西之後用)。 */
async function load(keep) {
  const box = $("left");
  const pos = keep ? { top: box.scrollTop, left: box.scrollLeft } : null;
  const first = state.days.length ? state.days[0].date : shiftDate(state.date, -BACK);
  const n = Math.max(CHUNK, state.days.length || CHUNK + BACK);
  const data = await fetchDays(first, n);
  if (!data) return;
  state.pool = data.pool;
  state.stale = data.stale || [];
  state.repeats = data.repeats || [];
  state.waiting = data.waiting || [];
  state.aiTasks = data.aiTasks || [];
  state.templates = data.templates;
  state.days = data.days;
  render();
  if (pos) { box.scrollTop = pos.top; box.scrollLeft = pos.left; }
  else { box.scrollTop = px(DAY_START_SCROLL); scrollToDate(state.date); }
}

/* 往右(或往左)補一段日子,不動已經在畫面上的。 */
async function extend(dir) {
  if (busy || !state.days.length) return;
  busy = true;
  try {
    const box = $("left");
    const startISO = dir > 0
      ? shiftDate(state.days[state.days.length - 1].date, 1)
      : shiftDate(state.days[0].date, -CHUNK);
    const data = await fetchDays(startISO, CHUNK);
    if (!data) return;
    state.pool = data.pool;
    state.repeats = data.repeats || [];
    state.waiting = data.waiting || [];
    state.aiTasks = data.aiTasks || [];
    const before = box.scrollWidth;
    state.days = dir > 0 ? state.days.concat(data.days) : data.days.concat(state.days);
    if (state.days.length > MAX_DAYS) {
      state.days = dir > 0
        ? state.days.slice(state.days.length - MAX_DAYS)
        : state.days.slice(0, MAX_DAYS);
    }
    const top = box.scrollTop;
    const left = box.scrollLeft;
    /* ⚠️ render() 會順手重貼編輯面板,但那時捲軸還沒補回去 —— 往左補日子時整排先右移,
       面板黏的那一塊瞬間跑出可視範圍,placeEditor 就把面板關了。
       2026-09-17 使用者回報已完成的方塊「完全打不開」,查到這裡是其中一個原因:
       捲到左邊附近按 ✎,面板一開就被這次重畫關掉。→ 捲軸補回去之後再貼一次。 */
    const keep = editing;
    render();
    box.scrollTop = top;
    // 往左補的時候整排會右移,要把捲軸補回去,不然畫面會跳
    box.scrollLeft = dir > 0 ? left : left + (box.scrollWidth - before);
    if (keep && !editing) {
      editing = keep;
      renderEditor();
    }
  } finally {
    busy = false;
  }
}

/* 領域下拉:選項照目前資料現有的領域長出來,不寫死。 */
function fillDomains() {
  const sel = $("f-domain");
  const cur = sel.value;
  const names = [...new Set(state.pool.filter((t) => !isLang(t)).map((t) => t.domain))].sort();
  if (sel.dataset.sig === names.join("|")) return;  // 沒變就不重畫,免得選到一半被洗掉
  sel.dataset.sig = names.join("|");
  sel.innerHTML = '<option value="">全部領域</option>';
  names.forEach((n) => {
    const o = el("option", null, n);
    o.value = n;
    sel.appendChild(o);
  });
  sel.value = names.includes(cur) ? cur : "";
}

function scrollToDate(iso) {
  const col = document.querySelector(`.daycol[data-date="${iso}"]`);
  // 減掉鐘點欄的寬度 + 幾 px 餘裕:那一欄是 sticky 的,會蓋住目標欄的左緣
  if (col) $("left").scrollLeft = Math.max(0, col.offsetLeft - 58);
}

/* ── 那一天已經佔用的區間(擋重疊用)─────────────────────────────── */
function placed(iso) {
  const day = dayOf(iso);
  if (!day) return [];
  const out = day.scheduled.map((t) => ({
    key: "t:" + t.slot.uid, start: fromHHMM(t.slot.at.slice(11, 16)), min: t.slot.min,
  }));
  day.blocks.forEach((b) => out.push({
    key: "b:" + b.uid, start: fromHHMM(b.start), min: b.min,
  }));
  return out;
}

/* 同一時段疊幾件事。使用者的需求(2026-08-11):「我覺得可以讓不同的行程可以疊加,就是同一塊
   裡面可以放幾個不同的行程,因為有時候就是確實會同時處理不同的事情。」
   → **不再擋**;改成算出「這件事在第幾欄、那一叢共幾欄」,像 Google 行事曆那樣並排。
   ⛔ 不並排的話後放的會整個蓋住先放的,等於有一件事憑空消失。 */
function overlapsWith(iso, start, mins, ignoreKey) {
  return placed(iso).filter((p) =>
    p.key !== ignoreKey && start < p.start + p.min && p.start < start + mins).length;
}

/* 把一天的區塊分成「互相重疊的一叢」,每一叢裡面各佔一個直欄。 */
function layout(items) {
  const sorted = [...items].sort((a, b) => a.start - b.start || b.min - a.min);
  let cluster = [];
  let clusterEnd = -1;
  const flush = () => {
    if (!cluster.length) return;
    const laneEnds = [];
    cluster.forEach((it) => {
      let lane = laneEnds.findIndex((end) => end <= it.start);
      if (lane === -1) { laneEnds.push(0); lane = laneEnds.length - 1; }
      laneEnds[lane] = it.start + it.min;
      it.col = lane;
    });
    cluster.forEach((it) => { it.cols = laneEnds.length; });
    cluster = [];
    clusterEnd = -1;
  };
  sorted.forEach((it) => {
    if (cluster.length && it.start >= clusterEnd) flush();
    cluster.push(it);
    clusterEnd = Math.max(clusterEnd, it.start + it.min);
  });
  flush();
  return sorted;
}

/* ── 寫 ─────────────────────────────────────────────────────────── */
async function patchTask(id, detail, why) {
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}/nodes/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ detail, by: why }),
  });
  if (!r.ok) {
    toast("存不進去:" + ((await r.json().catch(() => ({}))).detail || r.status), true);
    return false;
  }
  return true;
}

async function saveBlocks(iso) {
  const day = dayOf(iso);
  const r = await fetch(`/api/day/${iso}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks: day ? day.blocks : [] }),
  });
  if (!r.ok) toast("日常區塊存不進去", true);
  return r.ok;
}

/* 排程存成一個陣列:[{uid, at, min}]。同一件事可以切成好幾段。
   ⛔ 一定要把整個陣列傳回去(PATCH 是整欄覆寫),不能只傳改動的那一段。 */
/* ⚠️ 一定要用**伺服器給的完整 planned**,不是畫面上看得到的那幾段 ——
   排在畫面外(捲出去的那幾週)的段落也在裡面,漏掉的話拖一下就把它們洗掉了。 */
const slotsOf = (task) => (task.planned || []).map((s2) => ({ ...s2 }));

async function writeSlots(taskId, slots, why, msg) {
  const ok = await patchTask(taskId, {
    planned: slots, plannedAt: null, plannedMin: null,  // 順手清掉舊格式
  }, why);
  if (ok) { if (msg) toast(msg); load(true); }
  return ok;
}

async function placeTask(task, iso, startMin, mins, slotUid) {
  const at = `${iso}T${toHHMM(startMin)}`;
  const slots = slotsOf(task).filter((s2) => s2.uid !== slotUid);
  slots.push({ uid: slotUid || uid(), at, min: mins });
  await writeSlots(task.id, slots, `${iso} ${toHHMM(startMin)} 排上行程`,
    `${task.topic} → ${iso.slice(5)} ${toHHMM(startMin)}`);
}

async function unplaceSlot(task, slotUid) {
  const slots = slotsOf(task).filter((s2) => s2.uid !== slotUid);
  await writeSlots(task.id, slots, "從行程拿掉一段", `「${task.topic}」拿掉那一段了`);
}

/* ── 這一天的時間花在哪些分類上 ──────────────────────────────────
   使用者的需求(2026-08-17):「你有幫我去做各個項目的分類,那你可以在這個我每天安排的這個行程的
   最上面或最下面幫我寫一個,所以我這一天總共花了多少時間在做哪個分別分類的事情。」

   ⛔ 分類**只有**兩組、而且不合併:
     · 任務 → 領域(domain),顏色沿用 colorOf()
     · 日常區塊 → 範本(吃飯/運動/語言學習…),顏色沿用範本自己的
   「語言學習(日常)」跟「Language(領域)」是兩件不同的事,自動併成一類會讓數字對不上
   任何一份原始資料。⛔ 也不准把排程那套分軌搬進來當分類 —— 這一頁刻意沒有它(見檔頭)。
   ⛔ 這是每次重畫當場算的衍生值,不存回任何地方(沒有第二份資料)。 */
const DAY_MIN = 24 * 60;
/* Google 行事曆抓下來的事件(2026-08-22 使用者要的:「行事曆有什麼活動,他也可以卡住我的行程表」)。
   ⛔ 這些格子不能拖、不能刪、不能拉長度 —— 它們不是我們的資料。要改去 Google 行事曆改。
   單向:行事曆進來卡時段,我們的待辦永遠不寫回去。 */
const CAL_COLOR = "#868e96";
const calMins = (e) => {
  const a = fromHHMM(e.start);
  const b = fromHHMM(e.end);
  return b > a ? b - a : DAY_MIN - a;  // 跨午夜的只算到今天結束,剩下那截是明天的
};
const ROWS = 3;    // 摘要固定幾列。⛔ 列數一變高度就變,各欄的時間軸立刻對不齊
let sumOpen = null;
const fmtH = (m) => (m % 60 === 0 ? `${m / 60}h` : `${(m / 60).toFixed(1)}h`);

/* 跨過午夜的那一截不算在這一天 —— 23:30 排 60 分,有 30 分其實是明天的。 */
function clipped(startMin, mins) {
  const a = Math.max(0, Math.min(DAY_MIN, startMin));
  const b = Math.max(0, Math.min(DAY_MIN, startMin + mins));
  return b > a ? [a, b] : null;
}

function tally(day) {
  const rows = new Map();
  const spans = [];
  const add = (key, label, color, kind, seg) => {
    spans.push(seg);
    const r = rows.get(key) || { label, color, kind, min: 0 };
    r.min += seg[1] - seg[0];
    rows.set(key, r);
  };
  (day.scheduled || []).forEach((t) => {
    const seg = clipped(fromHHMM(t.slot.at.slice(11, 16)), t.slot.min);
    // 同一件事同一天切成兩段 → 累加,⛔ 不是拿 totalMin(那是整件事的量,會重複計)
    if (seg) add("t:" + t.domain, t.domain || "(沒填領域)", colorOf(t.domain), "task", seg);
  });
  (day.blocks || []).forEach((b) => {
    const tpl = state.templates.find((x) => x.id === b.tpl);
    const seg = clipped(fromHHMM(b.start), b.min);
    if (seg) {
      // 範本被刪掉的孤兒:名字要短到塞得下半欄,⛔ 又不能假裝它不存在(時數是真的佔掉了)
      add("b:" + b.tpl,
          tpl ? `${tpl.emoji || ""} ${tpl.name}`.trim() : `⚠️ ${b.tpl}`,
          tpl ? tpl.color : "#868e96", "daily", seg);
    }
  });
  const allDay = [];
  (day.events || []).forEach((e) => {
    // 整天的事件不佔鐘點 —— 它沒有「幾點到幾點」可以畫,改成標頭的 🗓 讓使用者一眼看到
    if (e.allDay) { allDay.push(e); return; }
    const seg = clipped(fromHHMM(e.start), calMins(e));
    if (seg) add("c:cal", "🗓 行事曆", CAL_COLOR, "cal", seg);
  });
  const invest = spans.reduce((a, s) => a + s[1] - s[0], 0);
  /* 這一頁刻意允許同一時段疊好幾件事(使用者要的)。所以「各段加起來」會比
     「這天真的被佔掉多久」多 —— 兩個數不一樣,⛔ 不能只給一個然後叫它「這天花了幾小時」。 */
  let occupy = 0;
  let end = -1;
  [...spans].sort((a, b) => a[0] - b[0]).forEach(([s, e]) => {
    occupy += Math.max(0, e - Math.max(s, end));
    end = Math.max(end, e);
  });
  const list = [...rows.values()].sort((a, b) =>
    (a.kind === b.kind ? 0 : a.kind === "task" ? -1 : 1)
    || b.min - a.min || a.label.localeCompare(b.label, "zh-Hant"));
  return { list, invest, overlap: invest - occupy, allDay };
}

function tallyCell(r) {
  const c = el("div", "cell " + r.kind);
  const dot = el("i");
  dot.style.background = r.color;
  c.appendChild(dot);
  c.appendChild(el("span", "nm", r.label));
  c.appendChild(el("span", "mn", fmtH(r.min)));
  return c;
}

/* ⚠️ 2026-08-17 第二版。第一版做成兩欄六格,使用者反映:「整個都擠在一起,字都被擠不見了」,
   而且放不下的那幾類收進 tooltip —— 使用者說「幫我滑上去根本就看不到哪四類」。
   → 改成**一欄**(一列一類,字有地方站),放不下的不藏進 tooltip,
     改成一列看得見的「全部 N 類 ▸」,**按下去列出全部**。
   ⛔ tooltip 不算「看得到」:要滑上去、要等、還會被螢幕邊緣切掉。 */
function tallyBox(sum, day) {
  const box = el("div", "tally");
  if (!sum.list.length) {
    box.appendChild(el("div", "none", "還沒排東西"));
    return box;
  }
  const over = sum.list.length > ROWS;
  (over ? sum.list.slice(0, ROWS - 1) : sum.list).forEach((r) => box.appendChild(tallyCell(r)));
  if (over) {
    const more = el("div", "cell all");
    // 這裡放**整天的總數**而不是「剩下那幾類的和」—— 標題寫「全部 N 類」,
    // 旁邊卻是一個算不出來的數字,只會讓使用者更困惑
    more.appendChild(el("span", "nm", `全部 ${sum.list.length} 類 ▸`));
    more.appendChild(el("span", "mn", fmtH(sum.invest)));
    box.appendChild(more);
  }
  box.title = "按一下看這天的完整分類";
  box.onclick = (e) => { e.stopPropagation(); openSumPop(day, sum, box); };
  return box;
}

/* 這天的完整分類 —— 放不下的那幾類住這裡,⛔ 不是住 tooltip。 */
function openSumPop(day, sum, anchor) {
  closeEditor();
  const old = $("sumpop");
  if (old) old.remove();
  if (sumOpen === day.date) { sumOpen = null; return; }
  sumOpen = day.date;
  const pop = el("div", "pop");
  pop.id = "sumpop";
  const head = el("div", "hd");
  head.appendChild(el("b", null, `${day.date.slice(5).replace("-", "/")}(${day.weekday}) 這天的時間`));
  const x = el("button", "x", "✕");
  x.onclick = () => { sumOpen = null; pop.remove(); };
  head.appendChild(x);
  pop.appendChild(head);

  const list = el("div", "sumlist");
  sum.list.forEach((r) => list.appendChild(tallyCell(r)));
  pop.appendChild(list);

  const foot = el("div", "sumfoot");
  foot.appendChild(el("div", null, `各段加起來 ${fmtMin(sum.invest)}`));
  if (sum.overlap) {
    foot.appendChild(el("div", "warn",
      `其中 ${fmtMin(sum.overlap)} 是同一個時段排了不只一件事(被算了兩次)`));
    foot.appendChild(el("div", null, `這天真的被佔掉 ${fmtMin(sum.invest - sum.overlap)}`));
  }
  foot.appendChild(el("div", "dim2", "⛔ 已經標完成的任務不算在裡面"));
  pop.appendChild(foot);

  document.body.appendChild(pop);
  placePop(pop, anchor.getBoundingClientRect());
}

/* ── 一天一欄 ───────────────────────────────────────────────────── */
function frame(startMin, mins, color, col, cols) {
  const n = cols || 1;
  const box = el("div", "blk" + (mins <= 30 ? " short" : "") + (n > 2 ? " narrow" : ""));
  box.style.top = px(startMin) + "px";
  box.style.height = Math.max(18, px(mins) - 2) + "px";
  box.style.color = color;
  // 疊在一起的並排放,不是互相蓋住
  box.style.left = `calc(${((col || 0) / n) * 100}% + 3px)`;
  box.style.width = `calc(${100 / n}% - 6px)`;
  box.style.right = "auto";
  box.draggable = true;
  return box;
}

/* 下緣拉長度。⚠️ 不用 HTML5 drag(那個抓不到即時座標),用 pointer 事件。 */
function grip(commit, curMin) {
  const g = el("div", "grip");
  g.title = "上下拉可以改長度";
  g.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const box = g.parentElement;
    const startY = e.clientY;
    const perMin = px(1);
    let mins = curMin;
    const move = (ev) => {
      mins = Math.max(SNAP, snap(curMin + (ev.clientY - startY) / perMin));
      box.style.height = Math.max(18, px(mins) - 2) + "px";
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (mins !== curMin) commit(mins);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
  return g;
}

function taskBlock(t, iso, col, cols) {
  const startMin = fromHHMM(t.slot.at.slice(11, 16));
  const mins = t.slot.min;
  const box = frame(startMin, mins, colorOf(t.domain), col, cols);
  box.appendChild(el("div", "ttl", t.topic));
  const sub = el("div", "sub");
  if (t.pri) sub.appendChild(el("span", "pill " + t.pri, t.pri));
  // 排進去之後更看不出來這是誰的事(標題被裁成兩行),所以區塊上也要講
  sub.appendChild(el("span", "dom", whoseOf(t)));
  sub.appendChild(el("span", null, `${toHHMM(startMin)}–${toHHMM(startMin + mins)}`));
  if (t.due && iso > t.due) sub.appendChild(el("span", "late", `⚠️ 死線 ${t.due} 已過`));
  else if (t.due) sub.appendChild(el("span", null, "⏰" + t.due.slice(5)));
  box.appendChild(sub);
  box.title = `${toHHMM(startMin)}–${toHHMM(startMin + mins)}　這段 ${fmtMin(mins)}`
    + (t.due ? `\n⏰ 死線 ${t.due}` : "")
    + `\n\n${originOf(t)}`;

  box.dataset.slot = t.slot.uid;   // 浮動編輯面板靠這個找回它黏在哪一塊

  const x = el("button", "x", "✕");
  x.title = "只拿掉這一段(這件事還會留在右邊)";
  x.onclick = (e) => { e.stopPropagation(); unplaceSlot(t, t.slot.uid); };
  box.appendChild(x);

  /* ✎ = 排進去之後照樣能改。⚠️ 擠成好幾欄時 ✕ 會被藏起來(CSS),但 ✎ 一定要留著
     —— 面板裡有「從行程拿掉」,所以藏掉 ✕ 不會少一條路;藏掉 ✎ 就沒得改了。 */
  const pen = el("button", "pen", "✎");
  pen.title = "改時間／等級／到期日／狀態";
  pen.onclick = (e) => {
    e.stopPropagation();
    if (editing && editing.slotUid === t.slot.uid) return closeEditor();
    editing = { slotUid: t.slot.uid };
    return renderEditor();
  };
  box.appendChild(pen);
  box.appendChild(grip((newMin) => placeTask(t, iso, startMin, newMin, t.slot.uid), mins));

  box.addEventListener("dragstart", (e) => {
    closeEditor();   // 拖走了就別讓面板停在原地指著空氣
    drag = { kind: "move", task: t, mins, key: "t:" + t.slot.uid, slotUid: t.slot.uid,
             from: iso, grabMin: grabMinOf(e, box) };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", t.id);
    box.classList.add("dragging");
  });
  box.addEventListener("dragend", () => { box.classList.remove("dragging"); drag = null; clearGhost(); });
  return box;
}

function dailyBlock(b, iso, col, cols) {
  const tpl = state.templates.find((x) => x.id === b.tpl) || { name: b.tpl, color: "#868e96" };
  const startMin = fromHHMM(b.start);
  const box = frame(startMin, b.min, tpl.color, col, cols);
  box.appendChild(el("div", "ttl", `${tpl.emoji || ""} ${tpl.name}`.trim()));
  box.appendChild(el("div", "sub", `${b.start}–${toHHMM(startMin + b.min)}`));

  const x = el("button", "x", "✕");
  x.title = "拿掉這一塊";
  x.onclick = async (e) => {
    e.stopPropagation();
    const day = dayOf(iso);
    day.blocks = day.blocks.filter((o) => o.uid !== b.uid);
    if (await saveBlocks(iso)) { toast(`拿掉「${tpl.name}」`); load(true); }
  };
  box.appendChild(x);
  box.appendChild(grip(async (newMin) => {
    b.min = newMin;
    if (await saveBlocks(iso)) load(true);
  }, b.min));

  box.addEventListener("dragstart", (e) => {
    drag = { kind: "moveBlock", block: b, mins: b.min, key: "b:" + b.uid,
             from: iso, grabMin: grabMinOf(e, box) };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", b.uid);
    box.classList.add("dragging");
  });
  box.addEventListener("dragend", () => { box.classList.remove("dragging"); drag = null; clearGhost(); });
  return box;
}

/* 行事曆的一格。⚠️ 刻意跟任務長得不一樣(灰色、虛線邊、沒有任何按鈕):
   看到就知道「這段被別的事佔走了,不是我排的,也不能在這裡改」。 */
function calBlock(ev, col, cols) {
  const box = frame(fromHHMM(ev.start), calMins(ev), CAL_COLOR, col, cols);
  box.classList.add("cal");
  box.draggable = false;
  box.title = `${ev.title}\n${ev.start}–${ev.end}`
    + `\n來自 Google 行事曆${ev.cal ? "(" + ev.cal + ")" : ""}`
    + "\n要改請去 Google 行事曆改,這裡改不了";
  box.appendChild(el("div", "ttl", `🗓 ${ev.title}`));
  box.appendChild(el("div", "sub", `${ev.start}–${ev.end}`));
  return box;
}

/* ✅ 已完成的一格。淡色、標題劃掉,一眼看得出「這件做完了」。
   ⚠️ 它**不算進那一欄的時數統計** —— 卡片上一直寫著「已經標完成的任務不算在裡面」,
   偷偷算進去等於改掉那個數字的意思。

   ⭐ 2026-09-17 改成跟沒做完的一樣能拖、能拉長度、能按 ✎ 打開、能按 ✕ 拿掉。
   使用者反映:「如果我今天這個任務完成的話,他就不能動到他了也不能刪除,
   如果是已經寫在排行程那邊的話,他完全打不開。」
   舊版(08-24)刻意做成「不能拖也不能刪」,理由是它只是紀錄 ——
   ⛔ 但那等於按錯完成就沒有回頭路,時間記錯也改不了。
   打開 ✎ 之後,狀態那排有「⏳」,按了就改回沒做完、回到右邊。 */
function doneBlock(t, col, cols) {
  const iso = t.slot.at.slice(0, 10);
  const box = taskBlock(t, iso, col, cols);
  box.classList.add("done");
  box.querySelector(".ttl").textContent = "✅ " + t.topic;
  const sub = box.querySelector(".sub");
  sub.textContent = "";
  sub.appendChild(el("span", null, t.doneOn ? `${t.doneOn} 完成` : "完成日不詳"));
  const startMin = fromHHMM(t.slot.at.slice(11, 16));
  sub.appendChild(el("span", null, `${toHHMM(startMin)}–${toHHMM(startMin + t.slot.min)}`));
  box.title = `${t.topic}\n排在 ${t.slot.at.replace("T", " ")}`
    + `\n✅ ${t.doneOn ? t.doneOn + " 標完成" : "標完成(沒記到哪天)"}`
    + "\n\n可以拖、拉長度、按 ✕ 拿掉;要改回沒做完,按 ✎ 再按「⏳」"
    + "\n放 7 天後會自動搬進「完成紀錄」,那之後就從那裡查";
  return box;
}

function dayColumn(day) {
  const isToday = day.date === todayISO();
  const col = el("section", "daycol" + (isToday ? " today" : ""));
  col.dataset.date = day.date;

  const head = el("header");
  const top = el("div", "top");
  top.appendChild(el("b", null, day.date.slice(5).replace("-", "/")));
  top.appendChild(el("span", "dow", `（${day.weekday}）` + (isToday ? " 今天" : "")));
  const sum = tally(day);
  const h = el("span", "h", sum.invest ? fmtH(sum.invest) : "");
  h.title = sum.invest
    ? `各段加起來 ${fmtMin(sum.invest)}`
      + (sum.overlap ? `\n其中 ${fmtMin(sum.overlap)} 是疊在一起的時段(被算了兩次)`
                       + `\n這天真的被佔掉 ${fmtMin(sum.invest - sum.overlap)}` : "")
      + "\n⛔ 已經標完成的任務不算在裡面"
    : "";
  top.appendChild(h);
  if (sum.overlap) {
    // 疊起來的時段被算了兩次 —— ⛔ 只給一個總數會讓使用者以為那天真的花了那麼久
    const ov = el("span", "ov", `⧉${fmtH(sum.overlap)}`);
    ov.title = `有 ${fmtMin(sum.overlap)} 是同一個時段排了不只一件事,上面那個總數把它算了兩次。`
      + `\n這天真的被佔掉的是 ${fmtMin(sum.invest - sum.overlap)}。`;
    top.appendChild(ov);
  }
  if (sum.allDay.length) {
    // 整天的事件(出遊、演唱會)—— 行程表那邊已經把這天算成整天沒空,這裡讓使用者看得到為什麼
    const chip = el("span", "cal-all", `🗓${sum.allDay.length > 1 ? sum.allDay.length : ""}`);
    chip.title = sum.allDay.map((e) => `${e.title}(整天)`).join("\n")
      + "\n來自 Google 行事曆,這天排程不排事情";
    top.appendChild(chip);
  }
  const dump = el("button", "dump", "↩");
  dump.title = "這天排的任務全部丟回右邊的任務池(日常區塊不動)";
  dump.onclick = () => dumpDay(day);
  top.appendChild(dump);
  head.appendChild(top);
  head.appendChild(tallyBox(sum, day));
  col.appendChild(head);

  const grid = el("div", "grid");
  grid.dataset.date = day.date;
  grid.style.height = px(24 * 60) + "px";  // 時間線是 CSS 背景畫的,這裡不放 div
  // 先算好誰跟誰疊在一起、各佔第幾欄,再畫 —— 不算的話後畫的會蓋住先畫的
  const laid = layout([
    ...day.scheduled.map((t) => ({
      kind: "task", ref: t, start: fromHHMM(t.slot.at.slice(11, 16)), min: t.slot.min,
    })),
    ...day.blocks.map((b) => ({
      kind: "daily", ref: b, start: fromHHMM(b.start), min: b.min,
    })),
    ...(day.events || []).filter((e) => !e.allDay).map((e) => ({
      kind: "cal", ref: e, start: fromHHMM(e.start), min: calMins(e),
    })),
    ...(showDone ? (day.done || []) : []).map((t) => ({
      kind: "done", ref: t, start: fromHHMM(t.slot.at.slice(11, 16)), min: t.slot.min,
    })),
  ]);
  laid.forEach((it) => {
    if (it.kind === "task") grid.appendChild(taskBlock(it.ref, day.date, it.col, it.cols));
    else if (it.kind === "cal") grid.appendChild(calBlock(it.ref, it.col, it.cols));
    else if (it.kind === "done") grid.appendChild(doneBlock(it.ref, it.col, it.cols));
    else grid.appendChild(dailyBlock(it.ref, day.date, it.col, it.cols));
  });
  if (isToday) {
    const now = new Date();
    const line = el("div", "now");
    line.style.top = px(now.getHours() * 60 + now.getMinutes()) + "px";
    grid.appendChild(line);
  }
  wireDrop(grid, day.date);
  col.appendChild(grid);
  return col;
}

/* ── 右邊 ───────────────────────────────────────────────────────── */
const PRIS = ["P1", "P2", "P3", "P4"];
const STATUSES = [
  { mark: "⏳", label: "還沒開始" },
  { mark: "🔜", label: "正在做" },
  { mark: "⏸️", label: "等別人/等你決定" },
  { mark: "✅", label: "完成" },
];

/* 池子裡直接改東西 —— 使用者的需求是:「不知道能不能讓我連這個地方也能直接編輯裡面的內容?
   例如編輯它的狀態、優先序、需要花多久時間、到期日等。」
   ⚠️ 狀態要改 topic(狀態是寫在標題開頭的圖示),不能走只准改 detail 的 PATCH。 */
async function setPri(t, pri) {
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}`);
  const out = await r.json();
  let hit = null;
  const find = (n) => { if (n.id === t.id) hit = n; (n.children || []).forEach(find); };
  find(out.data.nodeData);
  if (!hit) return toast("那個節點不在圖上了", true);
  hit.tags = (hit.tags || []).filter((x) => !PRIS.includes(x)).concat(pri ? [pri] : []);
  delete hit.aiEdited;
  hit.scEdited = `${todayISO()} 在排行程改了等級`;
  const put = await fetch(`/api/maps/${encodeURIComponent(MAP)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: out.data, base_mtime: out.mtime }),
  });
  if (!put.ok) return toast(put.status === 409 ? "圖被別人改過了,重新整理再試" : "存不進去", true);
  load(true);
}

async function setStatus(t, mark) {
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}`);
  const out = await r.json();
  let hit = null;
  const find = (n) => { if (n.id === t.id) hit = n; (n.children || []).forEach(find); };
  find(out.data.nodeData);
  if (!hit) return toast("那個節點不在圖上了", true);
  let topic = (hit.topic || "").trim();
  for (const m of ["⏳", "🔜", "⏸️", "⏸", "✅", "🎯"]) {
    if (topic.startsWith(m)) { topic = topic.slice(m.length).trim(); break; }
  }
  const wasDone = (hit.topic || "").trim().startsWith("✅");
  hit.topic = `${mark} ${topic}`.trim();
  /* ⚠️ 完成日一定要在打勾的當下寫下來(2026-08-24 補的,以前這頁根本沒寫)。
     任務板一直有寫,這頁沒有 —— 於是在這裡打的勾,「哪天做完的」就沒人知道了,
     要等 7 天後 janitor 幫它補一個「今天」,那個日期是錯的。
     使用者反映:「沒有辦法看到我到底這個東西是什麼時候做完的。」 */
  const det = hit.detail || (hit.detail = {});
  if (mark !== "✅") delete det.doneOn;
  else if (!wasDone || !det.doneOn) det.doneOn = todayISO();
  delete hit.aiEdited;
  hit.scEdited = `${todayISO()} 在排行程改了狀態`;
  const put = await fetch(`/api/maps/${encodeURIComponent(MAP)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: out.data, base_mtime: out.mtime }),
  });
  if (!put.ok) return toast(put.status === 409 ? "圖被別人改過了,重新整理再試" : "存不進去", true);
  toast(`「${t.topic}」→ ${STATUSES.find((x) => x.mark === mark).label}`);
  load(true);
}

/* ❌ 不做了 —— 一顆事情的第二條出路(2026-08-22 使用者問「應該也有取消任務吧」)。
   ⚠️ 在這之前畫面上只有「完成」一個出口 → 不想做的事只能硬標完成
   (完成紀錄會多一筆從沒做過的事)或爛在圖上,兩個都會讓之後查「這件事做了沒」查到假的。
   ⛔ 一定要問理由:一年後看到「這件事不做了」而沒有理由等於沒有紀錄,
   下一輪規劃時它會原封不動地被重新提出來,然後再評估一次。
   ⛔ 這條路會把節點從圖上移走 → 一定要二次確認,而且理由空白就不送。 */
async function dropTask(t) {
  const why = window.prompt(
    `要把「${t.topic}」標成「不做了」嗎?\n\n`
    + "它會從圖上移走,連同下面這個理由一起記進「完成紀錄」,以後查得到。\n"
    + "⛔ 這不是「完成」—— 完成紀錄那邊會標成 ❌ 不做了。\n\n"
    + "為什麼不做了?(一定要寫)", "");
  if (why === null) return;                       // 按取消
  if (!why.trim()) return toast("要寫理由才送得出去", true);
  const r = await fetch(
    `/api/maps/${encodeURIComponent(MAP)}/nodes/${encodeURIComponent(t.id)}/drop`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ why: why.trim() }) });
  if (!r.ok) {
    const out = await r.json().catch(() => ({}));
    return toast(out.detail || "送不出去", true);
  }
  toast(`「${t.topic}」→ ❌ 不做了(理由已記進完成紀錄)`);
  load(true);
}

/* 等級／到期日／狀態 —— **池子的卡片與行事曆上的區塊共用同一組控制項**。
   ⛔ 不准複製第二份到別的地方:兩份遲早長不一樣,使用者就會在某一邊找不到某個欄位。 */
function editRows(t) {
  const row0 = el("div", "row name");
  const name = el("input", "rename");
  name.type = "text";
  name.value = t.topic || "";
  name.title = "改這件事的名字(心智圖那邊也會跟著改)";
  name.onkeydown = (e) => { if (e.key === "Enter") e.target.blur(); };
  name.onchange = () => setTopic(t, name.value);
  row0.appendChild(lab("✏️", name));

  const row1 = el("div", "row");
  PRIS.forEach((v) => {
    const b = el("button", "pri-btn " + v + (t.pri === v ? " on" : ""), v);
    b.title = t.pri === v ? "再按一次拿掉等級" : `改成 ${v}`;
    b.onclick = (e) => { e.preventDefault(); setPri(t, t.pri === v ? "" : v); };
    row1.appendChild(b);
  });

  /* ⛔ 這裡刻意沒有「要花多久」—— 使用者 2026-08-30 定案從排行程拿掉。
     欄位還在,心智圖與任務板改得到,只是這一頁不看它。 */
  const row2 = el("div", "row");
  const due = el("input");
  due.type = "date";
  due.value = t.due || "";
  due.title = "到期日(⛔ 只填別人給的日期)";
  due.onchange = () => patchTask(t.id, { due: due.value || null }, "在排行程改了到期日").then(() => load(true));
  row2.appendChild(lab("⏰", due));

  const row3 = el("div", "row");
  STATUSES.filter((x) => x.mark !== t.status).forEach((x) => {
    const b = el("button", "st-btn", x.mark + " " + x.label);
    b.onclick = (e) => { e.preventDefault(); setStatus(t, x.mark); };
    row3.appendChild(b);
  });
  const drop = el("button", "st-btn drop-btn", "❌ 不做了");
  drop.title = "決定不做這件事了 —— 會從圖上移走,理由記進完成紀錄(不是標成完成)";
  drop.onclick = (e) => { e.preventDefault(); dropTask(t); };
  row3.appendChild(drop);
  return [row0, row1, row2, row3];
}

/* ── 排進去之後也要能改 ─────────────────────────────────────────────
   使用者的需求(2026-08-17):「我東西排進去之後我就不能夠再去編輯了,變成說我要先把它拉回去
   再選的畫面,然後再去編輯,很麻煩。我希望我拉過去的時候就可以編輯了。」

   ⛔ 不能做成「在區塊裡面展開」——**區塊的高度就是它的時間長度**,15 分鐘的塊只有
   20px,編輯列有三行、展不開;硬撐開又會把它畫成假的時間長度。
   → 浮在上面的小面板,黏在那個區塊旁邊。捲動時跟著移動;那個區塊不見了(被拿掉、
     標成完成、捲出載入範圍)就自己關掉,⛔ 不留一個對不到任何東西的面板在畫面上。 */
const LENGTHS = [15, 30, 45, 60, 90, 120, 180, 240, 300, 360, 480];
let editing = null;   // { slotUid }

function closeEditor() {
  editing = null;
  const p = $("editpop");
  if (p) p.remove();
}

/* 這一段現在還在不在、在哪一天 —— 每次重畫都要重問,不能記著舊物件。 */
function findSlot() {
  for (const d of state.days) {
    // ⚠️ 已完成的在 d.done,不在 d.scheduled —— 只找 scheduled 的話,
    //    已完成的方塊按 ✎ 永遠打不開(2026-09-17 使用者回報「完全打不開」)。
    const hit = d.scheduled.find((t) => t.slot.uid === editing.slotUid)
      || (d.done || []).find((t) => t.slot.uid === editing.slotUid);
    if (hit) return { t: hit, iso: d.date };
  }
  return null;
}

/* 浮動面板黏在某個東西旁邊。預設放右邊;右邊塞不下翻到左邊,
   最後一定夾進畫面內 —— 不夾的話會有一半在視窗外,等於看不到。 */
function placePop(pop, r) {
  const w = pop.offsetWidth;
  const h = pop.offsetHeight;
  let left = r.right + 8;
  if (left + w > window.innerWidth - 8) left = r.left - w - 8;
  pop.style.left = Math.max(8, Math.min(left, window.innerWidth - w - 8)) + "px";
  pop.style.top = Math.max(8, Math.min(r.top, window.innerHeight - h - 8)) + "px";
}

function placeEditor() {
  const pop = $("editpop");
  const anchor = document.querySelector(`.blk[data-slot="${CSS.escape(editing.slotUid)}"]`);
  if (!pop || !anchor) return closeEditor();
  /* 區塊被捲出可視範圍就關掉。⛔ 不能只把面板夾進畫面 —— 那會變成一個黏在角落、
     指著看不到的東西的面板,使用者改了半天不知道自己在改哪一件。 */
  const r = anchor.getBoundingClientRect();
  const box = $("left").getBoundingClientRect();
  if (r.bottom < box.top || r.top > box.bottom || r.right < box.left || r.left > box.right) {
    return closeEditor();
  }
  placePop(pop, r);
  return undefined;
}

function renderEditor() {
  if (!editing) return;
  const found = findSlot();
  if (!found) return closeEditor();
  const { t, iso } = found;
  let pop = $("editpop");
  if (!pop) {
    pop = el("div", "pop");
    pop.id = "editpop";
    document.body.appendChild(pop);
  }
  pop.innerHTML = "";
  pop.style.color = colorOf(t.domain);

  const head = el("div", "hd");
  const nameBox = el("div", "who");
  nameBox.appendChild(el("div", "path", t.path || t.domain));
  nameBox.appendChild(el("b", null, t.topic));
  head.appendChild(nameBox);
  const close = el("button", "x", "✕");
  close.title = "關閉(Esc 也可以)";
  close.onclick = closeEditor;
  head.appendChild(close);
  pop.appendChild(head);

  /* 使用者的需求(2026-08-17):「我應該要知道這個東西是為了什麼做的…不然我在拉動我的個人任務的時候
     我不知道這什麼東西。」→ 理由就放在使用者正在拖的東西旁邊,⛔ 不要叫使用者自己跑回心智圖找。 */
  const why = el("div", "why" + (t.explain ? "" : " empty"));
  why.textContent = t.explain || "這件事還沒寫「為什麼」—— 去心智圖補一句,以後你就看得懂它了。";
  pop.appendChild(why);

  const startMin = fromHHMM(t.slot.at.slice(11, 16));
  const when = el("div", "row");
  // ⚠️ 面板上會出現兩個日期(排哪天做 / 到期日),不標一下使用者分不出來
  when.appendChild(el("span", "note", "這一段"));
  const dt = el("input");
  dt.type = "date";
  dt.value = iso;
  dt.title = "換一天做(⛔ 這是「排哪天做」,不是到期日)";
  dt.onchange = () => dt.value && placeTask(t, dt.value, startMin, t.slot.min, t.slot.uid);
  when.appendChild(lab("🗓", dt));

  const tm = el("input");
  tm.type = "time";
  tm.step = SNAP * 60;
  tm.value = toHHMM(startMin);
  tm.title = "幾點開始";
  tm.onchange = () => tm.value
    && placeTask(t, iso, snap(fromHHMM(tm.value)), t.slot.min, t.slot.uid);
  when.appendChild(lab("🕐", tm));

  const len = el("select");
  len.title = "這一段做多久(拉區塊下緣也可以)";
  [...new Set(LENGTHS.concat(t.slot.min))].sort((a, b) => a - b).forEach((v) => {
    const o = el("option", null, fmtMin(v));
    o.value = v;
    if (v === t.slot.min) o.selected = true;
    len.appendChild(o);
  });
  len.onchange = () => placeTask(t, iso, startMin, Number(len.value), t.slot.uid);
  when.appendChild(lab("⏳", len));
  pop.appendChild(when);

  editRows(t).forEach((r) => pop.appendChild(r));

  const foot = el("div", "row foot");
  foot.appendChild(el("span", "note", t.status === "✅"
    ? `這件已經完成・排了 ${(t.planned || []).length} 段・按上面「⏳」可以改回沒做完`
    : `這件事排了 ${(t.planned || []).length} 段・按「✅ 完成」才會離開右邊`));
  const off = el("button", "st-btn", "↩ 從行程拿掉");
  off.title = "只拿掉這一段,這件事還會留在右邊";
  off.onclick = () => { const u = t.slot.uid; closeEditor(); unplaceSlot(t, u); };
  foot.appendChild(off);
  pop.appendChild(foot);

  placeEditor();
  return undefined;
}

/* 面板開著的時候:捲動跟著移、Esc 關、點到別的地方關。
   ⛔ 捲動不做成「自動關閉」——使用者捲一下就要重開,那又變成另一種麻煩。 */
$("left").addEventListener("scroll", () => { if (editing) placeEditor(); }, { passive: true });
window.addEventListener("resize", () => { if (editing) placeEditor(); });
function closeSumPop() {
  sumOpen = null;
  const p = $("sumpop");
  if (p) p.remove();
}

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeEditor(); closeSumPop(); }
});
document.addEventListener("pointerdown", (e) => {
  const pop = $("editpop");
  if (editing && pop && !pop.contains(e.target) && !e.target.closest(".blk .pen")) closeEditor();
  const sp = $("sumpop");
  if (sp && !sp.contains(e.target) && !e.target.closest(".tally")) closeSumPop();
});

/* 這件事是「誰的」——路徑最後一段(通常就是那個專案)。頂層待辦沒有專案就退回領域。 */
function whoseOf(t) {
  const parts = (t.path || "").split(" › ").filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 1] : (t.domain || "");
}

/* 領域標籤(2026-09-17)。使用者的需求:「我會希望我在直接看的時候,我會知道這個東西是屬於什麼領域的。」
   08-17 那次卡片只放專案,理由寫「領域那層太粗,顏色已經在講了」——
   ⛔ 但顏色要先記得哪個顏色是哪個領域,使用者看不出來。專案照樣留著,領域另外用字標出來,
   放在等級後面:跟待辦事項頁同一個順序(優先區 → 分類 → 內容,09-08 定案)。 */
function domTag(domain) {
  const tag = el("span", "dtag", domain || "未分類");
  tag.style.color = colorOf(domain);
  return tag;
}

/* 專案那一格:跟領域同名時就不再重複一次(直接掛在領域底下的事) */
function whoseTag(t) {
  const w = whoseOf(t);
  return w && w !== t.domain ? el("span", "dom", w) : null;
}

/* 滑上去要看得到完整來歷與理由 —— 卡片上只放得下一行。 */
function originOf(t) {
  return `${t.path || t.domain}\n${t.topic}`
    + (t.explain ? `\n\n為什麼:\n${t.explain}` : "\n\n(這件事還沒寫為什麼)");
}

/* 改標題。使用者的需求(2026-08-18):「我在排今天這邊能不能也修改一下標題文字,
   那他修改之後也會連動到心智圖。」—— 本來就是同一顆節點,寫回去就是改圖。
   ⚠️ 走整張圖的 PUT(跟改等級/狀態同一條路):`topic` 不在 PATCH 的白名單裡,
   它不是 detail 的欄位。⛔ 也不要為了這個去放寬那個白名單 —— 那是防「亂改節點」的閘門。
   ⚠️ 狀態圖示在標題最前面,改名時要原樣接回去,不然 ⏳/✅ 會被洗掉。 */
async function setTopic(t, text) {
  const want = (text || "").trim();
  if (!want || want === (t.topic || "").trim()) return;
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}`);
  const out = await r.json();
  let hit = null;
  const find = (n) => { if (n.id === t.id) hit = n; (n.children || []).forEach(find); };
  find(out.data.nodeData);
  if (!hit) return toast("那個節點不在圖上了", true);
  let mark = "";
  for (const m of ["⏳", "🔜", "⏸️", "⏸", "✅", "🎯", "♾️"]) {
    if ((hit.topic || "").trim().startsWith(m)) { mark = m; break; }
  }
  hit.topic = `${mark} ${want}`.trim();
  delete hit.aiEdited;
  hit.scEdited = `${todayISO()} 在排行程改了標題`;
  const put = await fetch(`/api/maps/${encodeURIComponent(MAP)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: out.data, base_mtime: out.mtime }),
  });
  if (!put.ok) return toast(put.status === 409 ? "圖被別人改過了,重新整理再試" : "存不進去", true);
  toast("改好了,心智圖那邊也是這個名字");
  return load(true);
}

function poolItem(t) {
  const placed = (t.planned || []).length;
  const box = el("div", "item" + (t.due && t.due <= todayISO() ? " urgent" : ""));
  box.style.color = colorOf(t.domain);
  box.draggable = true;
  box.title = originOf(t);
  box.appendChild(el("div", "ttl", t.topic));

  const sub = el("div", "sub");
  /* ⚠️ 等級一定要在收起來的時候就看得見 —— 2026-08-11 曾經把它塞進編輯列裡,
     使用者反映:「他其他的東西被擋住了看不太到,我在想的是你至少把等級 P1~4 還是要能夠顯示出來」。
     池子預設就是照等級排的,看不到等級等於看不懂排序。 */
  sub.appendChild(el("span", "pill " + (t.pri || "none"), t.pri || "無"));
  sub.appendChild(domTag(t.domain));
  // 週期性/AI 的事在它們自己的選單裡,但拖到行事曆上還是要認得出來
  if (t.repeat) sub.appendChild(el("span", "rep", "🔁 " + t.repeat));
  if (t.owner === "ai") sub.appendChild(el("span", "rep", "🤖 AI"));
  if (t.status === "⏸️") sub.appendChild(el("span", "late", "⏸️ 等你決定"));
  if (t.status === "🔜") sub.appendChild(el("span", null, "🔜 進行中"));
  /* 已經放到時間軸上幾段、加起來多久。⛔ 不是「還剩多少」—— 這一頁沒有總時數了。
     它只回答「這件事我已經放過幾次」;拖幾次都不會讓它從這一區消失。 */
  if (placed) {
    sub.appendChild(el("span", "rest", `已排 ${placed} 段・共 ${fmtMin(t.used || 0)}`));
  }
  if (t.due) {
    const late = t.due < todayISO();
    const now = t.due === todayISO();
    sub.appendChild(el("span", late || now ? "late" : "",
      late ? `⏰${t.due.slice(5)} 已過期` : now ? "⏰今天到期" : "⏰" + t.due.slice(5)));
  }
  /* ⚠️ 顯示的是「哪個專案」不是「哪個領域」 —— 使用者的需求(2026-08-17):「你只有寫這個專案要做什麼
     事情…應該要把這是什麼專案然後要做什麼事情寫上去,我比較會知道這到底在幹嘛。」
     光看「排版與分類優化」不知道是誰的排版。
     ⚠️ 2026-09-17 起領域也用字標了(上面的 domTag),這裡只剩專案;同名就不重複。 */
  const who = whoseTag(t);
  if (who) sub.appendChild(who);

  /* 「✎」放在同一行的最右邊,不另外佔一行 —— 96 張卡片每張多一行就多 96 行。
     ⛔ 不用 <details>:它的 summary 一定是獨立一行,擠掉的正是使用者要看的資訊。 */
  const pen = el("button", "pen", "✎");
  pen.title = "改等級／到期日／狀態";
  const more = el("div", "edit");
  pen.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const open = more.classList.toggle("open");
    pen.classList.toggle("on", open);
  };
  sub.appendChild(pen);
  box.appendChild(sub);
  editRows(t).forEach((r) => more.appendChild(r));
  box.appendChild(more);

  box.addEventListener("dragstart", (e) => {
    drag = { kind: "task", task: t, mins: DEFAULT_BLOCK_MIN };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", t.id);
    box.classList.add("dragging");
  });
  box.addEventListener("dragend", () => { box.classList.remove("dragging"); drag = null; clearGhost(); });
  return box;
}

/* 排過去了、沒標完成的一張卡(2026-08-24 使用者問「為什麼心智圖有、排行程沒有」)。

   ⚠️ 2026-08-30 之後它同時也還在「待辦事項」那一區(按完成才離開),
   所以這一區不再是「不看就消失」,而是**「你排了卻沒做」的提醒** ——
   時間軸上那一塊躺在過去,而畫面預設從今天前三天開始,往左捲才看得到。
   ⛔ 這張卡一定要給得出出口,不能只是列出來讓使用者自己想辦法。 */
function staleItem(t) {
  const box = poolItem(t);
  box.classList.add("stale");
  const when = (t.lastAt || "").replace("T", " ").slice(5);
  const days = Math.round((new Date(todayISO()) - new Date((t.lastAt || "").slice(0, 10))) / 864e5);
  const tag = el("div", "sub");
  tag.appendChild(el("span", "late", `⏰ 排在 ${when},過了 ${days} 天`));
  box.insertBefore(tag, box.querySelector(".edit"));

  const acts = el("div", "sub");
  const move = el("button", "mini", "搬到今天");
  move.title = "同一個鐘點,日期換成今天";
  move.onclick = async (e) => {
    e.stopPropagation();
    const slots = slotsOf(t).map((s2) => ({ ...s2, at: `${todayISO()}T${s2.at.slice(11, 16)}` }));
    await writeSlots(t.id, slots, "在排行程搬到今天", `「${t.topic}」搬到今天`);
  };
  const back = el("button", "mini", "丟回待辦");
  back.title = "清掉排定的時段,回到「待辦事項」那一區重新排";
  back.onclick = async (e) => {
    e.stopPropagation();
    await writeSlots(t.id, [], "在排行程丟回待辦", `「${t.topic}」丟回待辦事項`);
  };
  acts.appendChild(move);
  acts.appendChild(back);
  acts.appendChild(el("span", "dim2", "或按 ✎ 標完成"));
  box.insertBefore(acts, box.querySelector(".edit"));
  return box;
}

function lab(icon, control) {
  const wrap = el("label", "f");
  wrap.appendChild(el("span", null, icon));
  wrap.appendChild(control);
  return wrap;
}

/* 語言學習的卡片住 🗣 專屬分頁(使用者 2026-08-18:「怎麼還放在待辦事項啊…是不是也要拿過去」)
   —— 待辦/週期/常設職責/等條件/AI 這些通用分頁一律不再列它們,
   同一張卡兩邊出現會讓池子數字虛胖、也讓使用者以為沒搬過去。 */
const isLang = (t) => t.domain === "Language";

/* 篩選 + 排序(使用者的需求:「能不能改成可以自訂其他篩選或排序方式?例如我只想看在 Work
   或 Finance 專案之類的」)。⛔ 只影響顯示,不動資料。 */
function visiblePool() {
  const dom = $("f-domain").value;
  const q = $("f-q").value.trim().toLowerCase();
  const onlyDue = $("f-due").checked;
  const onlyPart = $("f-part").checked;
  let list = state.pool.filter((t) => {
    if (isLang(t)) return false;
    if (dom && t.domain !== dom) return false;
    if (onlyDue && !t.due) return false;
    if (onlyPart && !(t.used > 0)) return false;
    if (q && !`${t.topic} ${t.path} ${t.domain}`.toLowerCase().includes(q)) return false;
    return true;
  });
  const byPri = (t) => (PRIS.includes(t.pri) ? PRIS.indexOf(t.pri) : 9);
  const byDue = (t) => t.due || "9999-99-99";
  const mode = $("f-sort").value;
  const cmp = {
    pri: (a, b) => byPri(a) - byPri(b) || byDue(a).localeCompare(byDue(b)),
    due: (a, b) => byDue(a).localeCompare(byDue(b)) || byPri(a) - byPri(b),
    placed: (a, b) => (b.used || 0) - (a.used || 0),
    unplaced: (a, b) => (a.used || 0) - (b.used || 0),
    topic: (a, b) => a.topic.localeCompare(b.topic, "zh-Hant"),
  }[mode];
  return list.sort(cmp);
}

function tplItem(tpl) {
  const box = el("div", "item");
  box.style.color = tpl.color;
  box.draggable = true;
  box.appendChild(el("div", "ttl", `${tpl.emoji || ""} ${tpl.name}`.trim()));
  const sub = el("div", "sub", `預設 ${tpl.min} 分・拖了不會消失`);
  if (tpl.kind === "duty") {
    // 常設職責要看得出「是誰的」,跟任務卡片同一個規矩(2026-08-17 使用者要求;領域 2026-09-17 加)
    sub.prepend(domTag(tpl.domain));
    const who = (tpl.path || "").split(" › ").pop();
    if (who && who !== tpl.domain) sub.appendChild(el("span", "dom", who));
    box.title = `${tpl.path}\n${tpl.name}`
      + (tpl.explain ? `\n\n為什麼:\n${tpl.explain}` : "")
      + "\n\n♾️ 這是常設職責:永遠不會完成,拖進去佔時間就好。\n"
      + "具體「這一輪要做什麼」掛在它底下,那個才會完成、才會歸檔。";
  }
  box.appendChild(sub);
  box.addEventListener("dragstart", (e) => {
    drag = { kind: "tpl", tpl, mins: tpl.min };
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData("text/plain", tpl.id);
    box.classList.add("dragging");
  });
  box.addEventListener("dragend", () => { box.classList.remove("dragging"); drag = null; clearGhost(); });
  return box;
}

/* AI 在做的:唯讀一行就好。⛔ 不用完整卡片 —— 使用者不會去拖、不會去改,
   給一堆可點的東西只是讓使用者以為那也是自己要做的。 */
/* 等條件的:重點是「在等什麼」,不是等級與死線 —— 那些現在都不成立。
   ⛔ 不能拖進行程(不知道哪天做得了),但要一鍵放行,不然使用者會忘了它存在。 */
function waitItem(t) {
  const box = el("div", "item wait");
  box.style.color = colorOf(t.domain);
  box.title = originOf(t);
  box.appendChild(el("div", "ttl", t.topic));
  const cond = el("div", "cond");
  cond.appendChild(el("span", null, "⏸️ 等:" + t.until));
  box.appendChild(cond);
  const sub = el("div", "sub");
  sub.appendChild(el("span", "pill " + (t.pri || "none"), t.pri || "無"));
  sub.appendChild(domTag(t.domain));
  const who = whoseTag(t);
  if (who) sub.appendChild(who);
  const go = el("button", "st-btn", "▶️ 條件成立了");
  go.title = "放回待辦事項";
  go.onclick = () => releaseTask(t);
  sub.appendChild(go);
  box.appendChild(sub);
  return box;
}

/* 條件成立 → 拿掉 until,它就回到待辦事項那一區。 */
async function releaseTask(t) {
  if (await patchTask(t.id, { until: null }, "等的條件成立了")) {
    toast(`「${t.topic}」回到待辦事項了`);
    load(true);
  }
}

function aiItem(t) {
  const box = el("div", "item ai");
  box.style.color = colorOf(t.domain);
  const name = t.topic || t.name || "";
  box.appendChild(el("div", "ttl", name));
  const sub = el("div", "sub");
  if (t.kind === "duty") sub.appendChild(el("span", "rep", "♾️ 一直在做"));
  else if (t.repeat) sub.appendChild(el("span", "rep", "🔁 " + t.repeat));
  sub.appendChild(el("span", "dom", (t.path || "").split(" › ").pop() || t.domain));
  box.appendChild(sub);
  box.title = `${t.path || t.domain}\n${name}`
    + (t.explain ? `\n\n為什麼:\n${t.explain}` : "")
    + "\n\n🤖 這是 AI 在做的,不佔你的時間。";
  return box;
}

/* 右邊的分頁(2026-08-18 使用者要求)。⛔ 不再用五疊摺疊區 ——
   那會讓每一種都只分到一小條,而且展開時互相把對方推出畫面。
   一次只顯示一種,那一種就拿到整個高度。 */
const TABS = [
  { id: "pool", label: "📋 待辦事項",
    tip: "會完成的一次性任務。排進行程不會讓它消失,按下完成才會離開這一區" },
  { id: "stale", label: "⏰ 排過去了沒做",
    tip: "排進行程但那天過了、也沒標完成 —— 你排了卻沒做的事" },
  { id: "lang", label: "🗣 語言學習", tip: "語言學習的讀書排程:每日積木、週期練習、單次任務集中在這裡" },
  { id: "reps", label: "🔁 週期性", tip: "做完會再來:每天/每週/每月/每年" },
  { id: "wait", label: "⏸️ 等條件", tip: "要等某件事發生才做得了(例:等換到新工作)" },
  { id: "duty", label: "♾️ 常設職責", tip: "永遠不會完成、要一直做的事" },
  { id: "tpl", label: "🧱 日常積木", tip: "吃飯、運動、通勤這種固定時段" },
  { id: "ai", label: "🤖 AI", tip: "AI 在做的,不佔你的時間" },
  { id: "legend", label: "🎨 顏色", tip: "行程上的顏色代表哪個領域" },
];
let tab = localStorage.getItem("day.tab") || "pool";

function showTab(id) {
  if (!TABS.some((t) => t.id === id)) id = "pool";
  tab = id;
  localStorage.setItem("day.tab", id);   // 介面偏好而已,⛔ 這裡不准放任務或時間
  TABS.forEach((t) => { $("tab-" + t.id).hidden = t.id !== id; });
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.tab === id);
  });
}

function renderTabs(counts) {
  const bar = $("tabs");
  bar.innerHTML = "";
  TABS.forEach((t) => {
    const b = el("button", "tab" + (t.id === tab ? " on" : ""));
    b.dataset.tab = t.id;
    b.title = t.tip;
    b.appendChild(el("span", null, t.label));
    if (counts[t.id] !== undefined) b.appendChild(el("span", "cnt", counts[t.id]));
    b.onclick = () => showTab(t.id);
    bar.appendChild(b);
  });
}

function fillPane(boxId, items) {
  const box = $(boxId);
  box.innerHTML = "";
  if (!items.length) box.appendChild(el("div", "empty", "（沒有）"));
  items.forEach((n) => box.appendChild(n));
}

function render() {
  $("date").value = state.date;

  const week = $("week");
  week.innerHTML = "";
  const gutter = el("div", "gutter");
  gutter.appendChild(el("header", null, ""));
  const ruler = el("div", "grid ruler");
  ruler.style.height = px(24 * 60) + "px";
  for (let h = 0; h < 24; h += 1) {
    const lb = el("span", "lbl", `${pad(h)}:00`);
    lb.style.top = px(h * 60) + "px";
    ruler.appendChild(lb);
  }
  gutter.appendChild(ruler);
  week.appendChild(gutter);
  state.days.forEach((d) => week.appendChild(dayColumn(d)));

  fillDomains();
  const pool = $("pool");
  pool.innerHTML = "";
  const shownPool = visiblePool();
  const basePool = state.pool.filter((t) => !isLang(t));   // 語言的不算,它們住 🗣 分頁
  if (!shownPool.length) {
    pool.appendChild(el("div", "empty",
      basePool.length ? "（這個條件下沒有東西）" : "（都做完了）"));
  }
  shownPool.forEach((t) => pool.appendChild(poolItem(t)));
  /* ⛔ 不再顯示「共幾小時」—— 那是拿「要花多久」加出來的,而那個欄位已經從這一頁
     退休了。這一區現在的意思是「還沒做完的事」,不是「還沒排掉的時數」。 */
  const poolNote = shownPool.length === basePool.length
    ? `${basePool.length} 件還沒做完(按完成才會離開這一區)`
    : `${shownPool.length}/${basePool.length} 件`;
  $("tab-pool").querySelector(".hint").textContent = poolNote;

  /* 三個獨立選單(2026-08-18 使用者要求)。⛔ 不要跟「還沒排進來」混在一起 ——
     一次性的才是「等你動手」;週期性的做完會再來、常設職責永遠不會完成、
     AI 的根本不該佔使用者的容量。混著看就分不出哪些是真的要使用者做。 */
  const life = state.templates.filter((t) => t.kind !== "duty");
  const duties = state.templates.filter((t) => t.kind === "duty");
  const genDuties = duties.filter((t) => !isLang(t));
  const genReps = state.repeats.filter((t) => !isLang(t));
  const genWaits = state.waiting.filter((t) => !isLang(t));
  const genAi = state.aiTasks.filter((t) => !isLang(t));
  const stale = (state.stale || []).filter((t) => !isLang(t));
  fillPane("stale", stale.map(staleItem));
  fillPane("tpl", life.map(tplItem));
  fillPane("duty", genDuties.map(tplItem));
  fillPane("reps", genReps.map(poolItem));
  fillPane("waits", genWaits.map(waitItem));
  fillPane("aitasks", genAi.map(aiItem));

  /* 語言學習專區(使用者的需求,2026-08-18):「我專門為著語言學習設一個排程」+
     「怎麼還放在待辦事項啊…是不是也要拿過去」——
     domain=Language 的卡片**只在這裡列**(上面那幾個通用分頁都濾掉了),
     資料照舊只有圖上那一份,這只是顯示上的分家。 */
  const langBox = $("langlist");
  langBox.innerHTML = "";
  let langN = 0;
  [["♾️ 每日積木(拖進時段,不會消失)", duties.filter(isLang).map(tplItem)],
   ["🔁 週期練習(打勾會推到下一期)", state.repeats.filter(isLang).map(poolItem)],
   ["📋 單次任務", state.pool.filter(isLang).map(poolItem)],
   ["⏸️ 等條件", state.waiting.filter(isLang).map(waitItem)],
   ["🤖 AI 在做(不佔你的時間)", state.aiTasks.filter(isLang).map(aiItem)],
  ].forEach(([ttl, items]) => {
    if (!items.length) return;
    langBox.appendChild(el("div", "sect", ttl));
    items.forEach((n) => langBox.appendChild(n));
    if (!ttl.startsWith("🤖")) langN += items.length;   // AI 的只是給使用者看,不算在角標裡
  });
  if (!langBox.childElementCount) langBox.appendChild(el("div", "empty", "（沒有）"));

  renderTabs({ pool: shownPool.length, stale: stale.length,
               lang: langN, reps: genReps.length,
               wait: genWaits.length, duty: genDuties.length,
               tpl: life.length, ai: genAi.length });
  showTab(tab);

  const lg = $("legend");
  lg.innerHTML = "";
  const shown = state.pool.concat(...state.days.map((d) => d.scheduled));
  [...new Set(shown.map((t) => t.domain))].forEach((d) => {
    const k = el("span", "key");
    const i = el("i");
    i.style.background = colorOf(d);
    k.appendChild(i);
    k.appendChild(el("span", null, d));
    lg.appendChild(k);
  });

  // 重畫之後區塊是全新的 DOM —— 面板要重新黏一次,順便換成新資料(不然按了沒反應)
  renderEditor();
  closeSumPop();   // 那份分類是重畫前算的,留著會變成過期數字

  /* ⛔ 不要再寫「還有 N 件沒排」—— 排進行程不會讓任務離開池子了,那個 N 是
     「還沒做完」的件數,寫成「沒排」會讓使用者以為那些都還沒放到時間軸上。 */
  const n = state.days.reduce((a, d) => a + d.scheduled.length, 0);
  const from = state.days.length ? state.days[0].date.slice(5) : "";
  const to = state.days.length ? state.days[state.days.length - 1].date.slice(5) : "";
  $("status").textContent =
    `${from} → ${to}(${state.days.length} 天)・這幾天排了 ${n} 段・`
    + `${state.pool.length} 件還沒做完`;
}

/* ── 拖進某一天 ─────────────────────────────────────────────────── */
function clearGhost() {
  const g = document.querySelector(".ghost");
  if (g) g.remove();
  document.querySelectorAll(".grid.drop-on").forEach((n) => n.classList.remove("drop-on"));
}

/* 滑鼠位置 → 區塊「上緣」該落在幾點。

   使用者的需求(2026-08-11):「現在的拖拉他是看滑鼠的位置,可是你可以參考一下 Google 行事曆,
   他們是根據我顯示的那個區塊的上端的部分去對應到確切的位置區塊。」
   → 抓區塊中間拖的時候,要保留你抓的那個位移;不然區塊會突然往上跳到滑鼠底下,
     手感像「甩」出去而不是「移動」。從右邊池子拖進來的沒有既有區塊,位移就是 0。 */
function yToMin(grid, clientY) {
  const offset = (drag && drag.grabMin) || 0;
  return snap((clientY - grid.getBoundingClientRect().top) / px(1) - offset);
}

/* 抓在區塊的第幾分鐘。dragstart 當下量,之後 dragover 沒有這個資訊。 */
function grabMinOf(e, box) {
  return Math.max(0, (e.clientY - box.getBoundingClientRect().top) / px(1));
}

function wireDrop(grid, iso) {
  grid.addEventListener("dragover", (e) => {
    if (!drag) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = drag.kind === "tpl" ? "copy" : "move";
    grid.classList.add("drop-on");
    const start = yToMin(grid, e.clientY);
    let g = grid.querySelector(".ghost");
    if (!g) {
      clearGhost();
      grid.classList.add("drop-on");
      g = el("div", "ghost");
      grid.appendChild(g);
    }
    const n = overlapsWith(iso, start, drag.mins,
      drag.slotUid ? "t:" + drag.slotUid : drag.key);
    g.classList.toggle("stacked", n > 0);
    g.style.top = px(start) + "px";
    g.style.height = Math.max(16, px(drag.mins) - 2) + "px";
    // 疊得起來是刻意允許的,但要先講一聲 —— 不然使用者不會發現自己同時排了三件事
    g.textContent = `${toHHMM(start)}–${toHHMM(start + drag.mins)}`
      + (n ? `（跟 ${n} 件並排)` : "");
  });
  grid.addEventListener("dragleave", (e) => {
    if (!grid.contains(e.relatedTarget)) {
      grid.classList.remove("drop-on");
      const g = grid.querySelector(".ghost");
      if (g) g.remove();
    }
  });
  grid.addEventListener("drop", async (e) => {
    e.preventDefault();
    const d = drag;
    clearGhost();
    if (!d) return;
    const start = yToMin(grid, e.clientY);
    if (d.kind === "task" || d.kind === "move") {
      placeTask(d.task, iso, start, d.mins, d.slotUid);
    } else if (d.kind === "tpl") {
      dayOf(iso).blocks.push({
        uid: `${d.tpl.id}-${Date.now()}`, tpl: d.tpl.id, start: toHHMM(start), min: d.tpl.min,
      });
      if (await saveBlocks(iso)) { toast(`${d.tpl.name} → ${iso.slice(5)} ${toHHMM(start)}`); load(true); }
    } else if (d.kind === "moveBlock") {
      const from = dayOf(d.from);
      from.blocks = from.blocks.filter((o) => o.uid !== d.block.uid);
      const moved = { ...d.block, start: toHHMM(start) };
      dayOf(iso).blocks.push(moved);
      const okFrom = d.from === iso ? true : await saveBlocks(d.from);
      if (okFrom && await saveBlocks(iso)) load(true);
    }
  });
}

/* 拖曳期間讓欄頭「穿透」—— 欄頭是 sticky 的,永遠蓋著時間軸最上面那一截,
   而摘要讓它從 30px 變成 74px。不放行的話,拖到被蓋住的那一小時**完全沒有反應
   也沒有任何提示**,正是這個專案最忌諱的靜默失敗。 */
["dragstart", "dragend", "drop"].forEach((ev) => document.addEventListener(ev, (e) => {
  document.body.classList.toggle("dragging", e.type === "dragstart");
}, true));
/* 保底:來源區塊在拖曳中被重畫掉(存檔後 load() 重建 DOM)就收不到 dragend,
   欄頭會永遠停在「可穿透」狀態 —— 從此點不到 ↩、也點不開分類摘要,而且看起來一切正常。 */
["pointerup", "mouseup", "keyup"].forEach((ev) =>
  document.addEventListener(ev, () => document.body.classList.remove("dragging"), true));

/* 拖回右邊 = 從行程拿掉 */
$("right").addEventListener("dragover", (e) => {
  if (drag && (drag.kind === "move" || drag.kind === "moveBlock")) e.preventDefault();
});
$("right").addEventListener("drop", async (e) => {
  e.preventDefault();
  const d = drag;
  if (!d) return;
  if (d.kind === "move") unplaceSlot(d.task, d.slotUid);
  else if (d.kind === "moveBlock") {
    const day = dayOf(d.from);
    day.blocks = day.blocks.filter((o) => o.uid !== d.block.uid);
    if (await saveBlocks(d.from)) { toast("拿掉了"); load(true); }
  }
});

/* ── 工具列 ─────────────────────────────────────────────────────── */
/* 跳到某一天:已經載入的就直接捲過去(不重載,快);沒載入的才重來。 */
function go(iso) {
  state.date = iso;
  if (state.days.some((d) => d.date === iso)) {
    scrollToDate(iso);
    $("date").value = iso;
    return;
  }
  state.days = [];
  load();
}
["f-domain", "f-sort", "f-due", "f-part", "f-q"].forEach((id) => {
  $(id).addEventListener("input", render);
  $(id).addEventListener("change", render);
});


$("prev").onclick = () => go(shiftDate(state.date, -7));
$("next").onclick = () => go(shiftDate(state.date, 7));
$("today-btn").onclick = () => go(todayISO());
$("f-done").checked = showDone;
$("f-done").onchange = () => {
  showDone = $("f-done").checked;
  localStorage.setItem("day.showDone", showDone ? "1" : "0");
  render();   // 資料本來就抓下來了,不必重新問伺服器
};
$("date").onchange = (e) => go(e.target.value);

/* 捲到邊緣就自動長出更多日子。⚠️ 節流靠 busy 旗標,不然一次捲動會連發好幾個請求。 */
$("left").addEventListener("scroll", () => {
  const box = $("left");
  if (box.scrollLeft + box.clientWidth > box.scrollWidth - 500) extend(1);
  else if (box.scrollLeft < 300) extend(-1);
}, { passive: true });

/* 「沒做完的丟回去」—— 使用者選的:不自作主張幫使用者排到明天哪個時段,只是還回池子。 */
async function dumpDay(day) {
  const list = [...new Map(day.scheduled.map((t) => [t.id, t])).values()];
  if (!list.length) return toast(`${day.date.slice(5)} 沒有排任務`);
  if (!confirm(`把 ${day.date} 的 ${list.length} 件任務全部丟回右邊的任務池?\n\n`
    + list.slice(0, 8).map((t) => "・" + t.topic).join("\n")
    + (list.length > 8 ? `\n…還有 ${list.length - 8} 件` : "")
    + "\n\n（日常區塊不會動）")) return;
  for (const t of list) {
    const slots = slotsOf(t).filter((s2) => s2.at.slice(0, 10) !== day.date);
    if (!await patchTask(t.id, { planned: slots, plannedAt: null, plannedMin: null },
      "沒做完丟回任務池")) return;
  }
  toast(`${list.length} 件回到任務池`);
  load(true);
}

/* 網址可以指定從哪天開始:/day?date=2026-09-15 —— 可以加書籤,也方便截圖驗證。 */
const wanted = new URLSearchParams(location.search).get("date");
state.date = /^\d{4}-\d{2}-\d{2}$/.test(wanted || "") ? wanted : todayISO();
state.days = [];
load();

// 右下角「＋」隨手記加完東西 → 馬上重新載入(2026-09-17,事件由 nav.js 發出)
document.addEventListener("sc:todo-added", () => load(true));
