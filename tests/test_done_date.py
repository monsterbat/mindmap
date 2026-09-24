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
def fake_api(monkeypatch):
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


def _node(state):
    return state["data"]["nodeData"]["children"][0]["children"][0]


def test_repro(fake_api, archive_to, capsys):
    today = mm.date.today()
    d10 = (today - mm.timedelta(days=7)).isoformat()   # 「6 天前」= 原本標 ✅ 那天
    d12 = today.isoformat()                            # 今天 = 真正做完那天

    # ① 6 天前 AI 標 ✅(模擬:直接寫成當時 set-status 的結果)
    n = _node(fake_api)
    n["topic"] = "✅ 既有待辦"
    n["detail"] = {"doneOn": d10}

    # ② 今天使用者在任務板取消打勾 —— board.js setStatus 只改 topic,不碰 doneOn
    n["topic"] = "🔜 既有待辦"
    print("UI 取消打勾後 detail =", n["detail"])

    # ③ 今天做完,AI 跑 mm.py set-status 完成
    mm.main(["set-status", "t", "完成"])
    after = _node(fake_api)
    print("重新標 ✅ 後 detail =", after["detail"])
    print("真正完成日應為", d12, " 但 doneOn =", after["detail"]["doneOn"])

    # ④ janitor 跑 autoarchive --days 7
    mm.main(["autoarchive", "--days", "7"])
    left = _node_list(fake_api)
    print("圖上還剩", left)
    print(archive_to.read_text(encoding="utf-8"))

    assert after["detail"]["doneOn"] == d12, "應該記今天,實際記成舊日期"


def _node_list(state):
    return [c["id"] for c in state["data"]["nodeData"]["children"][0].get("children", [])]
