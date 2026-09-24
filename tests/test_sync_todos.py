"""sync_todos 的把關測試。

這支會**寫使用者專案資料夾裡的 TODO.md**,所以測試的重點不是「功能對不對」,
是「**它會不會弄壞不該碰的東西**」。
"""

import json

import pytest

import sync_todos as S

MAP = {
    "nodeData": {
        "id": "root",
        "topic": "圖",
        "children": [
            {
                "id": "proj",
                "topic": "專案 Alpha",
                "source": "Work/Alpha",
                "children": [
                    {"id": "t1", "topic": "⏳ Draft the proposal", "todo": True, "tags": ["P1"]},
                    {"id": "t2", "topic": "✅ 已經做完的", "todo": True},
                    {
                        "id": "t3",
                        "topic": "⏸️ 等別人",
                        "todo": True,
                        "detail": {"due": "2026-08-13"},
                    },
                ],
            },
            {"id": "other", "topic": "沒掛專案的", "children": [
                {"id": "t9", "topic": "⏳ 只活在圖上", "todo": True},
            ]},
        ],
    }
}

HANDWRITTEN = """# TODO — 專案 Alpha

## 這個專案自己的細項
- [ ] 104 接 salaryLow/High
- [x] 已完成的手寫項目
"""


@pytest.fixture(autouse=True)
def _no_real_backups(tmp_path, monkeypatch):
    """⛔ 測試絕不能寫到使用者的真實目錄。備份路徑一律導到 tmp。
    (曾經出過的問題:沒導的那幾項把 tmp 檔的備份寫進真的 mindmaps/.history/)"""
    monkeypatch.setattr(S, "BACKUP_DIR", tmp_path / "_backups")
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "_backups" / "_last_sync.json")


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "Work" / "Alpha"
    d.mkdir(parents=True)
    (d / "TODO.md").write_text(HANDWRITTEN, encoding="utf-8")
    return tmp_path


def fresh():
    return json.loads(json.dumps(MAP))


def test_只有掛了source的節點會被同步():
    groups = S.collect(fresh())
    assert set(groups) == {"Work/Alpha"}
    assert [n["id"] for n in groups["Work/Alpha"]] == ["t1", "t2", "t3"]


def test_第一次跑會把同步區插在標題後面(proj):
    S.sync(fresh(), proj, apply=True)
    text = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    assert text.startswith("# TODO — 專案 Alpha")
    assert S.BEGIN in text and S.END in text


def test_MUST_手寫區一個字都不能被動到(proj):
    """這是整支工具最重要的一條:碰壞使用者的專案檔就完了。"""
    S.sync(fresh(), proj, apply=True)
    text = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    assert "## 這個專案自己的細項" in text
    assert "- [ ] 104 接 salaryLow/High" in text
    assert "- [x] 已完成的手寫項目" in text


def test_狀態與等級與截止日都帶過去(proj):
    S.sync(fresh(), proj, apply=True)
    text = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    assert "- [ ] ⏳ Draft the proposal `P1` <!--mm:t1-->" in text
    assert "- [x] ✅ 已經做完的 <!--mm:t2-->" in text
    assert "⏰2026-08-13" in text


def test_在專案打勾會回寫心智圖並圈起來(proj):
    S.sync(fresh(), proj, apply=True)
    p = proj / "Work/Alpha/TODO.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            "- [ ] ⏳ Draft the proposal", "- [x] ⏳ Draft the proposal"
        ),
        encoding="utf-8",
    )
    data = fresh()
    report = S.sync(data, proj, apply=True)
    node = next(n for n, _ in S.walk(data["nodeData"]) if n["id"] == "t1")
    assert node["topic"] == "✅ Draft the proposal"
    assert node["aiEdited"]  # 圈起來讓使用者知道是自動改的
    assert report["ticked_back"]


def test_MUST_專案檔沒打勾但圖上已完成_不回寫只報告(proj):
    """圖是正本:同步區下一步就會照圖重畫成 [x],所以這裡只列出來,⛔ 不改圖。"""
    S.sync(fresh(), proj, apply=True)
    p = proj / "Work/Alpha/TODO.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace("- [x] ✅ 已經做完的", "- [ ] ✅ 已經做完的"),
        encoding="utf-8",
    )
    data = fresh()
    report = S.sync(data, proj, apply=True)
    node = next(n for n, _ in S.walk(data["nodeData"]) if n["id"] == "t2")
    assert node["topic"] == "✅ 已經做完的"  # 沒被改掉
    assert report["stale_file"]


def test_MUST_dry_run什麼都不寫(proj):
    p = proj / "Work/Alpha/TODO.md"
    before = p.read_text(encoding="utf-8")
    data = fresh()
    report = S.sync(data, proj, apply=False)
    assert p.read_text(encoding="utf-8") == before
    assert report["written"]  # 但有告訴你「本來要寫什麼」


def test_重跑不會一直長出新的同步區(proj):
    """冪等:跑第二次檔案內容必須一模一樣,不然每次同步都會 diff。"""
    S.sync(fresh(), proj, apply=True)
    once = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    S.sync(fresh(), proj, apply=True)
    assert (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8") == once


def test_MUST_舊措辭的標記也認得_不會長出第二個同步區(proj):
    """標記說明文字 2026-08-04 改過措辭。舊措辭認不得的話,五個專案的既有
    同步區會被當成「沒有標記」→ 再插一份新的 → 同一檔兩個同步區,直接災難。"""
    p = proj / "Work/Alpha/TODO.md"
    old_begin = "<!-- mm:begin ⚠️ 這一區由心智圖產生。可以打勾，但不要改文字或新增 -->"
    p.write_text(
        "# TODO — 專案 Alpha\n\n"
        + old_begin + "\n- [x] ⏳ Draft the proposal <!--mm:t1-->\n" + S.END + "\n\n"
        + "## 這個專案自己的細項\n- [ ] 104 接 salaryLow/High\n",
        encoding="utf-8",
    )
    data = fresh()
    report = S.sync(data, proj, apply=True)
    text = p.read_text(encoding="utf-8")
    assert text.count("<!-- mm:begin") == 1, "只能有一個同步區"
    assert S.BEGIN in text and old_begin not in text, "重寫時換成新措辭"
    assert report["ticked_back"], "舊同步區裡的勾也要讀得到"


def test_MUST_標記不成對就跳過不亂猜(proj):
    p = proj / "Work/Alpha/TODO.md"
    p.write_text(S.BEGIN + "\n- [ ] 壞掉的\n" + HANDWRITTEN, encoding="utf-8")
    report = S.sync(fresh(), proj, apply=True)
    assert report["skipped"]
    assert "壞掉的" in p.read_text(encoding="utf-8")  # 原檔沒被動


def test_MUST_寫之前一定先備份(proj, tmp_path):
    """⚠️ Blog / Finance / Work 這些資料夾**不在 git 裡**,備份是唯一的救命索。"""
    original = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    S.sync(fresh(), proj, apply=True)
    saved = list((tmp_path / "_backups").rglob("*.md"))
    assert len(saved) == 1, "沒有備份"
    assert saved[0].read_text(encoding="utf-8") == original, "備份的是寫入前的內容才有意義"


def test_dry_run不會產生備份(proj, tmp_path):
    S.sync(fresh(), proj, apply=False)
    assert not (tmp_path / "_backups").exists()


def test_MUST_跑過就要留下時間戳_就算沒有任何改動(proj, tmp_path):
    """「有跑過」跟「有改過」是兩件事。圖上要顯示的是前者 ——
    沒改動就不記的話,時間會永遠停在最後一次有差異的那天,看起來像很久沒對帳。"""
    S.sync(fresh(), proj, apply=True)
    S.sync(fresh(), proj, apply=True)  # 第二次沒有任何改動
    state = json.loads((tmp_path / "_backups" / "_last_sync.json").read_text(encoding="utf-8"))
    assert "Work/Alpha" in state


def test_dry_run不留時間戳(proj, tmp_path):
    S.sync(fresh(), proj, apply=False)
    assert not (tmp_path / "_backups" / "_last_sync.json").exists()


def test_專案沒有TODO_md就只是報告(tmp_path):
    (tmp_path / "Work" / "Alpha").mkdir(parents=True)
    report = S.sync(fresh(), tmp_path, apply=True)
    assert report["missing"] == ["Work/Alpha"]


def test_沒掛專案的待辦不會被寫到任何地方(proj):
    S.sync(fresh(), proj, apply=True)
    text = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    assert "只活在圖上" not in text


def test_MUST_圖上的待辦被刪光_同步區要清掉不能留孤兒行(proj):
    """實際出過的問題:某個專案那 4 條併進管道節點後,TODO.md 還留著 4 行,
    而工具回報「兩邊一致」。孤兒行點了也沒反應(節點已經不在),等於騙人。"""
    S.sync(fresh(), proj, apply=True)
    empty = fresh()
    for n, _ in S.walk(empty["nodeData"]):
        n.pop("todo", None)
    report = S.sync(empty, proj, apply=True)
    text = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    assert "mm:t1" not in text and "mm:t2" not in text
    assert S.BEGIN in text and S.END in text  # 區塊本身留著,下次有待辦才填得回去
    assert "- [ ] 104 接 salaryLow/High" in text  # 手寫區照樣不能動
    assert report["written"]  # ⛔ 不准回報「兩邊一致」


def test_沒待辦也沒同步區的專案_不要無中生有插一個空區塊(tmp_path):
    d = tmp_path / "Work" / "Alpha"
    d.mkdir(parents=True)
    (d / "TODO.md").write_text("# TODO\n\n- [ ] 我自己寫的\n", encoding="utf-8")
    empty = fresh()
    for n, _ in S.walk(empty["nodeData"]):
        n.pop("todo", None)
    S.sync(empty, tmp_path, apply=True)
    assert (d / "TODO.md").read_text(encoding="utf-8") == "# TODO\n\n- [ ] 我自己寫的\n"


def test_MUST_已經畢業成現況節點的_不准把_完成_塞回去(proj):
    """做完的東西照三分法「畢業」成現況節點(例:每日報告從 ✅ 待辦變成綠色設施節點)後,
    專案 TODO.md 那行舊的 `- [x]` 還在 —— 不能因此判成「打勾了但圖上沒完成」把 ✅ 塞回標題。"""
    S.sync(fresh(), proj, apply=True)  # 先讓 t2(✅ 已經做完的)以打勾狀態進同步區
    data = fresh()
    node = next(n for n, _ in S.walk(data["nodeData"]) if n["id"] == "t2")
    node["topic"] = "📈 每日報告(平日 07:30 自動送出)"  # 畢業:拿掉 ✅、拿掉 todo
    node.pop("todo")
    node["kind"] = "infra"
    report = S.sync(data, proj, apply=True)
    assert node["topic"] == "📈 每日報告(平日 07:30 自動送出)"  # ⛔ 不准被塞回 ✅
    assert not report["ticked_back"]
    assert report["graduated_ignored"]
    text = (proj / "Work/Alpha/TODO.md").read_text(encoding="utf-8")
    assert "mm:t2" not in text  # 舊行由第②步整段重寫時清掉
