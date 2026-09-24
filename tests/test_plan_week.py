"""plan_week.py 的把關測試。

排程是要拿來過日子的東西,錯了不是「醜」而是「他今天做錯事」。
所以測的是那四條硬規則會不會失效,以及「排不下」有沒有老實講出來。
"""

from datetime import date

import plan_week as pw

START = date(2026, 8, 8)


def task(topic, **kw):
    base = {
        "id": topic, "topic": topic, "status": "⏳", "pri": "P2", "tags": [],
        "due": "", "effort": "2h", "hours": 2.0, "guessed_hours": False,
        "window": "", "earliest": "", "domain": "💰 Finance", "path": "",
    }
    base.update(kw)
    return base


def days_of(result, topic):
    return [d["date"] for d in result["days"]
            for item in d["items"] if item["topic"] == topic]


def test_死線之前排完_不會排到死線之後():
    r = pw.plan([task("A", due="2026-08-10", hours=2.0)], START, 7)
    assert days_of(r, "A") and max(days_of(r, "A")) <= "2026-08-10"


def test_MUST_排不進死線就進趕不上清單_不硬塞():
    """⛔ 默默延期是最糟的結果 —— 他會以為排進去了。"""
    r = pw.plan([task("大工程", due="2026-08-08", hours=12.0)], START, 7)
    assert not days_of(r, "大工程") or r["late"], "12h 的事一天做不完,要講出來"
    assert [t["topic"] for t in r["late"]] == ["大工程"]
    assert r["late"][0]["left"] > 0


def test_死線在這幾天之後的不算趕不上_只是輪不到():
    """否則整張表會被下個月的事塞滿假警報,真正的紅字就被淹掉了。"""
    r = pw.plan([task("下個月的事", due="2026-09-17", hours=50.0)], START, 7)
    assert not r["late"]
    assert [t["topic"] for t in r["backlog"]] == ["下個月的事"]


def test_超過一天容量的事會自動切開排到連續幾天():
    r = pw.plan([task("八小時", due="2026-08-12", hours=8.0)], START, 7)
    assert len(days_of(r, "八小時")) == 2, "主線一天 4h,8h 要跨兩天"
    assert not r["late"]


def test_MUST_雜項不可分割():
    """把一件 1 小時的事切成兩天各半小時毫無意義,只會讓表變得沒人看得懂。"""
    small = [task(f"零碎{i}", hours=1.0, effort="1h") for i in range(3)]
    r = pw.plan(small, START, 7)
    for i in range(3):
        assert len(days_of(r, f"零碎{i}")) == 1


def test_標了一起做的整批塞得下就排同一天():
    batch = [task(f"不動產{i}", due="2026-08-14", hours=0.5, effort="1h",
                  tags=[pw.BATCH_TAG]) for i in range(3)]
    r = pw.plan(batch, START, 7)
    landed = {days_of(r, f"不動產{i}")[0] for i in range(3)}
    assert len(landed) == 1, f"塞得下卻被拆到不同天:{landed}"


def test_一起做整批塞不進一天就排連續的日子_不散開():
    """那一批五條共 9h,一天放不下。重點是「連著處理完」,不是硬擠同一天。"""
    batch = [task(f"不動產{i}", due="2026-08-14", hours=1.0, effort="1h",
                  tags=[pw.BATCH_TAG]) for i in range(4)]
    r = pw.plan(batch, START, 7)
    landed = sorted({days_of(r, f"不動產{i}")[0] for i in range(4)})
    span = (date.fromisoformat(landed[-1]) - date.fromisoformat(landed[0])).days
    assert span == len(landed) - 1, f"「一起做」散開了:{landed}"


def test_主線一天以一個領域為主():
    a = task("主線甲", hours=4.0, effort="4h", domain="💰 Finance")
    b = task("主線乙", hours=4.0, effort="4h", domain="💼 Work")
    r = pw.plan([a, b], START, 7)
    assert days_of(r, "主線甲") != days_of(r, "主線乙")


def test_語言走自己的格子_不跟主線搶時間():
    main = task("主線", hours=4.0, effort="4h")
    lang = task("語言", hours=4.0, effort="4h", domain=pw.LANG_DOMAIN)
    r = pw.plan([main, lang], START, 7)
    assert days_of(r, "主線")[0] == days_of(r, "語言")[0] == "2026-08-08"


def test_整天有事的日子不排任何東西():
    r = pw.plan([task("X", hours=4.0, effort="4h")], START, 7,
                busy={"2026-08-08": "演唱會"})
    assert r["days"][0]["items"] == []
    assert r["days"][0]["busy"] == "演唱會"
    assert days_of(r, "X") == ["2026-08-09"]


def test_有地點限制的交回給使用者自己挑日子_不亂排():
    r = pw.plan([task("當面談的事", window="人在外地", hours=2.0)], START, 7)
    assert not days_of(r, "當面談的事")
    assert [t["topic"] for t in r["manual"]] == ["當面談的事"]


def test_卡在別人身上的不佔使用者的時間():
    r = pw.plan([task("等銀行回信", status="⏸️")], START, 7)
    assert not days_of(r, "等銀行回信")
    assert [t["topic"] for t in r["blocked"]] == ["等銀行回信"]


def test_完成的不再排():
    r = pw.plan([task("做完了", status="✅")], START, 7)
    assert r["totals"]["scheduled"] == 0


def test_沒填要花多久的會被列出來提醒補():
    r = pw.plan([task("沒填", effort="", hours=pw.DEFAULT_HOURS, guessed_hours=True)],
                START, 7)
    assert [t["topic"] for t in r["no_effort"]] == ["沒填"]
    assert days_of(r, "沒填"), "沒填不代表不排,只是用假設值先排"


def test_死線近的排在前面_同死線再比等級():
    early_p4 = task("死線近但不重要", due="2026-08-09", pri="P4", hours=4.0, effort="4h")
    later_p1 = task("重要但死線遠", due="2026-08-14", pri="P1", hours=4.0, effort="4h")
    r = pw.plan([later_p1, early_p4], START, 7)
    assert days_of(r, "死線近但不重要")[0] < days_of(r, "重要但死線遠")[0]


def test_collect_tasks_帶得出領域與路徑():
    root = {"topic": "🌐 根", "children": [
        {"topic": "💰 Finance", "children": [
            {"topic": "資產盤點", "children": [
                {"id": "n1", "topic": "⏳ 查稅", "todo": True, "tags": ["P2", "一起做"],
                 "detail": {"due": "2026-08-14", "effort": "1h"}}]}]}]}
    got = pw.collect_tasks(root)[0]
    assert got["domain"] == "💰 Finance"
    assert got["path"] == "💰 Finance › 資產盤點"
    assert got["topic"] == "查稅" and got["hours"] == 1.0
    assert got["pri"] == "P2" and got["tags"] == ["一起做"]


# ── 那天沒那麼多時間(2026-08-11 加:在那之前只有「整天/整天不」兩種) ────────


def test_MUST_還在上班的日子只排得下縮水後的時數():
    """⛔ 這條失效 = 排出一張他上班日做不到的表,然後整張表就沒人信了。"""
    busy = {"2026-08-08": {"why": "上班", "cap": {"main": 0, "misc": 1.0, "lang": 2.0}}}
    r = pw.plan([task("要專注的", hours=4.0), task("零碎", hours=1.0)],
                START, 3, busy=busy)
    day0 = r["days"][0]
    assert day0["cap"] == {"main": 0.0, "misc": 1.0, "lang": 2.0}
    assert day0["busy"] == "", "只是縮水,不是整天沒空"
    assert day0["note"] == "上班"
    assert "要專注的" not in [i["topic"] for i in day0["items"]], "主線 0h 排不下"
    assert days_of(r, "要專注的")[0] > "2026-08-08"


def test_沒寫到的時段照原本的容量():
    busy = {"2026-08-08": {"why": "下午出門", "cap": {"main": 2.0}}}
    r = pw.plan([task("零碎", hours=1.0)], START, 2, busy=busy)
    assert r["days"][0]["cap"] == {"main": 2.0, "misc": 1.5, "lang": 4.0}


def test_容量全部歸零等同整天沒空():
    busy = {"2026-08-08": {"why": "演唱會", "cap": {"main": 0, "misc": 0, "lang": 0}}}
    r = pw.plan([task("A", hours=1.0)], START, 2, busy=busy)
    assert r["days"][0]["busy"] == "演唱會"
    assert not r["days"][0]["items"]


def test_整天沒空維持舊的字串寫法():
    """舊格式不能壞掉 —— 檔案裡還有既有的日子。"""
    r = pw.plan([task("A", hours=1.0)], START, 2, busy={"2026-08-08": "演唱會"})
    assert r["days"][0]["busy"] == "演唱會"
    assert r["days"][0]["cap"] == {"main": 0.0, "misc": 0.0, "lang": 0.0}


def test_load_busy_兩種寫法都讀得進來(tmp_path):
    p = tmp_path / "整天沒空.json"
    p.write_text('{"2026-08-09":"演唱會","2026-08-11":{"why":"上班","cap":{"main":0}}}',
                 encoding="utf-8")
    got = pw.load_busy(p)
    assert got["2026-08-09"] == "演唱會"
    assert got["2026-08-11"]["cap"] == {"main": 0}


def test_MUST_一起做的一批看整批時數決定放哪一格():
    """⛔ 這條失效 = 同一批那三件各 1h 被丟進雜項格(一天 1.5h),
    同一件事被拆成三天做,而主線 4h 整天空著。"""
    batch = [task(f"批次{i}", hours=1.0, effort="1h", tags=["一起做"],
                  domain="💼 Work") for i in range(3)]
    r = pw.plan(batch, START, 7)
    day0 = r["days"][0]
    assert {i["topic"] for i in day0["items"]} == {"批次0", "批次1", "批次2"}
    assert all(i["track"] == "main" for i in day0["items"]), "整批 3h 應該進主線"
    assert day0["used"]["main"] == 3.0


def test_沒標一起做的零碎事還是雜項():
    r = pw.plan([task("零碎", hours=1.0, effort="1h")], START, 2)
    assert r["days"][0]["items"][0]["track"] == "misc"


# ── earliest:不能比這天早做(2026-08-11 加) ──────────────────────────


def test_MUST_不能比_earliest_早排():
    """⛔ 失效的後果是實際的:排程曾把「8/13 當天去機關窗口辦手續」排到 8/12
    (那天合約還沒到期)、把「款項入帳對帳」排到錢還沒進來的日子。"""
    r = pw.plan([task("去就業服務站", hours=2.0, due="2026-08-13",
                      earliest="2026-08-13")], START, 7)
    assert days_of(r, "去就業服務站") == ["2026-08-13"]


def test_earliest_晚於死線就進趕不上_不會偷偷排():
    r = pw.plan([task("矛盾", hours=1.0, due="2026-08-10",
                      earliest="2026-08-15")], START, 7)
    assert not days_of(r, "矛盾")
    assert [t["topic"] for t in r["late"]] == ["矛盾"]


def test_一起做的一批看最晚的_earliest():
    batch = [task("先決", hours=1.0, tags=["一起做"], earliest="2026-08-12"),
             task("跟著", hours=1.0, tags=["一起做"])]
    r = pw.plan(batch, START, 7)
    assert min(days_of(r, "跟著") + days_of(r, "先決")) >= "2026-08-12"


# ── 確切的鐘點(2026-08-11 加) ─────────────────────────────────────


RHYTHM = [
    {"track": "main", "start": "09:00", "end": "13:00"},
    {"track": "misc", "start": "14:00", "end": "15:30"},
    {"track": "lang", "start": "19:00", "end": "23:00"},
]


def times_of(result, topic):
    return [(i.get("start_at"), i.get("end_at"))
            for d in result["days"] for i in d["items"] if i["topic"] == topic]


def test_MUST_每件事都落在確切的鐘點上():
    """使用者的需求:「我希望可以為自己排一個確切的時間軸…現在這個感覺就不是。」
    只講「今天這幾件」沒辦法拿來過日子,也判斷不了「現在 16:30 還剩多少」。"""
    r = pw.plan([task("A", hours=2.0), task("B", hours=2.0)], START, 1, rhythm=RHYTHM)
    assert times_of(r, "A") == [("09:00", "11:00")]
    assert times_of(r, "B") == [("11:00", "13:00")]


def test_三個時段互不重疊_各自從自己的起點開始():
    r = pw.plan([task("主線事", hours=1.5),
                 task("零碎", hours=1.0, effort="1h"),
                 task("語言", hours=2.0, domain="Language")], START, 1, rhythm=RHYTHM)
    assert times_of(r, "主線事") == [("09:00", "10:30")]
    assert times_of(r, "零碎") == [("14:00", "15:00")]
    assert times_of(r, "語言") == [("19:00", "21:00")]


def test_容量是從作息算出來的_不另外寫死():
    """⛔ 兩個地方各寫一份容量 = 改了作息但容量沒動,表就是騙人的。"""
    assert pw.capacity_of(RHYTHM) == {"main": 4.0, "misc": 1.5, "lang": 4.0}
    short = [{"track": "main", "start": "10:00", "end": "12:00"}]
    r = pw.plan([task("A", hours=4.0)], START, 1, rhythm=short)
    assert r["days"][0]["cap"]["main"] == 2.0
    assert times_of(r, "A") == [("10:00", "12:00")]  # 只放得下 2h,剩下的跨天


def test_那天容量被砍時鐘點從時段開頭算():
    busy = {"2026-08-08": {"why": "上班", "cap": {"main": 2.0}}}
    r = pw.plan([task("A", hours=2.0)], START, 1, busy=busy, rhythm=RHYTHM)
    assert times_of(r, "A") == [("09:00", "11:00")]


def test_load_rhythm_壞掉就用預設_不讓排程掛掉(tmp_path):
    bad = tmp_path / "作息.json"
    bad.write_text("{ 這不是 json", encoding="utf-8")
    assert pw.load_rhythm(bad) == pw.DEFAULT_RHYTHM


def test_MUST_使用者自己排好的時段_程式不准再排一次():
    """使用者在 /day 把 2h 的事整件拖到 8/12,行程表就不該再挑一天塞它。
    ⛔ 兩個視圖各講各的,他不知道該信哪一個(2026-08-13 盤點抓到的矛盾)。"""
    t = task("手排的事", hours=2.0,
             planned=[{"uid": "s1", "at": "2026-08-12T09:00", "min": 120}])
    r = pw.plan([t], START, 7)
    on = [(d["date"], item) for d in r["days"] for item in d["items"]
          if item["topic"] == "手排的事"]
    assert [d for d, _ in on] == ["2026-08-12"], "只該出現在他排的那天"
    assert on[0][1]["by_sc"] is True, "要標出來是他排的,不是程式算的"
    assert not r["late"] and not r["backlog"], "已經排好了,不該再喊排不下"


def test_只排了一半_剩下的還是要幫他排():
    """4h 的事他只排了 1h → 剩 3h 仍要進行程表(⛔ 不准當成整件做完了)。"""
    t = task("半排的事", hours=4.0, effort="4h",
             planned=[{"uid": "s1", "at": "2026-08-12T09:00", "min": 60}])
    r = pw.plan([t], START, 7)
    hrs = {}
    for d in r["days"]:
        for item in d["items"]:
            if item["topic"] == "半排的事":
                hrs[d["date"]] = hrs.get(d["date"], 0) + item["hours_today"]
    assert hrs.get("2026-08-12") == 1.0
    assert round(sum(hrs.values()), 2) == 4.0, "手排 1h + 程式排 3h,總量要對得起來"


def test_手排會佔掉那天的容量():
    """他把 4h 拖進星期一,程式就不能再往星期一塞滿 —— 那天只剩得下的量。"""
    big = task("他排的", hours=4.0, effort="4h",
               planned=[{"uid": "s1", "at": "2026-08-10T09:00", "min": 240}])
    other = task("程式排的", hours=4.0, effort="4h", pri="P1")
    r = pw.plan([big, other], START, 7)
    mon = [item["hours_today"] for d in r["days"] if d["date"] == "2026-08-10"
           for item in d["items"] if item["track"] == "main"]
    assert sum(mon) <= 4.0, f"主線一天 4h,手排 4h 之後不該再塞:{mon}"
