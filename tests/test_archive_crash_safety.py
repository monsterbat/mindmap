"""回歸:歸檔的順序與完成日 —— 兩個都是 2026-08-17 對抗式複查抓到的。"""
import json

import pytest

import mm


@pytest.fixture
def archive_to(tmp_path, monkeypatch):
    f = tmp_path / "完成紀錄.md"
    f.write_text("# 完成紀錄\n\n> 說明\n\n---\n\n## 2026 Q3\n\n"
                 "| 完成的事 | 實際完成日 | 回報日 |\n|---|---|---|\n", encoding="utf-8")
    monkeypatch.setattr(mm, "ARCHIVE_PATH", f)
    return f


@pytest.fixture
def api_409(monkeypatch):
    """PUT 一律 409(使用者開著 /day 拖卡片時,main.py:142 說「幾乎一定會撞」)。"""
    state = {"data": {"nodeData": {
        "id": "root", "topic": "圖", "children": [
            {"id": "p", "topic": "某個項目", "children": [
                {"id": "t", "topic": "✅ 既有待辦", "todo": True, "tags": ["P2"],
                 "detail": {"doneOn": (mm.date.today() - mm.timedelta(days=9)).isoformat(),
                            "explain": "理由"}}]},
        ]}}, "mtime": 111.0, "puts": []}

    def api(path, payload=None):
        if payload is None:
            return {"data": json.loads(json.dumps(state["data"])), "mtime": state["mtime"]}
        state["puts"].append(payload)
        raise SystemExit("⛔ 伺服器回 409:...(409 = 這張圖在你讀取後被別人改過,重跑一次就好)")

    monkeypatch.setattr(mm, "api", api)
    return state


def test_repro_409_留下孤兒列而且每晚重覆(api_409, archive_to, capsys):
    for night in range(3):                       # 連跑三晚,圖始終沒存成
        with pytest.raises(SystemExit):
            mm.main(["autoarchive"])
    body = archive_to.read_text(encoding="utf-8")
    rows = [ln for ln in body.splitlines() if "既有待辦" in ln]
    print("\n完成紀錄裡的列數 =", len(rows))
    for r in rows:
        print("  ", r)
    print("retired =", mm.retired_ids())
    print("圖上還在嗎 =",
          [c["id"] for c in api_409["data"]["nodeData"]["children"][0]["children"]])
    assert len(rows) == 0, "存圖沒成功 → 完成紀錄一列都不該有(修好後的正確行為)"
    assert mm.retired_ids() == set(), "存圖沒成功 → 不該把 id 記成已退休"
    assert [c["id"] for c in api_409["data"]["nodeData"]["children"][0]["children"]] == ["t"]
