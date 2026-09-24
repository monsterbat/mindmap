"""Google 行事曆 → 行程表的單向連結(2026-08-22 定案)。

使用者的需求是:「我 Google 行事曆有什麼活動的話,他也可以卡住我的行程表,
讓我自己知道那邊有事情我不應該去安排。」

這裡守三件會造成實害的事:
① 整天事件的 `end.date` **不含當天** —— 這件 2026-08-07 已經出過一次問題
   (一筆 8/1–8/9 的整天事件被讀成待到 8/8),那次是人手動減錯,所以現在交給程式減。
② 有時間的事件要從**撞到的那一格**扣時數,⛔ 不能整天砍掉。
③ 手寫的 `整天沒空.json` 要贏過行事曆算出來的 —— 那是使用者明講的,行事曆只是推測。
"""

import json

import cal_cache
import plan_week

RHYTHM = [
    {"track": "main", "start": "09:00", "end": "13:00"},
    {"track": "misc", "start": "14:00", "end": "15:30"},
    {"track": "lang", "start": "19:00", "end": "23:00"},
]
CAP = plan_week.capacity_of(RHYTHM)


def test_有時間的事件只扣撞到的那一格():
    busy = plan_week.calendar_busy(
        [{"date": "2026-08-25", "start": "10:00", "end": "12:00", "title": "看牙醫"}],
        RHYTHM, CAP)
    entry = busy["2026-08-25"]
    assert entry["cap"]["main"] == 2.0   # 4h 撞掉 2h
    assert entry["cap"]["misc"] == CAP["misc"]
    assert entry["cap"]["lang"] == CAP["lang"]
    assert "看牙醫" in entry["why"]


def test_沒撞到時段的事件不扣時數但要看得到():
    busy = plan_week.calendar_busy(
        [{"date": "2026-08-25", "start": "16:00", "end": "17:00", "title": "剪頭髮"}],
        RHYTHM, CAP)
    assert busy["2026-08-25"]["cap"] == CAP
    assert "剪頭髮" in busy["2026-08-25"]["why"]


def test_整天的事件當成整天沒空():
    busy = plan_week.calendar_busy(
        [{"date": "2026-10-24", "allDay": True, "title": "出差 Day1"}], RHYTHM, CAP)
    # 字串 = 整天不排事情(day_capacity 的第一種寫法)
    assert busy["2026-10-24"] == "出差 Day1"
    hours, why, _ = plan_week.day_capacity("2026-10-24", busy, CAP)
    assert not any(hours.values())
    assert why == "出差 Day1"


def test_不擋的事件看得到但不吃時間():
    """⚠️ 這條是 2026-08-22 真的抓下來才發現的:Main 上有一筆橫跨 8/25–9/9 的整天事件,
    是使用者自己標成「顯示為有空」的。照「整天=整天沒空」會一口氣清掉十六天。"""
    busy = plan_week.calendar_busy([
        {"date": "2026-08-31", "allDay": True, "title": "報名截止", "blocks": False},
        {"date": "2026-08-26", "start": "10:00", "end": "12:00", "title": "在外地但有空",
         "blocks": False},
    ], RHYTHM, CAP)
    assert busy["2026-08-31"]["cap"] == CAP          # ⛔ 不准把提醒當成整天沒空
    assert "報名截止" in busy["2026-08-31"]["why"]       # 但使用者要看得到
    assert busy["2026-08-26"]["cap"] == CAP


def test_出遊本的整天事件才真的整天沒空():
    events, _ = cal_cache.normalize([
        {"allDay": True, "startDate": "2026-10-24", "endDate": "2026-10-25",
         "title": "出差", "cal": "Travel"},
        {"allDay": True, "startDate": "2026-08-31", "endDate": "2026-09-01",
         "title": "報名截止", "cal": "Main"},
    ])
    blocks = {e["title"]: e["blocks"] for e in events}
    assert blocks == {"出差": True, "報名截止": False}


def test_標成顯示為有空的一律不擋():
    events, _ = cal_cache.normalize([
        {"allDay": True, "startDate": "2026-08-25", "endDate": "2026-09-10",
         "title": "出差", "cal": "Main", "free": True},
        {"date": "2026-08-24", "start": "20:00", "end": "21:00", "title": "抽選截止",
         "cal": "Main", "free": True},
    ])
    assert all(e["blocks"] is False for e in events)


def test_跨午夜的事件只算到今天結束():
    busy = plan_week.calendar_busy(
        [{"date": "2026-08-25", "start": "22:00", "end": "02:00", "title": "夜衝"}],
        RHYTHM, CAP)
    # 19:00–23:00 的語言格被吃掉 1 小時,⛔ 不是整天砍掉、也⛔ 不是負數
    assert busy["2026-08-25"]["cap"]["lang"] == 3.0


def test_手寫的整天沒空贏過行事曆(tmp_path):
    cal = tmp_path / "行事曆快取.json"
    cal.write_text(json.dumps({"events": [
        {"date": "2026-08-25", "start": "10:00", "end": "12:00", "title": "看牙醫"}]}),
        encoding="utf-8")
    busy_file = tmp_path / "整天沒空.json"
    busy_file.write_text(json.dumps({"2026-08-25": "那天要出門"}), encoding="utf-8")
    merged = plan_week.merged_busy(busy_file, cal, RHYTHM)
    assert merged["2026-08-25"] == "那天要出門"


def test_讀不到快取不會讓排程掛掉(tmp_path):
    assert plan_week.load_calendar(tmp_path / "沒有這個檔.json") == []
    bad = tmp_path / "壞掉.json"
    bad.write_text("{這不是 JSON", encoding="utf-8")
    assert plan_week.load_calendar(bad) == []


def test_整天事件的結束日要減一天再展開():
    """⚠️ Google 的 end.date 不含當天。10/24–10/29 其實是待到 10/28。"""
    events, skipped = cal_cache.normalize([
        {"allDay": True, "startDate": "2026-10-24", "endDate": "2026-10-29",
         "title": "出差", "cal": "Travel"}])
    assert not skipped
    assert [e["date"] for e in events] == [
        "2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28"]
    assert all(e["allDay"] for e in events)


def test_讀不懂的那一筆跳過但要回報():
    events, skipped = cal_cache.normalize([
        {"date": "亂寫", "start": "10:00", "end": "11:00", "title": "壞的"},
        {"date": "2026-08-25", "start": "10:00", "end": "11:00", "title": "好的"}])
    assert [e["title"] for e in events] == ["好的"]
    assert skipped  # ⛔ 不准安靜丟掉


def test_ISO_時間也吃得下來():
    events, _ = cal_cache.normalize([
        {"start": "2026-08-25T14:00:00+08:00", "end": "2026-08-25T15:30:00+08:00",
         "title": "會議"}])
    assert events == [{"date": "2026-08-25", "start": "14:00", "end": "15:30",
                       "title": "會議", "cal": "", "blocks": True}]


def test_快取過期要講出來(tmp_path):
    path = tmp_path / "行事曆快取.json"
    assert cal_cache.check(path)[0] is False          # 還沒抓過
    cal_cache.write([], path)
    assert cal_cache.check(path)[0] is True           # 剛寫的就是今天
    data = json.loads(path.read_text(encoding="utf-8"))
    data["抓取時間"] = "2020-01-01T08:00:00+08:00"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    fresh, msg = cal_cache.check(path)
    assert fresh is False and "2020-01-01" in msg


def test_排今天的每一天都要帶行事曆事件(tmp_path, monkeypatch):
    import main
    maps = tmp_path / "mindmaps"
    (maps / "排程設定").mkdir(parents=True)
    (maps / "全局總覽圖.json").write_text(
        json.dumps({"nodeData": {"id": "root", "topic": "圖", "children": []}}),
        encoding="utf-8")
    (maps / "排程設定" / "行事曆快取.json").write_text(json.dumps({"events": [
        {"date": "2026-08-25", "start": "14:00", "end": "15:30", "title": "看牙醫"}]}),
        encoding="utf-8")
    monkeypatch.setattr(main, "MAPS_DIR", maps)
    monkeypatch.setattr(main, "CAL_PATH", maps / "排程設定" / "行事曆快取.json")
    monkeypatch.setattr(main, "DAY_DIR", maps / "排程設定" / "每日行程")
    monkeypatch.setattr(main, "DAILY_TPL_PATH", maps / "排程設定" / "日常區塊.json")
    view = main.day_view("date=2026-08-25&days=2")
    assert [e["title"] for e in view["days"][0]["events"]] == ["看牙醫"]
    assert view["days"][1]["events"] == []


def test_網頁要把行事曆畫成不能拖的格子():
    """⛔ 這幾個記號掉了 = 那些格子變成可以拖的任務,使用者會拖然後以為改到了 Google。"""
    js = (plan_week.Path(__file__).resolve().parent.parent / "static" / "js" / "day.js").read_text(
        encoding="utf-8")
    assert "function calBlock" in js
    assert "box.draggable = false" in js
    assert "day.events" in js
