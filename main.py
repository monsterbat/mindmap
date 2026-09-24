"""mindmap — 使用者與 AI 共編心智圖的本地伺服器。

正本是 MAPS_DIR 裡的 JSON 檔(mind-elixir 格式,一圖一檔);本伺服器只做三件事:
serve 靜態編輯器頁面、列出圖、讀寫單張圖。架構見 DESIGN.md。

⚠️ 技術棧(2026-07-31 定案):純 stdlib、跑在 /usr/bin/python3(3.9)。
不用 FastAPI/uvicorn——launchd 下只有系統 python3 有 TCC 磁碟授權(brain_server
同款配方),uv 的 python 會卡死在讀 ~/Documents。語法必須相容 3.9。
"""

import base64
import hmac
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

# ⚠️ 整支「不做了」轉呼叫 mm.py,不自己重寫 —— 那裡面包了 lint 閘門、mtime 衝突偵測、
#    id 退休名單、完成紀錄的落地順序。重寫一份必然漏掉幾樣,而漏掉的都是安靜壞掉型的。
import mm

HOST = os.environ.get("MINDMAP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MINDMAP_PORT", "8030"))

# ── 誰不用打密碼(2026-08-17 定案)──────────────────────────────────────
# 背景:8030 上是使用者的整張心智圖(含私人的財務與生涯規劃節點),
# 之前 tailnet 上任何裝置打開就看得到、不問任何身分。而 tailnet 上除了使用者
# 自己的電腦與手機,還有**家裡共用的那台電腦** ——
# 真正的風險不是駭客,是別人坐在那台前面隨手打開。
# 需求是:自己常用的那幾台裝置無縫接軌、完全不必輸入密碼,
#         其他電腦一律鎖起來、要輸入密碼。
#
# 為什麼認 IP 是可靠的(不是敷衍):Tailscale 的 100.x 位址是用金鑰綁在裝置上發的,
# 別台機器沒辦法冒充成使用者的電腦 —— 這跟一般網際網路上「IP 可偽造」不是同一回事。
TRUSTED_IPS = set(
    filter(
        None,
        os.environ.get(
            "MINDMAP_TRUSTED_IPS",
            "127.0.0.1,::1"  # 要讓別的位址免密碼就用逗號接在後面
        ).split(","),
    )
)
# 其他裝置要看 → 需要密碼。檔案不存在 = 誰都進不來(**刻意 fail-closed**):
# 「沒設密碼就自動放行」會變成又一個只會說 OK 的假閘門。
GATE_PW_FILE = Path(
    os.environ.get("MINDMAP_GATE_PW_FILE", "~/.config/sc-mindmap/gate_password")
).expanduser()
MAPS_DIR = Path(
    os.environ.get("MINDMAP_MAPS_DIR", "~/mindmaps")
).expanduser()
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 靜態檔照副檔名分資料夾(pages / css / js),⛔ 只有這裡知道怎麼分 ——
# 別的地方給檔名就好,以後再搬也只改這一個函式。
_STATIC_SUB = {"html": "pages", "css": "css", "js": "js"}


def static_file(name: str) -> Path:
    """給 "day.js" 回 static/js/day.js。認不得的副檔名就放在 static/ 底下。"""
    sub = _STATIC_SUB.get(name.rsplit(".", 1)[-1], "")
    return STATIC_DIR / sub / name if sub else STATIC_DIR / name
# 各專案資料夾的根。節點可以掛 `source: "Program/voice_to_text"`,伺服器即時去讀它的進度。
PROJECTS_ROOT = Path(
    os.environ.get("MINDMAP_PROJECTS_ROOT", "~/projects")
).expanduser()
# 規則正本住這裡:全域 core.md/macos.md、各領域的 CLAUDE.md(資料根目錄底下那些是 symlink
# 指過來的)、以及 skills。要讓規則指針節點點得開,唯讀檢視必須認得這個根。
CONFIG_ROOT = Path(
    os.environ.get("MINDMAP_CONFIG_ROOT", "~/claude-config")
).expanduser()
def default_map_name():
    """四個頁面預設載哪一張圖。

    ⛔ 不准寫死圖名:別人把這套裝起來時,他自己的圖不會叫這個名字 ——
    寫死的話心智圖頁有下拉可以換,另外三頁會**整頁空白**,而且只寫一行
    「讀不到圖」,看起來像程式壞了。
    順序:環境變數 → 慣用的那張(存在才算)→ 資料夾裡的第一張。
    """
    env = os.environ.get("MINDMAP_MAP")
    if env:
        return env
    if (MAPS_DIR / f"{mm.MAP_NAME}.json").is_file():
        return mm.MAP_NAME
    names = sorted(q.stem for q in MAPS_DIR.glob("*.json"))
    return names[0] if names else mm.MAP_NAME

# 「整天沒空」的日子(演唱會、出遊、看醫生…)。正本是 Google 行事曆,這份是給排程用的
# 摘要,由 AI 在週日重排時對照行事曆更新。⚠️ 一定要放在子資料夾 —— MAPS_DIR 頂層的
# *.json 會被 list_maps 當成一張圖(實測 pathlib 的 glob 連 .開頭的檔案都吃)。
BUSY_PATH = MAPS_DIR / "排程設定" / "整天沒空.json"
# 每天的固定時段 —— 容量也是從它算的。⚠️ 指令列跟網頁必須讀同一份。
RHYTHM_PATH = MAPS_DIR / "排程設定" / "作息.json"
# Google 行事曆抓下來的副本(正本永遠在 Google,我們只讀不寫)。由每天的排程程式更新。
CAL_PATH = MAPS_DIR / "排程設定" / "行事曆快取.json"
SYNC_STATE = MAPS_DIR / ".history" / "todo_sync" / "_last_sync.json"
SYNC_STALE_DAYS = 7  # 超過這麼久沒對帳就標出來

# 圖名=檔名(不含 .json):中英數字、底線、連字號、空格;禁路徑符號
NAME_RE = re.compile(r"^[\w\- 一-鿿぀-ヿ]{1,80}$")

HISTORY_DIR = ".history"  # MAPS_DIR 底下,list_maps 不會掃到(只 glob 頂層 *.json)
KEEP_VERSIONS = 30


def static_build():
    """靜態檔的版本戳=最新的 mtime。前端拿載入當下的值跟輪詢到的比,
    不一樣就代表「這一頁跑的程式是舊的」→ 提示重新整理。
    (2026-08-02 修正:分頁開著沒重整,看到的還是舊 UI,會誤以為程式沒改。)"""
    times = [p.stat().st_mtime for p in STATIC_DIR.rglob("*") if p.is_file()]
    return round(max(times), 3) if times else 0.0


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def map_path(name):
    if not NAME_RE.match(name):
        raise ApiError(400, f"圖名不合法:{name!r}")
    path = (MAPS_DIR / (name + ".json")).resolve()
    if path.parent != MAPS_DIR.resolve():
        raise ApiError(400, "圖名不可含路徑")
    return path


def list_maps():
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    maps = []
    for p in sorted(MAPS_DIR.glob("*.json")):
        stat = p.stat()
        maps.append({"name": p.stem, "mtime": stat.st_mtime, "size": stat.st_size})
    return maps


def get_map(name):
    path = map_path(name)
    if not path.exists():
        raise ApiError(404, f"沒有這張圖:{name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ApiError(500, f"JSON 壞了:{e}")
    return {"name": name, "mtime": path.stat().st_mtime, "data": data}


def snapshot(path):
    """每次覆寫前先留一份舊版。

    為什麼要有:mtime 衝突偵測只擋得住「使用者當下有未存改動」的情況;
    只要他剛存完(乾淨),別的寫入者(AI、另一個視窗、測試腳本)就會靜靜蓋掉,
    而他的畫面還會自動重載成別人的版本 —— 2026-08-02 真的發生過。
    """
    if not path.exists():
        return
    hist = path.parent / HISTORY_DIR / path.stem
    hist.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    shutil.copy2(path, hist / f"{stamp}.json")
    olds = sorted(hist.glob("*.json"))
    for old in olds[:-KEEP_VERSIONS]:
        old.unlink()


def _write_map(path, data):
    """原子寫入 + 備份。put_map / patch_node 共用,⛔ 不要各寫一份。"""
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot(path)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path.stat().st_mtime


# 只准這幾個欄位被 PATCH 動到。⛔ 不要開放整個 detail ——
# 這支沒有衝突偵測,能改的範圍越小,誤傷就越小。
PATCHABLE = {"planned", "plannedAt", "plannedMin", "due", "effort",
             "earliest", "hardDue", "window", "until"}


def patch_node(name, node_id, payload):
    """只改一個節點的排程欄位,伺服器端讀 → 改 → 寫。

    為什麼要有這支(2026-08-11):`/day` 拖一下就要存一次,而 PUT 是整張圖重寫
    (300 個節點)。使用者同時開著心智圖網頁時,整張重寫幾乎一定會撞 409,
    每拖一次就跳「圖被別人改過了」—— 那個工具就沒法用了。
    這支只碰那一顆節點的那幾個欄位,別人同時改別的地方不會互相蓋掉。
    """
    fields = payload.get("detail")
    if not isinstance(fields, dict):
        raise ApiError(400, "detail 必須是物件")
    bad = set(fields) - PATCHABLE
    if bad:
        raise ApiError(400, f"這些欄位不准用 PATCH 改:{'、'.join(sorted(bad))}")
    path = map_path(name)
    if not path.exists():
        raise ApiError(404, f"沒有這張圖:{name}")
    data = json.loads(path.read_text(encoding="utf-8"))

    hit = []

    def walk(node):
        if node.get("id") == node_id:
            hit.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(data["nodeData"])
    if not hit:
        raise ApiError(404, f"圖上沒有這個節點:{node_id}")
    node = hit[0]
    detail = node.setdefault("detail", {})
    for key, value in fields.items():
        if value in (None, "", False) or value == []:
            detail.pop(key, None)
        else:
            detail[key] = value
    if not detail:
        node.pop("detail", None)
    # 使用者自己在畫面上拖的,不是 AI 動的 —— 紫圈的意思是「AI 動過你還沒看」
    node.pop("aiEdited", None)
    node["scEdited"] = payload.get("by") or "在行程上調整"
    return {"id": node_id, "mtime": _write_map(path, data)}


def patch_view_order(name, payload):
    """待辦事項頁 `/topics` 的主題顯示順序。⛔ 只碰 `detail.viewOrder`,別的一個都不動。

    為什麼不用 PUT 整張圖(2026-09-08):拖一次要重編 20 幾個節點的號碼,
    而使用者常常同時開著心智圖網頁 —— 整張重寫幾乎一定撞 409,
    每拖一次跳一次「圖被別人改過了」,那個功能就沒法用。理由同 patch_node。

    payload: {"order": ["節點id-1", "節點id-2", ...]}  ← 由前到後
             {"reset": true}                        ← 全部清掉,回到自動排
    ⚠️ 「零星待辦」桶沒有自己的節點,前端會把它換成該領域節點的 id 再送過來。
    ⚠️ reset 一定要有:⛔ 一個「只進不出」的排序會讓人不敢亂拖 —— 要讓人知道反悔得了。
    """
    reset = bool(payload.get("reset"))
    order = payload.get("order")
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise ApiError(400, "order 必須是一串節點 id")
    path = map_path(name)
    if not path.exists():
        raise ApiError(404, f"沒有這張圖:{name}")
    data = json.loads(path.read_text(encoding="utf-8"))

    rank = {node_id: i for i, node_id in enumerate(order)}
    seen = []

    def walk(node):
        detail = node.get("detail")
        if reset:
            if isinstance(detail, dict) and "viewOrder" in detail:
                detail.pop("viewOrder")
                seen.append(node["id"])
                if not detail:
                    node.pop("detail", None)
        elif node.get("id") in rank:
            node.setdefault("detail", {})["viewOrder"] = rank[node["id"]]
            seen.append(node["id"])
        for child in node.get("children") or []:
            walk(child)

    walk(data["nodeData"])
    missing = [x for x in order if x not in seen]
    # ⛔ 不因為有幾個找不到就整批不寫 —— 圖是活的,節點可能剛被別條對話歸檔掉。
    #    照樣寫得進去的那些,把找不到的回報出來就好。
    return {"written": len(seen), "missing": missing, "mtime": _write_map(path, data)}


# ── 隨手記:每一頁右下角的「＋」(2026-09-17)──────────────────────────
# 使用者的需求(2026-09-17):「有時候我突然想到一些任務、一些想要做的事情,
# 好像就沒有辦法直接加在我們這個上面。」—— 當時四頁只有待辦事項頁加得了,
# 而且只能加在已經存在的主題底下;「還不知道要放哪裡的念頭」沒有地方放。
INBOX_ID = "inbox"          # ⛔ 固定 id:改名不影響,前端與測試都靠它
INBOX_TOPIC = "📥 收件匣"
STAGE_ID = "ai-004"         # 🎯 現在的階段:不是領域,不列進「放哪裡」
QUICK_MAX = 200


def _inbox_node(root, create=False):
    """找收件匣(任何位置都算);沒有而且 create=True → 在根底下開一個。

    ⚠️ 用到才開,不預先開:空的收件匣掛在圖上只是雜訊。
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if node.get("id") == INBOX_ID:
            return node
        stack.extend(node.get("children") or [])
    if not create:
        return None
    node = {"id": INBOX_ID, "topic": INBOX_TOPIC, "children": [],
            "detail": {"explain": "用每一頁右下角「＋」隨手記、還不知道放哪裡的事。"
                                  "他說「整理收件匣」,AI 就一件一件搬到該去的地方。"
                                  "(2026-09-17 開,程式在 Program/mindmap/main.py quick_todo)"}}
    root.setdefault("children", []).append(node)
    return node


def quick_targets(name):
    """「放哪裡」下拉選單:收件匣排第一,後面是各領域(根的直接子節點)。"""
    path = map_path(name)
    if not path.exists():
        raise ApiError(404, f"沒有這張圖:{name}")
    root = json.loads(path.read_text(encoding="utf-8"))["nodeData"]
    out = [{"id": INBOX_ID, "label": f"{INBOX_TOPIC},之後再分"}]
    for child in root.get("children") or []:
        if child.get("id") in (INBOX_ID, STAGE_ID) or child.get("todo"):
            continue
        out.append({"id": child["id"], "label": (child.get("topic") or "").strip()})
    return {"targets": out}


def quick_todo(name, payload):
    """隨手記一件事:伺服器端讀 → 加一顆待辦 → 寫。

    ⛔ 只准加在收件匣或某個領域底下 —— 網頁傳來的 parent 不能是任意節點,
       不然一個錯的 id 就能把東西塞進圖的任何角落。
    ⛔ 不用 PUT 整張圖:他常同時開著心智圖,整張重寫幾乎一定撞 409(理由同 patch_node)。
    """
    text = " ".join(str(payload.get("text") or "").split())
    if not text:
        raise ApiError(400, "沒有內容")
    if len(text) > QUICK_MAX:
        raise ApiError(400, f"太長了,{QUICK_MAX} 字以內")
    pri = payload.get("pri") or "P2"
    if pri not in ("P1", "P2", "P3", "P4"):
        raise ApiError(400, "等級只能是 P1–P4")
    target = payload.get("parent") or INBOX_ID

    path = map_path(name)
    if not path.exists():
        raise ApiError(404, f"沒有這張圖:{name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    root = data["nodeData"]
    if target == INBOX_ID:
        parent = _inbox_node(root, create=True)
    else:
        parent = next((c for c in root.get("children") or []
                       if c.get("id") == target and c.get("id") != STAGE_ID and not c.get("todo")), None)
        if parent is None:
            raise ApiError(400, "只能放進收件匣或某個領域")

    ids = set()
    stack = [root]
    while stack:
        node = stack.pop()
        ids.add(node.get("id"))
        stack.extend(node.get("children") or [])
    base = "sc-" + _b36(time.time_ns() // 1_000_000)
    new_id, n = base, 1
    while new_id in ids:          # 同一毫秒連點兩下也不會撞號
        n += 1
        new_id = f"{base}-{n}"

    today = datetime.now().astimezone().date().isoformat()
    node = {
        "id": new_id, "topic": f"⏳ {text}", "todo": True, "tags": [pri],
        "detail": {"explain": f"{today} 用「＋」隨手記的(還沒寫為什麼要做)。"},
        # ⛔ 這是他自己按的,不是 AI 改的 —— 紫圈的意思是「AI 動過、你還沒看」
        "scEdited": f"{today} 用「＋」隨手記",
    }
    parent.setdefault("children", []).append(node)
    return {"id": new_id, "parent": parent["id"], "parentTopic": parent.get("topic", ""),
            "mtime": _write_map(path, data)}


def _b36(n):
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = chars[r] + out
    return out or "0"


def drop_node(name, node_id, payload):
    """把一顆待辦標成「❌ 不做了」,從圖上移走,理由寫進完成紀錄。

    ⚠️ 為什麼要有這支(2026-08-22 使用者問起):一顆事情的出路本來只有「完成」一條。
    真實世界還有第二條 —— **決定不做了**。`mm.py drop` 從 2026-08-19 就有了,
    但那是指令列;在 /day 與 /board 上按不到,於是畫面上只有「打勾」這一個出口
    → 不想做的事只能硬標完成(完成紀錄會多一筆從沒做過的事)或爛在圖上。

    ⛔ 一定要有理由:一年後看到「這件事不做了」而沒有理由等於沒有紀錄,
    下一輪規劃時它會原封不動地被重新提出來,然後再評估一次。

    ⚠️ 刻意整支轉呼叫 `mm.py` 而不是自己重寫一遍 —— 那裡面包了 lint 閘門、
    mtime 衝突偵測、id 退休名單、完成紀錄落地順序。重寫一份必然漏掉其中幾樣,
    而漏掉的那幾樣正好都是「安靜地壞掉」型的。
    """
    why = (payload or {}).get("why", "").strip()
    if not why:
        raise ApiError(400, "要寫理由 —— 沒有理由的『不做了』一年後等於沒有紀錄")
    if name != default_map_name():
        raise ApiError(400, f"只支援 {default_map_name()}")
    args = SimpleNamespace(id=node_id, why=why)
    try:
        mm.cmd_drop(args)
    except SystemExit as e:
        raise ApiError(400, str(e) or "不做了失敗") from e
    return {"id": node_id, "dropped": True}


def put_map(name, payload):
    """payload = {data: <mind-elixir JSON>, base_mtime: float|None}

    base_mtime 是前端上次讀到的檔案 mtime;檔案在那之後被別人(AI/另一視窗)
    改過就回 409,不靜默覆蓋。base_mtime 傳 None = 強制覆蓋。
    """
    data = payload.get("data")
    if not isinstance(data, dict) or "nodeData" not in data:
        raise ApiError(400, "data 必須是含 nodeData 的物件")
    path = map_path(name)
    base_mtime = payload.get("base_mtime")
    if (
        path.exists()
        and base_mtime is not None
        and path.stat().st_mtime - float(base_mtime) > 1e-4
    ):
        raise ApiError(409, "檔案在你上次載入後被修改過(可能是 AI 或另一個視窗)")
    return {"name": name, "mtime": _write_map(path, data)}


ITEM_LIMIT = 12  # 詳情面板列得完的量;超過就只給數字(圖是門戶不是倉庫)


def _clean_item(text):
    """把 markdown 裝飾拿掉,讓它在詳情面板讀起來像一句話。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"<!--.*?-->", "", text)
    return " ".join(text.split())[:120]


def project_status(rel):
    """即時讀一個專案的 TODO.md / CHANGELOG.md,回傳摘要。

    **⛔ 只讀不寫,而且絕不寫回心智圖的 JSON。** 使用者提出的對齊問題(2026-08-03):
    專案那邊改了東西心智圖要看得到,但**不能把進度複製進圖裡**——一複製就會 drift,
    而且會跟使用者自己的編輯打架。所以走「拉」:前端要顯示時才問伺服器,問完就丟。
    (同一招 `brain/build_plan.py` 的「專案現況」頁已經用了兩個月,沒出過事。)

    解析規則刻意只認最簡單的兩種寫法,認不出來就回 0,**不猜、不推論**:
      - `TODO.md`      `- [ ]`=未完成、`- [x]`=完成;該行有 `⏳`=卡在使用者身上
      - `CHANGELOG.md` 第一個 `## ` 標題 = 最近一次更新
    """
    rel = (rel or "").strip().strip("/")
    if not rel:
        raise ApiError(400, "沒給 source")
    root = PROJECTS_ROOT.resolve()
    target = (PROJECTS_ROOT / rel).resolve()
    if target != root and root not in target.parents:
        raise ApiError(400, "路徑不合法")  # 擋 ../ 跳出去
    out = {"path": rel, "exists": target.is_dir(), "open": 0, "done": 0, "waiting": 0,
           "last": "", "unreadable": False, "synced_days": None, "items": [],
           "declared_no_own": False}
    # 上次跟心智圖對帳是多久以前。**沒對過或太久沒對要看得出來** ——
    # 規則沒人查等於沒有,所以把「有沒有跑」變成畫面上的狀態。
    try:
        state = json.loads(SYNC_STATE.read_text(encoding="utf-8"))
        when = state.get(rel)
        if when:
            delta = datetime.now().astimezone() - datetime.fromisoformat(when)
            out["synced_days"] = max(0, delta.days)
    except (OSError, ValueError):
        pass
    if not out["exists"]:
        return out
    todo = target / "TODO.md"
    if todo.is_file():
        # ⛔ 同步區整段跳過,不只 ⏳:那一區是心智圖生成的**回音**,算進 open/done
        # 就變成自己數自己(2026-08-04 抓到:Finance 的徽章被灌水 26 條,而那 26 條
        # 本來就以待辦節點的形式掛在同一個分支上)。這裡數的是「專案自己另外的事」。
        in_sync_block = False
        stray = 0  # 同步區外「長得像清單卻沒有方框」的行 —— 讀不懂格式的訊號
        raw = todo.read_text(encoding="utf-8", errors="replace")
        for line in raw.splitlines():
            s = line.strip()
            if s.startswith("<!-- mm:begin"):
                in_sync_block = True
                continue
            if s.startswith("<!-- mm:end"):
                in_sync_block = False
                continue
            if in_sync_block:
                continue
            if s.startswith("- [ ]"):
                out["open"] += 1
                # `⏳` 在專案慣例=「等使用者的輸入」(心智圖那邊的 ⏳ 已隨同步區整段跳過)
                if "⏳" in s:
                    out["waiting"] += 1
                # ⚠️ 連內容一起回傳(上限 ITEM_LIMIT)。
                # 使用者的需求(2026-08-08):「我所有專案都是直接看這個心智圖」——
                # 只給數字的話就得離開圖去翻檔案,那就不叫「在同一個地方查得到」。仍然是**拉**:
                # 每分鐘即時去讀,不寫回 JSON,所以不會 drift。
                if len(out["items"]) < ITEM_LIMIT:
                    out["items"].append(_clean_item(s[5:]))
            elif s.startswith(("- [x]", "- [X]")):
                out["done"] += 1
            elif s.startswith("- "):
                stray += 1
        # ⚠️ 有清單卻一個方框都沒有 → **不是「都做完了」,是我讀不懂它的格式**。
        # 靜默回 0 會讓圖上顯示「這個專案沒事了」,那是最傷的一種錯。
        #
        # 「同步區外的條列」有兩種,而且程式分不出來:①真的待辦寫錯格式(voice_to_text 的
        # 「Google OAuth 驗證審核:待人工審核」)②純說明(某個已封存專案的維護注意事項)。
        # ⛔ 不猜:預設當成①報出來,專案要主張自己是②就**明確宣告**一行
        # `<!-- mm:no-own-todos -->`。使用者的需求(2026-08-08):「不要有些專案讀到沒
        # 感覺,有些讀到會做」—— 每個專案都要有明確狀態,靠猜就會有的準有的不準。
        declared = "mm:no-own-todos" in raw
        out["declared_no_own"] = declared
        out["unreadable"] = out["open"] == 0 and out["done"] == 0 and stray > 0 and not declared
    changelog = target / "CHANGELOG.md"
    if changelog.is_file():
        for line in changelog.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("## "):
                out["last"] = line[3:].strip()
                break
    return out


FILE_VIEW_PAGE = """<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin:0; background:#151922; color:#e8eaed;
         font-family:-apple-system,"PingFang TC",sans-serif; }}
  header {{ position:sticky; top:0; background:#1f2430; padding:10px 16px;
            font-weight:700; border-bottom:1px solid #333a48; font-size:14px; }}
  header small {{ color:#9aa4b2; font-weight:400; margin-left:10px; }}
  pre {{ white-space:pre-wrap; word-break:break-word; margin:0; padding:16px;
         font:13px/1.7 ui-monospace,Menlo,monospace; }}
</style></head><body>
<header>📄 {title}<small>{rel} — 唯讀,正本請在檔案裡改</small></header>
<pre>{body}</pre>
</body></html>"""


def file_view(rel):
    """`/file/<相對路徑>` — 唯讀 markdown 檢視頁。

    給 SOP 指針節點用:心智圖是門戶,SOP 正本在 notes/*.md ——
    抄內容進圖=兩份=必 drift(使用者定的鐵則),所以圖上只放連結,點了來這裡看正本。

    ⛔ 只讀不寫、只收 .md、只能落在兩個根底下 —— 這台伺服器綁在
    Tailscale 介面上,路徑防護跟 /api/project 同一套標準。

    兩個根:PROJECTS_ROOT(資料與 SOP)與 CONFIG_ROOT(規則與 skill 正本)。
    ⚠️ 判斷用「resolve 之後」的路徑:領域的 CLAUDE.md 是 symlink 指到 claude-config,
    只認 PROJECTS_ROOT 的話會被自己的防護擋掉。`@config/` 開頭 = 直接指 CONFIG_ROOT。"""
    rel = (rel or "").strip().strip("/")
    if not rel.endswith(".md"):
        raise ApiError(400, "只供 .md 檔檢視")
    if rel.startswith("@config/"):
        target = (CONFIG_ROOT / rel[len("@config/") :]).resolve()
    else:
        target = (PROJECTS_ROOT / rel).resolve()
    roots = [PROJECTS_ROOT.resolve(), CONFIG_ROOT.resolve()]
    if not any(r in target.parents for r in roots):
        raise ApiError(400, "路徑不合法")
    if not target.is_file():
        raise ApiError(404, f"找不到:{rel}")
    text = target.read_text(encoding="utf-8", errors="replace")
    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return FILE_VIEW_PAGE.format(title=target.stem, rel=rel, body=esc)


def load_busy():
    """哪幾天排不了事。實作只有一份(plan_week),不然指令列跟網頁會算出兩種答案。

    來源兩個:Google 行事曆抓下來的快取 + 手寫的 `整天沒空.json`(手寫的贏)。
    """
    import plan_week

    return plan_week.merged_busy(BUSY_PATH, CAL_PATH, plan_week.load_rhythm(RHYTHM_PATH))


def calendar_by_date(dates):
    """那幾天各自有哪些行事曆事件 —— 給 /day 畫成灰色鎖住的格子。

    ⛔ 這些格子在網頁上不能拖、不能刪:它們不是我們的資料,要改去 Google 改。
    """
    import plan_week

    out = {d: [] for d in dates}
    for ev in plan_week.load_calendar(CAL_PATH):
        if str(ev.get("date")) in out:
            out[str(ev["date"])].append(ev)
    for items in out.values():
        items.sort(key=lambda e: (0 if e.get("allDay") else 1, str(e.get("start") or "")))
    return out


# ── /day 拖拉排程器(2026-08-11)────────────────────────────────────
# 使用者的需求:「我想設計一個更好讓我去做拖拉行程的工具…左邊 24 小時、右邊還沒排進行程
# 的任務,固定行程(讀書/語言/運動/吃飯/通勤)拉到左邊後右邊不會消失。」
DAILY_TPL_PATH = MAPS_DIR / "排程設定" / "日常區塊.json"
DAY_DIR = MAPS_DIR / "排程設定" / "每日行程"
DEFAULT_TEMPLATES = [
    {"id": "meal", "name": "吃飯", "emoji": "🍴", "min": 60, "color": "#f59f00"},
    {"id": "lang", "name": "語言學習", "emoji": "📖", "min": 120, "color": "#b197fc"},
    {"id": "read", "name": "讀書", "emoji": "📚", "min": 60, "color": "#4dabf7"},
    {"id": "sport", "name": "運動", "emoji": "🏃", "min": 90, "color": "#38d9a9"},
    {"id": "commute", "name": "通勤", "emoji": "🚇", "min": 30, "color": "#868e96"},
]


def _read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def daily_templates():
    data = _read_json(DAILY_TPL_PATH, None)
    blocks = (data or {}).get("blocks") if isinstance(data, dict) else None
    out = blocks if blocks else list(DEFAULT_TEMPLATES)
    return [{**b, "kind": "life"} for b in out]


DUTY_COLORS = ["#4dabf7", "#f59f00", "#38d9a9", "#b197fc", "#ff8787", "#a9e34b", "#e599f7"]


def duty_blocks(root):
    """常設職責 = 永遠不會完成、但要一直做的事(2026-08-18 定案)。

    它們**不是待辦**(做不完的東西掛死線與打勾沒有意義,只會一直卡在任務池裡),
    而是像吃飯運動那樣「可以重複拖進行程」的積木 —— 差別只在它連得回圖上那顆節點。
    ⛔ 不另外開一份清單:認 `detail.duty`,正本還是那張圖。
    """
    import plan_week
    out = []
    def walk(node, domain, path):
        here = path + [plan_week.strip_mark(node.get("topic"))]
        for child in node.get("children") or []:
            walk(child, domain, here)
        det = node.get("detail") or {}
        if not det.get("duty"):
            return
        name = plan_week.strip_mark(node.get("topic"))
        for m in ("♾️", "♾"):
            if name.startswith(m):
                name = name[len(m):].strip()
        out.append({
            "id": "duty:" + node["id"], "node": node["id"], "kind": "duty",
            "owner": (det.get("owner") or "").strip(),
            "name": name, "emoji": "♾️",
            "min": int(det.get("dutyMin") or 120),
            "color": det.get("color") or DUTY_COLORS[sum(map(ord, node["id"])) % len(DUTY_COLORS)],
            "domain": domain, "path": " › ".join(path[1:]),
            "explain": (det.get("explain") or "").strip(),
        })
    for dom in root.get("children") or []:
        walk(dom, plan_week.strip_mark(dom.get("topic")), [plan_week.strip_mark(root.get("topic"))])
    return sorted(out, key=lambda d: (d["domain"], d["name"]))


def day_file(date_iso):
    return DAY_DIR / f"{date_iso}.json"


def day_blocks(date_iso):
    """那一天放了哪些日常區塊。⚠️ 只有日常區塊住這裡 ——
    任務的「幾點做」存在心智圖節點上(2026-08-11 選的:任務板要看得到)。"""
    return (_read_json(day_file(date_iso), {}) or {}).get("blocks", [])


def put_day_blocks(date_iso, payload):
    date.fromisoformat(date_iso)  # 擋掉亂七八糟的檔名
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        raise ApiError(400, "blocks 必須是陣列")
    DAY_DIR.mkdir(parents=True, exist_ok=True)
    path = day_file(date_iso)
    text = json.dumps({"blocks": blocks}, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"date": date_iso, "count": len(blocks)}


def stale_tasks(root, today_iso):
    """排進行程、那天過了、卻沒標完成的事 —— **這一區存在是因為它們會整件消失**。

    使用者的回報(2026-08-24):「為什麼我在心智圖裡面有看到這個項目,但是我在我的排行程卻沒有?」
    那顆(一篇要寫的文章)是他自己在 8/20 排進 20:30、排滿 2 小時的。
    於是:①右邊「待辦事項」不列它 —— 那一區只收**還沒排進去**的額度,它已經排滿了
    ②時間軸上它在 8/20,而畫面預設從今天前三天開始 —— 往左捲才看得到。
    **兩個地方都合理,合起來就是查無此人。** 當天盤點有 11 件是這個狀態。

    ⚠️ 2026-08-30 起「待辦事項」改成「按完成才離開」,所以它們本來就還在那一區
    —— 這一區不再是「不看就消失」,而是**「你排了卻沒做」的提醒**,
    而且要能一鍵處理掉(搬到今天 / 丟回待辦)。
    """
    import plan_week

    out = []
    for task in plan_week.collect_tasks(root):
        if task["status"] == plan_week.DONE or not task["planned"]:
            continue
        if task["owner"] == "ai":
            continue  # AI 的不佔他的時間,掉了是我的事,⛔ 不要丟進他的清單
        last = max(slot["at"] for slot in task["planned"])
        if last[:10] >= today_iso:
            continue
        out.append({**task, "lastAt": last})
    out.sort(key=lambda t: t["lastAt"])
    return out


def day_view(query):
    """排程頁要的全部資料:每一天已排上去的、還沒排的、日常區塊。

    使用者的需求(2026-08-11):「所以他只能排一天喔,好爛喔…我想要可以一直往後看看到很多天的,
    不如就設定為一個禮拜吧,我看 Google 行事曆好像也都這樣設定的。」
    → 一次回連續幾天,前端並排成欄、左右捲。
    """
    import plan_week

    params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
    start_iso = unquote(params.get("date", "")) or datetime.now().astimezone().date().isoformat()
    try:
        start = date.fromisoformat(start_iso)
        span = max(1, min(31, int(params.get("days", "7"))))
    except ValueError:
        raise ApiError(400, "date 要 YYYY-MM-DD、days 要數字")

    dates = [(start + timedelta(days=i)).isoformat() for i in range(span)]
    events = calendar_by_date(dates)
    root = get_map(default_map_name())["data"]["nodeData"]
    by_date = {d: [] for d in dates}
    pool = []
    done_by_date = {d: [] for d in dates}
    for task in plan_week.collect_tasks(root):
        if task["status"] == plan_week.DONE:
            # ⛔ 完成的**不進 scheduled** —— 那一欄的時數統計刻意不算已完成的
            # (卡片上的說明就寫著「已經標完成的任務不算在裡面」),混進去等於偷改那個數字。
            # 它們走自己這一條:預設不畫,打開「顯示已完成」才出現。
            # 使用者的回報(2026-08-24):「按下完成任務的時候他就不見了…沒有辦法看到我到底
            # 這個東西是什麼時候做完的。」
            for slot in task["planned"]:
                if slot["at"][:10] in done_by_date:
                    done_by_date[slot["at"][:10]].append({**task, "slot": slot})
            continue
        # ⛔ 排進行程**不會**讓它離開右邊的任務池 —— 只有標完成才會。
        # 使用者的需求(2026-08-30):「一旦我把這個任務拉到左半邊的時間軸上的話,他並不會消失掉,
        # 他還是會繼續在右邊的部分可以繼續讓我拉動…好處就是我可以一個事情在一天的
        # 不同時段同時都放上去,而且還可以放到其他天。」
        # ⚠️ 舊版是拿「要花多久 − 已排時數」當額度,排滿就從池子移走 —— 那個算法
        # 連同「要花多久」一起從這一頁退休了(欄位本身還在,/plan 行程表還在讀)。
        used = sum(slot["min"] for slot in task["planned"])
        for slot in task["planned"]:
            if slot["at"][:10] in by_date:
                by_date[slot["at"][:10]].append({**task, "slot": slot})
        pool.append({**task, "used": used})
    order = (lambda t: (plan_week.PRIS.index(t["pri"]) if t["pri"] in plan_week.PRIS else 9,
                        t["due"] or "9999-99-99", t["topic"]))
    pool.sort(key=order)
    # ⚠️ 用**真的今天**,不是畫面上那一週的起點 —— 往回翻幾天不該讓這一區憑空縮水
    stale = stale_tasks(root, datetime.now().astimezone().date().isoformat())
    # 使用者的需求(2026-08-18):「周期性的或者是會一直要需要去做的東西,我們可能需要另外一個選單去區分出來。」
    # ⛔ 三種東西不要混在同一個池子裡:一次性的才是「還沒排進來」,
    #    週期性的做完會再來、AI 的根本不該佔使用者的容量 —— 混著看就分不出哪些是真的要人動手。
    duties = duty_blocks(root)
    waiting = [t for t in pool if t["until"] and t["owner"] != "ai"]
    pool = [t for t in pool if not t["until"] or t["owner"] == "ai"]
    repeats = [t for t in pool if t["repeat"] and t["owner"] != "ai"]
    ai_tasks = ([t for t in pool if t["owner"] == "ai"]
                + [d for d in duties if d["owner"] == "ai"])
    pool = [t for t in pool if not t["repeat"] and t["owner"] != "ai"]
    week = "一二三四五六日"
    return {
        "date": start_iso,
        "days": [{
            "date": d,
            "weekday": week[date.fromisoformat(d).weekday()],
            "scheduled": by_date[d],
            "blocks": day_blocks(d),
            "events": events[d],
            "done": done_by_date[d],
        } for d in dates],
        "pool": pool,
        "stale": stale,
        "repeats": repeats,
        "waiting": waiting,
        "aiTasks": ai_tasks,
        # 日常積木與常設職責走同一條算繪路徑(拖了不消失、不進任務池),只差顯示分兩區
        # ⛔ AI 的常設職責不進他的可拖清單 —— 他不會去做,放進去只是讓他多滑一段
        "templates": daily_templates() + [d for d in duties if d["owner"] != "ai"],
    }


# ⛔ `/plan` 行程表 2026-09-08 退休(定案)。理由:①使用者自己說「我好像也都沒有在用他的」
#    ②「行程表 /plan」跟「排行程 /day」名字只差一個字,分不出來。
#    ⚠️ 退休的是**網頁那一頁**,`plan_week.py` 沒有動 —— 它是 /day、mm.py 與
#    每週死線警報的共用核心,砍了那三個都會壞。
#    「哪幾件趕不上死線」現在只剩一條路:每週的排程跑指令列版 plan_week.py。


def _gate_password():
    """讀門禁密碼。讀不到就回 None = 只有信任清單上的裝置進得來。"""
    try:
        pw = GATE_PW_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return pw or None


def gate_verdict(ip, auth_header):
    """回 (放行?, 給人看的理由)。純函式,好測。

    ⛔ 順序不可調換:先看 IP,再看密碼。信任的裝置永遠不會被密碼問題擋在外面 ——
       密碼檔壞掉/被誤刪時,使用者自己的機器要照樣能用,不能把人一起鎖在門外。
    """
    if ip in TRUSTED_IPS:
        return True, "信任的裝置"
    pw = _gate_password()
    if pw is None:
        return False, "這台裝置不在信任清單,而且還沒設門禁密碼"
    if not auth_header.startswith("Basic "):
        return False, "要密碼"
    try:
        raw = base64.b64decode(auth_header[len("Basic ") :]).decode("utf-8")
    except (ValueError, TypeError):
        # ⚠️ 2026-08-18 單元測抓到:原本只接 (binascii.Error, UnicodeDecodeError),
        #    但 base64 收到**非 ASCII 字元**時丟的是裸的 ValueError(不是 binascii.Error)
        #    → 例外會一路噴出 parse_request,對方拿到的是連線被切斷而不是乾淨的 401,
        #      而且 log 裡多一坨堆疊。改接 ValueError(binascii.Error 與 UnicodeDecodeError
        #      本來就是它的子類,一併涵蓋)。同樣的洞 mindmap/main.py 也有,已一起修。
        return False, "認證格式看不懂"
    got = raw.split(":", 1)[1] if ":" in raw else ""
    # compare_digest:避免用比對時間反推密碼(對本機服務是小題大作,但不花成本)
    return (hmac.compare_digest(got, pw), "密碼正確" if got == pw else "密碼不對")


class Handler(BaseHTTPRequestHandler):
    def parse_request(self):
        """門禁閘門。

        ⛔ 刻意放在 parse_request,不是放在每一個 do_GET/do_PUT/do_PATCH 裡面:
           那樣以後有人加一個 do_POST 就得記得補一行,而**漏掉不會報錯、只會靜靜開後門**
           (2026-08-17 已經在另外兩處白名單式的檢查上
            各出過一次同樣形狀的問題)。放這裡 = 所有現在與未來的方法自動都被擋。
        """
        if not BaseHTTPRequestHandler.parse_request(self):
            return False
        ok, why = gate_verdict(
            self.client_address[0], self.headers.get("Authorization", "")
        )
        if ok:
            return True
        print(f"{self.client_address[0]} - 擋下({why})", flush=True)
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="mindmap"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        body = f"需要密碼才能看({why})".encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body, ctype):
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path):
        if not path.is_file():
            return self._json({"detail": "not found"}, 404)
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 一律不給快取:改完 app.js/css 只要普通重新整理就生效。
        # (使用者的看圖環境不一定按得到硬重新整理,不能靠他手動清快取)
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path = unquote(self.path.split("?", 1)[0])
            if path == "/api/health":
                self._json({"ok": True, "maps_dir": str(MAPS_DIR), "build": static_build()})
            elif path == "/api/maps":
                self._json(list_maps())
            elif path == "/api/project":
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                rel = ""
                for part in query.split("&"):
                    if part.startswith("path="):
                        rel = unquote(part[len("path=") :])
                self._json(project_status(rel))
            elif path == "/api/day":
                self._json(day_view(self.path.split("?", 1)[1] if "?" in self.path else ""))
            elif path.startswith("/api/maps/") and path.endswith("/quick-targets"):
                self._json(quick_targets(path[len("/api/maps/") : -len("/quick-targets")]))
            elif path.startswith("/api/maps/"):
                self._json(get_map(path[len("/api/maps/") :]))
            elif path.startswith("/file/"):
                body = file_view(path[len("/file/") :]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/":
                self._file(static_file("index.html"))
            elif path in ("/board", "/board/"):
                # 任務板:同一份圖的第二個視圖(卡片式,依狀態分欄)
                self._file(static_file("board.html"))
            elif path in ("/day", "/day/"):
                # 拖拉排程器:左邊一天的時間軸、右邊還沒排進來的任務
                self._file(static_file("day.html"))
            elif path in ("/topics", "/topics/"):
                # 待辦事項:同一份圖按「主題」收起來(2026-09-08)。
                # 任務板回答「有哪些事」,這一頁回答「這件事我還剩什麼沒做」。
                self._file(static_file("topics.html"))
            elif path == "/static/js/config.js":
                # 前端唯一的設定來源:現在預設要載哪一張圖。⛔ 不要在 js 裡寫死圖名。
                self._text(f"window.MM_MAP = {json.dumps(default_map_name(), ensure_ascii=False)};\n",
                           "application/javascript")
            elif path.startswith("/static/"):
                target = (STATIC_DIR / path[len("/static/") :]).resolve()
                if STATIC_DIR.resolve() not in target.parents:
                    raise ApiError(400, "路徑不合法")
                self._file(target)
            else:
                self._json({"detail": "not found"}, 404)
        except ApiError as e:
            self._json({"detail": e.detail}, e.status)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError(400, "body 不是合法 JSON")

    def do_POST(self):
        try:
            path = unquote(self.path.split("?", 1)[0])
            prefix = "/api/maps/"
            if path.startswith(prefix) and path.endswith("/quick-todo"):
                # 每一頁右下角「＋」隨手記(2026-09-17)
                self._json(quick_todo(path[len(prefix) : -len("/quick-todo")], self._body()))
                return
            if path.startswith(prefix) and path.endswith("/drop") and "/nodes/" in path:
                rest = path[len(prefix):-len("/drop")]
                name, node_id = rest.split("/nodes/", 1)
                self._json(drop_node(name, node_id, self._body()))
            else:
                raise ApiError(404, "not found")
        except ApiError as e:
            self._json({"detail": e.detail}, e.status)

    def do_PUT(self):
        try:
            path = unquote(self.path.split("?", 1)[0])
            if path.startswith("/api/day/"):
                self._json(put_day_blocks(path[len("/api/day/") :], self._body()))
            elif path.startswith("/api/maps/"):
                self._json(put_map(path[len("/api/maps/") :], self._body()))
            else:
                raise ApiError(404, "not found")
        except ApiError as e:
            self._json({"detail": e.detail}, e.status)

    def do_PATCH(self):
        """只改一個節點的排程欄位 —— /day 每拖一下就存一次,不能整張圖重寫。"""
        try:
            path = unquote(self.path.split("?", 1)[0])
            prefix = "/api/maps/"
            if path.startswith(prefix) and path.endswith("/view-order"):
                # 待辦事項頁拖主題排順序(2026-09-08)
                self._json(patch_view_order(path[len(prefix) : -len("/view-order")], self._body()))
                return
            if not path.startswith(prefix) or "/nodes/" not in path:
                raise ApiError(404, "not found")
            name, node_id = path[len(prefix) :].split("/nodes/", 1)
            self._json(patch_node(name, node_id, self._body()))
        except ApiError as e:
            self._json({"detail": e.detail}, e.status)

    def log_message(self, fmt, *args):  # 保持單行、帶來源,寫到 stdout(launchd log)
        print(f"{self.client_address[0]} - {fmt % args}", flush=True)


def build_server(host, port):
    return ThreadingHTTPServer((host, port), Handler)


def main():
    server = build_server(HOST, PORT)
    print(f"mindmap server on http://{HOST}:{PORT} (maps: {MAPS_DIR})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
