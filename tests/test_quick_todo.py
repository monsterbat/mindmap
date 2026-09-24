"""每一頁右下角「＋」隨手記(2026-09-17)的伺服器端把關。

使用者的需求(2026-09-17):「有時候我突然想到一些任務…好像就沒有辦法直接加在我們這個上面。」
⛔ 全部寫進 tmp,不准碰正式圖。
"""

import json

import pytest

import main


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    maps = tmp_path / "mindmaps"
    maps.mkdir()
    data = {"nodeData": {"id": "root", "topic": "圖", "children": [
        {"id": "dom", "topic": "💼 Work", "children": [
            {"id": "t1", "topic": "⏳ 做一件事", "todo": True, "tags": ["P1"]},
        ]},
        {"id": "ai-004", "topic": "🎯 現在的階段", "children": []},
        {"id": "loose", "topic": "⏳ 掛在根底下的待辦", "todo": True, "tags": ["P3"]},
    ]}}
    (maps / "全局總覽圖.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "MAPS_DIR", maps)
    return maps


def load(maps):
    return json.loads((maps / "全局總覽圖.json").read_text(encoding="utf-8"))["nodeData"]


def find(node, nid):
    if node.get("id") == nid:
        return node
    for c in node.get("children") or []:
        hit = find(c, nid)
        if hit:
            return hit
    return None


def test_沒選放哪裡就進收件匣_而且收件匣是用到才開(sandbox):
    assert find(load(sandbox), main.INBOX_ID) is None, "空的收件匣不該先掛在圖上"
    out = main.quick_todo("全局總覽圖", {"text": "問房東押金什麼時候退"})
    root = load(sandbox)
    inbox = find(root, main.INBOX_ID)
    assert inbox is not None and inbox in root["children"], "收件匣要開在根底下"
    node = find(root, out["id"])
    assert node in inbox["children"]
    assert node["topic"] == "⏳ 問房東押金什麼時候退"
    assert node["todo"] is True and node["tags"] == ["P2"]


def test_MUST_是使用者自己按的_不准標成AI改的(sandbox):
    out = main.quick_todo("全局總覽圖", {"text": "x"})
    node = find(load(sandbox), out["id"])
    assert "scEdited" in node
    assert "aiEdited" not in node, "紫圈的意思是「AI 動過你還沒看」"
    assert node["detail"]["explain"], "沒有說明的話,一個月後他不知道那是什麼"


def test_可以直接放進某個領域(sandbox):
    out = main.quick_todo("全局總覽圖", {"text": "寄文件", "parent": "dom", "pri": "P1"})
    dom = find(load(sandbox), "dom")
    assert out["id"] in [c["id"] for c in dom["children"]]
    assert find(load(sandbox), out["id"])["tags"] == ["P1"]


@pytest.mark.parametrize("parent", ["t1", "ai-004", "loose", "不存在", "root"])
def test_MUST_不准塞進任意節點(sandbox, parent):
    """⛔ 網頁傳來的 parent 只能是收件匣或領域 —— 不然一個錯的 id 就能把東西塞進任何角落。"""
    with pytest.raises(main.ApiError) as e:
        main.quick_todo("全局總覽圖", {"text": "x", "parent": parent})
    assert e.value.status == 400


@pytest.mark.parametrize("payload,msg", [
    ({"text": "   "}, "沒有內容"),
    ({"text": "字" * 201}, "太長"),
    ({"text": "x", "pri": "P9"}, "P1–P4"),
])
def test_壞輸入要擋下來(sandbox, payload, msg):
    with pytest.raises(main.ApiError) as e:
        main.quick_todo("全局總覽圖", payload)
    assert msg in e.value.detail


def test_連按兩下不會撞號(sandbox, monkeypatch):
    monkeypatch.setattr(main.time, "time_ns", lambda: 1_789_000_000_000_000_000)
    a = main.quick_todo("全局總覽圖", {"text": "一"})["id"]
    b = main.quick_todo("全局總覽圖", {"text": "二"})["id"]
    assert a != b


def test_換行與多餘空白會被收掉(sandbox):
    out = main.quick_todo("全局總覽圖", {"text": "  買  牛奶\n\n明天  "})
    assert find(load(sandbox), out["id"])["topic"] == "⏳ 買 牛奶 明天"


def test_下拉選單_收件匣排第一_不列現在的階段與根底下的待辦(sandbox):
    ids = [t["id"] for t in main.quick_targets("全局總覽圖")["targets"]]
    assert ids[0] == main.INBOX_ID
    assert "dom" in ids
    assert "ai-004" not in ids and "loose" not in ids


def test_收件匣被搬走或改名_照樣找得到(sandbox):
    main.quick_todo("全局總覽圖", {"text": "第一件"})
    data = json.loads((sandbox / "全局總覽圖.json").read_text(encoding="utf-8"))
    root = data["nodeData"]
    inbox = next(c for c in root["children"] if c["id"] == main.INBOX_ID)
    root["children"].remove(inbox)
    inbox["topic"] = "📥 隨手記"
    root["children"][0]["children"].append(inbox)           # 搬到 Work 底下
    (sandbox / "全局總覽圖.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    main.quick_todo("全局總覽圖", {"text": "第二件"})
    root = load(sandbox)
    assert sum(1 for c in root["children"] if c["id"] == main.INBOX_ID) == 0, "不該再開第二個收件匣"
    assert len(find(root, main.INBOX_ID)["children"]) == 2


# ── 前端(讀程式碼看得出來的那幾條;真正的行為在 verify_nav.py)──────────────

def test_四頁共用的右下角加號在_nav_js_裡():
    """⛔ 放在共用的 nav.js,四頁位置才不會又各寫各的(使用者抱怨過「跳來跳去」)。"""
    js = (main.static_file("nav.js")).read_text(encoding="utf-8")
    assert "qa-fab" in js and "/quick-todo" in js and "/quick-targets" in js
    for name in ("topics.js", "board.js", "day.js", "app.js"):
        other = main.static_file(name).read_text(encoding="utf-8")
        assert "qa-fab" not in other, f"{name} 自己又做了一顆加號"


def test_MUST_選字的_Enter_不算送出():
    """用注音/拼音選字時按的 Enter 也會觸發 keydown。不擋的話,他打中文會被截斷送出。
    2026-09-17 做加號時才發現待辦事項頁的「＋ 加進」框從第一版就沒擋。"""
    for name in ("nav.js", "topics.js"):
        js = main.static_file(name).read_text(encoding="utf-8")
        assert "isComposing" in js, f"{name} 沒擋選字的 Enter"


def test_MUST_存失敗不准清掉他打的字():
    js = (main.static_file("nav.js")).read_text(encoding="utf-8")
    body = js[js.index("async function submit"):]
    ok_part = body[:body.index("catch (e)")]
    err_part = body[body.index("catch (e)"):body.index("finally")]
    assert 'inp.value = ""' in ok_part, "成功才清空"
    assert 'inp.value = ""' not in err_part, "⛔ 失敗時清空 = 他突然想到的東西就丟了"


def test_MUST_心智圖頁要先存完再送():
    """不然心智圖下一次存檔會跳「圖被別人改過了」。"""
    js = (main.static_file("nav.js")).read_text(encoding="utf-8")
    assert "isDirty" in js and "saveMap" in js and "pollExternal" in js
    app = (main.static_file("app.js")).read_text(encoding="utf-8")
    for fn in ("function isDirty", "async function saveMap", "async function pollExternal"):
        assert fn in app, f"app.js 的 {fn} 改名了,nav.js 會安靜地叫不到"


def test_三頁加完東西都會重新載入():
    for name in ("topics.js", "board.js", "day.js"):
        js = main.static_file(name).read_text(encoding="utf-8")
        assert '"sc:todo-added"' in js, f"{name} 加完東西不會更新畫面"


def test_收件匣在待辦事項頁排第一():
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    assert "isInbox" in js
