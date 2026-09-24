#!/usr/bin/env python3
"""mm — 讓「任何一條對話的 AI」都能安全地查心智圖、把變動寫回去。

使用者的需求(2026-08-07):「我有任何的計畫變動或是計畫新增、或是我的系統有變更,
AI 會不會同步更新這個心智圖?**不要我之後看這個表格查不到東西。**
而且我也會叫其他專案的 AI 去查這個心智圖。」

## 為什麼要有這支(⛔ 不要繞過它直接改 JSON)

心智圖是全局正本,而且**同時有好幾條對話在動它**(排程的程式、各專案、使用者自己開著網頁)。
直接 Edit JSON 會踩四個坑,而且都是安靜地踩:
  ① 覆蓋掉別人剛存的(沒有 base_mtime 檢查)
  ② id 撞號 → 節點會神祕消失
  ③ 忘了標 aiEdited → 使用者不知道 AI 動過什麼(那個圈圈是明確要求過的)
  ④ 破壞規則(待辦沒等級、項目掛等級…)而沒人發現
這支把四件事都包好:走 API(有衝突偵測)、自動配 id、自動圈起來、寫完自動跑 lint。

## 用法

    python3 mm.py find 關鍵字                    # 找節點(印 id / 路徑 / 狀態)
    python3 mm.py show g-proj-alpha-sub          # 看單一節點(說明 + 子節點)
    python3 mm.py tree g-proj --depth 2          # 看某一支的結構
    python3 mm.py add-todo <父id> "⏳ 要做的事" --pri P2 [--due 2026-08-13] [--why "為什麼"]
    python3 mm.py add-node <父id> "標題" [--kind infra|sop|tool] [--why "這是什麼"]
    python3 mm.py add-article <分類id> "文章名" [--video] [--step "自訂步驟"]
    python3 mm.py set-status <id> 完成           # 待辦/進行中/等別人/完成
    python3 mm.py set <id…> --due 2026-08-20 --effort 4h      # 改死線/工時(可一次多個 id)
    python3 mm.py set <id…> --earliest 2026-08-13             # 不能比這天早做
    python3 mm.py set <id> --pri P1 --tag 一起做 --rename "新標題"
    python3 mm.py explain <id> "新的說明"         # 覆寫說明(⛔ 只寫現況,要做的事用 add-todo)
    python3 mm.py move <id> <新父id>              # 掛錯地方了(⛔ 不要刪掉重加,id 會換)
    python3 mm.py merge <留的id> <併掉的id…> [--rename "…"]  # 幾件小事併成一項(說明保留成清單)
    python3 mm.py archive <id…> [--on 2026-08-12] # 做完了 → 搬進完成紀錄,從圖上移除
    python3 mm.py autoarchive [--days 7] [--dry-run]  # ✅ 放滿 7 天自動搬(janitor 每天叫)
    python3 mm.py lint                           # 體檢(等同 lint_map.py)

伺服器沒開就會明講並停下 —— ⛔ 不准改成「直接寫檔」繞過去(那正是坑①的來源)。
"""

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import lint_map

# ⚠️ 伺服器只綁 Tailscale 介面(見 launchd/mindmap_server.sh 的 MINDMAP_HOST),
#    localhost 一定連不上 —— 兩台 Mac 都走這個位址。
BASE = os.environ.get("MINDMAP_URL", "http://127.0.0.1:8030")
MAP_NAME = os.environ.get("MINDMAP_MAP", "全局總覽圖")
# 做完的事的出口。⛔ 不要改成寫進圖裡的某個「已完成」分支 —— 那只是把垃圾換個地方堆,
# 圖照樣越長越大(使用者的需求,2026-08-13:「做完就是做完了,不用放在上面」)。
ARCHIVE_PATH = pathlib.Path(os.environ.get(
    "MINDMAP_ARCHIVE",
    pathlib.Path.home() / "notes/完成紀錄.md"))
STATUS_BY_NAME = {"待辦": "⏳", "進行中": "🔜", "等別人": "⏸️", "完成": "✅", "無": "", "目標": "🎯"}
PRIORITIES = ("P1", "P2", "P3", "P4")
# 要花多久的八檔。正本是 plan_week.EFFORT_HOURS —— 排程照這個換算成小時,
# 填了它以外的字排程會當成「沒填」,一律先猜 2h。
EFFORTS = ("1h", "2h", "4h", "8h", "12h", "1天", "2天", "1週")
# 「做完之後多久會再來」。⛔ 只收這幾個字 —— 自由輸入的話排程看不懂就會安靜當成一次性,
# 而漏掉一期的代價是真的(週期性申報漏一期就會失去資格)。
REPEATS = {"每天": 1, "每週": 7, "每兩週": 14, "每四週": 28, "每月": "m", "每季": "q", "每年": "y"}



def api(path, payload=None):
    url = f"{BASE}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        method="PUT" if payload is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"⛔ 伺服器回 {e.code}:{detail}\n（409 = 這張圖在你讀取後被別人改過,重跑一次就好）")
    except OSError as e:
        raise SystemExit(
            f"⛔ 連不上心智圖伺服器({BASE}):{e}\n"
            "   它是 launchd 常駐服務,先確認:\n"
            "     launchctl kickstart -k gui/$(id -u)/com.sc.mindmap-server\n"
            "   ⛔ 不要改成直接寫 JSON 檔繞過去 —— 那會蓋掉別條對話剛存的東西。"
        )


def load():
    out = api(f"/api/maps/{urllib.parse.quote(MAP_NAME)}")
    return out["data"], out["mtime"]


def hard_problems(data):
    """回傳這張圖現在的硬錯集合 {(檢查項, 節點id)}。"""
    found = lint_map.lint(data)
    return {(k, nid) for k in lint_map.HARD for nid, _ in found[k]}


def blocked_by(before, after):
    """⛔ 只擋「這次改動製造出來的」問題。

    圖上本來就有的舊問題不擋 —— 否則一張有歷史包袱的圖會讓所有新增都寫不進去,
    等於罰錯了人(2026-08-07 實測:沙盒圖有 5 個舊問題,害冒煙測試整個寫不進去)。"""
    return after - before


def walk(node, path=""):
    here = f"{path} › {node['topic']}" if path else node["topic"]
    yield node, here
    for child in node.get("children") or []:
        yield from walk(child, here)


def find_node(data, nid):
    for node, path in walk(data["nodeData"]):
        if node["id"] == nid:
            return node, path
    raise SystemExit(f"⛔ 找不到 id={nid}。先用 `mm.py find <關鍵字>` 查。")


RETIRED_PATH = pathlib.Path(os.environ.get(
    "MINDMAP_RETIRED", ARCHIVE_PATH.parent.parent / "mindmaps/.retired_ids.json"))


def retired_ids():
    """已經離開圖的 id。⛔ 不准再發給新節點。

    出過的問題:某一顆歸檔之後,下一次 add-todo 就把同一個 id 撿回去用了。
    專案 TODO.md 那些 `<!--mm:節點id-->` 認親記號**不會報錯**,它們會安靜地指到
    一件完全不相干的事 —— 比斷鏈更糟,斷鏈至少 drift_check 會喊。

    ⚠️ 「檔案不存在」與「檔案壞掉」要分開(2026-08-17 複查抓到):以前兩種都回空集合,
    於是壞檔的下一次 retire() 會把整份名單覆蓋成只剩這次那幾個 —— 靜靜地,
    而且之後那些 id 就會被重新發出去。壞掉要炸開,不要自己「復原」。
    """
    if not RETIRED_PATH.exists():
        return set()
    try:
        return set(json.loads(RETIRED_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        raise SystemExit(
            f"⛔ 退休 id 名單讀不了({RETIRED_PATH}):{e}\n"
            "   ⛔ 不會當成空的繼續跑 —— 那會把整份名單洗掉,離場過的 id 又被發出去,\n"
            "      專案 TODO 的 <!--mm:id--> 就會安靜地指到不相干的事。\n"
            "   先修好那個檔(它就是一個字串陣列)或先刪掉它再跑。"
        ) from e


def retire(ids):
    keep = sorted(retired_ids() | set(ids))
    RETIRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 先寫暫存再換過去:中途斷掉不會留下半份 JSON(半份 = 下次讀就壞 = 整份被洗掉)
    tmp = RETIRED_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    tmp.replace(RETIRED_PATH)


def new_id(data, prefix):
    used = {n["id"] for n, _ in walk(data["nodeData"])} | retired_ids()
    i = 1
    while f"{prefix}-{i:03d}" in used:
        i += 1
    return f"{prefix}-{i:03d}"


MM_MARK = re.compile(r"<!--\s*mm:([\w-]+)\s*-->")


def warn_dangling(ids):
    """節點要離開圖了 → 先去專案 TODO.md 看看有沒有人掛著它的認親記號。

    ⛔ 只報告不動手:那些檔在別的領域資料夾,全域規則要先問過使用者才能改。
    但**一定要講** —— 安靜地留下斷鏈,下週日 drift_check 才喊,那時已經沒人記得是誰弄的。
    """
    root = pathlib.Path(os.environ.get(
        "MINDMAP_PROJECTS_ROOT", pathlib.Path.home() / "projects"))
    hits = []
    for path in sorted(root.glob("*/TODO.md")) + sorted(root.glob("*/*/TODO.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            if any(m.group(1) in ids for m in MM_MARK.finditer(line)):
                hits.append(f"{path.relative_to(root)}:{n}")
    if hits:
        print(f"   ⚠️ 有 {len(hits)} 行專案待辦還掛著這些 id,不改就會變成斷鏈:")
        for h in hits:
            print(f"      {h}")
        print("      → 那一行若也結束了就刪掉;還沒結束就補一顆新節點再改掛過去。")
    return hits


def save(data, mtime, why, before=frozenset(), circled=True):
    """寫回去之前先體檢 —— 規則沒人查等於沒有,所以把查的動作綁在寫的動作上。

    circled=False 用在「把節點移走」的操作 —— 東西都不在圖上了,
    叫使用者去看紫圈只會讓人找不到(⛔ 訊息要對得起實際發生的事)。
    """
    made = blocked_by(before, hard_problems(data))
    if made:
        print("⛔ 這次改動會製造出違規,沒有寫入:")
        for key, nid in sorted(made):
            print(f"   {key}:[{nid}]")
        raise SystemExit(1)
    if before:
        print(f"👀 這張圖本來就有 {len(before)} 個舊問題(不是這次造成的),跑 `mm.py lint` 看細節")
    api(f"/api/maps/{urllib.parse.quote(MAP_NAME)}", {"data": data, "base_mtime": mtime})
    print(f"✅ {why}")
    _remind_waiting(data)
    if circled:
        print("   已經圈起來(紫色虛線)—— 可以用工具列的 ⭕ 逐顆檢查,不必另外通知。")


def _remind_waiting(data):
    """每次寫入圖之後都提一句「還有什麼在等條件」。

    使用者的需求(2026-08-18):「送進暫停的那些東西,你就會去觸發去看一下…我們就不用管他了吧?」
    ⚠️ **靠 AI 記得是不成立的** —— 每條對話都是新的,昨天的承諾帶不過來。
    所以把提醒掛在**工具**上:任何一條對話只要動了圖,就會看到這一行。
    (另外兩道:每週的排程念一遍、/day 有「⏸️ 等條件」分頁。三道都不靠記憶。)
    ⛔ 只印一行、只印條件不印細節 —— 每次寫入都洗一大段等於沒人看。
    """
    conds = []
    for node, _ in walk(data["nodeData"]):
        cond = ((node.get("detail") or {}).get("until") or "").strip()
        if cond and cond not in conds:
            conds.append(cond)
    if conds:
        print(f"   ⏸️ 另外有 {len(conds)} 個條件還在等:{' / '.join(conds[:3])}"
              + (" …" if len(conds) > 3 else "")
              + "　→ 成立了就 `mm.py release --until \"<原句>\"`")


def stamp(what):
    return f"{datetime.now().astimezone().date().isoformat()} {what}"


# ── 查 ────────────────────────────────────────────────────────────
def cmd_find(args):
    data, _ = load()
    kw = args.keyword.lower()
    hits = 0
    for node, path in walk(data["nodeData"]):
        blob = " ".join([
            node.get("topic", ""),
            (node.get("detail") or {}).get("explain", ""),
            " ".join(node.get("tags") or []),
        ]).lower()
        if kw in blob:
            kind = "待辦" if node.get("todo") else (node.get("kind") or "項目")
            pri = next((t for t in (node.get("tags") or []) if t in PRIORITIES), "")
            print(f"[{node['id']}] {kind}{' ' + pri if pri else ''} — {path}")
            hits += 1
    print(f"\n{hits} 筆" if hits else "沒找到。換個關鍵字,或用 `mm.py tree` 看整體結構。")


def cmd_show(args):
    data, _ = load()
    node, path = find_node(data, args.id)
    kind = "待辦" if node.get("todo") else (node.get("kind") or "項目")
    print(f"[{node['id']}] {node['topic']}\n位置:{path}\n種類:{kind}")
    if node.get("tags"):
        print("標籤:", " ".join(node["tags"]))
    d = node.get("detail") or {}
    for key, label in (("due", "截止日"), ("effort", "要花多久"),
                       ("earliest", "不能早於"), ("window", "只能在哪做")):
        if d.get(key):
            lock = " 🔒 外力死線,不會被整串推走" if key == "due" and d.get("hardDue") else ""
            print(f"{label}:{d[key]}{lock}")
    if node.get("hyperLink"):
        print("連結:", node["hyperLink"])
    if d.get("explain"):
        print("\n說明:\n" + d["explain"])
    kids = node.get("children") or []
    if kids:
        print(f"\n底下 {len(kids)} 個:")
        for c in kids:
            mark = "☑" if c.get("todo") else "·"
            print(f"  {mark} [{c['id']}] {c['topic']}")


def cmd_tree(args):
    data, _ = load()
    root = find_node(data, args.id)[0] if args.id else data["nodeData"]

    def dump(n, depth=0):
        if depth > args.depth:
            return
        mark = "☑" if n.get("todo") else ("📐" if n.get("kind") == "sop" else "·")
        print("  " * depth + f"{mark} [{n['id']}] {n['topic']}")
        for c in n.get("children") or []:
            dump(c, depth + 1)

    dump(root)


# ── 改 ────────────────────────────────────────────────────────────
def cmd_add_todo(args):
    data, mtime = load()
    before = hard_problems(data)
    parent, path = find_node(data, args.parent)
    if args.pri not in PRIORITIES:
        raise SystemExit(f"⛔ 等級要是 {PRIORITIES} 其中之一 —— 每條待辦都要有,不然排程排不了")
    topic = args.topic.strip()
    if topic[:1] not in "⏳🔜⏸✅":
        topic = "⏳ " + topic  # 待辦一定看得出處在哪一階段
    node = {
        "id": new_id(data, "ai"),
        "topic": topic,
        "todo": True,
        "tags": [args.pri],
        "aiEdited": stamp(args.by or "AI 新增的待辦"),
    }
    detail = {}
    if args.why:
        detail["explain"] = args.why
    if args.due:
        detail["due"] = args.due
    if detail:
        node["detail"] = detail
    parent.setdefault("children", []).append(node)
    # 父節點如果長得像任務,加了子待辦之後它就該是項目了 —— 提醒,不擅自改
    if (parent.get("topic") or "")[:1] in "⏳🔜⏸" and not parent.get("todo"):
        print(f"👀 父節點「{parent['topic']}」標題像任務又不是待辦,建議改成項目的講法")
    save(data, mtime, f"新增待辦 [{node['id']}] {topic}({args.pri})→ 掛在 {path}", before)


def cmd_add_node(args):
    data, mtime = load()
    before = hard_problems(data)
    parent, path = find_node(data, args.parent)
    node = {
        "id": new_id(data, "ai"),
        "topic": args.topic.strip(),
        "aiEdited": stamp(args.by or "AI 新增的節點"),
    }
    if args.kind:
        node["kind"] = args.kind
    if args.why:
        node["detail"] = {"explain": args.why}
    parent.setdefault("children", []).append(node)
    save(data, mtime, f"新增節點 [{node['id']}] {node['topic']} → 掛在 {path}", before)


# 每篇文章底下都是同一組固定的事。使用者的需求(2026-08-08):「我每一次都要去填,有幾個固定任務
# 就是整理照片跟撰寫文章,有時候會有比較特別的像是製作成影片,這些我每次都要自己填寫嗎?」
# → 不用。一行長出來,等級由 --pri 帶,免得每條都要點一次。
ARTICLE_STEPS = ["⏳ 整理照片", "⏳ 撰寫文章"]


def cmd_add_article(args):
    data, mtime = load()
    before = hard_problems(data)
    parent, path = find_node(data, args.parent)
    art = {"id": new_id(data, "art"), "topic": args.title.strip(),
           "aiEdited": stamp("新增文章")}
    if args.why:
        art["detail"] = {"explain": args.why}
    steps = list(ARTICLE_STEPS)
    if args.video:
        steps.append("⏳ 製作影片")
    for extra in args.step or []:
        steps.append(extra if extra[:1] in "⏳🔜⏸✅" else "⏳ " + extra)
    art["children"] = []
    for i, topic in enumerate(steps, 1):
        art["children"].append({
            "id": f"{art['id']}-{i}", "topic": topic, "todo": True,
            "tags": [args.pri], "aiEdited": stamp("文章的固定步驟"),
        })
    parent.setdefault("children", []).append(art)
    save(data, mtime, f"新增文章「{art['topic']}」+ {len(steps)} 個步驟 → 掛在 {path}", before)


def _guard_sc_status(node, topic, mark, force):
    """使用者自己在 /day 或任務板按過的狀態,⛔ AI 不准安靜地改掉。

    2026-08-18 出過的問題:使用者在排今天把一顆節點按成完成,那次改動被另一條對話的
    commit 順手帶走;我看到 commit 訊息沒提這顆,就判成「誤標」並用 set-status 改回 ⏳,
    還把錯的推論寫進說明。他隔天問「我已經按了好幾次完成,為什麼還一直跳出來」——
    **一直跳出來的原因就是我把它按回去了。**

    節點上其實有證據:day.js / board.js 改狀態時會寫 `scEdited`(而且會刪掉 aiEdited),
    只是沒有人去看。改成機械擋下來:要反轉他近期親手設的狀態,得先問過他再帶 --force。
    ⛔ 不要把這條放寬成「印個警告就過」—— 警告在自動流程裡等於沒有。
    """
    sc = (node.get("scEdited") or "").strip()
    if not sc or "狀態" not in sc:
        return
    m = re.match(r"(\d{4}-\d{2}-\d{2})", sc)
    if m:
        try:
            age = (datetime.now().astimezone().date() - date.fromisoformat(m.group(1))).days
        except ValueError:
            age = 0
        if age > 7:
            return
    cur = ""
    for x in ("⏳", "🔜", "⏸️", "⏸", "✅", "🎯"):
        if (node.get("topic") or "").strip().startswith(x):
            cur = x
            break
    if cur == mark or force:
        return
    raise SystemExit(
        f"⛔ 這顆的狀態是使用者自己按的({sc}),現在是「{cur or '無'}」,你要改成「{mark or '無'}」。\n"
        f"   節點:{topic}\n"
        "   ⛔ 不准自己改回去 —— 先問他「這件事你按完成了,但我查到 X,要維持完成嗎?」\n"
        "   他說要改,再加 --force 跑一次。"
    )


def cmd_set_status(args):
    data, mtime = load()
    before = hard_problems(data)
    node, path = find_node(data, args.id)
    mark = STATUS_BY_NAME.get(args.status, args.status)
    if mark not in ("", "⏳", "🔜", "⏸️", "✅", "🎯"):
        raise SystemExit(f"⛔ 狀態要是:{'/'.join(STATUS_BY_NAME)}")
    topic = (node.get("topic") or "").strip()
    was_done = topic.startswith("✅")
    _guard_sc_status(node, topic, mark, args.force)
    for m in ("⏳", "🔜", "⏸️", "⏸", "✅", "🎯"):
        if topic.startswith(m):
            topic = topic[len(m):].strip()
            break
    node["topic"] = f"{mark} {topic}".strip()
    # 標 ✅ 的那天要記下來 —— 7 天後自動歸檔靠它算,⛔ 不能靠 aiEdited(任何一次改說明都會蓋掉)。
    # ⚠️ 「本來就是 ✅ 又標一次」保留原日期;「從別的狀態轉成 ✅」一定要蓋成今天 ——
    #    不然「打勾 → 取消 → 過幾週再打勾」會沿用第一次那個舊日期,當晚就被判到期搬走。
    det = node.setdefault("detail", {})
    if mark == "✅":
        today_iso = datetime.now().astimezone().date().isoformat()
        if was_done:
            det.setdefault("doneOn", today_iso)
        else:
            det["doneOn"] = today_iso
    else:
        det.pop("doneOn", None)
    node["aiEdited"] = stamp(f"狀態改成 {mark or '無'}")
    save(data, mtime, f"[{node['id']}] {path} → {node['topic']}", before)
    if mark == "✅":
        _warn_stale_copies(node)


def _warn_stale_copies(node):
    """標 ✅ 的當下,順手去各專案 TODO.md 找「同一件事的手寫副本還沒打勾」。

    ⚠️ 為什麼要在這個時間點做,而不是等每週日的 drift_check:
    使用者抱怨過:同一件早就做完的事,另一個地方還一直把它拉出來。
    圖上那顆早就 ✅,但兩個專案的 TODO.md 各留一條手寫的沒打勾,
    而早報是掃那些檔的 → 同一件已完成的事被一問再問。
    **打勾的那一刻,是唯一「有人在現場而且知道這件事做完了」的時刻** —— 錯過就要等到下週日,
    那時沒有人記得這條是哪來的。⛔ 只印警告,不自動改別人的專案檔。
    """
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import drift_check
        hits = drift_check.zombie_todos(
            {"nodeData": {"id": "x", "topic": "x", "children": [dict(node, children=[])]}},
            include_archive=False)          # 只問這一顆,別把整份完成紀錄的舊帳翻出來
    except (OSError, ValueError, ImportError, KeyError):
        return                                   # ⛔ 查不到就閉嘴,不要害 set-status 失敗
    if not hits:
        return
    print("\n⚠️ 這件事在專案檔裡還有沒打勾的副本 —— 不清掉的話早報會繼續把它撈出來:")
    for rel, _tag, detail in hits:
        print(f"   {rel} {detail}")


def cmd_explain(args):
    data, mtime = load()
    before = hard_problems(data)
    node, path = find_node(data, args.id)
    node.setdefault("detail", {})["explain"] = args.text
    node["aiEdited"] = stamp("更新說明")
    save(data, mtime, f"[{node['id']}] {path} 的說明已更新", before)


def _check_source(rel):
    """把一顆節點認養成某個專案的入口。

    ⚠️ 為什麼需要這個指令:`source` 是整套「圖 ↔ 專案」連動的開關 ——
    掛了它,sync_todos 才會在那個專案的 TODO.md 生同步區、drift_check 才會去對帳。
    但在 2026-08-22 之前 mm.py **完全沒有辦法設它**,唯一的做法是直接 Edit 那份 JSON,
    而那正是規則明令禁止的。結果就是:有 TODO.md 卻沒掛上的專案一直沒人接,
    圖上 39 條待辦在任何專案檔裡都看不到 —— 使用者說「我希望我在每個地方都可以看到
    我有哪些待辦事項」,缺的就是這一個開關。

    ⛔ 路徑一定要真的存在 —— 打錯字的話 sync 會安靜地什麼都不做,沒有任何錯誤訊息。
    """
    root = pathlib.Path(
        os.environ.get("MINDMAP_PROJECTS_ROOT", pathlib.Path.home() / "projects"))
    target = root / rel
    if not target.is_dir():
        raise SystemExit(f"⛔ 找不到資料夾 {target} —— 專案路徑要相對 {root},例如 Finance、Program/mindmap")
    if not (target / "TODO.md").is_file():
        raise SystemExit(
            f"⛔ {rel} 底下沒有 TODO.md。同步區要寫進那個檔,沒有檔就沒地方寫。\n"
            f"   先建一個(至少一行 `# TODO`),再掛上來。")


def cmd_set(args):
    """改死線 / 要花多久 / 等級 / 標籤 / 標題。可以一次給好幾個 id。

    為什麼要有這支:規則要 AI「給了死線或估了工時就填 detail.due / detail.effort」,
    但在此之前 mm.py 只能新增跟改狀態 —— 唯一的辦法是直接 Edit 那份 JSON,
    而那正是規則明令禁止的(會蓋掉別條對話、id 撞號、忘了標 aiEdited)。
    2026-08-11 重排 26 條死線時補上。
    """
    if args.effort and args.effort not in EFFORTS:
        raise SystemExit(f"⛔ 要花多久只能填:{'/'.join(EFFORTS)}")
    if args.repeat and args.repeat != "none" and args.repeat not in REPEATS:
        raise SystemExit(f"⛔ 多久來一次只能填:{'/'.join(REPEATS)}(或 none 拿掉)")
    if args.owner and args.owner not in ("ai", "me"):
        raise SystemExit("⛔ 這是誰的事只能填 ai 或 me")
    if args.pri and args.pri not in PRIORITIES:
        raise SystemExit(f"⛔ 等級要是 {PRIORITIES} 其中之一")
    if args.rename and len(args.id) > 1:
        raise SystemExit("⛔ 改標題一次只能一個 id")

    data, mtime = load()
    before = hard_problems(data)
    changed = []
    for nid in args.id:
        node, path = find_node(data, nid)
        detail = node.setdefault("detail", {})
        did = []
        if args.due:
            detail["due"] = args.due
            did.append(f"死線→{args.due}")
        if args.no_due:
            detail.pop("due", None)
            did.append("拿掉死線")
        if args.effort:
            detail["effort"] = args.effort
            did.append(f"要花{args.effort}")
        if args.repeat:
            if args.repeat == "none":
                detail.pop("repeat", None)
                did.append("拿掉週期")
            else:
                detail["repeat"] = args.repeat
                did.append(f"週期→{args.repeat}")
        if args.owner:
            if args.owner == "me":
                detail.pop("owner", None)
                did.append("改回我的事")
            else:
                detail["owner"] = "ai"
                did.append("改成 AI 的事")
        if args.hard_due:
            detail["hardDue"] = True
            did.append("鎖成外力死線")
        if args.soft_due:
            detail.pop("hardDue", None)
            did.append("改成可移動的日期")
        if args.earliest:
            detail["earliest"] = args.earliest
            did.append(f"不能早於{args.earliest}")
        if args.no_earliest:
            detail.pop("earliest", None)
            did.append("拿掉最早日期")
        if args.source:
            _check_source(args.source)
            node["source"] = args.source
            did.append(f"掛上專案 {args.source}")
        if args.no_source:
            node.pop("source", None)
            did.append("拿掉專案掛載")
        if args.window:
            detail["window"] = args.window
            did.append("改成要你自己挑日子")
        if args.no_window:
            detail.pop("window", None)
            did.append("拿掉挑日子限制")
        tags = node.setdefault("tags", [])
        if args.pri:
            node["tags"] = [t for t in tags if t not in PRIORITIES] + [args.pri]
            tags = node["tags"]
            did.append(f"等級→{args.pri}")
        for t in args.tag:
            if t not in tags:
                tags.append(t)
                did.append(f"+{t}")
        for t in args.untag:
            if t in tags:
                tags.remove(t)
                did.append(f"-{t}")
        if args.rename:
            mark = next((m for m in ("⏳", "🔜", "⏸️", "⏸", "✅", "🎯")
                         if (node.get("topic") or "").startswith(m)), "")
            node["topic"] = f"{mark} {args.rename}".strip()
            did.append("改標題")
        if not did:
            raise SystemExit("⛔ 沒指定要改什麼")
        if not detail:
            node.pop("detail", None)
        node["aiEdited"] = stamp("、".join(did))
        changed.append(f"[{nid}] {path} → {'、'.join(did)}")
    save(data, mtime, f"改了 {len(changed)} 個節點:\n   " + "\n   ".join(changed), before)


def cmd_move(args):
    """把節點(連同底下整支)換一個父節點。

    ⛔ 為什麼要有:在這之前掛錯地方就只能刪掉重加 —— 而重加會換掉 id,
    專案 TODO 那些 `<!--mm:id-->` 認親記號會全部變成斷鏈。搬比重建安全。
    """
    data, mtime = load()
    before = hard_problems(data)
    node, path = find_node(data, args.id)
    dest, dest_path = find_node(data, args.to)
    if args.id == args.to:
        raise SystemExit("⛔ 不能搬到自己底下。")
    if any(n["id"] == args.to for n, _ in walk(node)):
        raise SystemExit(f"⛔ [{args.to}] 在 [{args.id}] 底下 —— 搬過去會讓這一支從圖上消失。")
    parent = next((pn for pn, _ in walk(data["nodeData"])
                   if any(c["id"] == args.id for c in pn.get("children") or [])), None)
    if parent is None:
        raise SystemExit(f"⛔ [{args.id}] 是根節點或找不到父節點,不動它。")
    parent["children"] = [c for c in parent["children"] if c["id"] != args.id]
    dest.setdefault("children", []).append(node)
    node["aiEdited"] = stamp(f"搬到「{dest['topic']}」底下")
    save(data, mtime, f"[{args.id}] {path}\n   → {dest_path} › {node['topic']}", before)


def _cell(text):
    """塞進表格欄位的字:`|` 會把欄位切斷、換行會把列切斷,兩個都要處理。"""
    return text.replace("|", "\\|").replace("\n", "<br>").strip()


def _archive_line(node, path, done_on, reported_on):
    """一顆節點在完成紀錄裡長什麼樣。

    ⛔ 必須是**表格列** —— `notes/完成紀錄.md` 是三欄表(完成的事/實際完成日/回報日),
    插條列進去會把表格從中間切斷。2026-08-17 差點就這樣寫進去。
    理由要一起搬 —— 只留標題等於把「為什麼」丟掉。
    """
    topic = (node.get("topic") or "").strip()
    for m in ("⏳", "🔜", "⏸️", "⏸", "✅", "🎯"):
        if topic.startswith(m):
            topic = topic[len(m):].strip()
            break
    det = node.get("detail") or {}
    pri = next((t for t in (node.get("tags") or []) if t.startswith("P")), "")
    where = " › ".join(path.split(" › ")[:-1][-2:])
    meta = " · ".join(x for x in [pri, det.get("effort", ""), where] if x)
    what = f"**{_cell(topic)}**"
    if meta:
        what += f"({_cell(meta)})"
    why = (det.get("explain") or "").strip()
    if why:
        what += f" ── {_cell(why)}"
    # ⚠️ 把節點 id 一起留下來(HTML 註解,markdown 算圖看不到)。
    # 為什麼:專案 TODO.md 那些手寫行是用 `<!--mm:節點id-->` 認親的,而歸檔會把節點從圖上移走
    # → 那些指標全部變成「查無此顆」,drift_check 就永遠報 ⛔ 斷鏈。真的抓到過一顆
    # 就是這樣:它其實早就完成並歸檔了,警告卻長得像「你打錯字」。**假警報比漏報更糟**,
    # 因為 ⛔ 一多就沒有人看 ⛔ 了。留著 id,drift 才分得出「歸檔了」跟「真的斷鏈」。
    nid = node.get("id")
    if nid:
        what += f" <!--mm:{nid}-->"
    return f"| {what} | {done_on or '實際完成日不詳'} | {reported_on} |"


def cmd_archive(args):
    """把做完的待辦從圖上移走,搬進 notes/完成紀錄.md。

    使用者的需求(2026-08-13):「做完就是做完了,不用放在上面。除非它做完之後會變成一個結構 ——
    但通常不會,通常就是完善這個結構。」
    ⛔ 只搬「待辦」。設施/規則/專案那種**結構**節點本來就不是待辦,它們一直都在;
    做完之後長出來的結構是**另外一顆**節點,不是同一顆變過去。
    """
    data, mtime = load()
    before = hard_problems(data)
    moved, lines = [], []
    for nid in args.id:
        node, path = find_node(data, nid)
        if not node.get("todo"):
            raise SystemExit(
                f"⛔ [{nid}] {path} 不是待辦,是結構節點 —— 結構不歸檔,它一直都在。\n"
                "   (要拿掉一個結構節點請自己想清楚再手動處理,這支刻意不做。)")
        if node.get("children"):
            raise SystemExit(f"⛔ [{nid}] 底下還有 {len(node['children'])} 顆,先處理完再歸檔。")
        if (lines_ := _arrows_on(data, nid)):
            raise SystemExit(f"⛔ [{nid}] 上面有 {len(lines_)} 條關聯線,搬走會讓線的另一端"
                             "顯示「對方節點已不在圖上」。先處理線。")
        parent = _parent_of(data, nid)
        if parent is None:
            raise SystemExit(f"⛔ [{nid}] 找不到父節點,不動它。")
        lines.append(_archive_line(node, path, *_dates_for(node, args.on)))
        parent["children"] = [c for c in parent["children"] if c["id"] != nid]
        moved.append((nid, path))

    # ⛔ 順序不可以反過來:save() 走網路,409(使用者開著網頁)跟伺服器重啟都會 SystemExit。
    #    先寫完成紀錄就會留下「圖上還在、紀錄已多一列」的孤兒,而 api() 還叫人「重跑一次就好」
    #    —— 照做就再 append 一列一模一樣的。存圖成功了才落地,失敗就整批什麼都沒發生。
    save(data, mtime, f"歸檔 {len(moved)} 顆 → {ARCHIVE_PATH}", before, circled=False)
    _commit_archive(lines)
    retire([nid for nid, _ in moved])
    for nid, path in moved:
        print(f"   📦 [{nid}] {path}")
    warn_dangling({nid for nid, _ in moved})
    print("   ⚠️ 專案的事記得也在該專案 CHANGELOG 留一行(這支不會自己去改別人的檔)。")


def cmd_drop(args):
    """決定不做了 —— 把待辦從圖上移走,但記成「❌ 不做了」而不是「完成」。

    2026-08-19 使用者決定砍掉某個專案的一個分頁時發現的洞:圖上一顆事情的出路
    只有「做完」一條(archive)。真實世界還有第二條 —— **決定不做了**。
    沒有這條路,AI 只能① 硬標 ✅ 讓完成紀錄多一筆從沒做過的事,或② 就讓它爛在圖上。
    兩個都很糟:①之後查「這功能做了沒」會查到假的;②正是他今天連續問三顆的原因。

    ⛔ 一定要有 --why:一年後看到「這件事不做了」而沒有理由,等於沒有紀錄 ——
    下一輪規劃時它會原封不動地被重新提出來,然後再評估一次。
    """
    data, mtime = load()
    before = hard_problems(data)
    node, path = find_node(data, args.id)
    if not node.get("todo"):
        raise SystemExit(f"⛔ [{args.id}] {path} 不是待辦,是結構節點 —— 結構不走這條。")
    if node.get("children"):
        raise SystemExit(f"⛔ [{args.id}] 底下還有 {len(node['children'])} 顆,先處理完。")
    if (arrows := _arrows_on(data, args.id)):
        raise SystemExit(f"⛔ [{args.id}] 上面有 {len(arrows)} 條關聯線,先處理線。")
    parent = _parent_of(data, args.id)
    if parent is None:
        raise SystemExit(f"⛔ [{args.id}] 找不到父節點,不動它。")

    det = node.setdefault("detail", {})
    det["explain"] = ((det.get("explain") or "").strip()
                      + f"\n\n❌ {datetime.now().astimezone().date().isoformat()} 決定不做了:"
                      + args.why).strip()
    today = datetime.now().astimezone().date().isoformat()
    # 「實際完成日」那一欄對「不做了」沒有意義 —— ⛔ 不要留「不詳」,那看起來像做了但忘了記。
    line = (_archive_line(node, path, "", today)
            .replace("| **", "| ❌ 不做了 · **", 1)
            .replace("| 實際完成日不詳 |", "| —(沒做) |", 1))
    parent["children"] = [c for c in parent["children"] if c["id"] != args.id]

    # ⛔ 順序同 archive:存圖成功了才落地,不然會留下「圖上還在、紀錄已多一列」的孤兒。
    save(data, mtime, f"[{args.id}] {path} → ❌ 不做了", before, circled=False)
    _commit_archive([line])
    retire([args.id])
    warn_dangling({args.id})
    print(f"   ❌ [{args.id}] {path} —— 理由已寫進 {ARCHIVE_PATH}")
    print("   ⚠️ 專案的事記得也在該專案 CHANGELOG/TODO 留一行(這支不會去改別人的檔)。")


def _parent_of(data, nid):
    return next((p for p, _ in walk(data["nodeData"])
                 if any(c["id"] == nid for c in p.get("children") or [])), None)


def _arrows_on(data, nid):
    """指到這顆節點的關聯線。節點要離場前一定要看 —— 線的另一端會變成「對方已不在圖上」。

    merge 本來就擋,archive/autoarchive 以前不擋(2026-08-17 複查抓到);
    autoarchive 還是**無人值守**在跑的,靜靜把線的另一端弄壞最糟。
    """
    return [a for a in data.get("arrows") or []
            if a.get("from") == nid or a.get("to") == nid]


def _dates_for(node, on=None):
    """(實際完成日, 回報日)。

    `doneOn` = 標 ✅ 的那天,由 set-status 記下。AI 是做完當下標的,所以那天通常就是完成日;
    事後補勾舊的東西要自己給 `--on`,⛔ 不要讓工具去猜。兩個都沒有 → 誠實寫「不詳」。
    """
    marked = ((node.get("detail") or {}).get("doneOn") or "").strip()
    today = datetime.now().astimezone().date().isoformat()
    return (on or marked or "", marked or today)


def _quarter_of(iso):
    return f"{iso[:4]} Q{(int(iso[5:7]) - 1) // 3 + 1}"


def _write_archive(lines, quarter=None):
    """插進「這一批屬於的那個季度」的表格第一列。

    ⛔ 不要插在 `---` 後面(會落在所有季度之外),也⛔ 不要插在 `## ` 標題正下方
    —— 那裡是表頭,插進去等於把資料列擠到表頭前面,整張表就散了。
    ⚠️ 也⛔ 不能一律插「檔案裡第一個 ## 」(2026-08-17 複查抓到):跨季之後
       10 月做完的事會被塞進 `## 2026 Q3` 的表,而那份檔的排序規則就是依季分段。
    """
    quarter = quarter or _quarter_of(datetime.now().astimezone().date().isoformat())
    src = ARCHIVE_PATH.read_text(encoding="utf-8") if ARCHIVE_PATH.exists() else "# 完成紀錄\n"
    rows = src.splitlines()
    head = ["| 完成的事 | 實際完成日 | 回報日 |", "|---|---|---|"]
    at = next((i for i, ln in enumerate(rows)
               if ln.startswith("## ") and quarter in ln), None)
    if at is None:  # 這一季還沒有段落 → 開一段,放在所有季度之前(最新在上)
        first = next((i for i, ln in enumerate(rows) if ln.startswith("## ")), None)
        anchor = (first - 1 if first is not None
                  else next((i for i, ln in enumerate(rows) if ln.strip() == "---"), len(rows) - 1))
        rows[anchor + 1:anchor + 1] = ["", f"## {quarter}", ""] + head + lines + [""]
    else:
        # 找那個季度底下的表格分隔列(|---|),資料列從它下一行開始
        sep = next((i for i in range(at, min(at + 8, len(rows)))
                    if rows[i].startswith("|") and set(rows[i]) <= set("|-: ")), None)
        if sep is None:  # 那一季還沒有表 → 連表頭一起補
            rows[at + 1:at + 1] = [""] + head + lines
        else:
            rows[sep + 1:sep + 1] = lines
    ARCHIVE_PATH.write_text("\n".join(rows).rstrip("\n") + "\n", encoding="utf-8")


def _commit_archive(lines):
    """圖已經存成功了,現在才寫紀錄。

    ⛔ 順序不可以反過來(2026-08-17 複查抓到,而且是無人值守的 janitor 在跑):
    先寫檔、後存圖 → 存圖撞 409(使用者開著 /day 拖卡片時很容易)就留下一列孤兒紀錄,
    節點卻還在圖上;而 409 的訊息還寫著「重跑一次就好」—— 重跑就再多一列。
    存圖是會失敗的那一步,先做;它失敗時什麼都還沒發生,重跑是乾淨的。
    寫檔失敗雖然罕見,但那時節點已經不在圖上了 → **一定要把整列印出來**,不能安靜地弄丟。
    """
    try:
        # 一批裡面可能跨季(補登舊的東西時) → 各自進各自那一季,⛔ 不要全塞進同一段
        groups = {}
        for ln in lines:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            # ⚠️ 用**實際完成日**(第一個日期欄)分季,不是回報日 ——
            #    補登十月做完的事,它該進 Q4,不是進「我今天才想起來」的那一季。
            iso = next((c for c in cells if len(c) == 10 and c[4] == "-"), None)
            key = _quarter_of(iso) if iso else _quarter_of(
                datetime.now().astimezone().date().isoformat())
            groups.setdefault(key, []).append(ln)
        for quarter, batch in sorted(groups.items()):
            _write_archive(batch, quarter)
    except OSError as e:
        print(f"⛔ 圖已經存好了,但完成紀錄寫不進去({e})。下面這幾列請自己補進 {ARCHIVE_PATH}:")
        for ln in lines:
            print("   " + ln)
        raise SystemExit(1) from e


def _effort_sum(nodes):
    """把有填工時的加起來往上取一檔,並回報有幾顆沒填。回 (檔位, 沒填幾顆)。

    ⛔ 不能往下取:合併後的那一項只會比原本更花時間,取小了排程就排不完。
    ⚠️ 有人沒填**不能回空字串**(2026-08-17 複查抓到):呼叫端會把 keeper 本來填好的
       工時一起刪掉,而排程對「沒填」是猜 2h、/day 甚至只給 60 分 ——
       「誠實地不知道」在下游其實等於「假設更小」,還順手弄丟了使用者填過的資料。
       → 用已知的加總當**下限**,並把「有幾顆不知道」講出來。
    """
    import plan_week
    total = 0.0
    unknown = 0
    for n in nodes:
        eff = ((n.get("detail") or {}).get("effort") or "").strip()
        if eff in plan_week.EFFORT_HOURS:
            total += plan_week.EFFORT_HOURS[eff]
        else:
            unknown += 1
    if total <= 0:
        return "", unknown
    return next((e for e in EFFORTS if plan_week.EFFORT_HOURS[e] >= total), EFFORTS[-1]), unknown


def cmd_merge(args):
    """好幾件小事併成一項。

    使用者的需求(2026-08-17):「幫我把這個東西合成一個項目吧,然後裡面項目的說明要講清楚一點,
    我要做哪些事情,就是我做完之後跟 AI 確認我們有沒有做對、有沒有做完的時候再看那個。
    你一次寫五個,我在拉行程的時候很難拉。」
    → 圖上五顆 P2、同一天到期、標著「一起做」的待辦,在 /day 是五塊要各拖一次。

    ⛔ 原本每一顆的說明**逐字保留**進清單裡 —— 合併最容易出的問題就是
       「標題留著、為什麼不見了」,而那些說明裡有的是「要當面問的六個問題」這種真的會用到的東西。
    """
    data, mtime = load()
    before = hard_problems(data)
    keep, drop_ids = args.keep, args.ids
    if keep in drop_ids:
        raise SystemExit("⛔ 要留的那顆不要再列一次。")
    dup = [i for i in set(drop_ids) if drop_ids.count(i) > 1]
    if dup:
        # 同一顆列兩次會被算兩份工時、清單也會出現兩次,而且完全不會報錯
        raise SystemExit(f"⛔ 這幾個 id 列了不只一次:{', '.join(sorted(dup))}")

    keeper, keep_path = find_node(data, keep)
    parent = _parent_of(data, keep)
    nodes = [keeper]
    for nid in drop_ids:
        node, path = find_node(data, nid)
        if not node.get("todo") or not keeper.get("todo"):
            raise SystemExit(f"⛔ [{nid}] {path} 不是待辦 —— 只有待辦能合併,結構節點各有各的意思。")
        if node.get("children"):
            raise SystemExit(f"⛔ [{nid}] 底下還有 {len(node['children'])} 顆,合併會把它們弄不見。")
        if _parent_of(data, nid) is not parent:
            raise SystemExit(f"⛔ [{nid}] 跟 [{keep}] 不在同一個父節點底下,不併 —— "
                             "跨處合併等於偷偷搬家。要搬先用 move。")
        hit = [a for a in data.get("arrows") or []
               if a.get("from") == nid or a.get("to") == nid]
        if hit:
            raise SystemExit(f"⛔ [{nid}] 上面有 {len(hit)} 條關聯線,併掉會讓線斷掉。先處理線。")
        nodes.append(node)

    det = keeper.setdefault("detail", {})
    lines = [args.intro or "這一項包含下面幾件事,做完一件打一個勾;跟 AI 對進度的時候照這張清單念。", ""]
    for i, n in enumerate(nodes, 1):
        topic = (n.get("topic") or "").strip()
        for m in ("⏳", "🔜", "⏸️", "⏸", "✅", "🎯"):
            if topic.startswith(m):
                topic = topic[len(m):].strip()
                break
        # 本來就做完的那幾件要保持打勾 —— 一律寫成 [ ] 等於把做完的事改回沒做
        done = (n.get("topic") or "").strip().startswith("✅")
        lines.append(f"[{'x' if done else ' '}] {i}. {topic}")
        why = ((n.get("detail") or {}).get("explain") or "").strip()
        if why:
            lines.extend("      " + ln for ln in why.splitlines())
        lines.append("")
    det["explain"] = "\n".join(lines).rstrip()

    # 欄位一律取「最保守」的那個:等級最高、死線最早、最早可做日最晚、工時相加
    import plan_week
    pris = [p for n in nodes for p in (n.get("tags") or []) if p in plan_week.PRIS]
    dues = [d for n in nodes if (d := ((n.get("detail") or {}).get("due") or ""))]
    earliest = [e for n in nodes if (e := ((n.get("detail") or {}).get("earliest") or ""))]
    tags = [t for n in nodes for t in (n.get("tags") or []) if t not in plan_week.PRIS]
    if pris:
        keeper["tags"] = [min(pris, key=plan_week.PRIS.index)] + list(dict.fromkeys(tags))
    if dues:
        det["due"] = min(dues)
    if earliest:
        det["earliest"] = max(earliest)
    if any((n.get("detail") or {}).get("hardDue") for n in nodes):
        det["hardDue"] = True
    eff, unknown = _effort_sum(nodes)
    if eff:
        det["effort"] = eff
        if unknown:
            print(f"   ⚠️ 有 {unknown} 件沒填工時,所以 {eff} 是「至少」,不是全部。")
    elif unknown:
        # ⛔ 不准把 keeper 本來填好的工時刪掉:排程對「沒填」是猜 2h(/day 甚至只給 60 分),
        #    刪掉等於把使用者填過的資料換成一個更小的假設,而且沒有人會發現。
        print("   ⚠️ 全部都沒填工時 → 維持原狀,排程會照「沒填」處理(猜 2h)。")

    slots = [s for n in nodes for s in ((n.get("detail") or {}).get("planned") or [])]
    if slots:
        det["planned"] = slots

    # 狀態也照「取最保守」:只要有一件還沒做完,合併後就不算做完。
    # ⛔ 少了這段:keeper 是 ✅ 時 topic 與 doneOn 都原封不動 → 隔幾天 autoarchive 會把
    #    併進來、根本還沒做的那幾件當成完成,搬進完成紀錄、移出圖、id 進退休名單,全程無聲。
    undone = [n for n in nodes if not (n.get("topic") or "").strip().startswith("✅")]
    if args.rename:
        keeper["topic"] = f"⏳ {args.rename.strip()}"
    elif undone and (kt := (keeper.get("topic") or "").strip()).startswith("✅"):
        keeper["topic"] = f"⏳ {kt[len('✅'):].strip()}"
        print("   ⚠️ 要留的那顆本來標了 ✅,但併進來的還沒做完 → 狀態退回 ⏳。")
    if undone:
        det.pop("doneOn", None)
    keeper["aiEdited"] = stamp(f"併入 {len(drop_ids)} 件")

    parent["children"] = [c for c in parent["children"] if c["id"] not in drop_ids]
    retire(drop_ids)
    save(data, mtime, f"[{keep}] {keep_path} ← 併入 {len(drop_ids)} 件", before)
    print(f"   併掉的 id:{', '.join(drop_ids)}")
    warn_dangling(set(drop_ids))


def _add_months(d, n):
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m])
    return date(y, m + 1, day)


def _next_due(base_iso, repeat, today=None):
    """下一期是哪天。⚠️ 一定要落在**今天之後** —— 拖過好幾期的話一次補到未來,
    不然算出來是個過去的日期,行程表立刻噴紅字,而紅字一多就等於沒有紅字。"""
    today = today or datetime.now().astimezone().date()
    step = REPEATS[repeat]
    try:
        cur = date.fromisoformat(base_iso)
    except (TypeError, ValueError):
        cur = today
    for _ in range(400):   # 上限只是防呆,正常一兩圈就跳出
        cur = (cur + timedelta(days=step) if isinstance(step, int)
               else _add_months(cur, {"m": 1, "q": 3, "y": 12}[step]))
        if cur > today:
            return cur.isoformat()
    return cur.isoformat()


def cmd_wait(args):
    """把「要等某件事發生才做得了」的待辦park起來,並寫清楚在等什麼。

    使用者的需求(2026-08-18):「換工作後要打電話去辦職業變更…我根本就還不知道什麼時候
    找到工作,他應該是找到工作之後才要有人提醒我要做這件事情,他一直放在待辦事項覺得很怪。」

    ⚠️ 跟 `--earliest` 不一樣:earliest 要填**日期**,而這種事的日期根本不知道 ——
    硬填一個就是編出來的,而編出來的日期會變成行程表的紅字(⛔ 紅字一多就等於沒有紅字)。
    → `detail.until` 收的是**一句話寫在等什麼**,並讓它離開「待辦事項」那一區。
    條件成立那天用 `mm.py release` 放它回來。
    """
    data, mtime = load()
    before = hard_problems(data)
    done = []
    for nid in args.id:
        node, path = find_node(data, nid)
        if not node.get("todo"):
            raise SystemExit(f"⛔ [{nid}] {path} 不是待辦 —— 只有待辦會等條件。")
        det = node.setdefault("detail", {})
        det["until"] = args.until.strip()
        det.pop("earliest", None)   # 兩個一起填會互相打架:一個是日期、一個是事件
        node["aiEdited"] = stamp(f"改成等條件:{args.until.strip()[:20]}")
        done.append((nid, path))
    save(data, mtime, f"{len(done)} 條改成「等條件」:{args.until}", before)
    for nid, path in done:
        print(f"   ⏸️ [{nid}] {path.split(' › ')[-1][:34]}")
    print("   → 它們離開「待辦事項」了,住在 /day 的「⏸️ 等條件」分頁。")
    print(f'   條件成立那天跑:mm.py release --until "{args.until}"')


def cmd_release(args):
    """條件成立了 → 把等它的那幾件放回待辦。

    ⛔ 這件事沒辦法自動偵測(沒有人知道他哪天找到工作)。所以做兩件事:
    ① 一個指令一次放行同一個條件的全部
    ② 每週的排程把「還在等什麼」念一遍 —— 規則沒人查等於沒有。
    """
    data, mtime = load()
    before = hard_problems(data)
    freed = []
    for node, path in walk(data["nodeData"]):
        det = node.get("detail") or {}
        cond = (det.get("until") or "").strip()
        if not cond:
            continue
        if args.id and node["id"] not in args.id:
            continue
        # ⚠️ 精準比對,⛔ 不用「包含」(2026-08-18 差點出錯):
        #    「換到新工作」是「換到新工作且就保滿 3 個月」的子字串 ——
        #    包含比對會在他剛找到工作那天,把還要再等三個月的那條也一起放出來,
        #    然後它就混進待辦事項,他去申請會被打回票。要模糊比對請加 --contains。
        if args.until and (args.until != cond if not args.contains else args.until not in cond):
            continue
        det.pop("until", None)
        node["aiEdited"] = stamp("等的條件成立了,放回待辦")
        freed.append((node["id"], path, cond))
    if not freed:
        print("✅ 沒有符合的「等條件」項目。用 `mm.py waiting` 看現在在等什麼。")
        return
    save(data, mtime, f"{len(freed)} 條的條件成立,放回待辦", before)
    for nid, path, cond in freed:
        print(f"   ▶️ [{nid}] {path.split(' › ')[-1][:34]}　(原本在等:{cond})")


def cmd_waiting(_args):
    """現在有哪些事卡在「還沒發生的事」上。⛔ 這一份沒人念就會被忘掉。"""
    data, _ = load()
    rows = []
    for node, path in walk(data["nodeData"]):
        cond = ((node.get("detail") or {}).get("until") or "").strip()
        if cond:
            rows.append((cond, node["id"], path))
    if not rows:
        print("✅ 沒有在等任何條件。")
        return
    for cond in sorted({r[0] for r in rows}):
        print(f"⏸️ 等「{cond}」:")
        for c, nid, path in rows:
            if c == cond:
                print(f"     [{nid}] {path.split(' › ')[-1][:40]}")
    print('\n條件成立了就跑:mm.py release --until "<那句話>"')


def cmd_shift_plan(args):
    """把某一天(含)以後排好的行程整批往後推。

    使用者的需求(2026-08-18):「今天比較晚起來,事情也有蠻多延後的…排今天的這個東西,
    從今天開始全部往後拖一天,你可以幫我做到嗎?我懶得自己拉。」
    (2026-08-11 也講過同一件事:「我要把原本排在今天的一大堆東西全部往後移到明天,
    可是明天的又要再往後移到後天。」→ 第二次了,所以做成工具。)

    ⛔ **只動「哪天做」(detail.planned),絕不動死線(due)。** 那是兩件事:
       死線是外力給的,不會因為他晚起就往後移。
    ⛔ **標了 🔒 hardDue、而且推下去會超過死線的,不推**(照 Workspace CLAUDE.md 那條:
       「合約到期 8/13、機關約定日 8/27、款項入帳 8/31 推了就是錯的」)。要硬推加 --force。
    ⛔ **不碰日常區塊**(吃飯/運動/通勤):那是每天都有的作息,推一天等於今天沒得吃飯,
       而且隔天本來就有一份 —— 推它沒有任何意義。
    """
    data, mtime = load()
    before = hard_problems(data)
    moved, held = [], []
    for node, path in walk(data["nodeData"]):
        det = node.get("detail") or {}
        slots = det.get("planned") or []
        if not slots:
            continue
        due = (det.get("due") or "").strip()
        hard = bool(det.get("hardDue"))
        touched = False
        for slot in slots:
            at = slot.get("at") or ""
            if at[:10] < args.since:
                continue
            # --until:只推一段區間。⛔ 沒有它的時候要改某一段就得手工挑 pid 逐段改
            #    (2026-08-20 已經第二次了:先是「24 號以後的幫我調回來」,再來是
            #     「21 到 25 號往後移一天」)—— 手工挑最容易漏掉一兩段而且沒人查得出來。
            if args.until and at[:10] > args.until:
                continue
            new_day = (date.fromisoformat(at[:10]) + timedelta(days=args.days)).isoformat()
            if hard and due and new_day > due and not args.force:
                held.append((node["id"], path, at[:10], due))
                continue
            slot["at"] = new_day + at[10:]
            touched = True
            moved.append((node["id"], path, at[:10], new_day, due, hard))
        if touched and not args.dry_run:
            node["aiEdited"] = stamp(f"行程整批往後推 {args.days} 天")

    for nid, path, old, new, due, hard in moved:
        late = f"　⚠️ 死線 {due}" if due and new > due else ""
        print(f"   {'(演練)' if args.dry_run else '→'} [{nid}] {path.split(' › ')[-1][:30]}"
              f"　{old} → {new}{late}")
    for nid, path, old, due in held:
        print(f"   🔒 [{nid}] {path.split(' › ')[-1][:30]}　留在 {old} 不推 —— "
              f"外力死線 {due},推下去就錯過了")
    if not moved and not held:
        rng = f"{args.since} ~ {args.until}" if args.until else f"{args.since} 之後"
        print(f"✅ {rng} 沒有排任何東西,不動。")
        return
    if args.dry_run:
        print(f"   (--dry-run:什麼都沒改。會推 {len(moved)} 段、留下 {len(held)} 段)")
        return
    rng = f"{args.since}~{args.until}" if args.until else f"{args.since} 起"
    save(data, mtime, f"{rng} 的行程往後推 {args.days} 天({len(moved)} 段)", before)
    if held:
        print(f"   ⚠️ 有 {len(held)} 段標了 🔒 外力死線沒有推 —— 真的要推請加 --force。")
    print("   ⛔ 死線一個字都沒動(那是外力給的,不會因為晚起就往後)。"
          "日常區塊(吃飯/運動)也沒動。")


def cmd_undo_duty(args):
    """常設職責 → 變回一般待辦(`duty --off`)。

    使用者的需求(2026-08-19):「你這個每日積木、週期練習什麼的…我其實是希望我們可以直接把它
    變成一個單次任務」「像是小說的話,我們就要明確地說我們要讀哪裡讀哪裡」。
    → 「每日語言 90 分」這種**時段容器**看不出今天要幹嘛,要的是「讀序章 P.11–15」。

    ⚠️ 沒有回頭路的單行道是設計缺陷:降級當下看起來對的判斷,兩天後可能被推翻,
    而唯一的補救手段(直接 Edit JSON)正是規則明令禁止的。
    ⛔ 一定要給 --pri:待辦沒等級 lint 會擋,而且沒等級的待辦排不進行程。
    """
    if not args.pri:
        raise SystemExit("⛔ 變回待辦一定要給 --pri(P1–P4)—— 沒等級的待辦 lint 會擋、也排不進行程")
    if args.pri not in PRIORITIES:
        raise SystemExit(f"⛔ 等級要是 {PRIORITIES} 其中之一")
    data, mtime = load()
    before = hard_problems(data)
    done = []
    for nid in args.id:
        node, path = find_node(data, nid)
        det = node.setdefault("detail", {})
        if not det.get("duty"):
            print(f"   ⏭️ [{nid}] 本來就不是常設職責,跳過。")
            continue
        topic = (node.get("topic") or "").strip()
        for m in ("♾️", "♾"):
            if topic.startswith(m):
                topic = topic[len(m):].strip()
                break
        node["topic"] = f"⏳ {topic}"
        node["todo"] = True
        node["tags"] = [t for t in (node.get("tags") or []) if t not in PRIORITIES] + [args.pri]
        det.pop("duty", None)
        det.pop("dutyMin", None)
        if not det:
            node.pop("detail", None)
        node["aiEdited"] = stamp(f"常設職責→待辦({args.pri})")
        done.append((nid, path))
    if not done:
        return
    save(data, mtime, f"{len(done)} 條從常設職責變回待辦", before)
    for nid, path in done:
        print(f"   ⏳ [{nid}] {path}")
    print("   ⚠️ 它現在會佔任務池、要打勾才會消失 —— 標題請寫成「做得完」的樣子。")


def cmd_duty(args):
    """把「永遠不會完成」的待辦降級成常設職責。

    使用者的需求(2026-08-18):「有些任務他是每週任務,就是他這個任務是不太可能會結束的,
    或者是說他就是要一直去調整一直去設定的東西…我們應該給他用一個特殊的區塊,
    就是平日任務,像是跟吃飯休息一樣,就是那種他永遠不會完成,但是他就是要一直去做事情。」

    做完之後它:⛔ 不再出現在任務池、⛔ 不再有死線與打勾,改成 /day 右邊
    「常設職責」那一區的積木 —— 可以重複拖進行程,時數會進每日分類統計。
    ⚠️ 這其實是使用者自己在 2026-08-07 立的判準:「項目的標題不應該是任務本身。
    如果這個項目還沒完成、需要繼續進行,後面肯定會跟著待辦事項。」
    → 降級之後,底下要掛「這一輪的具體待辦」,那個才會完成、才會歸檔。
    """
    if args.off:
        return cmd_undo_duty(args)
    data, mtime = load()
    before = hard_problems(data)
    done = []
    for nid in args.id:
        node, path = find_node(data, nid)
        det = node.setdefault("detail", {})
        if not node.get("todo") and det.get("duty"):
            print(f"   ⏭️ [{nid}] 已經是常設職責了,跳過。")
            continue
        if not node.get("todo"):
            raise SystemExit(f"⛔ [{nid}] {path} 不是待辦 —— 這支是「把待辦降級」,別的節點不要碰。")
        topic = (node.get("topic") or "").strip()
        for m in ("⏳", "🔜", "⏸️", "⏸", "✅", "🎯"):
            if topic.startswith(m):
                topic = topic[len(m):].strip()
                break
        node["topic"] = f"♾️ {topic}"
        node.pop("todo", None)
        # ⛔ 等級要拿掉:lint 的「不是待辦卻掛著優先序」會擋,而且常設職責沒有優先序可言
        node["tags"] = [t for t in (node.get("tags") or []) if t not in PRIORITIES]
        for gone in ("due", "hardDue", "earliest", "doneOn", "effort", "repeat"):
            det.pop(gone, None)
        det["duty"] = True
        if args.min:
            det["dutyMin"] = args.min
        node["aiEdited"] = stamp("降級成常設職責")
        done.append((nid, path))
    if not done:
        return
    save(data, mtime, f"{len(done)} 條降級成常設職責(不再佔任務池)", before)
    for nid, path in done:
        print(f"   ♾️ [{nid}] {path}")
    print("   ⚠️ 記得在它底下開「這一輪的具體待辦」—— 那個才會完成、才會歸檔。")


def _untick_repeat_copies(node_ids, dry_run=False):
    """週期性的推到下一期之後,把專案 TODO.md 裡那一行的勾**取消掉**。

    ⛔ 少了這一步就是一個每晚重跑的無限迴圈,而且它安靜地在污染完成紀錄:
      04:15 janitor 把 ✅ 的週期任務推到下一期(標題變回 ⏳)
      → 但 `Finance/TODO.md` 那一行還是 `- [x]`
      → `sync_todos` 第①步看到「打勾了但圖上沒完成」,把 ✅ 又蓋回去
      → 隔天 04:15 再推一次、**再往完成紀錄多寫一列**
    2026-08-24 抓到:一件「每年都要辦一次」的事在完成紀錄裡有 3 列,
    而那件事其實只做過一次。⛔ 一份紀錄一旦會自己長出假資料,它就不能拿來查了。
    """
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import drift_check
    except ImportError:
        return []
    want = {f"<!--mm:{nid}-->" for nid in node_ids}
    hit = []
    for path in drift_check.all_todo_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            continue
        changed = False
        for i, line in enumerate(lines):
            if not any(tag in line for tag in want):
                continue
            new = re.sub(r"^(\s*-\s*)\[[xX]\]", r"\1[ ]", line)
            if new != line:
                lines[i] = new
                changed = True
        if changed:
            rel = path.relative_to(drift_check.PROJECTS_ROOT)
            hit.append(str(rel))
            if not dry_run:
                path.write_text("".join(lines), encoding="utf-8")
    return hit


def cmd_autoarchive(args):
    """✅ 放滿 N 天就自動搬走。每天 04:15 由 janitor.sh 叫,⛔ 不推播(例行成功不打擾)。

    2026-08-17 定案:「做完就做完了,不要再出現在上面。」但**不是標了就立刻消失** ——
    留 7 天當「最近做完什麼」的告示欄,他一週內看得到成果,過期才清。
    這取代了舊的「每週日問他要不要歸檔」(他不回,✅ 就一直堆著,那條規則等於沒有)。

    ⛔ 只碰待辦、⛔ 底下有東西的不碰 —— 跟手動 archive 同一組防呆。
    """
    data, mtime = load()
    before = hard_problems(data)
    today = datetime.now().astimezone().date()
    due, started, lines, changed = [], [], [], False
    rolled = []

    for node, path in walk(data["nodeData"]):
        if not node.get("todo") or node.get("children"):
            continue
        det = node.get("detail") or {}
        # 週期性的做完不歸檔 —— 記一筆之後把它推到下一期。
        # ⛔ 歸檔掉的話下一期就沒有任何東西提醒他(週期性申報漏一期會失去資格)。
        if (rep := (det.get("repeat") or "").strip()) and \
                (node.get("topic") or "").strip().startswith("✅"):
            if rep not in REPEATS:
                print(f"   ⚠️ [{node['id']}] 週期「{rep}」看不懂,當成一次性處理。")
            else:
                nxt = _next_due(max(det.get("due") or "", det.get("doneOn") or ""), rep, today)
                lines.append(_archive_line(node, path, *_dates_for(node)))
                node["topic"] = "⏳ " + (node["topic"] or "").strip()[len("✅"):].strip()
                det.pop("doneOn", None)
                det["due"] = nxt
                node["aiEdited"] = stamp(f"這一期做完 → 推到 {nxt}")
                rolled.append((node["id"], path, nxt))
                changed = True
                continue
        if not (node.get("topic") or "").strip().startswith("✅"):
            if det.pop("doneOn", None):  # 取消打勾了 → 時鐘歸零,不要留著舊的
                changed = True
            continue
        marked = (det.get("doneOn") or "").strip()
        if not marked:
            # 在任務板打的勾不會寫 doneOn → 這裡補記,時鐘從今天開始算。
            # ⛔ 不准當成「今天到期」直接搬:那會讓他剛打完勾就看著它消失。
            node.setdefault("detail", {})["doneOn"] = today.isoformat()
            started.append((node["id"], path))
            changed = True
            continue
        try:
            age = (today - date.fromisoformat(marked)).days
        except ValueError:
            print(f"   ⚠️ [{node['id']}] doneOn 讀不懂({marked}),跳過不動它。")
            continue
        if age < args.days:
            continue
        if (hit := _arrows_on(data, node["id"])):
            # 無人值守的程式最不該做的事:安靜地把線的另一端弄成「對方已不在圖上」
            print(f"   ⏭️ [{node['id']}] {path} 上面有 {len(hit)} 條關聯線,不自動搬。"
                  "要搬請自己處理線之後跑 mm.py archive。")
            continue
        due.append((node, path, age))

    for node, path, _ in due:
        lines.append(_archive_line(node, path, *_dates_for(node)))
    if lines and not args.dry_run:
        for node, _, _ in due:
            parent = _parent_of(data, node["id"])
            parent["children"] = [c for c in parent["children"] if c["id"] != node["id"]]
        changed = True

    # ⚠️ 演練模式**不報**「開始計時」——「他剛在任務板打了勾」不是異常。
    #    週日的保底檢查跑的就是 --dry-run,照報的話每次都會誤喊「歸檔卡住了」。
    unticked = _untick_repeat_copies([nid for nid, _, _ in rolled], args.dry_run) if rolled else []
    for nid, path, nxt in rolled:
        print(f"   🔁 [{nid}] {path} —— 這一期做完了,下一期 {nxt}")
    if unticked:
        print(f"   ↩️ 順手把專案檔那一行的勾取消掉({', '.join(unticked)})"
              " —— 不取消的話 sync 明天會把 ✅ 蓋回來,完成紀錄每天多一列假的")
    for nid, path in (started if not args.dry_run else []):
        print(f"   ⏱️ [{nid}] {path} —— 開始算 {args.days} 天")
    for node, path, age in due:
        print(f"   {'(演練)' if args.dry_run else '📦'} [{node['id']}] {path} —— 放了 {age} 天")
    if not due and not rolled and (args.dry_run or not started):
        print(f"✅ 沒有放超過 {args.days} 天的完成項目,不動。")
    elif args.dry_run:
        print("   (--dry-run:什麼都沒改)")
    if changed and not args.dry_run:
        # ⛔ 存圖成功了才寫完成紀錄 —— 反過來的話 409 / 伺服器重啟會讓 save() SystemExit,
        #    留下「圖上還在、紀錄已多一列」的孤兒;隔天 04:15 doneOn 沒變、age 照樣 ≥N,
        #    同一列每晚再 append 一次。janitor 那句「歸檔失敗」吞在 pipe 裡不會印,完全無聲。
        save(data, mtime,
             f"自動歸檔 {len(due)} 顆、{len(rolled)} 顆推到下一期、{len(started)} 顆開始計時",
             before, circled=False)
        if lines:
            _commit_archive(lines)
            retire([n["id"] for n, _, _ in due])
            # 無人值守跑的,喊出來才會進 janitor.log;⛔ 不然斷鏈要等到週日才有人發現
            warn_dangling({n["id"] for n, _, _ in due})


def cmd_lint(_args):
    sys.exit(lint_map.main(["lint_map.py", MAP_NAME]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="心智圖:查與安全地改")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("find", help="用關鍵字找節點")
    p.add_argument("keyword")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("show", help="看單一節點")
    p.add_argument("id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("tree", help="看結構")
    p.add_argument("id", nargs="?")
    p.add_argument("--depth", type=int, default=2)
    p.set_defaults(func=cmd_tree)

    p = sub.add_parser("add-todo", help="加一條待辦")
    p.add_argument("parent")
    p.add_argument("topic")
    p.add_argument("--pri", required=True, help="P1–P4,每條待辦都要有")
    p.add_argument("--due", help="YYYY-MM-DD;⛔ 沒有明確死線就別填")
    p.add_argument("--why", required=True,
                   help="這是什麼、為什麼要做(必填)。需求原句:「我應該要知道這個東西是"
                        "為了什麼做的…不然我在拉動我的個人任務的時候我不知道這什麼東西」")
    p.add_argument("--by", help="圈圈上要寫的一句話")
    p.set_defaults(func=cmd_add_todo)

    p = sub.add_parser("add-node", help="加一個結構/設施/指針節點")
    p.add_argument("parent")
    p.add_argument("topic")
    p.add_argument("--kind", choices=("sop", "tool", "infra"))
    p.add_argument("--why")
    p.add_argument("--by")
    p.set_defaults(func=cmd_add_node)

    p = sub.add_parser("add-article", help="加一篇文章 + 它的固定步驟")
    p.add_argument("parent", help="分類節點 id")
    p.add_argument("title")
    p.add_argument("--pri", default="P3", help="這幾個步驟共用的等級,預設 P3")
    p.add_argument("--video", action="store_true", help="這篇要做影片")
    p.add_argument("--step", action="append", help="再加一個自訂步驟(可重複)")
    p.add_argument("--why")
    p.set_defaults(func=cmd_add_article)

    p = sub.add_parser("set-status", help="改狀態")
    p.add_argument("id")
    p.add_argument("status", help="待辦/進行中/等別人/完成/目標/無")
    p.add_argument("--force", action="store_true",
                   help="使用者自己按過的狀態要反轉時才需要 —— 先問過再用")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("explain", help="覆寫說明")
    p.add_argument("id")
    p.add_argument("text")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("set", help="改死線/要花多久/等級/標籤/標題(可一次多個 id)")
    p.add_argument("id", nargs="+")
    p.add_argument("--due", help="死線 YYYY-MM-DD。⚠️ 只填外力給的日期,「我希望這天做完」不要填")
    p.add_argument("--no-due", action="store_true", help="拿掉死線,改用 P1–P4 排順序")
    p.add_argument("--effort", help="要花多久:" + "/".join(EFFORTS))
    p.add_argument("--repeat", help="做完多久會再來:" + "/".join(REPEATS) + "(填 none 拿掉)")
    p.add_argument("--owner", help="這是誰的事:ai(不佔使用者的容量)/ me(拿掉標記)")
    p.add_argument("--pri", help="等級 P1–P4")
    p.add_argument("--tag", action="append", default=[], help="加標籤(例:一起做)")
    p.add_argument("--untag", action="append", default=[], help="拿掉標籤")
    p.add_argument("--rename", help="改標題(狀態符號會保留)")
    p.add_argument("--hard-due", action="store_true",
                   help="🔒 這個日期是外力給的(法定期限/對方在等),行程表整串往後推時不會動它")
    p.add_argument("--soft-due", action="store_true", help="拿掉 🔒,變回可以被推走的日期")
    p.add_argument("--earliest", help="不能比這天早做 YYYY-MM-DD(要等某件事發生才做得了)")
    p.add_argument("--no-earliest", action="store_true", help="拿掉最早日期")
    p.add_argument("--window", help="改成「要你自己挑日子」並寫上限制")
    p.add_argument("--no-window", action="store_true", help="拿掉挑日子的限制")
    p.add_argument("--source", help="把這顆認養成某專案的入口(相對路徑,例:Language/English)"
                                    " —— 掛了才會有同步區、才會被 drift_check 對帳")
    p.add_argument("--no-source", action="store_true", help="拿掉專案掛載")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("move", help="把節點(連同底下整支)換一個父節點")
    p.add_argument("id")
    p.add_argument("to", help="新的父節點 id")
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("archive", help="做完的待辦搬進完成紀錄並從圖上移除(可一次多個 id)")
    p.add_argument("id", nargs="+")
    p.add_argument("--on", help="實際完成日 YYYY-MM-DD(不填就用標 ✅ 的那天;都沒有就寫「不詳」)")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("drop", help="決定不做了(從圖上移走,記成 ❌ 不做了,不算完成)")
    p.add_argument("id")
    p.add_argument("--why", required=True, help="為什麼不做了 —— 沒有理由的紀錄等於沒有紀錄")
    p.set_defaults(func=cmd_drop)

    p = sub.add_parser("merge", help="好幾件小事併成一項(說明逐字保留成清單)")
    p.add_argument("keep", help="要留下來的那顆 id")
    p.add_argument("ids", nargs="+", help="要併進去、然後消失的那幾顆 id")
    p.add_argument("--rename", help="順便改標題")
    p.add_argument("--intro", help="清單開頭那句話(預設會寫「做完一件打一個勾」)")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("wait", help="這件事要等某件事發生才做得了(會離開待辦事項那一區)")
    p.add_argument("id", nargs="+")
    p.add_argument("--until", required=True, help='在等什麼,一句話。例:"換到新工作"')
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("release", help="等的條件成立了 → 放回待辦")
    p.add_argument("id", nargs="*")
    p.add_argument("--until", help="一次放行等同一件事的全部(⚠️ 要一模一樣,用 mm.py waiting 複製)")
    p.add_argument("--contains", action="store_true", help="改成模糊比對(⛔ 想清楚:會多放行)")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("waiting", help="現在有哪些事在等條件")
    p.set_defaults(func=cmd_waiting)

    p = sub.add_parser("shift-plan", help="某天(含)以後排好的行程整批往後推幾天")
    p.add_argument("--since", required=True, help="從哪一天(含)開始推 YYYY-MM-DD")
    p.add_argument("--until", help="推到哪一天(含)為止 YYYY-MM-DD;不給=一路推到底")
    p.add_argument("--days", type=int, default=1, help="往後推幾天(預設 1)")
    p.add_argument("--force", action="store_true", help="連 🔒 外力死線的也推(⛔ 想清楚再用)")
    p.add_argument("--dry-run", action="store_true", help="只看會推什麼,不動")
    p.set_defaults(func=cmd_shift_plan)

    p = sub.add_parser("duty", help="把「永遠不會完成」的待辦降級成常設職責(可一次多個 id)")
    p.add_argument("id", nargs="+")
    p.add_argument("--min", type=int, help="拖進行程時預設佔幾分鐘(預設 120)")
    p.add_argument("--off", action="store_true",
                   help="反過來:常設職責變回一般待辦(要一起給 --pri)")
    p.add_argument("--pri", help="配 --off 用:變回待辦之後的等級 P1–P4")
    p.set_defaults(func=cmd_duty)

    p = sub.add_parser("autoarchive", help="✅ 放滿 N 天就自動搬走(janitor 每天叫,不必手動跑)")
    p.add_argument("--days", type=int, default=7, help="放幾天才搬(預設 7)")
    p.add_argument("--dry-run", action="store_true", help="只印會搬什麼,不動任何東西")
    p.set_defaults(func=cmd_autoarchive)

    sub.add_parser("lint", help="體檢").set_defaults(func=cmd_lint)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
