"""任務板的把關測試 —— 它是心智圖的第二個視圖,不是第二份資料。"""

import main


def test_board_頁面存在():
    assert (main.static_file("board.html")).is_file()
    assert (main.static_file("board.js")).is_file()
    assert (main.static_file("board.css")).is_file()


def test_MUST_任務板不另外存一份資料():
    """⛔ 它只能讀寫 /api/maps/<圖> —— 自己存一份就會 drift,那是整套設計最忌諱的事。"""
    js = (main.static_file("board.js")).read_text(encoding="utf-8")
    assert "/api/maps/" in js
    assert "localStorage" not in js, "任務板不准把任務狀態存在瀏覽器裡"


def test_MUST_改狀態要帶著_base_mtime():
    """沒有它就沒有衝突偵測 —— 會蓋掉心智圖那頁或 AI 剛存的東西。"""
    js = (main.static_file("board.js")).read_text(encoding="utf-8")
    assert "base_mtime" in js


# ── ❌ 不做了(使用者的需求,2026-08-22:「應該也有取消任務吧」)────────
# 在這之前畫面上只有「完成」一個出口 → 不想做的事只能硬標完成
# (完成紀錄會多一筆從沒做過的事)或爛在圖上,之後查「這件事做了沒」就會查到假的。

def test_任務板要有不做了這條路():
    js = (main.static_file("board.js")).read_text(encoding="utf-8")
    assert "不做了" in js
    assert "/drop" in js


def test_排今天也要有不做了這條路():
    """⛔ 兩個視圖要一致 —— 只有一邊有的話,使用者在另一邊會以為這功能不存在。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    assert "不做了" in js
    assert "/drop" in js


def test_MUST_不做了一定要問理由():
    """一年後看到「這件事不做了」而沒有理由 = 沒有紀錄,
    下一輪規劃它會原封不動地被重新提出來,然後再評估一次。"""
    for name in ("board.js", "day.js"):
        js = main.static_file(name).read_text(encoding="utf-8")
        assert "prompt(" in js, f"{name} 沒有問理由"
        assert "why" in js, f"{name} 沒有把理由送出去"


def test_MUST_伺服器端也要擋掉空理由():
    """⛔ 前端擋不算數 —— 別的程式直接打 API 一樣要擋。"""
    import pytest
    with pytest.raises(main.ApiError) as e:
        main.drop_node("全局總覽圖", "任何id", {"why": "   "})
    assert "理由" in e.value.detail
