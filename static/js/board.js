/* 任務板 — 心智圖的第二個視圖(同一份 JSON,不是另一份資料)。

   使用者的需求(2026-08-08):「其實真的很難每一個東西都設定好截止日,我頂多只能說這個要花多久、
   大概說明這個要幹嘛、重要程度是什麼…我們是不是可以依照待辦事項再開一個項目,
   就是我們的心智圖它有另外一個分頁,在講任務狀況。」

   設計三條:
   ① 只讀圖上的待辦節點,**不另外存一份**。改狀態就是改那張圖(走同一個 API,有衝突偵測)。
   ② 沒有截止日是常態,不是缺陷 —— 排序要能在「大部分沒死線」的情況下仍然有用。
   ③ 卡片上看得到:它在哪個領域/專案、等級、死線、要花多久、只能在哪做。 */

const MAP = window.MM_MAP || "全局總覽圖";   // 伺服器說了算,見 /static/js/config.js
const STATUSES = [
  { mark: "⏳", label: "還沒開始" },
  { mark: "🔜", label: "正在做" },
  { mark: "⏸️", label: "卡住/等別人" },
  { mark: "✅", label: "完成" },
];
const PRIS = ["P1", "P2", "P3", "P4"];
// 八檔。正本是 plan_week.EFFORT_HOURS —— 填別的字排程會當成「沒填」,一律猜 2h。
const EFFORTS = ["1h", "2h", "4h", "8h", "12h", "1天", "2天", "1週"];
const $ = (id) => document.getElementById(id);

let baseMtime = null;
let cards = [];

function statusOf(topic) {
  const t = (topic || "").trim();
  for (const s of STATUSES) if (t.startsWith(s.mark)) return s.mark;
  if (t.startsWith("⏸")) return "⏸️";
  return "⏳";
}

function stripMark(topic) {
  let t = (topic || "").trim();
  for (const m of ["⏳", "🔜", "⏸️", "⏸", "✅", "🎯"]) {
    if (t.startsWith(m)) return t.slice(m.length).trim();
  }
  return t;
}

function priOf(node) {
  return (node.tags || []).find((t) => PRIS.includes(t)) || "";
}

/* 差幾天要用「日期」算,不能用時間戳 —— 用時間戳的話今天到期會算成「剩 1 天」,
   而「今天」跟「剩一天」在排程上是兩件事。 */
function daysLeft(due) {
  if (!due) return null;
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const [y, m, d] = due.split("-").map(Number);
  return Math.round((Date.UTC(y, m - 1, d) - today) / 86400000);
}

/* 走訪:一路帶著「領域(根的直接子節點)」與「最近的專案資料夾」,
   卡片才講得出「這件事屬於哪一塊」—— 只有標題的話,離開圖就認不出來了。 */
function collect(root) {
  const out = [];
  const walk = (node, domain, path) => {
    const here = path.concat(stripMark(node.topic));
    (node.children || []).forEach((c) => walk(c, domain, here));
    if (node.todo) {
      out.push({
        id: node.id,
        topic: stripMark(node.topic),
        mark: statusOf(node.topic),
        pri: priOf(node),
        tags: (node.tags || []).filter((t) => !PRIS.includes(t)),
        due: (node.detail || {}).due || "",
        effort: (node.detail || {}).effort || "",
        earliest: (node.detail || {}).earliest || "",
        hardDue: !!(node.detail || {}).hardDue,
        window: (node.detail || {}).window || "",
        explain: (node.detail || {}).explain || "",
        domain,
        path: path.slice(1).join(" › "), // 去掉根
      });
    }
  };
  // ⚠️ 起點只放根,領域由 walk 自己接上去 —— 兩邊都放會變成「Workspace › Workspace」
  (root.children || []).forEach((d) => walk(d, stripMark(d.topic), [stripMark(root.topic)]));
  return out;
}

async function load() {
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}`);
  if (!r.ok) {
    $("status").textContent = "✘ 讀不到圖";
    return;
  }
  const out = await r.json();
  baseMtime = out.mtime;
  cards = collect(out.data.nodeData);
  fillDomains();
  render();
  $("status").textContent = `${cards.filter((c) => c.mark !== "✅").length} 件未完成`;
}

function fillDomains() {
  const sel = $("domain");
  const cur = sel.value;
  const names = [...new Set(cards.map((c) => c.domain))];
  sel.innerHTML = '<option value="">全部領域</option>';
  names.forEach((n) => {
    const o = document.createElement("option");
    o.value = n;
    o.textContent = n;
    sel.appendChild(o);
  });
  sel.value = cur;
}

function sortCards(list) {
  const byPri = (c) => (c.pri ? PRIS.indexOf(c.pri) : 9);
  // ⚠️ 沒有截止日的排最後,不是排最前 —— 大部分項目都沒死線,
  // 把「空值」當成 0 的話整個板子會被沒死線的淹掉。
  const byDue = (c) => (c.due ? c.due : "9999-99-99");
  const mode = $("sort").value;
  return list.sort((a, b) =>
    mode === "due"
      ? byDue(a).localeCompare(byDue(b)) || byPri(a) - byPri(b)
      : byPri(a) - byPri(b) || byDue(a).localeCompare(byDue(b)),
  );
}

function visible() {
  const dom = $("domain").value;
  const q = $("q").value.trim().toLowerCase();
  const onlyDue = $("chk-due").checked;
  return cards.filter((c) => {
    if (dom && c.domain !== dom) return false;
    if (onlyDue && !c.due) return false;
    if (q) {
      const blob = `${c.topic} ${c.path} ${c.explain} ${c.tags.join(" ")} ${c.window}`.toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });
}

function card(c) {
  const el = document.createElement("div");
  el.className = "card" + (c.pri ? " p-" + c.pri : "");
  // 拖到別欄 = 改狀態。⚠️ 拖曳在觸控裝置上不見得成立,所以下面的狀態鈕要留著。
  el.draggable = true;
  el.dataset.id = c.id;
  el.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", c.id);
    e.dataTransfer.effectAllowed = "move";
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));

  const t = document.createElement("div");
  t.className = "t";
  t.textContent = c.topic;
  el.appendChild(t);

  const p = document.createElement("div");
  p.className = "path";
  p.textContent = c.path;
  el.appendChild(p);

  // 只讀的標記(自由標籤、只能在哪做)—— 這兩個要改請去心智圖
  if (c.window || c.tags.length) {
    const meta = document.createElement("div");
    meta.className = "meta";
    if (c.window) {
      const w = document.createElement("span");
      w.className = "tag win";
      w.textContent = "📍 " + c.window;
      meta.appendChild(w);
    }
    c.tags.forEach((tag) => {
      const s2 = document.createElement("span");
      s2.className = "tag group";
      s2.textContent = tag;
      meta.appendChild(s2);
    });
    el.appendChild(meta);
  }

  /* ── 可以改的三格:等級 / 截止日 / 要花多久 ──
     使用者的需求(2026-08-11):「我要可以拉動、可以去改變我的優先級和要做的時間。」
     這三格就是排程吃的東西(見 plan_week 檔頭),在這裡改完行程表馬上重算。 */
  const edit = document.createElement("div");
  edit.className = "edit";

  const priRow = document.createElement("div");
  priRow.className = "row";
  PRIS.forEach((v) => {
    const b = document.createElement("button");
    b.className = "pri-btn " + v + (c.pri === v ? " on" : "");
    b.textContent = v;
    b.title = c.pri === v ? "再按一次可以拿掉等級" : `改成 ${v}`;
    b.onclick = () => setPri(c, c.pri === v ? "" : v);
    priRow.appendChild(b);
  });
  edit.appendChild(priRow);

  const dateRow = document.createElement("div");
  dateRow.className = "row";
  const due = document.createElement("input");
  due.type = "date";
  due.value = c.due || "";
  due.title = "截止日 —— ⛔ 只填別人給的日期(法定期限、對方在等)。「我希望這天做完」不要填";
  due.onchange = () => setDue(c, due.value);
  dateRow.appendChild(labelled("⏰", due));

  /* 🔒 = 外力給的日期(法定期限、對方在等)。行程表「整串往後推」不會動它。
     ⛔ 沒有這個分別,推一次就會把合約到期 8/13、機關約定日 8/27 一起推走。 */
  const lock = document.createElement("button");
  lock.className = "lock" + (c.hardDue ? " on" : "");
  lock.textContent = c.hardDue ? "🔒" : "🔓";
  lock.title = c.hardDue
    ? "外力死線:整串往後推時不會動它。按一下解鎖"
    : "這個日期可以被推走。按一下鎖成「外力死線」(法定期限、對方在等)";
  lock.onclick = () => setHardDue(c, !c.hardDue);
  dateRow.appendChild(lock);

  const eff = document.createElement("select");
  eff.title = "要花多久 —— 行程表靠它算排不排得下,沒填一律當 2h";
  [["", "要花多久?"]].concat(EFFORTS.map((v) => [v, v])).forEach(([v, label]) => {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = label;
    if (v === (c.effort || "")) o.selected = true;
    eff.appendChild(o);
  });
  eff.onchange = () => setEffort(c, eff.value);
  dateRow.appendChild(labelled("⏱", eff));
  edit.appendChild(dateRow);

  const early = document.createElement("input");
  early.type = "date";
  early.value = c.earliest || "";
  early.title = "不能比這天早做(要等別的事發生才做得了)——例:對方回覆之後才動得了";
  early.onchange = () => setEarliest(c, early.value);
  dateRow.appendChild(labelled("🚧", early));
  if (c.due) {
    const d = daysLeft(c.due);
    const hint = document.createElement("span");
    hint.className = "left " + (d < 0 ? "over" : d <= 3 ? "soon" : d <= 7 ? "near" : "");
    hint.textContent = d < 0 ? `過期 ${-d} 天` : d === 0 ? "今天到期" : `剩 ${d} 天`;
    dateRow.appendChild(hint);
  }
  el.appendChild(edit);

  const acts = document.createElement("div");
  acts.className = "acts";
  STATUSES.filter((s2) => s2.mark !== c.mark).forEach((s2) => {
    const b = document.createElement("button");
    b.textContent = s2.mark + " " + s2.label;
    b.title = `改成「${s2.label}」(也可以直接把卡片拖到那一欄)`;
    b.onclick = () => setStatus(c, s2.mark);
    acts.appendChild(b);
  });
  const drop = document.createElement("button");
  drop.className = "drop-btn";
  drop.textContent = "❌ 不做了";
  drop.title = "決定不做這件事了 —— 會從圖上移走,理由記進完成紀錄(⛔ 不是標成完成)";
  drop.onclick = () => dropCard(c);
  acts.appendChild(drop);

  const go = document.createElement("button");
  go.className = "go";
  go.textContent = "在圖上看 ↗";
  go.onclick = () => {
    location.href = `/?focus=${encodeURIComponent(c.id)}#${encodeURIComponent(MAP)}`;
  };
  acts.appendChild(go);
  el.appendChild(acts);
  return el;
}

function labelled(icon, control) {
  const wrap = document.createElement("label");
  wrap.className = "f";
  const i = document.createElement("span");
  i.textContent = icon;
  wrap.appendChild(i);
  wrap.appendChild(control);
  return wrap;
}

function render() {
  const box = $("cols");
  box.innerHTML = "";
  const list = sortCards(visible());
  STATUSES.forEach((s) => {
    const col = document.createElement("section");
    col.className = "col";
    const h = document.createElement("h2");
    const mine = list.filter((c) => c.mark === s.mark);
    h.innerHTML = `<span>${s.mark} ${s.label}</span><span class="n">${mine.length}</span>`;
    col.appendChild(h);
    const inner = document.createElement("div");
    inner.className = "col-list";
    inner.addEventListener("dragover", (e) => {
      e.preventDefault();
      inner.classList.add("over");
    });
    inner.addEventListener("dragleave", () => inner.classList.remove("over"));
    inner.addEventListener("drop", (e) => {
      e.preventDefault();
      inner.classList.remove("over");
      const id = e.dataTransfer.getData("text/plain");
      const c = cards.find((x) => x.id === id);
      if (c && c.mark !== s.mark) setStatus(c, s.mark);
    });
    if (!mine.length) {
      const e = document.createElement("div");
      e.className = "empty";
      e.textContent = "（空）";
      inner.appendChild(e);
    }
    mine.forEach((c) => inner.appendChild(card(c)));
    col.appendChild(inner);
    box.appendChild(col);
  });
}

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2600);
}

/* 改任何一格 = 改那張圖。⚠️ 重讀一次再寫,而且帶著 base_mtime ——
   這頁跟瀏覽器上的心智圖、AI 的 mm.py 可能同時在動同一份檔案。

   使用者的需求(2026-08-11):「我要可以拉動、可以去改變我的優先級和要做的時間。
   現在你這上面都不能讓我操作,等於我列在上面就什麼都不能做…
   結果你現在把任務板建立給我,它卻死在那邊什麼都動不了,那我要它幹嘛?」
   → 在那之前只有 setStatus 一個寫回動作,等級/死線/工時全是唯讀的死字。 */
async function patchNode(id, mutate, okMsg, what) {
  const r = await fetch(`/api/maps/${encodeURIComponent(MAP)}`);
  const out = await r.json();
  let hit = null;
  const find = (n) => {
    if (n.id === id) hit = n;
    (n.children || []).forEach(find);
  };
  find(out.data.nodeData);
  if (!hit) {
    toast("那個節點已經不在圖上了");
    return false;
  }
  mutate(hit);
  // ⛔ 這是使用者自己動的,不要標成 AI 改的 —— 圈圈是「AI 動過、你還沒看」的意思,
  //    自己改的東西也圈起來的話,那個圈圈就沒有訊息量了。
  delete hit.aiEdited;
  hit.scEdited = `${new Date().toLocaleDateString("sv-SE")} 在任務板${what}`;
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

const detailOf = (n) => (n.detail = n.detail || {});

/* ❌ 不做了 —— 一顆事情的第二條出路(2026-08-22 使用者問「應該也有取消任務吧」)。
   在這之前畫面上只有「完成」一個出口 → 不想做的事只能硬標完成(完成紀錄會多一筆
   從沒做過的事)或爛在圖上。⛔ 一定要問理由,不然一年後它會被原封不動地重新提出來。 */
async function dropCard(c) {
  const why = window.prompt(
    `要把「${c.topic}」標成「不做了」嗎?\n\n`
    + "它會從圖上移走,連同下面這個理由一起記進「完成紀錄」,以後查得到。\n"
    + "⛔ 這不是「完成」—— 完成紀錄那邊會標成 ❌ 不做了。\n\n"
    + "為什麼不做了?(一定要寫)", "");
  if (why === null) return;
  if (!why.trim()) return toast("要寫理由才送得出去");
  const r = await fetch(
    `/api/maps/${encodeURIComponent(MAP)}/nodes/${encodeURIComponent(c.id)}/drop`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ why: why.trim() }) });
  if (!r.ok) {
    const out = await r.json().catch(() => ({}));
    return toast(out.detail || "送不出去");
  }
  toast("已標成「❌ 不做了」,理由記進完成紀錄");
  load();
}

function setStatus(c, mark) {
  return patchNode(c.id, (n) => {
    const wasDone = (n.topic || "").trim().startsWith("✅");
    n.topic = `${mark} ${stripMark(n.topic)}`.trim();
    /* 完成的事放 7 天後自動歸檔,靠 detail.doneOn 算。⚠️ 打勾→取消→再打勾必須換成今天,
       不然會沿用第一次那個舊日期、當晚就被判到期搬走。 */
    const d = detailOf(n);
    if (mark !== "✅") delete d.doneOn;
    else if (!wasDone || !d.doneOn) d.doneOn = new Date().toLocaleDateString("sv-SE");
  }, `已改成「${STATUSES.find((s) => s.mark === mark).label}」`, "改了狀態");
}

function setPri(c, pri) {
  return patchNode(c.id, (n) => {
    n.tags = (n.tags || []).filter((t) => !PRIS.includes(t)).concat(pri ? [pri] : []);
  }, pri ? `等級改成 ${pri}` : "拿掉等級", "改了等級");
}

function setDue(c, iso) {
  return patchNode(c.id, (n) => {
    const d = detailOf(n);
    if (iso) d.due = iso; else delete d.due;
  }, iso ? `截止日改成 ${iso}` : "拿掉截止日", "改了截止日");
}

function setEffort(c, v) {
  return patchNode(c.id, (n) => {
    const d = detailOf(n);
    if (v) d.effort = v; else delete d.effort;
  }, v ? `要花多久改成 ${v}` : "拿掉要花多久", "改了要花多久");
}

function setHardDue(c, on) {
  return patchNode(c.id, (n) => {
    const d = detailOf(n);
    if (on) d.hardDue = true; else delete d.hardDue;
  }, on ? "鎖成外力死線,整串往後推時不會動它" : "改成可以被推走的日期", "改了死線種類");
}

function setEarliest(c, iso) {
  return patchNode(c.id, (n) => {
    const d = detailOf(n);
    if (iso) d.earliest = iso; else delete d.earliest;
  }, iso ? `不能早於 ${iso}` : "拿掉「不能早於」", "改了「不能早於」");
}

["domain", "sort", "q", "chk-due"].forEach((id) => {
  $(id).addEventListener("input", render);
  $(id).addEventListener("change", render);
});
load();
setInterval(load, 15000); // 別條對話或另一個視窗改了圖,這頁要跟上

// 右下角「＋」隨手記加完東西 → 馬上重新載入(2026-09-17,事件由 nav.js 發出)
document.addEventListener("sc:todo-added", () => load());
