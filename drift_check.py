#!/usr/bin/env python3
"""漏寫偵測:找出「專案那邊有動作,但心智圖沒跟上」的地方。

使用者定的判準(2026-08-08):「我所有專案都是直接看這個心智圖,我要確保我不論做了什麼樣的紀錄,
他都可以匯總到這個心智圖裡面。」

⚠️ 這支補的是整套系統唯一沒有保底的缺口:**「寫」靠規則,AI 忘了寫沒人抓得到。**
規則沒人查等於沒有 —— 所以把「有沒有漏」變成一句指令跑得出來的東西。

⛔ 只讀、只報告,不自動寫任何東西。判斷「這件事要不要進圖」是人的事。

用法::

    python3 drift_check.py            # 全部掛了 source 的專案
    python3 drift_check.py Finance    # 只看一個

三種訊號:
  ① ⛔ 專案的 TODO.md 格式讀不到 → 圖上看不到它在幹嘛(見全域 §十九之一)
  ② 👀 專案裡「⏳ 等你」的項目,圖上找不到對應節點 → 你最容易漏的就是這種
     ↳ 那一行結尾加 `<!--mm:節點id-->` 就是宣告「這件事在圖上是那一顆」,不再報。
       id 查無此顆 → 改報 ⛔ 斷鏈(⛔ 不准變成安靜關掉警告的開關)。
  ③ 👀 專案 CHANGELOG 有「上次對帳之後」且看起來像決定的新條目 → 可能該進圖
  ④ ⛔ **殭屍待辦**:圖上已經 ✅(或已歸檔進完成紀錄),專案檔裡卻還躺著一條沒打勾的
     手寫副本 → 每日排程報告/自動化流程照樣把它撈出來,使用者會被同一件已完成的事一問再問。
     ↳ 這是 ③ 的反方向。①②③ 全部只看「專案 → 圖」有沒有漏寫,
       沒有任何一支在看「圖 → 專案」有沒有沒清乾淨。真的發生過:
       圖上那顆早就 ✅,但兩個專案的 TODO.md 各留一條手寫的沒打勾。
     ↳ ⚠️ 它掃**所有** TODO.md,不限「掛了 source 的專案」——
       最嚴重的那一條就住在完全沒掛 source 的那個專案裡。

⛔ **刻意不報「專案待辦比圖上多」** —— 圖只放全局級的東西,專案永遠比圖多,
   那是設計本來就這樣。報它等於狼來了,久了連真的警告也不看(2026-08-08 第一版犯過)。
"""

import json
import os
import pathlib
import re
import sys

MAPS_DIR = pathlib.Path(
    os.environ.get("MINDMAP_MAPS_DIR", pathlib.Path.home() / "mindmaps")
)
PROJECTS_ROOT = pathlib.Path(
    os.environ.get("MINDMAP_PROJECTS_ROOT", pathlib.Path.home() / "projects")
)
SYNC_STATE = MAPS_DIR / ".history" / "todo_sync" / "_last_sync.json"
DATE_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")
# 條目標題出現這些字 = 很可能是「該進圖的決定」,不只是 commit 級的修修改改
DECISION_WORDS = re.compile(r"(拍板|定案|決定|改用|取代|規則確立|上線|退役|不做|方向|架構)")
SIM_THRESHOLD = 0.34  # 2-gram Jaccard;超過就當成「圖上已經有這件事了」
# 手寫的 ⏳ 行可以自己掛 `<!--mm:節點id-->` 宣告「這件事在圖上是那一顆」。
# ⚠️ 為什麼需要這個:2026-08-13 把 10 件「等你」補進圖之後,drift 還是照報 ——
# 因為它是拿**文字相似度**比對,而專案檔那幾行底下帶著大量細節(當時查到的設定狀態、
# 某個備份檔的檔名),標題根本不會長得一樣。
# 刪掉手寫行會丟掉那些細節,所以改成掛 id 認親。
# ⛔ 但 id 不驗證就等於給了一個「安靜地把事情藏起來」的開關 → 查不到那顆就照報,
#    而且明講是斷鏈(比默默放行或默默漏報都好)。
MM_ID_RE = re.compile(r"<!--\s*mm:([\w-]+)\s*-->")
# ④ 殭屍待辦用的。歸檔之後節點會離開圖,只剩這份紀錄 —— 不讀它的話,
# 「✅ 放 7 天被 autoarchive 搬走」的那些殭屍會重新變成隱形。
ARCHIVE_REL = "Workspace/notes/完成紀錄.md"
ARCHIVE_TITLE_RE = re.compile(r"^\|\s*\*\*(.+?)\*\*")
# 未打勾的寫法:標準的 `- [ ]`,以及手寫區常見的 `⬜`(格式不合規,但真的有人這樣寫,
# 而且每日排程報告掃得到 → 這裡也必須掃得到,不然抓不到最重要的那一條)
UNCHECKED_RE = re.compile(r"^-?\s*(\[ \]|⬜)\s*")
ZOMBIE_SIM = 0.36
# ⚠️ 為什麼要用「好幾種長度各比一次、取最像的那個」:手寫那條常常在標題後面接一大串細節
# (路徑、限量幾名、當初為什麼要做),整行拿去比會被稀釋。實測 2026-08-22 那條信用卡登錄活動,
# 只比前 40 字 = 0.375 比得中,整行 = 0.26 比不中。⛔ 不要只用一個固定長度。
ZOMBIE_WINDOWS = (30, 40, 50, 60)


def load_map():
    return json.loads((MAPS_DIR / "全局總覽圖.json").read_text(encoding="utf-8"))


def walk(node, owner=None):
    owner = node.get("source") or owner
    yield node, owner
    for child in node.get("children") or []:
        yield from walk(child, owner)


def map_todos_by_project(data):
    """每個專案 → 圖上那一支的待辦標題(未完成的)。"""
    topics = {}
    for node, owner in walk(data["nodeData"]):
        if not owner:
            continue
        topics.setdefault(owner, [])
        if node.get("todo") and not (node.get("topic") or "").strip().startswith("✅"):
            topics[owner].append(node.get("topic") or "")
    return topics


def last_synced():
    try:
        return json.loads(SYNC_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def bigrams(text):
    t = re.sub(r"[\s`*_（）()「」:,、。·\-—]+", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similar(a, b):
    x, y = bigrams(a), bigrams(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def all_node_ids(data):
    return {node.get("id") for node, _ in walk(data["nodeData"]) if node.get("id")}


def own_todos(rel):
    """專案自己的未完成待辦數(同步區不算——那是心智圖的回音)。

    `waiting` 的每一項回傳 `(文字, 掛到的節點id或None)`。
    """
    path = PROJECTS_ROOT / rel / "TODO.md"
    if not path.is_file():
        return 0, False, False, []
    raw = path.read_text(encoding="utf-8", errors="replace")
    in_block = False
    open_n = stray = 0
    waiting = []  # 「⏳ 等你」的那些 —— 最容易漏的不是 AI 的進度,是等使用者的輸入
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("<!-- mm:begin"):
            in_block = True
            continue
        if s.startswith("<!-- mm:end"):
            in_block = False
            continue
        if in_block:
            continue
        if s.startswith("- [ ]"):
            open_n += 1
            if "⏳" in s:
                hit = MM_ID_RE.search(s)
                text = MM_ID_RE.sub("", s[5:])
                waiting.append((" ".join(text.split())[:90], hit.group(1) if hit else None))
        elif s.startswith("- ") and not s.startswith(("- [x]", "- [X]")):
            stray += 1
    declared = "mm:no-own-todos" in raw
    return open_n, (stray > 0 and open_n == 0 and not declared), declared, waiting


def new_changelog_entries(rel, since):
    """回傳 [(日期, 標題)],只取比 since 新的。since=None → 只取最新一條當樣本。"""
    path = PROJECTS_ROOT / rel / "CHANGELOG.md"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = DATE_RE.match(line)
        if not m:
            continue
        day = m.group(1)
        if since and day <= since:
            break
        out.append((day, line.lstrip("# ").strip()))
        if not since and out:
            break
    return out


def done_on_map(data):
    """圖上已經打勾的待辦 → [(節點id, 標題)]。"""
    out = []
    for node, _owner in walk(data["nodeData"]):
        topic = (node.get("topic") or "").strip()
        if node.get("todo") and topic.startswith("✅"):
            out.append((node.get("id"), topic.lstrip("✅").strip()))
    return out


def archived_titles():
    """完成紀錄裡的標題 → [標題]。

    ⚠️ 只取粗體的那一段標題,不要整格。整格裡帶著幾百字的來龍去脈,
    拿去算相似度會被稀釋到永遠比不中(drift 自己在 ② 出過同一個問題)。
    """
    path = PROJECTS_ROOT / ARCHIVE_REL
    if not path.is_file():
        return []
    titles = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        hit = ARCHIVE_TITLE_RE.match(line.strip())
        if hit:
            titles.append(hit.group(1).strip())
    return titles


def archived_ids():
    """完成紀錄裡留下來的節點 id。歸檔之後節點離開圖,只剩這裡認得它。"""
    path = PROJECTS_ROOT / ARCHIVE_REL
    if not path.is_file():
        return set()
    return set(MM_ID_RE.findall(path.read_text(encoding="utf-8", errors="replace")))


def _looks_archived(text, titles):
    return any(max(similar(text[:w], t) for w in ZOMBIE_WINDOWS) >= ZOMBIE_SIM for t in titles)


def all_todo_files():
    """所有專案的 TODO.md。

    ⛔ 刻意不限「掛了 source 的專案」—— 2026-08-22 抓到的三條殭屍裡,
    最嚴重的那條住在 `Workspace/TODO.md`,而 Workspace 根本沒掛 source
    (它是圖自己的家)。只掃掛了 source 的等於漏掉每日排程報告真正在讀的那個檔。
    """
    out = []
    for depth in ("*/TODO.md", "*/*/TODO.md", "*/*/*/TODO.md"):
        out += [p for p in PROJECTS_ROOT.glob(depth) if ".git" not in p.parts]
    extra = PROJECTS_ROOT / "notes/current-sprint.md"
    if extra.is_file():
        out.append(extra)
    return sorted(set(out))


def zombie_todos(data, include_archive=True):
    """④ 圖上已完成/已歸檔,專案檔裡卻還有一條沒打勾的手寫副本。

    兩條認親路線,故意分開:
      ・掛了 `<!--mm:id-->` 而那顆是 ✅ → **確定**是殭屍(⛔)
      ・沒掛 id,只有文字像 → **可能**是殭屍(👀,要人看一眼)
    """
    done = done_on_map(data)
    done_ids = {i: t for i, t in done if i}
    archived = archived_ids()
    # include_archive=False:只拿圖上這幾顆去比。mm.py 標 ✅ 的當下用這種 ——
    # 那時只想知道「**這一顆**有沒有殭屍副本」,把整份完成紀錄拉進來比會噴出別人的舊帳。
    titles = [t for _, t in done] + (archived_titles() if include_archive else [])
    findings = []
    for path in all_todo_files():
        rel = str(path.relative_to(PROJECTS_ROOT))
        in_block = False
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if s.startswith("<!-- mm:begin"):
                in_block = True
                continue
            if s.startswith("<!-- mm:end"):
                in_block = False
                continue
            if in_block:
                continue          # 同步區是圖的回音,那裡的狀態由 sync_todos 負責
            if not UNCHECKED_RE.match(s):
                continue
            text = UNCHECKED_RE.sub("", s)
            hit = MM_ID_RE.search(text)
            if hit:
                if hit.group(1) in done_ids or hit.group(1) in archived:
                    findings.append((rel, "⛔ 殭屍待辦(圖上已完成,這裡還沒打勾)",
                                     f"第 {lineno} 行:{clean(text)[:80]}"))
                continue          # 掛了 id 又不是 ✅ → 正常的進行中,不要吵
            if any(max(similar(text[:w], t) for w in ZOMBIE_WINDOWS) >= ZOMBIE_SIM
                   for t in titles):
                findings.append((rel, "👀 這件事圖上已經完成了,這裡還沒打勾",
                                 f"第 {lineno} 行:{clean(text)[:80]}"))
    return findings


def clean(text):
    return " ".join(MM_ID_RE.sub("", text).split())


def check(only=None):
    data = load_map()
    on_map_all = map_todos_by_project(data)
    node_ids = all_node_ids(data)
    archived = archived_ids()
    arch_titles = archived_titles()
    state = last_synced()
    findings = []
    for rel in sorted(on_map_all):
        if only and only != rel:
            continue
        on_map = on_map_all[rel]
        _open_n, unreadable, _declared, waiting = own_todos(rel)
        since = None
        if state.get(rel):
            since = state[rel][:10]
        entries = new_changelog_entries(rel, since)
        hot = [e for e in entries if DECISION_WORDS.search(e[1])]

        if unreadable:
            msg = ("有條列卻沒有 `- [ ]` 方框 → 圖上看不到它在幹嘛。"
                   "修格式,或加一行 `<!-- mm:no-own-todos 原因 -->`(全域 §十九之一)")
            findings.append((rel, "⛔ TODO.md 讀不到", msg))
        if hot:
            for day, title in hot[:3]:
                findings.append((rel, f"👀 {day} 的決定可能沒進圖", title[:90]))
        elif entries:
            findings.append((rel, f"· {len(entries)} 條新 CHANGELOG(看起來是日常改動)",
                             entries[0][1][:70]))
        # ⏳ 是「球在使用者身上」。這種東西只躺在專案檔裡,使用者不會看到 → 最該提醒的就是它
        for item, node_id in waiting:
            if node_id:
                if node_id in node_ids:
                    continue  # 自己掛了 id,而且那顆真的在 → 已經在圖上了
                # ⚠️ 查無此顆有兩種完全不同的意思,⛔ 不可以混報:
                # ①它其實做完了、被歸檔了 → 這一行該打勾,不是打錯字
                # ②真的打錯字/節點被刪 → 才是斷鏈
                # 混在一起報的後果是 ⛔ 變成雜訊,久了連真的斷鏈也沒人看。
                # ⚠️ 2026-08-22 之前歸檔的那些列沒有留 id(那天才加的)→ 只靠 id 會把它們
                # 全部誤報成斷鏈。所以再退一步用標題比對:比得中就當作「已歸檔」。
                if node_id in archived or _looks_archived(item, arch_titles):
                    findings.append((rel, "👀 這件事已完成並歸檔了,這裡還沒打勾",
                                     f"{item} → mm:{node_id}"))
                else:
                    findings.append((rel, "⛔ 掛的心智圖 id 不存在(斷鏈)",
                                     f"{item} → mm:{node_id}"))
                continue
            if not any(similar(item, t) >= SIM_THRESHOLD for t in on_map):
                findings.append((rel, "👀 這件事在等你,圖上卻沒有", item))
    # ④ 反方向:圖說做完了,專案檔卻還留著沒打勾的副本(⛔ 不受 only 限制的檔也要掃)
    for rel, tag, detail in zombie_todos(data):
        if only and not rel.startswith(only):
            continue
        findings.append((rel, tag, detail))
    return findings


def main(argv):
    # 給別的腳本用的:印出「已經完成或已歸檔」的節點 id,一行一個。
    # 每日排程報告掃 ⏳ 的時候要拿它把殭屍濾掉 —— 不然圖上明明打勾了,報告還是天天念。
    if len(argv) > 1 and argv[1] == "--done-ids":
        data = load_map()
        ids = {i for i, _ in done_on_map(data) if i} | archived_ids()
        print("\n".join(sorted(ids)))
        return 0
    only = argv[1] if len(argv) > 1 else None
    findings = check(only)
    if not findings:
        print("✅ 沒有發現漏寫的跡象")
        return 0
    cur = None
    for rel, tag, detail in findings:
        if rel != cur:
            print(f"\n📁 {rel}")
            cur = rel
        print(f"   {tag}\n      {detail}")
    hard = sum(1 for f in findings if f[1].startswith("⛔"))
    print(f"\n⛔ 一定要處理 {hard} 項;其餘是提醒 —— 要不要進圖由你判斷,這支不會自己寫。")
    print("   要寫進圖:python3 mm.py find <關鍵字> → add-todo / explain / set-status")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
