"""plan_week.py — 從心智圖長出「這一週怎麼排」。

使用者的需求(2026-08-08):「根據現在建立好的心智圖,直接建立行程規劃跟這一個禮拜要做什麼事的規劃。」
心智圖節點上的 `detail.due`(死線)+ `detail.effort`(要花多久)+ `tags` 的 P1–P4,
剛好就是排程需要的三個輸入 —— 這支把它們算成一張「哪天做哪件」的表。

## 排程邏輯(這就是使用者要確認的那套「行程表建立邏輯」)

**一天分三格,互不搶時間。時段與容量的唯一正本 = `排程設定/作息.json`:**
| 格 | 預設時段 | 放什麼 |
|---|---|---|
| 主線 | 09:00–13:00(4h) | 需要使用者專注判斷的事(要花 >1h 的) |
| 雜項 | 14:00–15:30(1.5h) | 零碎事(≤1h 的) |
| 語言 | 19:00–23:00(4h) | 只放 Language 領域 |

⛔ **容量不要再寫死在別的地方** —— 一天有幾小時 = 那幾段加起來(`capacity_of`),
改作息容量就跟著動。每件事也會落到**確切的鐘點**上(`assign_times`),
因為使用者的需求(2026-08-11):「我希望可以為自己排一個確切的時間軸做事情的時間走。」

**🔒 外力死線 `detail.hardDue`:** 行程表可以「這天以後整串往後推 N 天」
(推的是 due,連鎖自動發生)。標了 `hardDue` 的**不會被推走** ——
合約到期 8/13、機關約定日 8/27、款項入帳 8/31 那種推了就是錯的,而那正是最不能出錯的一批。

**放的順序:**死線近的先 → 同死線比等級(P1→P4) → 都一樣比要花多久(短的先,先把零碎的清掉)。

**四條硬規則:**
1. **一件事一定要在死線當天(含)之前排完**,排不下就進「塞不下」清單,⛔ 不硬塞、不默默延期。
2. **超過一天容量的事會自動切開**排到連續幾天(8h 的事 = 主線格兩天)。
3. **標了「一起做」的一批盡量排同一天**;整批塞不進一天(例:某一批五條共 9h)
   就排**連續的日子**,⛔ 不會散在一週各處 —— 那批要的是「一次處理完」的連續性。
4. **主線一天以一個領域為主** —— 注意力一次只放一條線,同一天塞三個領域等於三次切換成本。

**「不能比這天早做」** → `detail.earliest`。2026-08-11 補的:排程只認死線,
於是把「8/13 當天去機關窗口辦手續」排到 8/12(那天合約還沒到期)、把「款項入帳對帳」
排到 8/18(錢 8/31 才進來)。⛔ 這種表比沒有表更糟 —— 照著做會白跑一趟。
凡是「要等某件事發生之後才做得了」的,一律填 earliest。

**🗓 使用者自己排過的時段一律尊重(2026-08-13 定案):** `detail.planned` 是他在
「排今天」(`/day`)拖出來的段落。行程表**先把那些時間佔掉**、把已排的時數從
該事的總量扣掉,剩下的才自己排;整件都排完的就完全不碰,畫面上標 🗓 跟程式算的分開。
⛔ 在這之前 `/plan` 會把他手排好的事再排一次 —— **兩個視圖各講各的,他就不知道該信哪一個**。
> 兩者的分工:`/day` = 他自己排(正本),死線警報 = 回答「照這樣排下去,哪幾件趕不上」。
>
> **⚠️ 2026-09-08 更正:上面那句「⛔ `/plan` 不退休」已經作廢 —— 網頁那一頁收掉了。**
> 定案收掉,兩個理由:①使用者自己說「我好像也都沒有在用他的」(2026-08-30)
> ②「行程表 /plan」跟「排行程 /day」名字只差一個字,分不出來。
>
> **⛔ 退休的是網頁,這支程式沒有退休,而且不能砍:**
> `main.py` 有 6 處、`mm.py` 有 2 處 import 它(`/day` 的「哪幾天排不了事」、
> 行事曆卡住的時段、`collect_tasks`、`EFFORT_HOURS`、`PRIS`),砍了那些全部會壞。
> **而且「哪幾件趕不上死線」現在只剩一條路:每週的排程跑這支的指令列版**
> (每週重排的排程腳本第 1 步)。⛔ 那一條斷了,那個能力就安靜地消失了 ——
> `tests/test_plan_route.py` 最後三條就是在守這件事。

**排不進去的三種下場**(都會明講,不會消失):
`塞不下` = 死線前湊不出時間 / `要你自己挑日子` = 有地點或情境限制 / `卡在別人身上` = ⏸️ 狀態。

**Google 行事曆會自己卡住時段(2026-08-22 定案)**:排程的程式每天早上把 Main 與 Travel
兩本未來 14 天的事件抓進 `排程設定/行事曆快取.json`,`calendar_busy` 把它換算成下面那兩種
寫法之一 —— 有時間的事件從撞到的那一格扣時數,整天的事件當「整天沒空」。
**只准單向**:行事曆進來卡住時段,⛔ 我們的待辦永遠不寫回 Google(兩邊互寫 = 同一件事兩份)。
手寫的 `整天沒空.json` **贏過**行事曆算出來的 —— 那是使用者明講的,行事曆只是推測。

**那天沒那麼多時間怎麼辦** → `排程設定/整天沒空.json`(見 `day_capacity`):
整天沒空寫一句話,只是縮水(還在上班、下午要出門)寫 `{"why","cap"}` 改那天的格子。
⚠️ 2026-08-11 補的:在那之前只有「整天/整天不」兩種,於是 8/11–8/13 使用者還要上班的日子
被當成完整 10 小時 —— 排出來的表他一件都做不到,然後整張表就沒人信了。

## ⚠️ 死線只填「外力給的」(2026-08-11 定案)

`detail.due` 只給**別人給的日期**:法定期限、對方在等、錯過就沒了。
「我希望這天做完」**不要填 due**,靠 P1–P4 排順序就好。
理由:2026-08-11 盤點,32 條有死線的裡面只有 6 條是真的,其餘是願望 ——
於是每次跑都噴 13 條紅字,紅字一多就等於沒有紅字,使用者就不看了。
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = "http://127.0.0.1:8030"  # ⚠️ 伺服器只綁 Tailscale 介面,127.0.0.1 連不到
MAP_NAME = "全局總覽圖"
# 「整天沒空」的日子。⚠️ 指令列跟網頁 /plan **必須讀同一份**,
# 不然同一套邏輯會算出兩種答案 —— 那比沒有排程更糟。
BUSY_PATH = Path(
    os.environ.get("MINDMAP_MAPS_DIR", "~/mindmaps")
).expanduser() / "排程設定" / "整天沒空.json"

# 每天固定的作息時段 —— **容量的唯一來源**。
# 使用者的需求(2026-08-11):「我會希望我可以為自己排一個確切的時間軸做事情的時間走,
# 那現在這個東西感覺就不是一個確切的時間軸。」
# ⛔ 容量不要再寫死在別的地方:一天有幾小時 = 這幾段加起來,改作息容量就跟著動。
RHYTHM_PATH = BUSY_PATH.parent / "作息.json"
# Google 行事曆的快取。⚠️ 這份是**抓下來的副本,不是正本** —— 正本永遠在 Google
# 那邊,我們只讀不寫(2026-08-22 定案:「只准單向」,兩邊互相寫同一件事會有兩份)。
# 誰負責抓:每天的排程程式用行事曆連接器抓未來 14 天,寫進這裡(見 cal_cache.py)。
# ⛔ 排程程式自己抓不到 —— 它被 launchd 派出時沒有 Google 的長期授權。
CAL_PATH = BUSY_PATH.parent / "行事曆快取.json"
DEFAULT_RHYTHM = [
    {"track": "main", "start": "09:00", "end": "13:00"},
    {"track": "misc", "start": "14:00", "end": "15:30"},
    {"track": "lang", "start": "19:00", "end": "23:00"},
]
TRACK_NAME = {"main": "主線", "misc": "雜項", "lang": "語言"}
MISC_MAX = 1.0  # 要花 ≤1h 的算零碎事,進雜項格
DEFAULT_HOURS = 2.0  # 沒填「要花多久」時的假設值(會另外列出來提醒補)

# 心智圖上的八檔 + 早期的三檔舊值(圖上可能還有殘留)
EFFORT_HOURS = {
    "1h": 1.0, "2h": 2.0, "4h": 4.0, "8h": 8.0, "12h": 12.0,
    "1天": 10.0, "2天": 20.0, "1週": 50.0,
    "小": 1.0, "中": 4.0, "大": 8.0,
}
PRIS = ("P1", "P2", "P3", "P4")
DONE, WAITING = "✅", "⏸️"


def hhmm_to_hours(text):
    h, m = str(text).split(":")
    return int(h) + int(m) / 60.0


def hours_to_hhmm(value):
    total = round(value * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def load_rhythm(path=None):
    """讀每天的固定時段。壞掉/沒有就用預設,⛔ 不讓排程整支掛掉。"""
    try:
        data = json.loads(Path(path or RHYTHM_PATH).read_text(encoding="utf-8"))
        blocks = data.get("blocks") if isinstance(data, dict) else data
        out = [b for b in blocks if b.get("track") in TRACK_NAME and b.get("start") and b.get("end")]
        return sorted(out, key=lambda b: b["start"]) if out else list(DEFAULT_RHYTHM)
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return list(DEFAULT_RHYTHM)


def capacity_of(rhythm):
    """一天各格有幾小時 = 那一格的時段加起來。⛔ 這是容量的唯一算法。"""
    cap = {t: 0.0 for t in TRACK_NAME}
    for b in rhythm:
        cap[b["track"]] += hhmm_to_hours(b["end"]) - hhmm_to_hours(b["start"])
    return {t: round(v, 2) for t, v in cap.items()}


CAP = capacity_of(DEFAULT_RHYTHM)  # 給測試與「讀不到設定檔」時用的預設
MARKS = ["⏳", "🔜", "⏸️", "⏸", "✅", "🎯"]
BATCH_TAG = "一起做"
LANG_DOMAIN = "Language"


def strip_mark(topic):
    text = (topic or "").strip()
    for mark in MARKS:
        if text.startswith(mark):
            return text[len(mark):].strip()
    return text


def status_of(topic):
    text = (topic or "").strip()
    if text.startswith(DONE):
        return DONE
    if text.startswith(("⏸️", "⏸")):
        return WAITING
    return "🔜" if text.startswith("🔜") else "⏳"


def collect_tasks(root):
    """走訪整張圖,把待辦節點抓成排程用的資料。

    一路帶著「領域」(根的直接子節點)與完整路徑 —— 卡片離開圖之後
    還要看得出「這件事屬於哪一塊」,不然排出來的表沒人看得懂。
    """
    out = []

    def walk(node, domain, path):
        here = path + [strip_mark(node.get("topic"))]
        for child in node.get("children", []):
            walk(child, domain, here)
        if not node.get("todo"):
            return
        detail = node.get("detail") or {}
        tags = node.get("tags") or []
        effort = detail.get("effort") or ""
        out.append({
            "id": node.get("id"),
            "topic": strip_mark(node.get("topic")),
            "status": status_of(node.get("topic")),
            "pri": next((t for t in tags if t in PRIS), ""),
            "tags": [t for t in tags if t not in PRIS],
            "due": detail.get("due") or "",
            "effort": effort,
            "hours": EFFORT_HOURS.get(effort, DEFAULT_HOURS),
            "guessed_hours": effort not in EFFORT_HOURS,
            "window": detail.get("window") or "",
            "earliest": detail.get("earliest") or "",
            # /day 拖拉排程器用的:排了哪幾段。
            # ⚠️ 是**陣列**不是單一時間 —— 使用者的需求(2026-08-11):「假設某個任務要花 4 小時,
            # 而我現在只排了 2 小時…應該要代表我還有剩下的 2 小時沒被放進去。」
            # 一件事可以切成好幾段排在不同時間/不同天,沒排完的留在池子裡。
            # ⚠️ 跟 due 是兩件事 —— due 是「什麼時候之前要做完」,這是「哪天幾點做」。
            "planned": planned_slots(detail),
            "totalMin": round(EFFORT_HOURS.get(effort, 1.0) * 60) if effort
                        else DEFAULT_SLOT_MIN,
            "hardDue": bool(detail.get("hardDue")),
            "domain": domain,
            "path": " › ".join(path[1:]),
            # 使用者的需求(2026-08-17):「我應該要知道這個東西是為了什麼做的…不然我在拉動我的個人任務
            # 的時候我不知道這什麼東西。」→ 理由跟著任務一起送到排程頁,不必他自己跑回圖上找。
            "explain": (detail.get("explain") or "").strip(),
            # 使用者的需求(2026-08-18):「周期性的或者是會一直要需要去做的東西,我們可能需要另外一個選單」
            # repeat = 做完之後多久會再來(空的 = 一次性);owner = 這是誰的事(ai = 不佔使用者的容量)
            "repeat": (detail.get("repeat") or "").strip(),
            "owner": (detail.get("owner") or "").strip(),
            # 使用者的需求(2026-08-18):「我根本就還不知道什麼時候找到工作,他應該是找到工作之後
            # 才要有人提醒我…一直放在待辦事項覺得很怪。」
            # ⚠️ 跟 earliest 不一樣:earliest 要填**日期**,這個是「等某件事發生」——
            # 事情什麼時候發生根本不知道,硬填一個日期就是編出來的。
            "until": (detail.get("until") or "").strip(),
            # 標 ✅ 的那一天。⚠️ 沒有這一欄就答不出「這件事什麼時候做完的」——
            # 而那正是使用者 2026-08-24 問的:「按下完成任務的時候他就不見了…
            # 沒有辦法看到我到底這個東西是什麼時候做完的。」
            "doneOn": (detail.get("doneOn") or "").strip(),
        })

    for dom in root.get("children", []):
        walk(dom, strip_mark(dom.get("topic")), [strip_mark(root.get("topic"))])
    return out


DEFAULT_SLOT_MIN = 60  # 沒填「要花多久」時,拖進行程預設佔多久


def planned_slots(detail):
    """把節點上的排程讀成 [{uid, at, min}]。

    舊格式(單一 plannedAt/plannedMin)自動轉成一段 —— ⛔ 不要求先跑遷移腳本,
    圖上隨時可能還有舊資料,讀的時候相容就好。
    """
    raw = detail.get("planned")
    out = []
    if isinstance(raw, list):
        for i, slot in enumerate(raw):
            if isinstance(slot, dict) and slot.get("at"):
                out.append({
                    "uid": slot.get("uid") or f"s{i}",
                    "at": slot["at"],
                    "min": int(slot.get("min") or DEFAULT_SLOT_MIN),
                })
    elif detail.get("plannedAt"):
        out.append({"uid": "s0", "at": detail["plannedAt"],
                    "min": int(detail.get("plannedMin") or DEFAULT_SLOT_MIN)})
    return sorted(out, key=lambda s: s["at"])


def track_of(task):
    """這件事放哪一格。

    ⚠️ 標了「一起做」的看**整批**總時數,不是單條 —— 同一批那三件
    各 1h,單看都是雜項,
    可是雜項格一天只有 1.5h,於是同一件事被拆成三天做,而主線 4h 空著。
    它們是同一件事,整批 3h 就該進主線。
    """
    if task["domain"] == LANG_DOMAIN:
        return "lang"
    hours = task.get("batch_hours", task["hours"])
    return "misc" if hours <= MISC_MAX else "main"


def _sort_key(task):
    """死線近的先 → 等級 → 短的先。沒死線的一律排到最後面(大部分項目都沒死線,
    把空值當成 0 的話整張表會被沒死線的淹掉)。"""
    due = task["due"] or "9999-99-99"
    pri = PRIS.index(task["pri"]) if task["pri"] in PRIS else 9
    return (due, pri, task["hours"])


def _group_key(task):
    """標了「一起做」的視為一批 —— 同領域同標籤的排同一天。"""
    return (task["domain"], BATCH_TAG) if BATCH_TAG in task["tags"] else None


def day_capacity(key, busy, cap):
    """算出某一天各時段真正有多少小時,以及要顯示什麼說明。

    兩種寫法(見 排程設定/整天沒空.json):
      "2026-08-09": "整天有活動"                          ← 整天不排
      "2026-08-11": {"why": "上班", "cap": {"main": 0, "lang": 2}}  ← 只有部分時段縮水
    後者沒寫到的時段照預設容量。⚠️ 沒有這個「半天」的表達方式,
    還在上班的日子就會被當成完整 10 小時,排出來的表是假的。

    回傳 (容量, 整天沒空的理由, 部分縮水的備註) —— 兩種說明分開,
    因為前端要把「這天不用看」跟「這天少一點」畫成不同的東西。
    """
    entry = busy.get(key)
    if entry is None:
        return dict(cap), "", ""
    if isinstance(entry, str):
        return {t: 0.0 for t in cap}, entry, ""
    why = str(entry.get("why") or "")
    over = entry.get("cap") or {}
    hours = {t: max(0.0, float(over.get(t, cap[t]))) for t in cap}
    if not any(hours.values()):
        return hours, why or "整天有事", ""
    return hours, "", why


def assign_times(items, rhythm, hours):
    """把已經排進某一天的事,落到**確切的鐘點**上(見 作息.json)。

    使用者的需求(2026-08-11):「我會希望我可以為自己排一個確切的時間軸做事情的時間走,
    那現在這個東西感覺就不是一個確切的時間軸。」
    在那之前一天只講「這幾件」,沒有幾點到幾點 —— 那沒辦法拿來過日子,
    也沒辦法判斷「現在 16:30 了,還剩多少」。

    ⚠️ 那天的容量被砍過(還在上班)時,可用的時間從時段的**開頭**算起。
    哪一段被砍掉其實只有人知道,所以這是個假設,不是事實。
    """
    for track, cap_hours in hours.items():
        blocks = [b for b in rhythm if b["track"] == track]
        if not blocks:
            continue
        left_in_day = cap_hours
        bi, pos = 0, hhmm_to_hours(blocks[0]["start"])
        for item in [i for i in items if i["track"] == track]:
            need, segs = item["hours_today"], []
            while need > 0.001 and bi < len(blocks) and left_in_day > 0.001:
                block_end = hhmm_to_hours(blocks[bi]["end"])
                room = min(block_end - pos, left_in_day)
                if room <= 0.001:
                    bi += 1
                    if bi < len(blocks):
                        pos = hhmm_to_hours(blocks[bi]["start"])
                    continue
                take = min(room, need)
                segs.append({"start": hours_to_hhmm(pos), "end": hours_to_hhmm(pos + take)})
                pos += take
                need -= take
                left_in_day -= take
            if segs:
                item["segments"] = segs
                item["start_at"] = segs[0]["start"]
                item["end_at"] = segs[-1]["end"]


def plan(tasks, start, days=7, busy=None, capacity=None, rhythm=None):
    """把待辦排進 start 起算的 days 天。回傳可以直接給前端畫的結構。

    busy: 見 day_capacity —— 整天沒空寫字串,只是縮水寫 {"why","cap"}。
    rhythm: 每天的固定時段(見 作息.json)。容量預設就是從它算出來的。
    capacity: 覆寫容量,測試用。
    """
    rhythm = rhythm if rhythm is not None else list(DEFAULT_RHYTHM)
    cap = dict(capacity or capacity_of(rhythm))
    busy = busy or {}
    horizon = [start + timedelta(days=i) for i in range(days)]
    end = horizon[-1]
    today = {d.isoformat(): day_capacity(d.isoformat(), busy, cap) for d in horizon}
    slots = {key: dict(v[0]) for key, v in today.items()}
    placed = {d.isoformat(): [] for d in horizon}
    day_domain = {d.isoformat(): None for d in horizon}  # 主線一天以一個領域為主

    schedulable, overflow, manual, blocked, no_effort = [], [], [], [], []
    for task in tasks:
        if task["status"] == DONE:
            continue
        if task["status"] == WAITING:
            blocked.append(task)
            continue
        if task["window"]:
            manual.append(task)  # 有地點/情境限制,程式判斷不了,交回給使用者自己挑日子
            continue
        if task["guessed_hours"]:
            no_effort.append(task)
        schedulable.append(task)

    # 🗓 使用者自己在 /day 拖出來的時段先佔位,剩下的才交給程式排。
    # ⛔ 不做這件事的話,他手排好的事會被 /plan 當成「還沒排」再排一次 ——
    #    兩個視圖各講各的,他就不知道該信哪一個(2026-08-13 盤點抓到的最後一個矛盾)。
    # ⚠️ track 要在扣掉時數「之前」算:1h 的雜項扣完剩 0 會被誤判成別的格子。
    for task in schedulable:
        track = track_of(task)
        booked = 0.0
        for slot in task.get("planned") or []:
            hours_ = (slot.get("min") or 0) / 60
            if hours_ <= 0:
                continue
            booked += hours_
            key = slot["at"][:10]
            if key in slots:
                slots[key][track] = max(0.0, slots[key][track] - hours_)
                if track == "main":
                    day_domain[key] = task["domain"]
                placed[key].append({**task, "track": track,
                                    "hours_today": round(hours_, 2), "by_sc": True})
        if booked:
            task["hours"] = max(0.0, round(task["hours"] - booked, 2))
    # 整件都排完了就不必再算它 —— 但仍留在 placed 裡看得到
    schedulable = [t for t in schedulable if t["hours"] > 0.01]

    schedulable.sort(key=_sort_key)

    # 排的單位是「一批」不是「一件」:標了「一起做」的黏成一個單位(規則③),
    # 其餘各自一個單位。整批一起排才排得出「這五件同一天處理完」。
    groups, units = {}, []
    for task in schedulable:
        key = _group_key(task)
        if not key:
            units.append([task])
        elif key not in groups:
            groups[key] = [task]
            units.append(groups[key])
        else:
            groups[key].append(task)
    for unit in units:
        if len(unit) > 1:  # 見 track_of:一批的格子看整批總時數
            total = sum(t["hours"] for t in unit)
            for member in unit:
                member["batch_hours"] = total
    units.sort(key=lambda unit: min(_sort_key(t) for t in unit))

    def fits(day_key, task, hours):
        track = track_of(task)
        if slots[day_key][track] < hours:
            return False
        # 主線一天以一個領域為主 —— 同一天塞三個領域等於三次切換成本
        return track != "main" or day_domain[day_key] in (None, task["domain"])

    def put(day_key, task, hours):
        track = track_of(task)
        slots[day_key][track] -= hours
        if track == "main":
            day_domain[day_key] = task["domain"]
        placed[day_key].append({**task, "track": track, "hours_today": round(hours, 2)})

    def place_one(task):
        """回傳還沒放完的小時數。
        ⚠️ 雜項(≤1h)是不可分割的 —— 把一件 1 小時的事切成兩天各半小時毫無意義;
        主線的大塊事情才准跨天(8h 的事 = 主線格兩天)。"""
        track, left = track_of(task), task["hours"]
        deadline = task["due"] or end.isoformat()
        for day in horizon:
            key = day.isoformat()
            if left <= 0 or key > deadline:
                break
            if key < task["earliest"]:
                continue  # 還沒到做得了的日子(見 earliest)
            if track != "main":
                if fits(key, task, left):
                    put(key, task, left)
                    left = 0
                continue
            free = slots[key]["main"]
            if free <= 0 or day_domain[key] not in (None, task["domain"]):
                continue
            take = min(free, left)
            put(key, task, take)
            left -= take
        return left

    def place_batch(tasks):
        """整批放同一天:找死線之前第一個「整批都塞得下」的日子。
        一天塞不完(整批 9h 這種)就一件接一件排 —— 因為整批是連著處理的,
        它們會自然落在連續的日子上,不會散開。"""
        deadline = min((t["due"] for t in tasks if t["due"]), default=end.isoformat())
        soonest = max((t["earliest"] for t in tasks), default="")
        for day in horizon:
            key = day.isoformat()
            if key > deadline:
                break
            if key < soonest:
                continue
            need = {}
            for task in tasks:
                need[track_of(task)] = need.get(track_of(task), 0) + task["hours"]
            doms = {track_of(t): t["domain"] for t in tasks}
            ok = all(slots[key][tr] >= hrs for tr, hrs in need.items()) and (
                "main" not in need or day_domain[key] in (None, doms["main"])
            )
            if ok:
                for task in tasks:
                    put(key, task, task["hours"])
                return []
        return [(task, place_one(task), True) for task in tasks]

    for unit in units:
        results = ([(unit[0], place_one(unit[0]), False)] if len(unit) == 1
                   else place_batch(unit))
        for task, left, split in results:
            if left > 0:
                overflow.append({
                    **task,
                    "left": round(left, 2),
                    "why": ("死線前排不出時間" if task["due"] else "這一週塞不下")
                           + ("(而且「一起做」那批被拆開了)" if split else ""),
                })

    out_days = []
    for day in horizon:
        key = day.isoformat()
        hours, off, note = today[key]
        assign_times(placed[key], rhythm, hours)
        out_days.append({
            "date": key,
            "weekday": "一二三四五六日"[day.weekday()],
            "busy": off,
            "note": note,
            "items": placed[key],
            "used": {t: round(hours[t] - slots[key][t], 2) for t in cap},
            "cap": {t: hours[t] for t in cap},
        })

    # 「趕不上死線」跟「這週輪不到」是兩件事:前者要使用者現在就決定砍誰,
    # 後者是正常的待辦庫存,混在一起講就等於沒講。
    # ⚠️ 死線落在這幾天之後的不算趕不上 —— 只是這一週還輪不到它,別製造假警報。
    horizon_end = end.isoformat()
    late = sorted((t for t in overflow if t["due"] and t["due"] <= horizon_end),
                  key=_sort_key)
    backlog = sorted((t for t in overflow if not (t["due"] and t["due"] <= horizon_end)),
                     key=_sort_key)
    return {
        "start": start.isoformat(),
        "rhythm": rhythm,
        "days": out_days,
        "late": late,
        "backlog": backlog,
        "manual": sorted(manual, key=_sort_key),
        "blocked": blocked,
        "no_effort": no_effort,
        "totals": {
            "tasks": len(tasks),
            "scheduled": sum(len(d["items"]) for d in out_days),
            "late": len(late),
            "backlog": len(backlog),
        },
    }


def load_busy(path=None):
    """讀「整天沒空」的日子。檔案不存在或壞掉都不該讓排程整支掛掉 —— 回空的就好。"""
    try:
        data = json.loads(Path(path or BUSY_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, (str, dict))}


def load_calendar(path=None):
    """讀行事曆快取。抓不到就當作沒有事件 —— ⛔ 不讓排程整支掛掉。

    一筆事件長這樣(日期一律是**本地日期**,跨天的事由抓取端拆成一天一筆):
        {"date": "2026-08-25", "start": "14:00", "end": "15:30", "title": "開會", "cal": "Main"}
        {"date": "2026-10-24", "allDay": true, "title": "出遊 Day1", "cal": "Travel"}
    """
    try:
        data = json.loads(Path(path or CAL_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    events = data.get("events") if isinstance(data, dict) else data
    out = []
    for item in events or []:
        if not isinstance(item, dict):
            continue
        try:
            date.fromisoformat(str(item.get("date")))
        except (ValueError, TypeError):
            continue
        out.append(item)
    return out


def calendar_busy(events, rhythm, cap):
    """把行事曆事件換算成 `day_capacity` 看得懂的那兩種寫法。

    ⛔ 刻意不做成第三種格式:整天的事件 → 字串(整天沒空),有時間的 →
    `{"why","cap"}`(那一格扣掉重疊的時數)。這樣「行事曆卡住的」跟「手寫卡住的」
    走完全同一條算法,⛔ 不會出現兩套邏輯算出兩種答案。

    ⚠️ 兩件事要分開:**看得到** 跟 **吃掉時間**。沒撞到任何時段的事件(例:16:00 剪頭髮)、
    以及 `blocks` 是 false 的事件(Main 本的整天提醒、他自己標成「顯示為有空」的),
    照樣寫進說明給他看,但⛔ 不扣時數。判斷誰 `blocks` 在 `cal_cache.py` 的檔頭那張表。
    """
    per = {}
    for ev in events:
        key = str(ev["date"])
        slot = per.setdefault(key, {"why": [], "cut": {t: 0.0 for t in cap}, "allday": False})
        title = str(ev.get("title") or "行事曆有事").strip()
        blocks = bool(ev.get("blocks", True))
        if ev.get("allDay") or not ev.get("start") or not ev.get("end"):
            slot["allday"] = slot["allday"] or blocks
            slot["why"].append(title if blocks else f"{title}(整天,沒有扣掉時間)")
            continue
        try:
            begin, end = hhmm_to_hours(ev["start"]), hhmm_to_hours(ev["end"])
        except (ValueError, AttributeError, TypeError):
            continue
        if end <= begin:
            end = 24.0  # 跨過午夜:這一天只算到 24:00,剩下那截是明天的事
        for block in (rhythm if blocks else []):
            over = min(end, hhmm_to_hours(block["end"])) - max(begin, hhmm_to_hours(block["start"]))
            if over > 0:
                slot["cut"][block["track"]] += over
        slot["why"].append(f"{title} {ev['start']}–{ev['end']}")

    out = {}
    for key, slot in per.items():
        why = "、".join(slot["why"][:3]) + ("…" if len(slot["why"]) > 3 else "")
        if slot["allday"]:
            out[key] = why
            continue
        out[key] = {
            "why": why,
            "cap": {t: max(0.0, round(cap[t] - slot["cut"][t], 2)) for t in cap},
        }
    return out


def merged_busy(busy_path=None, cal_path=None, rhythm=None):
    """行事曆算出來的 + 手寫的。**手寫的贏** —— 那是使用者明講的,行事曆只是推測。

    ⛔ 這是唯一該餵給 `plan()` 的 busy 來源:指令列跟網頁 /plan 都走這支,
    不然同一套邏輯會算出兩種答案。
    """
    rhythm = rhythm or load_rhythm()
    merged = calendar_busy(load_calendar(cal_path), rhythm, capacity_of(rhythm))
    merged.update(load_busy(busy_path))
    return merged


def load_map(name=MAP_NAME, base=BASE):
    url = f"{base}/api/maps/{urllib.request.quote(name)}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.load(resp)["data"]["nodeData"]


def _print(result):
    print(f"📅 {result['start']} 起 {len(result['days'])} 天\n")
    for day in result["days"]:
        head = f"{day['date']}({day['weekday']})"
        if day["busy"]:
            print(f"{head}  🚫 {day['busy']}")
            continue
        used = day["used"]
        note = f"  ⚠️ {day['note']}" if day.get("note") else ""
        print(f"{head}  主線 {used['main']}/{day['cap']['main']}h"
              f" · 雜項 {used['misc']}/{day['cap']['misc']}h"
              f" · 語言 {used['lang']}/{day['cap']['lang']}h{note}")
        for item in day["items"]:
            due = f" ⏰{item['due']}" if item["due"] else ""
            when = f"{item.get('start_at', '  :  ')}–{item.get('end_at', '  :  ')}"
            print(f"    {when} [{TRACK_NAME[item['track']]}] {item['pri'] or '--'} "
                  f"{item['topic']} ({item['hours_today']}h){due}  «{item['domain']}»")
        if not day["items"]:
            print("    (空)")
    for title, key, limit in (
        ("⛔ 趕不上死線(要現在決定砍掉還是延)", "late", None),
        ("📍 要你自己挑日子(有地點/情境限制)", "manual", None),
        ("⏸️ 卡在別人身上(不佔你的時間)", "blocked", None),
        ("❓ 沒填「要花多久」(先當 2h 算)", "no_effort", None),
        ("📦 這週輪不到(沒死線、或死線在這幾天之後)", "backlog", 8),
    ):
        rows = result[key]
        if not rows:
            continue
        print(f"\n{title} — {len(rows)} 件")
        for row in rows[: limit or len(rows)]:
            extra = f" 還差 {row['left']}h" if "left" in row else ""
            win = f" 📍{row['window']}" if row.get("window") else ""
            due = f" ⏰{row['due']}" if row["due"] else ""
            print(f"  {row['pri'] or '--'} {row['topic']}{due}{extra}{win}  «{row['domain']}»")
        if limit and len(rows) > limit:
            print(f"  …還有 {len(rows) - limit} 件")


def main(argv=None):
    ap = argparse.ArgumentParser(description="從心智圖排出這一週的行程")
    ap.add_argument("--start", default="", help="起始日 YYYY-MM-DD(預設今天)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--busy", action="append", default=[],
                    help=f"整天排不了事:YYYY-MM-DD=原因,可重複(預設另外讀 {BUSY_PATH})")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args(argv)

    start = date.fromisoformat(args.start) if args.start else datetime.now().astimezone().date()
    rhythm = load_rhythm()
    busy = merged_busy(rhythm=rhythm)
    for item in args.busy:
        day, _, why = item.partition("=")
        busy[day] = why or "整天有事"
    try:
        root = load_map(base=args.base)
    except OSError as exc:
        print(f"✘ 讀不到心智圖({args.base}):{exc}", file=sys.stderr)
        return 1
    result = plan(collect_tasks(root), start, args.days, busy, rhythm=rhythm)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
