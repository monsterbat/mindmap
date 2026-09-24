"""mm.py 的把關測試。

這支是「給別條對話的 AI 用的入口」,所以測的重點是**它不會讓外人把圖弄壞**:
不製造新違規、不撞 id、待辦一定帶等級與狀態、寫入一定經過衝突偵測的 API。
"""

import json

import pytest

import mm


@pytest.fixture
def fake_api(monkeypatch):
    """把網路換掉:GET 回一份假圖,PUT 記錄下來。⛔ 測試不准碰正式圖。"""
    state = {"data": {"nodeData": {
        "id": "root", "topic": "圖", "children": [
            {"id": "p", "topic": "某個項目", "children": [
                {"id": "t", "topic": "⏳ 既有待辦", "todo": True, "tags": ["P2"]}]},
        ]}}, "mtime": 111.0, "puts": []}

    def api(path, payload=None):
        if payload is None:
            return {"data": json.loads(json.dumps(state["data"])), "mtime": state["mtime"]}
        state["puts"].append(payload)
        state["data"] = payload["data"]
        return {"name": "x", "mtime": 222.0}

    monkeypatch.setattr(mm, "api", api)
    return state


def test_新增待辦會帶等級與狀態圖示並圈起來(fake_api):
    mm.main(["add-todo", "p", "做一件事", "--pri", "P1", "--why", "因為要"])
    node = fake_api["data"]["nodeData"]["children"][0]["children"][-1]
    assert node["topic"] == "⏳ 做一件事"  # 沒寫圖示會自動補
    assert node["todo"] and node["tags"] == ["P1"]
    assert node["aiEdited"]  # 使用者要求:AI 動過的一定要圈起來
    assert node["detail"]["explain"] == "因為要"


def test_MUST_寫入一定帶著讀取當下的_mtime(fake_api):
    """沒有它就沒有衝突偵測 —— 會蓋掉別條對話剛存的東西。"""
    mm.main(["add-todo", "p", "X", "--pri", "P3", "--why", "因為要"])
    assert fake_api["puts"][0]["base_mtime"] == 111.0


def test_待辦沒給等級就拒絕(fake_api):
    with pytest.raises(SystemExit):
        mm.main(["add-todo", "p", "X", "--pri", "P9", "--why", "因為要"])
    assert not fake_api["puts"]


def test_MUST_這次改動製造出違規就不寫入(fake_api, monkeypatch):
    """把等級拿掉會踩「待辦沒有優先序」——這種改動不准落地。"""
    def bad(args):
        data, mtime = mm.load()
        before = mm.hard_problems(data)
        data["nodeData"]["children"][0]["children"].append(
            {"id": "x", "topic": "⏳ 沒等級", "todo": True})
        mm.save(data, mtime, "測試", before)
    with pytest.raises(SystemExit):
        bad(None)
    assert not fake_api["puts"]


def test_MUST_圖上本來就有的舊問題不擋新的改動(fake_api):
    """否則一張有歷史包袱的圖會讓所有新增都寫不進去 —— 罰錯了人。"""
    fake_api["data"]["nodeData"]["children"].append({"id": "old", "topic": "舊的", "tags": ["P1"]})
    mm.main(["add-todo", "p", "照樣加得進去", "--pri", "P2", "--why", "因為要"])
    assert fake_api["puts"], "舊問題不該擋住這次改動"


def test_不會撞到既有的id(fake_api):
    mm.main(["add-todo", "p", "A", "--pri", "P4", "--why", "甲"])
    mm.main(["add-todo", "p", "B", "--pri", "P4", "--why", "乙"])
    ids = [n["id"] for n in fake_api["data"]["nodeData"]["children"][0]["children"]]
    assert len(ids) == len(set(ids))


def test_改狀態會換掉舊圖示而不是疊上去(fake_api):
    mm.main(["set-status", "t", "完成"])
    node = fake_api["data"]["nodeData"]["children"][0]["children"][0]
    assert node["topic"] == "✅ 既有待辦"


def test_找不到節點就明講_不亂猜(fake_api):
    with pytest.raises(SystemExit):
        mm.main(["show", "根本沒這個"])


def test_一行長出一篇文章與它的固定步驟(fake_api):
    """使用者的需求(2026-08-08):「我每一次都要自己填寫嗎?」——不用,固定步驟由指令帶出來。"""
    mm.main(["add-article", "p", "第一篇文章", "--video"])
    art = fake_api["data"]["nodeData"]["children"][0]["children"][-1]
    assert art["topic"] == "第一篇文章"
    assert [c["topic"] for c in art["children"]] == ["⏳ 整理照片", "⏳ 撰寫文章", "⏳ 製作影片"]
    assert all(c["tags"] == ["P3"] for c in art["children"]), "步驟要自動帶等級,不然又要一條條點"


def test_文章沒有影片就只有兩步(fake_api):
    mm.main(["add-article", "p", "第二篇文章"])
    art = fake_api["data"]["nodeData"]["children"][0]["children"][-1]
    assert len(art["children"]) == 2


# ── set:改死線 / 工時 / 標籤(2026-08-11 加,重排 26 條死線時發現缺這支) ──


def node_t(state):
    return state["data"]["nodeData"]["children"][0]["children"][0]


def test_set_改死線與工時並圈起來(fake_api):
    mm.main(["set", "t", "--due", "2026-08-20", "--effort", "4h"])
    n = node_t(fake_api)
    assert n["detail"] == {"due": "2026-08-20", "effort": "4h"}
    assert n["aiEdited"]


def test_set_可以拿掉死線(fake_api):
    mm.main(["set", "t", "--due", "2026-08-20"])
    mm.main(["set", "t", "--no-due"])
    assert "due" not in node_t(fake_api).get("detail", {})


def test_MUST_工時只收得到八檔之一(fake_api):
    """填了排程看不懂的字,它會當成「沒填」偷偷猜 2h —— 那比報錯糟。"""
    with pytest.raises(SystemExit):
        mm.main(["set", "t", "--effort", "半天"])
    assert not fake_api["puts"], "擋下來就不該寫入"


def test_set_改等級是換掉不是疊加(fake_api):
    mm.main(["set", "t", "--pri", "P1"])
    assert node_t(fake_api)["tags"] == ["P1"]


def test_set_加標籤不動等級(fake_api):
    mm.main(["set", "t", "--tag", "一起做"])
    assert node_t(fake_api)["tags"] == ["P2", "一起做"]


def test_set_一次改多個_id(fake_api):
    fake_api["data"]["nodeData"]["children"][0]["children"].append(
        {"id": "t2", "topic": "⏳ 另一條", "todo": True, "tags": ["P3"]})
    mm.main(["set", "t", "t2", "--due", "2026-08-25"])
    kids = fake_api["data"]["nodeData"]["children"][0]["children"]
    assert all(k["detail"]["due"] == "2026-08-25" for k in kids)


def test_set_改標題會留住狀態圖示(fake_api):
    mm.main(["set", "t", "--rename", "換個講法"])
    assert node_t(fake_api)["topic"] == "⏳ 換個講法"


def test_set_沒指定要改什麼就報錯(fake_api):
    with pytest.raises(SystemExit):
        mm.main(["set", "t"])


# ── archive:做完的出口 ────────────────────────────────────────────
@pytest.fixture
def archive_to(tmp_path, monkeypatch):
    """⚠️ 要跟真的 `notes/完成紀錄.md` 同構:那是三欄表,不是條列。"""
    f = tmp_path / "完成紀錄.md"
    f.write_text("# 完成紀錄\n\n> 說明\n\n---\n\n## 2026 Q3\n\n"
                 "| 完成的事 | 實際完成日 | 回報日 |\n|---|---|---|\n"
                 "| **舊的一筆** | 2026-08-01 | 2026-08-02 |\n", encoding="utf-8")
    monkeypatch.setattr(mm, "ARCHIVE_PATH", f)
    return f


def test_archive_把待辦搬進完成紀錄並從圖上移除(fake_api, archive_to):
    """使用者的需求(2026-08-13):「做完就是做完了,不用放在上面。」"""
    mm.main(["archive", "t", "--on", "2026-08-12"])
    left = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"]
    assert left == [], "節點要從圖上消失"
    text = archive_to.read_text(encoding="utf-8")
    assert "**既有待辦**" in text and "| 2026-08-12 |" in text
    assert "**舊的一筆**" in text, "⛔ 不准蓋掉既有內容"


def test_MUST_archive_寫的是表格列而不是條列(fake_api, archive_to):
    """完成紀錄是三欄表 —— 插一行 `- xxx` 進去會把表格從中間切斷。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["detail"] = {
        "explain": "第一行\n第二行 | 帶直線"}
    mm.main(["archive", "t", "--on", "2026-08-12"])
    row = next(ln for ln in archive_to.read_text(encoding="utf-8").splitlines()
               if "既有待辦" in ln)
    assert row.startswith("|") and row.endswith("|")
    assert row.count("|") - row.count("\\|") == 4, "剛好四根柱子=三欄"
    assert "<br>" in row, "說明的換行要變 <br>,不然會把表格切斷"


def test_MUST_archive_插在表頭底下而不是擠到表頭前面(fake_api, archive_to):
    rows = archive_to.read_text(encoding="utf-8").splitlines()
    mm.main(["archive", "t", "--on", "2026-08-12"])
    rows = archive_to.read_text(encoding="utf-8").splitlines()
    sep = next(i for i, ln in enumerate(rows) if ln.startswith("|---"))
    assert rows.index(next(ln for ln in rows if "既有待辦" in ln)) == sep + 1
    assert rows.index("## 2026 Q3") < sep


def test_MUST_archive_不准搬走結構節點(fake_api, archive_to):
    """⛔ 設施/規則/專案本來就不是待辦,它們一直都在 ——
    「做完之後長出來的結構」是另外一顆節點,不是同一顆變過去。"""
    with pytest.raises(SystemExit) as e:
        mm.main(["archive", "p"])
    assert "結構" in str(e.value)
    assert not fake_api["puts"], "被擋下來就一個字都不該寫"


def test_MUST_archive_底下還有子節點就不動(fake_api, archive_to):
    """整支砍掉會把底下的事一起弄不見,而且是安靜地不見。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["children"] = [
        {"id": "kid", "topic": "⏳ 還沒做", "todo": True, "tags": ["P3"]}]
    with pytest.raises(SystemExit) as e:
        mm.main(["archive", "t"])
    assert "先處理完再歸檔" in str(e.value)


def test_archive_把為什麼一起搬走(fake_api, archive_to):
    """只留標題等於把理由丟掉 —— 那正是他以後回來想查的東西。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["detail"] = {
        "explain": "因為對方先給了書面試算", "effort": "2h"}
    mm.main(["archive", "t", "--on", "2026-08-10"])
    text = archive_to.read_text(encoding="utf-8")
    assert "因為對方先給了書面試算" in text
    assert "P2 · 2h" in text, "等級與工時也要留著"


def test_archive_條目要落在季度標題底下(fake_api, archive_to):
    """⛔ 插在 `---` 後面會落在所有季度之外,那份檔的排序是「最新在上、依季分段」。"""
    mm.main(["archive", "t", "--on", "2026-08-12"])
    rows = archive_to.read_text(encoding="utf-8").splitlines()
    assert rows.index("## 2026 Q3") < rows.index(
        next(ln for ln in rows if "既有待辦" in ln))


def test_archive_沒給完成日就用標打勾的那天(fake_api, archive_to):
    """`--on` 是「真的做完那天」;沒給就用標 ✅ 那天,⛔ 不准硬編今天(會寫出假日期)。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["detail"] = {
        "doneOn": "2026-08-09"}
    mm.main(["archive", "t"])
    row = next(ln for ln in archive_to.read_text(encoding="utf-8").splitlines()
               if "既有待辦" in ln)
    assert row.endswith("| 2026-08-09 | 2026-08-09 |")


def test_archive_兩個日期都不知道就誠實寫不詳(fake_api, archive_to):
    mm.main(["archive", "t"])
    row = next(ln for ln in archive_to.read_text(encoding="utf-8").splitlines()
               if "既有待辦" in ln)
    assert "實際完成日不詳" in row


# ── 離場過的 id 不准回收 ──────────────────────────────────────────
@pytest.fixture
def retired_to(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "RETIRED_PATH", tmp_path / ".retired_ids.json")
    return tmp_path / ".retired_ids.json"


def test_MUST_歸檔過的id不准再發給新節點(fake_api, archive_to, retired_to):
    """出過的問題:某一顆歸檔之後,下一次 add-todo 就把同一個 id 撿回去用了。
    專案 TODO 的 `<!--mm:節點id-->` 不會報錯,會安靜指到不相干的事 —— 比斷鏈更糟。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["id"] = "ai-001"
    mm.main(["archive", "ai-001", "--on", "2026-08-12"])
    assert "ai-001" in json.loads(retired_to.read_text())
    mm.main(["add-todo", "p", "新的一件事", "--pri", "P2", "--why", "因為要"])
    made = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"][-1]
    assert made["id"] != "ai-001"


def test_併掉的id也要進退休名單(siblings, retired_to):
    mm.main(["merge", "t", "t2"])
    assert "t2" in json.loads(retired_to.read_text())


def test_歸檔會講出還掛著這個id的專案待辦(fake_api, archive_to, retired_to,
                                          tmp_path, monkeypatch, capsys):
    """⛔ 安靜地留下斷鏈,要等下週日 drift_check 才喊,那時沒人記得是誰弄的。"""
    proj = tmp_path / "Finance"
    proj.mkdir()
    (proj / "TODO.md").write_text("- [ ] ⏳ 還沒做完的事 <!--mm:t-->\n", encoding="utf-8")
    monkeypatch.setenv("MINDMAP_PROJECTS_ROOT", str(tmp_path))
    mm.main(["archive", "t", "--on", "2026-08-12"])
    out = capsys.readouterr().out
    assert "Finance/TODO.md:1" in out and "斷鏈" in out


# ── merge:幾件小事併成一項 ────────────────────────────────────────
@pytest.fixture
def siblings(fake_api):
    """同一個父節點底下三顆待辦(使用者說的「一起做」那種群)。"""
    kids = fake_api["data"]["nodeData"]["children"][0]["children"]
    kids[0].update({"tags": ["P2", "一起做"],
                    "detail": {"effort": "4h", "due": "2026-08-18", "explain": "甲的理由"}})
    kids.append({"id": "t2", "topic": "⏳ 第二件", "todo": True, "tags": ["P1", "一起做"],
                 "detail": {"effort": "1h", "due": "2026-08-20", "explain": "乙的理由\n第二行"}})
    kids.append({"id": "t3", "topic": "⏳ 第三件", "todo": True, "tags": ["P2"],
                 "detail": {"effort": "2h"}})
    return fake_api


def _kids(fake_api):
    return fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"]


def test_merge_併掉的節點消失而說明逐字留下(siblings):
    """⛔ 合併最容易出的問題是「標題留著、為什麼不見了」——
    那些說明裡有真的會用到的東西(例如要當面問的六個問題)。"""
    mm.main(["merge", "t", "t2", "t3", "--rename", "併起來的一項"])
    kids = _kids(siblings)
    assert [k["id"] for k in kids] == ["t"], "被併掉的要從圖上消失"
    text = kids[0]["detail"]["explain"]
    for keep in ("甲的理由", "乙的理由", "第二行", "1. ", "2. ", "3. "):
        assert keep in text
    assert kids[0]["topic"] == "⏳ 併起來的一項"


def test_merge_工時相加並往上取一檔(siblings):
    """⛔ 不能往下取:併起來只會更花時間,取小了排程排不完。4+1+2=7 → 8h。"""
    mm.main(["merge", "t", "t2", "t3"])
    assert _kids(siblings)[0]["detail"]["effort"] == "8h"


def test_MUST_merge_有人沒填工時也不准刪掉已經填好的(siblings, capsys):
    """⛔ 舊版是「有人沒填就整個不填」,結果把 keeper 的 4h 一起刪掉 ——
    而排程對「沒填」是猜 2h、/day 甚至只給 60 分。
    「誠實地不知道」在下游等於「假設更小」,還順手弄丟了使用者填過的資料。"""
    siblings["data"]["nodeData"]["children"][0]["children"][2]["detail"].pop("effort")
    mm.main(["merge", "t", "t2", "t3"])
    assert _kids(siblings)[0]["detail"]["effort"] == "8h", "已知的 4h+1h 要往上取到 8h"
    assert "至少" in capsys.readouterr().out, "要講清楚這個數字是下限"


def test_MUST_merge_併進已完成的節點要退回未完成(siblings, capsys):
    """⛔ keeper 是 ✅ 時舊版完全不動狀態 → 併進來、根本沒做的那幾件會被當成完成,
    幾天後 autoarchive 把整顆搬進完成紀錄、移出圖,全程無聲。"""
    keeper = siblings["data"]["nodeData"]["children"][0]["children"][0]
    keeper["topic"] = "✅ 已做完的那件"
    keeper["detail"]["doneOn"] = "2026-08-01"
    mm.main(["merge", "t", "t2"])
    got = _kids(siblings)[0]
    assert got["topic"].startswith("⏳"), "還有沒做完的 → 不准留著 ✅"
    assert "doneOn" not in got["detail"], "完成日要清掉,不然當晚就被判到期"
    assert "退回" in capsys.readouterr().out


def test_merge_清單保留原本已完成那幾項的勾(siblings):
    siblings["data"]["nodeData"]["children"][0]["children"][1]["topic"] = "✅ 第二件"
    mm.main(["merge", "t", "t2", "t3"])
    text = _kids(siblings)[0]["detail"]["explain"]
    assert "[x] 2. 第二件" in text, "本來做完的不准被改回沒做"


def test_MUST_merge_同一個id列兩次就拒絕(siblings):
    """不擋的話工時會被算兩份、清單也出現兩次,而且完全不報錯。"""
    with pytest.raises(SystemExit):
        mm.main(["merge", "t", "t2", "t2"])
    assert not siblings["puts"]


def test_merge_等級取最高死線取最早(siblings):
    mm.main(["merge", "t", "t2", "t3"])
    det = _kids(siblings)[0]
    assert det["tags"][0] == "P1", "P1 跟 P2 併起來要變 P1"
    assert det["detail"]["due"] == "2026-08-18"
    assert "一起做" in det["tags"]


def test_merge_已經排上行程的時段不會弄丟(siblings):
    siblings["data"]["nodeData"]["children"][0]["children"][1]["detail"]["planned"] = [
        {"uid": "s1", "at": "2026-08-18T09:00", "min": 60}]
    mm.main(["merge", "t", "t2", "t3"])
    assert _kids(siblings)[0]["detail"]["planned"][0]["uid"] == "s1"


def test_MUST_merge_不同父節點就拒絕(siblings):
    """跨處合併=偷偷搬家,而且他在圖上會找不到東西跑哪去了。"""
    siblings["data"]["nodeData"]["children"].append(
        {"id": "p2", "topic": "另一個項目",
         "children": [{"id": "x", "topic": "⏳ 別處的", "todo": True, "tags": ["P3"]}]})
    with pytest.raises(SystemExit) as e:
        mm.main(["merge", "t", "x"])
    assert "同一個父節點" in str(e.value)
    assert not siblings["puts"]


def test_MUST_merge_有關聯線就拒絕(siblings):
    """線的 from/to 指到被併掉的 id → 面板會顯示「對方節點已不在圖上」。"""
    siblings["data"]["arrows"] = [{"id": "a1", "from": "t2", "to": "t", "label": "餵給"}]
    with pytest.raises(SystemExit) as e:
        mm.main(["merge", "t", "t2"])
    assert "關聯線" in str(e.value)
    assert not siblings["puts"]


def test_MUST_merge_底下有子節點就拒絕(siblings):
    siblings["data"]["nodeData"]["children"][0]["children"][1]["children"] = [
        {"id": "k", "topic": "⏳ 小的", "todo": True, "tags": ["P4"]}]
    with pytest.raises(SystemExit) as e:
        mm.main(["merge", "t", "t2"])
    assert "弄不見" in str(e.value)


# ── shift-plan 的區間(--until)──────────────────────────────────
def _planned(fake_api, days):
    node = fake_api["data"]["nodeData"]["children"][0]["children"][0]
    node.setdefault("detail", {})["planned"] = [{"at": f"{d}T09:00", "min": 60} for d in days]
    return node


def test_until_只推區間內的(fake_api):
    """2026-08-20 使用者:「把 8/21 到 8/25 的行程往後移一天」—— 8/26 以後不准動。"""
    _planned(fake_api, ["2026-08-20", "2026-08-21", "2026-08-25", "2026-08-26"])
    mm.main(["shift-plan", "--since", "2026-08-21", "--until", "2026-08-25", "--days", "1"])
    got = [s["at"][:10] for s in fake_api["puts"][-1]["data"]["nodeData"]
           ["children"][0]["children"][0]["detail"]["planned"]]
    assert got == ["2026-08-20", "2026-08-22", "2026-08-26", "2026-08-26"], got


def test_沒給until就一路推到底(fake_api):
    _planned(fake_api, ["2026-08-21", "2026-08-30"])
    mm.main(["shift-plan", "--since", "2026-08-21", "--days", "1"])
    got = [s["at"][:10] for s in fake_api["puts"][-1]["data"]["nodeData"]
           ["children"][0]["children"][0]["detail"]["planned"]]
    assert got == ["2026-08-22", "2026-08-31"], got


def test_區間內沒東西就什麼都不做(fake_api):
    _planned(fake_api, ["2026-08-30"])
    mm.main(["shift-plan", "--since", "2026-08-21", "--until", "2026-08-25", "--days", "1"])
    assert not fake_api["puts"], "沒東西可推就不該寫入圖"


# ── 決定不做了 ────────────────────────────────────────────────
def test_drop_從圖上移走並記成不做了(fake_api, archive_to):
    """⛔ 不能標 ✅ 混進完成紀錄 —— 之後查「這功能做了沒」會查到假的。"""
    mm.main(["drop", "t", "--why", "功能重複"])
    assert fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"] == []
    text = archive_to.read_text(encoding="utf-8")
    assert "❌ 不做了" in text and "功能重複" in text
    assert "實際完成日不詳" not in text, "「不做了」不該留完成日欄位的預設值"


def test_MUST_drop一定要給理由(fake_api):
    """一年後看到「這件事不做了」而沒有理由,下一輪規劃會原封不動再提一次。"""
    with pytest.raises(SystemExit):
        mm.main(["drop", "t"])


def test_drop不碰結構節點(fake_api):
    node = fake_api["data"]["nodeData"]["children"][0]["children"][0]
    node.pop("todo", None)
    with pytest.raises(SystemExit) as e:
        mm.main(["drop", "t", "--why", "x"])
    assert "結構節點" in str(e.value)


# ── 使用者自己按的狀態,AI 不准安靜地翻回去 ──────────────────────────
def _sc_marked(fake_api, mark="✅", when=None):
    when = when or mm.date.today().isoformat()
    node = fake_api["data"]["nodeData"]["children"][0]["children"][0]
    node["topic"] = f"{mark} 既有待辦"
    node["scEdited"] = f"{when} 在排今天改了狀態"
    return node


def test_MUST_不准翻掉使用者自己按的狀態(fake_api):
    """2026-08-18:他在 /day 按了完成,我判成「誤標」改回 ⏳,他問「為什麼一直跳出來」。"""
    _sc_marked(fake_api)
    with pytest.raises(SystemExit) as e:
        mm.main(["set-status", "t", "待辦"])
    assert "使用者自己按的" in str(e.value)
    assert not fake_api["puts"], "被擋下來就不該寫進圖"


def test_問過他之後可以用force翻(fake_api):
    _sc_marked(fake_api)
    mm.main(["set-status", "t", "待辦", "--force"])
    assert fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"][0][
        "topic"].startswith("⏳")


def test_同一個狀態再標一次不算翻(fake_api):
    """例:autoarchive 前重新蓋 doneOn,不該被自己的閘門擋住。"""
    _sc_marked(fake_api)
    mm.main(["set-status", "t", "完成"])
    assert fake_api["puts"]


def test_超過七天就不再擋(fake_api):
    """閘門是防「我剛把他按的翻掉」,⛔ 不是把節點永久凍結。"""
    _sc_marked(fake_api, when=(mm.date.today() - mm.timedelta(days=8)).isoformat())
    mm.main(["set-status", "t", "待辦"])
    assert fake_api["puts"]


# ── autoarchive:✅ 放滿 7 天自動走 ────────────────────────────────
def test_set_status_完成會記下那一天(fake_api):
    """⛔ 不能靠 aiEdited 算天數 —— 隨便改一次說明就會把日期蓋掉。"""
    mm.main(["set-status", "t", "完成"])
    node = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"][0]
    assert node["detail"]["doneOn"] == mm.datetime.now().astimezone().date().isoformat()


def test_set_status_取消完成會把那天拿掉(fake_api):
    """打了勾又取消 → 時鐘要歸零,不然改回 ✅ 當天就被判到期搬走。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["detail"] = {
        "doneOn": "2026-08-01"}
    mm.main(["set-status", "t", "進行中"])
    node = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"][0]
    assert "doneOn" not in node["detail"]


def _mark_done(fake_api, on):
    node = fake_api["data"]["nodeData"]["children"][0]["children"][0]
    node["topic"] = "✅ 既有待辦"
    node.setdefault("detail", {})["doneOn"] = on
    return node


def test_autoarchive_放滿天數才搬(fake_api, archive_to):
    _mark_done(fake_api, (mm.date.today() - mm.timedelta(days=7)).isoformat())
    mm.main(["autoarchive"])
    assert fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"] == []
    assert "既有待辦" in archive_to.read_text(encoding="utf-8")


def test_autoarchive_還沒放滿就不動(fake_api, archive_to):
    """留 7 天是要讓他看得到「最近做完什麼」,提早搬掉就沒有告示欄了。"""
    _mark_done(fake_api, (mm.date.today() - mm.timedelta(days=3)).isoformat())
    mm.main(["autoarchive"])
    assert not fake_api["puts"], "沒事就不要寫圖"
    assert "既有待辦" not in archive_to.read_text(encoding="utf-8")


def test_autoarchive_任務板打的勾從今天開始算不是立刻搬(fake_api, archive_to):
    """任務板打勾不會寫 doneOn。⛔ 不准當成「今天到期」——他會看著剛打的勾消失。"""
    node = fake_api["data"]["nodeData"]["children"][0]["children"][0]
    node["topic"] = "✅ 既有待辦"
    mm.main(["autoarchive"])
    left = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"]
    assert len(left) == 1, "第一次看到只記時間,不搬"
    assert left[0]["detail"]["doneOn"] == mm.date.today().isoformat()
    assert "既有待辦" not in archive_to.read_text(encoding="utf-8")


def test_MUST_autoarchive_不碰結構節點(fake_api, archive_to):
    """結構節點沒有 todo 旗標 —— 就算標題被標成 ✅ 也不准自動搬走。"""
    fake_api["data"]["nodeData"]["children"][0]["topic"] = "✅ 某個項目"
    mm.main(["autoarchive"])
    assert "某個項目" not in archive_to.read_text(encoding="utf-8")


def test_MUST_autoarchive_底下有東西就不搬(fake_api, archive_to):
    _mark_done(fake_api, "2026-01-01")["children"] = [
        {"id": "kid", "topic": "⏳ 還沒做", "todo": True, "tags": ["P3"]}]
    mm.main(["autoarchive"])
    assert "既有待辦" not in archive_to.read_text(encoding="utf-8")


def test_autoarchive_dry_run_一個字都不改(fake_api, archive_to):
    before = archive_to.read_text(encoding="utf-8")
    _mark_done(fake_api, "2026-01-01")
    mm.main(["autoarchive", "--dry-run"])
    assert not fake_api["puts"]
    assert archive_to.read_text(encoding="utf-8") == before


def test_move_換父節點且不換id(fake_api):
    """⛔ 掛錯地方時不准刪掉重加 —— 重加會換 id,
    專案 TODO 那些 `<!--mm:id-->` 認親記號會全部斷鏈。"""
    fake_api["data"]["nodeData"]["children"].append({"id": "p2", "topic": "另一個項目"})
    mm.main(["move", "t", "p2"])
    root = fake_api["puts"][-1]["data"]["nodeData"]["children"]
    assert root[0].get("children", []) == [], "要從舊父節點拿掉"
    moved = root[1]["children"]
    assert len(moved) == 1 and moved[0]["id"] == "t", "id 不准變"


def test_MUST_move_不准搬到自己的子孫底下(fake_api):
    """那會讓整支從圖上消失,而且是安靜地消失。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["children"] = [
        {"id": "kid", "topic": "小孩"}]
    with pytest.raises(SystemExit) as e:
        mm.main(["move", "t", "kid"])
    assert "消失" in str(e.value)
    assert not fake_api["puts"]

def test_MUST_archive_有關聯線就不搬(fake_api, archive_to):
    """線的另一端會變成「對方節點已不在圖上」—— merge 本來就擋,archive 以前不擋。"""
    fake_api["data"]["arrows"] = [{"id": "a1", "from": "t", "to": "p", "label": "餵給"}]
    with pytest.raises(SystemExit) as e:
        mm.main(["archive", "t"])
    assert "關聯線" in str(e.value)
    assert not fake_api["puts"]


def test_MUST_autoarchive_有關聯線的跳過而不是安靜刪掉(fake_api, archive_to, capsys):
    """這支是 janitor 每天 04:15 無人值守跑的 —— 安靜地弄壞別的東西最糟。"""
    _mark_done(fake_api, "2026-01-01")
    fake_api["data"]["arrows"] = [{"id": "a1", "from": "t", "to": "p", "label": "餵給"}]
    mm.main(["autoarchive"])
    assert "既有待辦" not in archive_to.read_text(encoding="utf-8")
    assert "關聯線" in capsys.readouterr().out, "跳過要講出來,不然沒人知道它為什麼還在"


def test_MUST_autoarchive_演練不報剛打勾的那幾顆(fake_api, archive_to, capsys):
    """週日的保底檢查跑的就是 --dry-run。「他剛在任務板打了勾」不是異常,
    照報的話每週都會誤喊「歸檔卡住了」—— 狼來了,他就不看了。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["topic"] = "✅ 既有待辦"
    mm.main(["autoarchive", "--dry-run"])
    out = capsys.readouterr().out
    assert "開始算" not in out
    assert "沒有放超過" in out


def test_MUST_退休名單壞掉要炸開不准當成空的(fake_api, retired_to):
    """當成空的 → 下一次 retire() 把整份名單覆蓋成只剩這次那幾個,而且無聲。"""
    retired_to.write_text("{壞掉的 json", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        mm.retired_ids()
    assert "讀不了" in str(e.value)


def test_歸檔跨季會自己開一段而不是塞進上一季(fake_api, archive_to):
    """那份檔的排序規則就是「最新在上、依季分段」。"""
    mm.main(["archive", "t", "--on", "2026-11-05"])
    rows = archive_to.read_text(encoding="utf-8").splitlines()
    assert any(ln.startswith("## 2026 Q4") for ln in rows)
    assert rows.index("## 2026 Q4") < rows.index("## 2026 Q3"), "新的季度要在上面"
    q4 = rows.index("## 2026 Q4")
    assert any("既有待辦" in ln for ln in rows[q4:rows.index("## 2026 Q3")])


# ── 常設職責與週期性(2026-08-18 定案) ──────────────────────────────
def test_duty_降級之後不再是待辦也沒有等級(fake_api):
    """永遠做不完的事掛死線與打勾沒有意義,只會一直卡在任務池裡。"""
    mm.main(["duty", "t"])
    n = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"][0]
    assert n["topic"].startswith("♾️") and "todo" not in n
    assert n["tags"] == [], "⛔ 等級要拿掉,不然 lint 會擋『不是待辦卻掛著優先序』"
    assert n["detail"]["duty"] is True


def test_duty_off_變回待辦要有等級也要清掉職責欄位(fake_api):
    """降級是單行道的話,判斷被推翻時只剩「直接 Edit JSON」可用 —— 那是禁止的。"""
    mm.main(["duty", "t", "--min", "90"])
    mm.main(["duty", "t", "--off", "--pri", "P2"])
    n = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"][0]
    assert n["todo"] is True and n["topic"].startswith("⏳")
    assert n["tags"] == ["P2"]
    assert not {"duty", "dutyMin"} & set(n.get("detail") or {})


def test_MUST_duty_off_沒給等級就擋下來(fake_api):
    """沒等級的待辦 lint 會擋、也排不進行程 —— 與其寫進去再壞掉,不如當場擋。"""
    mm.main(["duty", "t"])
    puts = len(fake_api["puts"])
    with pytest.raises(SystemExit):
        mm.main(["duty", "t", "--off"])
    assert len(fake_api["puts"]) == puts, "擋下來就不該有第二次寫入"


def test_MUST_duty_不准拿去降級非待辦(fake_api):
    with pytest.raises(SystemExit):
        mm.main(["duty", "p"])
    assert not fake_api["puts"]


def test_duty_會清掉死線與打勾這些對它沒意義的欄位(fake_api):
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["detail"] = {
        "due": "2026-09-01", "hardDue": True, "doneOn": "2026-08-01", "explain": "留著"}
    mm.main(["duty", "t"])
    det = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"][0]["detail"]
    assert det["explain"] == "留著", "⛔ 為什麼要留著"
    assert not {"due", "hardDue", "doneOn"} & set(det)


def test_MUST_週期性做完不歸檔而是推到下一期(fake_api, archive_to, retired_to, capsys):
    """⛔ 歸檔掉的話下一期就沒有任何東西提醒他 —— 週期性申報漏一期會失去資格。"""
    n = fake_api["data"]["nodeData"]["children"][0]["children"][0]
    n["topic"] = "✅ 完成季度申報"
    n["detail"] = {"repeat": "每四週", "due": "2026-08-27",
                   "doneOn": (mm.date.today() - mm.timedelta(days=1)).isoformat()}
    mm.main(["autoarchive"])
    left = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"]
    assert len(left) == 1, "⛔ 週期性的不准從圖上消失"
    assert left[0]["topic"].startswith("⏳"), "要退回還沒開始"
    assert left[0]["detail"]["due"] > mm.date.today().isoformat(), "下一期要落在未來"
    assert "doneOn" not in left[0]["detail"]
    assert "完成季度申報" in archive_to.read_text(encoding="utf-8"), "這一期還是要留一筆紀錄"
    assert "完成季度申報" not in str(mm.retired_ids()), "⛔ id 不准退休,它還會再來"


def test_下一期一定落在今天之後(fake_api):
    """拖過好幾期時要一次補到未來 —— 算出過去的日期只會多一條紅字。"""
    old = (mm.date.today() - mm.timedelta(days=200)).isoformat()
    assert mm._next_due(old, "每四週") > mm.date.today().isoformat()
    assert mm._next_due(old, "每月") > mm.date.today().isoformat()


def test_MUST_週期只收得懂的那幾個(fake_api):
    with pytest.raises(SystemExit):
        mm.main(["set", "t", "--repeat", "每隔一陣子"])
    assert not fake_api["puts"]


# ── shift-plan:整批往後推(2026-08-18 定案) ────────────────────────
@pytest.fixture
def planned(fake_api):
    kids = fake_api["data"]["nodeData"]["children"][0]["children"]
    kids[0]["detail"] = {"planned": [{"uid": "a", "at": "2026-08-18T10:00", "min": 60},
                                     {"uid": "b", "at": "2026-08-17T10:00", "min": 60}]}
    kids.append({"id": "hard", "topic": "⏳ 外力的", "todo": True, "tags": ["P1"],
                 "detail": {"due": "2026-08-18", "hardDue": True,
                            "planned": [{"uid": "c", "at": "2026-08-18T16:00", "min": 60}]}})
    return fake_api


def _slots(state, idx):
    return state["puts"][-1]["data"]["nodeData"]["children"][0]["children"][idx]["detail"]["planned"]


def test_shift_只推指定日之後的段落(planned):
    mm.main(["shift-plan", "--since", "2026-08-18"])
    got = {s["uid"]: s["at"][:10] for s in _slots(planned, 0)}
    assert got["a"] == "2026-08-19", "今天(含)以後的要往後推"
    assert got["b"] == "2026-08-17", "⛔ 之前的不准動"


def test_MUST_shift_不准動死線(planned):
    """死線是外力給的,不會因為他晚起就往後移 —— 這是兩件事。"""
    mm.main(["shift-plan", "--since", "2026-08-18"])
    n = planned["puts"][-1]["data"]["nodeData"]["children"][0]["children"][1]
    assert n["detail"]["due"] == "2026-08-18"


def test_MUST_shift_外力死線的不推(planned, capsys):
    """使用者自己立的規則:「合約到期 8/13、機關約定日 8/27、款項入帳 8/31 推了就是錯的」。"""
    mm.main(["shift-plan", "--since", "2026-08-18"])
    n = planned["puts"][-1]["data"]["nodeData"]["children"][0]["children"][1]
    assert n["detail"]["planned"][0]["at"][:10] == "2026-08-18", "🔒 的要留在原地"
    assert "推下去就錯過了" in capsys.readouterr().out


def test_shift_force_才會連外力死線一起推(planned):
    mm.main(["shift-plan", "--since", "2026-08-18", "--force"])
    n = planned["puts"][-1]["data"]["nodeData"]["children"][0]["children"][1]
    assert n["detail"]["planned"][0]["at"][:10] == "2026-08-19"


def test_shift_dry_run_一個字都不改(planned):
    mm.main(["shift-plan", "--since", "2026-08-18", "--dry-run"])
    assert not planned["puts"]


# ── 等條件(2026-08-18 定案) ────────────────────────────────────────
def test_wait_把待辦park起來並寫清楚在等什麼(fake_api):
    """使用者的需求:「我根本就還不知道什麼時候找到工作…一直放在待辦事項覺得很怪。」"""
    mm.main(["wait", "t", "--until", "換到新工作"])
    det = node_t(fake_api)["detail"]
    assert det["until"] == "換到新工作"


def test_MUST_wait_會拿掉earliest(fake_api):
    """⛔ 兩個一起填會打架:earliest 是日期、until 是事件,排程會照日期放行。"""
    fake_api["data"]["nodeData"]["children"][0]["children"][0]["detail"] = {
        "earliest": "2026-09-01"}
    mm.main(["wait", "t", "--until", "換到新工作"])
    assert "earliest" not in node_t(fake_api)["detail"]


def test_release_一次放行等同一件事的全部(fake_api):
    kids = fake_api["data"]["nodeData"]["children"][0]["children"]
    kids[0]["detail"] = {"until": "換到新工作"}
    kids.append({"id": "t2", "topic": "⏳ 另一條", "todo": True, "tags": ["P3"],
                 "detail": {"until": "換到新工作"}})
    kids.append({"id": "t3", "topic": "⏳ 不相干", "todo": True, "tags": ["P3"],
                 "detail": {"until": "等款項入帳"}})
    mm.main(["release", "--until", "換到新工作"])
    left = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"]
    assert "until" not in (left[0].get("detail") or {})
    assert "until" not in (left[1].get("detail") or {})
    assert left[2]["detail"]["until"] == "等款項入帳", "⛔ 不相干的不准一起放行"


def test_MUST_wait_不准park非待辦(fake_api):
    with pytest.raises(SystemExit):
        mm.main(["wait", "p", "--until", "隨便"])
    assert not fake_api["puts"]


def test_MUST_release_不准把條件更嚴格的那條一起放出來(fake_api):
    """⚠️「換到新工作」是「換到新工作且就保滿 3 個月」的子字串。
    包含比對會在他剛找到工作那天,把還要再等三個月的那條也放進待辦 —— 他去申請會被打回票。"""
    kids = fake_api["data"]["nodeData"]["children"][0]["children"]
    kids[0]["detail"] = {"until": "換到新工作"}
    kids.append({"id": "t2", "topic": "⏳ 更嚴格的", "todo": True, "tags": ["P3"],
                 "detail": {"until": "換到新工作且就保滿 3 個月"}})
    mm.main(["release", "--until", "換到新工作"])
    left = fake_api["puts"][-1]["data"]["nodeData"]["children"][0]["children"]
    assert "until" not in (left[0].get("detail") or {})
    assert left[1]["detail"]["until"] == "換到新工作且就保滿 3 個月", "⛔ 這條不准被順手放出來"


def test_MUST_每次寫入都會提醒還有什麼在等條件(fake_api, capsys):
    """使用者的需求:「你就會去觸發去看一下…我們就不用管他了吧?」
    ⚠️ 靠 AI 記得不成立(每條對話都是新的)→ 把提醒掛在工具上。"""
    fake_api["data"]["nodeData"]["children"][0]["children"].append(
        {"id": "w", "topic": "⏳ 等著的", "todo": True, "tags": ["P3"],
         "detail": {"until": "換到新工作"}})
    mm.main(["set", "t", "--pri", "P1"])
    assert "還在等" in capsys.readouterr().out


def test_沒有等條件的就不要多印一行(fake_api, capsys):
    mm.main(["set", "t", "--pri", "P1"])
    assert "還在等" not in capsys.readouterr().out


def test_歸檔那一列要留下節點id():
    """⚠️ 專案 TODO.md 的手寫行用 `<!--mm:節點id-->` 認親,而歸檔會把節點移出圖
    → 不留 id 的話那些指標全部變成「查無此顆」,drift_check 會永遠報 ⛔ 斷鏈。
    2026-08-22 抓到 ai-030 就是這樣:它其實早就完成並歸檔了,警告卻長得像打錯字。
    **假警報比漏報更糟** —— ⛔ 一多就沒有人看 ⛔ 了。"""
    node = {"id": "ai-030", "topic": "✅ 補 Meta 那段的地點", "todo": True,
            "tags": ["P3"], "detail": {"explain": "master 是正本,該補完"}}
    line = mm._archive_line(node, "圖 › Work › 文件整理 › 補欄位", "2026-08-18", "2026-08-18")
    assert "<!--mm:ai-030-->" in line
    assert line.startswith("|") and line.count("|") == 4   # 還是合法的表格列


def test_source_路徑不存在要當場擋下來():
    """⛔ 打錯字的話 sync 會安靜地什麼都不做 —— 沒有錯誤訊息、也沒有同步區,
    那個專案就永遠不會被對帳,而且沒有人會發現。"""
    with pytest.raises(SystemExit):
        mm._check_source("這個資料夾不存在")


def test_source_沒有TODO檔也要擋(tmp_path, monkeypatch):
    """同步區要寫進 TODO.md,沒有那個檔就沒地方寫。"""
    monkeypatch.setenv("MINDMAP_PROJECTS_ROOT", str(tmp_path))
    (tmp_path / "Demo").mkdir()
    with pytest.raises(SystemExit):
        mm._check_source("Demo")
    (tmp_path / "Demo" / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    mm._check_source("Demo")          # 有了就過


def test_週期性推到下一期要順手取消專案檔的勾(tmp_path, monkeypatch):
    """⛔ 不取消 = 每晚重跑的無限迴圈,而且它會安靜地往完成紀錄寫假資料。

    2026-08-24 抓到:「補 113/114/115 年度住宅火險通知書」在完成紀錄裡有 4 列,
    而那件事只做過一次。迴圈是:janitor 推到下一期(標題變 ⏳)→ 專案檔還是 [x]
    → sync 把 ✅ 蓋回去 → 隔天再推一次、再多寫一列。
    """
    import drift_check
    root = tmp_path / "projects"
    (root / "Finance").mkdir(parents=True)
    todo = root / "Finance" / "TODO.md"
    todo.write_text(
        "# TODO\n"
        "- [x] ✅ 每年要做的事 `P4` <!--mm:rep-1-->\n"
        "- [x] 別人的事 <!--mm:other-->\n", encoding="utf-8")
    monkeypatch.setattr(drift_check, "PROJECTS_ROOT", root)

    hit = mm._untick_repeat_copies(["rep-1"])
    assert hit == ["Finance/TODO.md"]
    lines = todo.read_text(encoding="utf-8").splitlines()
    assert lines[1].startswith("- [ ]"), "該取消的那一行沒被取消"
    assert lines[2].startswith("- [x]"), "⛔ 動到不該動的那一行"


def test_演練模式不准真的改專案檔(tmp_path, monkeypatch):
    import drift_check
    root = tmp_path / "projects"
    (root / "Finance").mkdir(parents=True)
    todo = root / "Finance" / "TODO.md"
    before = "- [x] ✅ 每年要做的事 <!--mm:rep-1-->\n"
    todo.write_text(before, encoding="utf-8")
    monkeypatch.setattr(drift_check, "PROJECTS_ROOT", root)
    assert mm._untick_repeat_copies(["rep-1"], dry_run=True) == ["Finance/TODO.md"]
    assert todo.read_text(encoding="utf-8") == before
