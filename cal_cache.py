#!/usr/bin/env python3
"""cal_cache.py — 把 Google 行事曆抓下來的事件寫成排程看得懂的快取。

使用者的需求(2026-08-22):「我蠻希望我 Google 行事曆有什麼活動的話,他也可以卡住我的行程表。」

**只准單向**:行事曆 → 我們的行程表。⛔ 我們的待辦永遠不寫回 Google ——
兩邊互相寫,同一件事就會有兩份,改了一邊不知道另一邊。

## 誰在跑這支

自動化流程(tmux 裡的 Claude Code)每天產生每日排程報告時用行事曆連接器抓未來 14 天,
把事件丟給這支寫檔。⛔ 排程程式自己抓不到:它被 launchd 派出時
沒有 Google 的長期授權,而快取檔就是那條連結。

## 怎麼餵

    python3 cal_cache.py --write <<'JSON'
    [
      {"date": "2026-08-25", "start": "14:00", "end": "15:30", "title": "開會", "cal": "Main"},
      {"allDay": true, "startDate": "2026-10-24", "endDate": "2026-10-29",
       "title": "出遊", "cal": "Travel"}
    ]
    JSON

⚠️ **整天的事件直接照抄 Google 給的 `start.date` / `end.date`** —— `endDate` 不含當天,
這支會自己減一天展開成一天一筆。⛔ 不要自己先減:2026-08-07 就是有人手動減錯,
把「某趟行程 8/1–8/9」讀成人待到 8/8,少算一整天。**這種算術交給程式,不要交給記憶。**

## 哪幾本要抓

Main(對人的行程)與 Travel(出遊細排)。⛔ Focus(個人自由時間,2026-08-31 前
叫 Learning、id 沒變)不抓 —— 晚上 19:00–23:00 本來就是語言格,再卡一次等於
同一段時間被扣兩遍。

⚠️ **跑這支的流程要先用 ToolSearch 把行事曆工具叫出來**(`select:mcp__claude_ai_Google_Calendar__list_events`)。
沒這一步呼叫會失敗,而失敗長得像「連不上」—— 這支寫好之後空轉了 10 天(2026-08-22〜08-31)
就是因為每日排程報告那份說明沒寫這一句。

## ⚠️ 哪些事件才「真的把時間吃掉」(`blocks`)

**看得到 ≠ 排不了事。** 兩者要分開,不然這個功能會比沒有更糟:

| 事件 | 看得到 | 吃時間 | 為什麼 |
|---|---|---|---|
| 有幾點到幾點的 | ✅ | ✅ | 那段人真的不在 |
| Travel 本的整天事件 | ✅ | ✅ 整天 | 出遊 = 人不在 |
| **Main 本的整天事件** | ✅ | ⛔ **不吃** | Main 的整天事件多半是**提醒**不是缺席 |
| 標成「顯示為有空」的 | ✅ | ⛔ 不吃 | 那是使用者自己按的,使用者說有空就是有空 |

<!-- 由來:2026-08-22 第一次真的抓下來,Main 上有「⏰ 某項報名今日截止」(整天)
     跟一段 8/25–9/9 的長天數行程(整天、使用者自己標成顯示為有空)。照「整天事件=整天沒空」
     會一口氣清掉 8/25–9/9 十六天再加 8/31 —— 那不是排程,那是把使用者的行事曆清空。 -->

要蓋掉判斷 → 手寫 `整天沒空.json`,那份永遠贏(使用者明講的 > 程式推測的)。
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

CAL_PATH = Path(
    os.environ.get("MINDMAP_MAPS_DIR", "~/mindmaps")
).expanduser() / "排程設定" / "行事曆快取.json"

CALENDARS = ("Main", "Travel")  # ⛔ Learning 刻意不抓,理由見檔頭


def _day(text):
    """只取前 10 個字當日期。⚠️ Google 的全日事件回的是 "2026-08-25T00:00:00Z",
    而 `date.fromisoformat` 在 Python 3.10 以前吃不下結尾那個 Z —— 整筆會被當成壞資料跳過。"""
    return date.fromisoformat(str(text)[:10])


def _hhmm(text):
    """接受 "14:00" 或 "2026-08-25T14:00:00+08:00",一律回 HH:MM。"""
    text = str(text)
    if "T" in text:
        text = text.split("T", 1)[1]
    hour, _, rest = text.partition(":")
    return f"{int(hour):02d}:{int(rest[:2]):02d}"


def normalize(raw):
    """把餵進來的事件整成一天一筆的固定格式。壞掉的那一筆跳過,⛔ 不讓整批失敗。"""
    out, skipped = [], []
    for item in raw or []:
        if not isinstance(item, dict):
            skipped.append(str(item)[:40])
            continue
        title = str(item.get("title") or "").strip() or "(沒有標題)"
        cal = str(item.get("cal") or "").strip()
        free = bool(item.get("free"))  # Google 的「顯示為有空」(transparency: transparent)
        try:
            if item.get("allDay") or (not item.get("start") and not item.get("end")):
                first = _day(item.get("startDate") or item["date"])
                last = item.get("endDate")
                # Google 的 end.date **不含當天** → 減一天才是最後一天
                last = _day(last) - timedelta(days=1) if last else first
                last = max(last, first)  # endDate 比 startDate 早 = 資料壞了,當單日
                span = (last - first).days
                # ⛔ Main 本的整天事件不吃時間 —— 那多半是提醒,不是使用者不在(見檔頭那張表)
                blocks = (cal == "Travel") and not free
                for i in range(min(span, 90) + 1):
                    out.append({"date": (first + timedelta(days=i)).isoformat(),
                                "allDay": True, "title": title, "cal": cal, "blocks": blocks})
            else:
                day = _day(item.get("date") or item["start"])
                out.append({"date": day.isoformat(), "start": _hhmm(item["start"]),
                            "end": _hhmm(item["end"]), "title": title, "cal": cal,
                            "blocks": not free})
        except (KeyError, ValueError, TypeError, IndexError):
            skipped.append(f"{title}({item.get('date') or item.get('startDate')})")
    out.sort(key=lambda e: (e["date"], 0 if e.get("allDay") else 1, e.get("start") or ""))
    return out, skipped


def write(events, path=None):
    path = Path(path or CAL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_說明": "Google 行事曆抓下來的副本。⛔ 不要手改 —— 下次抓會整份蓋掉,"
                 "要改去 Google 行事曆改。正本永遠在 Google 那邊。",
        "_誰在寫": "每天的排程跑 cal_cache.py --write 寫的",
        "抓取時間": datetime.now().astimezone().isoformat(timespec="seconds"),
        "來源": list(CALENDARS),
        "events": events,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def check(path=None):
    """快取是不是今天抓的。⚠️ 過期不報錯只回話 —— 但**一定要講**,
    ⛔ 安靜地用昨天的資料排今天,表看起來正常卻是錯的。"""
    path = Path(path or CAL_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "⚠️ 還沒抓過行事曆(沒有快取檔)"
    stamp = str(data.get("抓取時間") or "")[:10]
    today = datetime.now().astimezone().date().isoformat()
    count = len(data.get("events") or [])
    if stamp == today:
        return True, f"✅ 行事曆快取是今天的({count} 筆事件)"
    return False, f"⚠️ 行事曆快取停在 {stamp or '不明'}({count} 筆),今天沒對到行事曆"


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 Google 行事曆事件寫成排程用的快取")
    ap.add_argument("--write", action="store_true", help="從 stdin 讀 JSON 寫檔")
    ap.add_argument("--check", action="store_true", help="看快取是不是今天的")
    ap.add_argument("--path", default="", help="快取檔路徑(預設用正式的)")
    args = ap.parse_args(argv)
    path = args.path or None

    if args.check or not args.write:
        fresh, msg = check(path)
        print(msg)
        return 0 if fresh else 1

    try:
        raw = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(f"✘ 餵進來的不是合法 JSON:{exc}", file=sys.stderr)
        return 2
    if isinstance(raw, dict):
        raw = raw.get("events") or []
    events, skipped = normalize(raw)
    written = write(events, path)
    print(f"✅ 寫好 {len(events)} 筆 → {written}")
    if skipped:
        # ⛔ 讀不懂的不准安靜丟掉:那一筆就是使用者那天真正要出門的事
        print(f"⚠️ 有 {len(skipped)} 筆讀不懂,跳過了:" + "、".join(skipped[:5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
