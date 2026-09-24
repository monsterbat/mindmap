"""待辦事項頁(/topics)的把關測試 —— 它是心智圖的第五個視圖,不是第五份資料。

⚠️ 這裡只驗「讀程式碼看得出來」的那幾條。真正的行為(分母有沒有漏、拖曳存不存得住、
   完成日有沒有當場寫)在 `verify_topics.py`,那支要開瀏覽器,刻意不進 `make check`。
"""

import pytest

import main


def test_topics_頁面存在():
    for name in ("topics.html", "topics.js", "topics.css"):
        assert main.static_file(name).is_file(), name


def test_MUST_不另外存一份資料():
    """⛔ 它只能讀寫 /api/maps/<圖> —— 自己存一份就會 drift,那是整套設計最忌諱的事。"""
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    assert "/api/maps/" in js
    assert "localStorage" not in js, "待辦事項頁不准把任務狀態存在瀏覽器裡"


def test_MUST_打勾要帶著_base_mtime():
    """沒有它就沒有衝突偵測 —— 會蓋掉心智圖那頁或 AI 剛存的東西。"""
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    assert "base_mtime" in js


def test_MUST_完成日要在按下去的當下寫():
    """2026-08-24 出過的問題:/day 標完成沒寫 doneOn,等 7 天後 janitor 補一個「今天」,
    那個日期最多錯 7 天,而且沒有人看得出它是補的。"""
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    assert "doneOn" in js


def test_MUST_使用者自己按的不准標成AI改的():
    """紫圈的意思是「AI 動過、你還沒看」。自己按的也圈起來,那個圈就沒有訊息量了。"""
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    assert "delete n.aiEdited" in js
    assert "scEdited" in js


# ── 一行的欄位順序(2026-09-08 定案)────────────────────────────────
# 需求是:「主題像是 Workspace、Blog、Music 這種東西應該是要放最前面的,
# 然後他的優先序的應該要排在更前面,就是第一個就是優先區、再來就是分類、再來才是內容。」

def test_MUST_欄位順序是優先區_分類_內容():
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    i_pri = js.index('class="pri ')
    i_dom = js.index('class="tdomain"')
    i_name = js.index('class="tname"')
    assert i_pri < i_dom < i_name, "順序必須是 優先區 → 分類 → 內容"


def test_MUST_排序要能自己調而且反悔得了():
    """⛔ 一個「只進不出」的排序,他不敢亂拖。"""
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    html = (main.static_file("topics.html")).read_text(encoding="utf-8")
    assert "viewOrder" in js or "view-order" in js
    assert "reset-order" in html, "頁面上要有一個「順序改回自動」的出口"
    assert '"reset": true' in js or "reset: true" in js


def test_MUST_拖曳不用HTML5的drag_and_drop():
    """①手機與平板的瀏覽器完全不支援 ②draggable 一設下去標題文字就選不起來了。"""
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    assert "pointerdown" in js
    assert "dataTransfer" not in js, "⛔ 又改回 HTML5 DnD 了,手機上會整個不能用"
    css = (main.static_file("topics.css")).read_text(encoding="utf-8")
    assert "touch-action" in css, "少了它手機上按住把手會變成捲頁"


# ── view-order API ───────────────────────────────────────────────

def test_view_order_只收一串id():
    with pytest.raises(main.ApiError) as e:
        main.patch_view_order("全局總覽圖", {"order": "不是陣列"})
    assert "order" in e.value.detail


def test_MUST_view_order_不准碰別的欄位():
    """⛔ 它是拖排序用的,開放太多就會在拖一下的時候誤傷 due/planned。"""
    src = (main.REPO / "main.py").read_text(encoding="utf-8") \
        if hasattr(main, "REPO") else __import__("pathlib").Path(main.__file__).read_text(encoding="utf-8")
    # ⚠️ 只切「這一個函式」:2026-09-17 在它後面插了 quick_todo(那支本來就要寫 topic),
    #    原本切到 drop_node 為止,就把別人的程式也算進來、誤報成它碰了 topic。
    start = src.index("def patch_view_order")
    body = src[start:src.index("\ndef ", start + 10)]
    for forbidden in ('"due"', '"planned"', '"effort"', '"topic"'):
        assert forbidden not in body, f"patch_view_order 碰到了 {forbidden}"


def test_MUST_四個視圖都連得到這一頁():
    """使用者的痛點是「找不到東西」—— 一個想不起來網址的分頁等於不存在。

    ⚠️ 2026-09-09 起連結由共用的 `nav.js` 產生,不再寫在各頁 HTML
       (使用者:「介面都長得不一樣、位置跳來跳去」)。所以驗的是那一份正本。
    """
    nav = (main.static_file("nav.js")).read_text(encoding="utf-8")
    assert '"/topics"' in nav, "共用導覽列裡沒有待辦事項"
    for name in ("index.html", "board.html", "day.html"):
        html = main.static_file(name).read_text(encoding="utf-8")
        assert "/static/js/nav.js" in html, f"{name} 沒有接上共用導覽列"


def test_MUST_等條件的標籤讀的是_mm_py_寫的那個欄位():
    """2026-09-08 第一版讀 detail.waitUntil,而 mm.py wait 寫的是 detail.until ——
    「⏸ 等某件事」的標籤從上線那天起一次都沒出現過,沒有任何錯誤訊息。
    ⚠️ 兩邊的欄位名必須一起改,只改一邊就會再安靜地消失一次。"""
    import pathlib
    mm = (pathlib.Path(main.__file__).parent / "mm.py").read_text(encoding="utf-8")
    assert 'det["until"]' in mm, "mm.py 的 wait 不再寫 detail.until 了,這條測試要跟著改"
    js = (main.static_file("topics.js")).read_text(encoding="utf-8")
    assert "d.until" in js
    assert "waitUntil" not in js.replace("不是 waitUntil", "").replace("寫成 waitUntil", "")
