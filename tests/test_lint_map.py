"""lint_map 的把關測試。

它是「規則變成機制」的那一半 —— 規則寫在 CLAUDE.md 沒人查等於沒有
(2026-08-03 立過「explain 不准藏待辦」,四天後再掃還是撈出 13 條)。
所以這裡測的是:該抓的抓得到、不該吵的不要吵(狼來了比漏抓更糟)。
"""

import lint_map as L


def m(*children):
    return {"nodeData": {"id": "root", "topic": "圖", "children": list(children)}}


def test_待辦沒有優先序要抓出來():
    r = L.lint(m({"id": "t1", "topic": "⏳ 做一件事", "todo": True}))
    assert r["待辦沒有優先序"] == [("t1", "圖 › ⏳ 做一件事")]


def test_項目掛著優先序要抓出來():
    """等級屬於「要做的事」(2026-08-07 定案)。項目也有等級的話,P1 就失去意義了。"""
    r = L.lint(m({"id": "p1", "topic": "某個項目", "tags": ["P1"]}))
    assert [i[0] for i in r["不是待辦卻掛著優先序"]] == ["p1"]


def test_長得像任務卻不是待辦_有沒有子待辦要講不同的話():
    r = L.lint(m(
        {"id": "a", "topic": "⏳ 其實是項目", "children": [
            {"id": "a1", "topic": "⏳ 子待辦", "todo": True, "tags": ["P2"]}]},
        {"id": "b", "topic": "⏳ 其實就是待辦"},
    ))
    got = dict(r["長得像任務卻不是待辦"])
    assert "它是項目" in got["a"]
    assert "它其實就是待辦" in got["b"]


def test_待辦底下掛待辦_代表它其實是項目():
    r = L.lint(m({"id": "t", "topic": "⏳ 大事", "todo": True, "tags": ["P1"], "children": [
        {"id": "s", "topic": "⏳ 小事", "todo": True, "tags": ["P1"]}]}))
    assert [i[0] for i in r["待辦底下還掛著待辦"]] == ["t"]


def test_MUST_待辦自己的說明講那件事_不算藏():
    """狼來了比漏抓更糟:待辦的說明本來就在講那件事,吵它會讓人不想看報告。"""
    r = L.lint(m({"id": "t", "topic": "⏳ 做 X", "todo": True, "tags": ["P1"],
                  "detail": {"explain": "下一步:等對方回覆。"}}))
    assert r["說明裡疑似藏著待辦"] == []


def test_MUST_指針節點的說明不算藏():
    r = L.lint(m({"id": "s", "topic": "📐 某 SOP", "kind": "sop",
                  "detail": {"explain": "什麼時候用:還沒整理過的東西要整理時。"}}))
    assert r["說明裡疑似藏著待辦"] == []


def test_項目說明裡的任務句要抓出來():
    r = L.lint(m({"id": "p", "topic": "保險",
                  "detail": {"explain": "現況如此。\n未來要整理成一張表。"}}))
    assert [i[0] for i in r["說明裡疑似藏著待辦"]] == ["p"]


def test_底下已經有子待辦的項目_不重複吵():
    r = L.lint(m({"id": "p", "topic": "保險", "detail": {"explain": "未來要整理成一張表。"},
                  "children": [{"id": "c", "topic": "⏳ 整理成表", "todo": True, "tags": ["P2"]}]}))
    assert r["說明裡疑似藏著待辦"] == []


def test_指針指到不存在的檔要抓出來():
    r = L.lint(m({"id": "s", "topic": "📐 X", "kind": "sop",
                  "hyperLink": "/file/Workspace/notes/根本沒有這份.md"}))
    assert [i[0] for i in r["指針指到不存在的檔"]] == ["s"]


def test_乾淨的圖要全過():
    r = L.lint(m(
        {"id": "p", "topic": "某個項目", "detail": {"explain": "它是什麼。"}, "children": [
            {"id": "t", "topic": "⏳ 要做的事", "todo": True, "tags": ["P2"],
             "detail": {"explain": "為什麼要做它。"}}]},
    ))
    assert not any(r.values())
