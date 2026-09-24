"""漏寫偵測的把關測試。

它補的是整套系統唯一沒有保底的缺口:「寫」靠規則,AI 忘了寫沒人抓得到。
所以這裡測的是:**該叫的要叫、不該叫的絕對不要叫**(狼來了比漏抓更糟 —— 第一版
報「專案待辦比圖上多」,對每個專案都會叫,那是設計本來就這樣,等於白噪音)。
"""

import json

import pytest

import drift_check as D


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "PROJECTS_ROOT", tmp_path / "proj")
    monkeypatch.setattr(D, "MAPS_DIR", tmp_path / "maps")
    (tmp_path / "maps").mkdir()
    monkeypatch.setattr(D, "SYNC_STATE", tmp_path / "maps" / "_state.json")
    (tmp_path / "proj" / "Demo").mkdir(parents=True)

    def write_map(todos):
        data = {"nodeData": {"id": "root", "topic": "圖", "children": [
            {"id": "p", "topic": "Demo", "source": "Demo", "children": [
                {"id": f"t{i}", "topic": t, "todo": True, "tags": ["P2"]}
                for i, t in enumerate(todos)]}]}}
        (tmp_path / "maps" / "全局總覽圖.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def write_todo(text):
        (tmp_path / "proj" / "Demo" / "TODO.md").write_text(text, encoding="utf-8")

    def write_changelog(text):
        (tmp_path / "proj" / "Demo" / "CHANGELOG.md").write_text(text, encoding="utf-8")

    return type("F", (), {"map": staticmethod(write_map), "todo": staticmethod(write_todo),
                          "changelog": staticmethod(write_changelog), "root": tmp_path})


def tags(findings):
    return [t for _, t, _ in findings]


def test_MUST_不准報_專案待辦比圖上多(fake):
    """圖只放全局級,專案永遠比圖多 —— 報它等於狼來了。"""
    fake.map(["⏳ 全局那一條"])
    fake.todo("# T\n" + "\n".join(f"- [ ] 專案細項 {i}" for i in range(20)))
    assert not any("比圖上多" in t for t in tags(D.check()))


def test_等你的項目圖上沒有就要提醒(fake):
    fake.map(["⏳ 別的事"])
    fake.todo("# T\n- [ ] ⏳ 2026-08-13 等使用者提供文件\n")
    found = D.check()
    assert any("在等你" in t for t in tags(found))
    assert "提供文件" in found[0][2]


def test_MUST_圖上已經有那件事就不要重複叫(fake):
    fake.map(["⏳ 等使用者提供文件"])
    fake.todo("# T\n- [ ] ⏳ 等使用者提供文件\n")
    assert not any("在等你" in t for t in tags(D.check()))


def test_格式讀不到是硬錯(fake):
    fake.map(["⏳ x"])
    fake.todo("# T\n- 用純項目符號寫的\n- 沒有方框\n")
    assert any(t.startswith("⛔") for t in tags(D.check()))


def test_宣告過沒有自己的待辦就不報(fake):
    fake.map(["⏳ x"])
    fake.todo("# T\n<!-- mm:no-own-todos 已暫停 -->\n- 封存說明\n")
    assert not any(t.startswith("⛔") for t in tags(D.check()))


def test_CHANGELOG_有像決定的新條目要提醒(fake):
    fake.map(["⏳ x"])
    fake.todo("# T\n- [ ] 一般的事\n")
    fake.changelog("# CHANGELOG\n\n## 2026-08-08 — 某個數字定案\n")
    (fake.root / "maps" / "_state.json").write_text(
        json.dumps({"Demo": "2026-08-01T10:00:00+08:00"}), encoding="utf-8")
    found = D.check()
    assert any("決定可能沒進圖" in t for t in tags(found))


def test_同步區的行不算專案自己的等你項目(fake):
    """同步區是圖的回音,拿它來比對自己等於自問自答。"""
    fake.map([])
    fake.todo("# T\n<!-- mm:begin -->\n- [ ] ⏳ 圖來的 <!--mm:a-->\n<!-- mm:end -->\n")
    assert not any("在等你" in t for t in tags(D.check()))


def test_掛了心智圖id的等你項不再重複報(fake):
    """專案檔那幾行底下常帶著大量細節(設定的實際狀態、檔名、稽核結果),
    刪掉會真的丟東西 → 改成掛 `<!--mm:id-->` 認親。文字長得完全不像也要認得。"""
    fake.map(["⏳ mini 的 FileVault 沒開,整碟未加密"])
    fake.todo("# T\n- [ ] 🔴 **⏳ 2026/08/11 等使用者 — 磁碟加密是關的,"
              "整碟未加密**(資安稽核發現) <!--mm:t0-->\n")
    assert "👀 這件事在等你,圖上卻沒有" not in tags(D.check())


def test_MUST_掛了不存在的id要報斷鏈而不是靜靜放行(fake):
    """⛔ 這個記號等於「叫警報閉嘴」的開關。不驗證 id 就是給了一個
    打錯字(或圖上那顆後來被刪了)就永遠不再提醒的後門 —— 那比沒有這功能還糟。"""
    fake.map(["完全不相干的事"])
    fake.todo("# T\n- [ ] ⏳ 等使用者決定要不要開磁碟加密 <!--mm:不存在的id-->\n")
    found = D.check()
    assert "⛔ 掛的心智圖 id 不存在(斷鏈)" in tags(found)
    assert any("mm:不存在的id" in d for _, _, d in found), "要講出是哪個 id 斷了"


def test_沒掛id而圖上真的沒有_照樣要報(fake):
    """把關上面兩條沒有把功能整個關掉。"""
    fake.map(["完全不相干的事"])
    fake.todo("# T\n- [ ] ⏳ 等使用者決定要不要開磁碟加密\n")
    assert "👀 這件事在等你,圖上卻沒有" in tags(D.check())


# ── ④ 殭屍待辦:圖上做完了,專案檔卻還留著沒打勾的副本 ──────────────────
# 使用者的回報(2026-08-22):同一件已經完成的事被一問再問。
# 圖上那顆早就 ✅,但兩個專案的 TODO.md 各留一條手寫的沒打勾,
# 而每日排程報告掃的是那些檔 → 做完的事又被撈出來。
# ①②③ 全部只看「專案 → 圖」有沒有漏寫,沒有任何一支在看反方向。

@pytest.fixture
def zfake(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "PROJECTS_ROOT", tmp_path / "proj")
    monkeypatch.setattr(D, "MAPS_DIR", tmp_path / "maps")
    (tmp_path / "maps").mkdir()
    (tmp_path / "proj" / "Demo").mkdir(parents=True)
    (tmp_path / "proj" / "Workspace" / "notes").mkdir(parents=True)

    monkeypatch.setattr(D, "SYNC_STATE", tmp_path / "maps" / "_state.json")

    def build(nodes, todo_text, archive_text=""):
        data = {"nodeData": {"id": "root", "topic": "圖", "children": [
            {"id": "p", "topic": "Demo", "source": "Demo", "children": nodes}]}}
        (tmp_path / "maps" / "全局總覽圖.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "proj" / "Demo" / "TODO.md").write_text(todo_text, encoding="utf-8")
        (tmp_path / "proj" / D.ARCHIVE_REL).write_text(archive_text, encoding="utf-8")
        return data

    return build


def node(nid, topic):
    return {"id": nid, "topic": topic, "todo": True, "tags": ["P2"]}


def test_圖上已完成專案檔還沒打勾要報(zfake):
    data = zfake([node("a1", "✅ 8/20 會員日加碼名額登錄")],
                 "# T\n- [ ] 8/20 會員日加碼名額登錄\n")
    found = D.zombie_todos(data)
    assert len(found) == 1 and "會員日" in found[0][2]


def test_MUST_圖上還沒完成就絕對不准報(zfake):
    """狼來了比漏抓更糟 —— 進行中的待辦本來就該是沒打勾的。"""
    data = zfake([node("a1", "⏳ 8/20 會員日加碼名額登錄")],
                 "# T\n- [ ] 8/20 會員日加碼名額登錄\n")
    assert D.zombie_todos(data) == []


def test_MUST_同步區裡的不算(zfake):
    """同步區是圖的回音,狀態由 sync_todos 負責,在這裡報等於自己罵自己。"""
    data = zfake([node("a1", "✅ 會員日登錄")],
                 "# T\n<!-- mm:begin x -->\n- [ ] 會員日登錄 <!--mm:a1-->\n<!-- mm:end -->\n")
    assert D.zombie_todos(data) == []


def test_掛了id指到已完成那顆就是確定的殭屍(zfake):
    data = zfake([node("a1", "✅ 完全不像的標題")],
                 "# T\n- [ ] 隨便寫的一行字 <!--mm:a1-->\n")
    found = D.zombie_todos(data)
    assert len(found) == 1 and found[0][1].startswith("⛔")


def test_手寫的空框寫法也要抓得到(zfake):
    """有些專案的 TODO.md 用的是 ⬜ 不是 `- [ ]`(格式不合規,但每日排程報告掃得到)。
    抓不到它就等於漏掉當初真正出問題的那個檔。"""
    data = zfake([node("a1", "✅ 8/20 會員日加碼名額登錄")],
                 "# T\n- ⬜ 08/20 16:00 — 會員日加碼名額登錄\n")
    assert len(D.zombie_todos(data)) == 1


def test_已歸檔的要報成歸檔不是斷鏈(zfake):
    """歸檔會把節點移出圖 → 手寫行掛的 id 全部查無此顆。
    報成「斷鏈」是假警報,而 ⛔ 一多就沒有人看 ⛔ 了。"""
    zfake([node("a1", "⏳ 別的事")],
          "# T\n- [ ] ⏳ 2026-08-13 補 Meta 那段的地點 <!--mm:gone-1-->\n",
          "| **補 Meta 那段的地點**(P3) | 2026-08-18 | 2026-08-18 | <!--mm:gone-1-->\n")
    tagset = [t for _, t, _ in D.check()]
    assert any("已完成並歸檔" in t for t in tagset)
    assert not any("斷鏈" in t for t in tagset)


def test_include_archive_False_只看圖上這幾顆(zfake):
    """mm.py 標 ✅ 的當下只想知道「這一顆」有沒有殭屍副本,
    ⛔ 不要把整份完成紀錄的舊帳一起翻出來噴給人看。"""
    data = zfake([node("a1", "⏳ 進行中")],
                 "# T\n- [ ] 補 Meta 那段的地點\n",
                 "| **補 Meta 那段的地點**(P3) | 2026-08-18 | 2026-08-18 |\n")
    assert D.zombie_todos(data, include_archive=False) == []
    assert len(D.zombie_todos(data, include_archive=True)) == 1
