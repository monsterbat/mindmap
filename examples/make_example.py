#!/usr/bin/env python3
"""產生一份範例心智圖,讓任何人 clone 下來就能看到四頁都是活的。

為什麼需要它:四個頁面裡有三頁(排行程、任務板、待辦事項)在「沒有任何圖」的時候
會回 404 —— 心智圖頁自己會顯示「按 ➕ 新圖開始」,另外三頁則是直接壞的。
所以這份範例不是加分項,是跑得起來的前提。

為什麼用產生器而不是直接放一份 JSON:排程相關的欄位(排進行程的時段、死線、
最早可以開始的日期)都是日期。寫死的日期過幾個月就全部變成過去式,
畫面上看起來像一份荒廢的圖。這支照「跑的當下」往後算,產出來永遠是活的。

用法:
    python3 examples/make_example.py                 # 寫到 examples/
    python3 examples/make_example.py --out <資料夾>   # 寫到別的地方
"""
import argparse
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = datetime.datetime.now().astimezone().date()


def day(n):
    """今天往後第 n 天,回 YYYY-MM-DD。"""
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def slot(n, hour, minutes=60):
    """排進行程的一塊:今天往後第 n 天的某個鐘點。"""
    return {"uid": f"ex{n}{hour}", "at": f"{day(n)}T{hour:02d}:00", "min": minutes}


def node(nid, topic, **kw):
    n = {"id": nid, "topic": topic}
    detail = {k: kw.pop(k) for k in list(kw) if k in DETAIL_KEYS}
    n.update(kw)
    if detail:
        n["detail"] = detail
    return n


DETAIL_KEYS = {"explain", "due", "hardDue", "earliest", "planned", "repeat",
               "until", "owner", "duty", "dutyMin", "effort", "doneOn"}


def build():
    """四個領域、31 顆節點。每一種欄位至少示範一顆。"""
    work = node("dom-work", "💼 Work", kind="項目", expanded=True, children=[
        node("w-1", "⏳ Draft the Q4 proposal", todo=True, tags=["P1"],
             explain="Important and urgent: the client review is a fixed external date, "
                     "so this one cannot be pushed. Everything else in this domain waits for it.",
             due=day(3), hardDue=True,
             planned=[slot(1, 9, 120), slot(2, 9)]),
        node("w-2", "🔜 Rewrite the onboarding doc", todo=True, tags=["P2"],
             explain="Important, not urgent. No deadline on purpose: a wished-for date would "
                     "show up as a red overdue line and train the reader to ignore red.",
             planned=[slot(4, 10)]),
        node("w-3", "⏸️ Renew the team licence", todo=True, tags=["P3"],
             explain="Waiting on someone else. It leaves the todo list and lives in the "
                     "'waiting' tab until the condition is met.",
             until="finance approves the budget"),
        node("w-4", "✅ Ship the release notes", todo=True, tags=["P2"],
             explain="Done items stay visible for seven days, then a nightly job files them "
                     "into the completion log and removes them from the map.",
             doneOn=day(-2)),
    ])

    study = node("dom-study", "📚 Study", kind="項目", expanded=True, children=[
        node("s-1", "⏳ Finish chapter 4 exercises", todo=True, tags=["P2"],
             explain="Sits in the evening capacity block, which the weekly planner keeps "
                     "separate from daytime work.",
             planned=[slot(1, 19), slot(3, 19)]),
        node("s-2", "🔁 Weekly review", todo=True, tags=["P3"],
             explain="Repeating item. Ticking it does not archive it; it rolls forward to "
                     "the next period, so the reminder never disappears.",
             repeat="每週"),
        node("s-duty", "♾️ Keep reading, 30 min a day", kind="職責",
             explain="A standing duty, not a task. Ticking a thing that is never finished is "
                     "meaningless, so these are drawn as reusable blocks instead of checkboxes.",
             duty=True, dutyMin=30),
    ])

    home = node("dom-home", "🏠 Home", kind="項目", expanded=True, children=[
        node("h-1", "⏳ Book the annual health check", todo=True, tags=["P2"],
             explain="Cannot start before the new policy year opens, so it carries an "
                     "earliest-start date rather than a deadline.",
             earliest=day(14)),
        node("h-2", "🔜 Replace the water filter", todo=True, tags=["P4"],
             explain="Neither important nor urgent. Kept on the map so it is not forgotten, "
                     "but it never competes for a planned slot.",
             planned=[slot(6, 14)]),
    ])

    side = node("dom-side", "🧪 Side Project", kind="項目", expanded=True, children=[
        node("sp-1", "⏳ Wire up the settings screen", todo=True, tags=["P2"],
             explain="This node is linked to a project folder, so its own TODO.md is read "
                     "live and shown in the detail panel. See examples/demo-project.",
             source="examples/demo-project"),
        node("sp-2", "🎯 Reach a usable first version", kind="項目",
             explain="A milestone, not a task: it is the acceptance condition that the "
                     "items under it are measured against."),
        node("sp-infra", "🏗️ Local dev server", kind="infra",
             explain="Infrastructure nodes describe how the system is put together, so the "
                     "map answers 'what does my setup look like' as well as 'what is left to do'.",
             owner="ai"),
        node("sp-sop", "📐 Release checklist", kind="sop",
             hyperLink="examples/demo-project/TODO.md",
             explain="Rules and procedures get their own node type, with a link to the "
                     "document that is the real source of truth."),
    ])

    stage = node("stage", "🎯 What I am pushing on right now", kind="項目", expanded=True, children=[
        node("stage-short", "Short term: ship the first version", kind="項目",
             explain="Acceptance: a stranger can clone the repo and see all four views work."),
        node("stage-mid", "Mid term: use it daily for a month", kind="項目",
             explain="Acceptance: thirty consecutive days with at least one planned block."),
        node("stage-long", "Long term: stop keeping a second list", kind="項目",
             explain="Acceptance: no task exists in a notes file that is not on this map."),
    ])

    inbox = node("inbox", "📥 Inbox", kind="項目", expanded=True, children=[
        node("in-1", "⏳ Look into the export format", todo=True, tags=["P3"],
             explain="還沒寫為什麼要做"),
    ])

    root = node("root", "🌐 Example overview", expanded=True,
                children=[stage, work, study, home, side, inbox])

    arrows = [
        {"id": "ex-arrow-1", "label": "feeds into", "from": "w-2", "to": "sp-1",
         "delta1": {"x": 240, "y": 40}, "delta2": {"x": -180, "y": -60}},
        {"id": "ex-arrow-2", "label": "blocks", "from": "w-3", "to": "w-1",
         "delta1": {"x": 200, "y": -30}, "delta2": {"x": -200, "y": 30}},
    ]
    return {"nodeData": root, "arrows": arrows, "summaries": [],
            "direction": 2, "theme": None, "compact": False}


SCHEDULE = {
    "作息.json": {
        "_readme": "How many hours a day exist. Capacity comes from here, nowhere else.",
        "blocks": [
            {"name": "main", "from": "09:00", "to": "13:00"},
            {"name": "misc", "from": "14:00", "to": "15:30"},
            {"name": "lang", "from": "19:00", "to": "23:00"},
        ],
    },
    "日常區塊.json": {
        "_readme": "Reusable blocks you drag onto a day: meals, commute, exercise.",
        "templates": [
            {"name": "Lunch", "min": 60},
            {"name": "Exercise", "min": 45},
            {"name": "Commute", "min": 30},
        ],
    },
    "整天沒空.json": {
        "_readme": "Hand-written days off. This always wins over anything inferred "
                   "from a calendar. Use cap to shrink a day instead of clearing it.",
        "days": {},
    },
    "行事曆快取.json": {
        "_readme": "Written by the calendar fetcher. Events only block time; "
                   "they never become todo items.",
        "fetched": None,
        "events": [],
    },
}

DEMO_TODO = """# Demo Project

一個掛在心智圖節點上的專案範例 —— 節點填了 `source` 之後,
心智圖的詳情面板就會**即時**讀這個檔,把下面的待辦列出來。

A project linked from a mind map node. Filling in `source` on a node makes the
detail panel read this file live and list the items below.

## 待辦 Todo

- [ ] Wire up the settings screen
- [ ] ⏳ Waiting on the API key from the provider
- [x] Sketch the data model

<!-- mm:begin -->
<!-- 這一區是心智圖產生的:只准打勾,⛔ 不要改文字或新增。
     This block is generated from the map: tick boxes only, do not edit the text. -->
<!-- mm:end -->
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()

    maps_dir = a.out
    os.makedirs(maps_dir, exist_ok=True)
    path = os.path.join(maps_dir, "Example.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build(), f, ensure_ascii=False, indent=1)
    print(f"✅ {path}")

    sched = os.path.join(maps_dir, "排程設定")
    os.makedirs(sched, exist_ok=True)
    for name, data in SCHEDULE.items():
        with open(os.path.join(sched, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"✅ {os.path.join(sched, name)}")

    demo = os.path.join(HERE, "demo-project")
    os.makedirs(demo, exist_ok=True)
    with open(os.path.join(demo, "TODO.md"), "w", encoding="utf-8") as f:
        f.write(DEMO_TODO)
    print(f"✅ {os.path.join(demo, 'TODO.md')}")

    n = len(json.dumps(build()["nodeData"]).split('"id"')) - 1
    print(f"\n{n} 顆節點,日期以 {TODAY} 為基準往後算。")


if __name__ == "__main__":
    main()
