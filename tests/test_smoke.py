import json
import threading
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest

import main


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "MAPS_DIR", tmp_path)
    srv = main.build_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def req(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


MAP_DATA = {"nodeData": {"id": "root", "topic": "測試", "children": []}}
NAME = quote("測試圖")


def test_health(base):
    status, out = req("GET", base + "/api/health")
    assert status == 200 and out["ok"] is True


def test_index_serves_editor(base):
    with urllib.request.urlopen(base + "/") as resp:
        assert resp.status == 200
        assert "MindElixir" in resp.read().decode()


def test_put_get_list_roundtrip(base, tmp_path):
    status, out = req("PUT", base + "/api/maps/" + NAME, {"data": MAP_DATA, "base_mtime": None})
    assert status == 200
    mtime = out["mtime"]

    status, out = req("GET", base + "/api/maps/" + NAME)
    assert status == 200
    assert out["data"] == MAP_DATA and out["mtime"] == mtime

    status, out = req("GET", base + "/api/maps")
    assert [m["name"] for m in out] == ["測試圖"]

    # 檔案落地且是可讀的 JSON(AI 用文字工具讀的就是這份)
    on_disk = json.loads((tmp_path / "測試圖.json").read_text())
    assert on_disk == MAP_DATA


def test_put_conflict_on_stale_base_mtime(base):
    status, out = req("PUT", base + "/api/maps/a", {"data": MAP_DATA, "base_mtime": None})
    mtime = out["mtime"]

    status, out = req("PUT", base + "/api/maps/a", {"data": MAP_DATA, "base_mtime": mtime})
    assert status == 200
    new_mtime = out["mtime"]

    if new_mtime - mtime > 1e-4:
        status, _ = req("PUT", base + "/api/maps/a", {"data": MAP_DATA, "base_mtime": mtime})
        assert status == 409

    status, _ = req("PUT", base + "/api/maps/a", {"data": MAP_DATA, "base_mtime": None})
    assert status == 200


def test_bad_names_rejected(base):
    for bad in [quote("../escape", safe=""), quote("a/b", safe=""), ".hidden"]:
        status, _ = req("PUT", base + "/api/maps/" + bad, {"data": MAP_DATA, "base_mtime": None})
        assert status in (400, 404), bad


def test_history_keeps_previous_version(base, tmp_path):
    """覆寫前要留舊版:誤覆蓋(AI/另一視窗/測試腳本)時救得回來。"""
    v1 = {"nodeData": {"id": "root", "topic": "第一版", "children": []}}
    v2 = {"nodeData": {"id": "root", "topic": "第二版", "children": []}}
    req("PUT", base + "/api/maps/h", {"data": v1, "base_mtime": None})
    req("PUT", base + "/api/maps/h", {"data": v2, "base_mtime": None})

    hist = sorted((tmp_path / ".history" / "h").glob("*.json"))
    assert len(hist) == 1, "第二次寫入前應留下第一版"
    assert json.loads(hist[0].read_text())["nodeData"]["topic"] == "第一版"
    # 備份目錄不可以出現在圖清單裡
    _, listed = req("GET", base + "/api/maps")
    assert [m["name"] for m in listed] == ["h"]


def test_bad_data_rejected(base):
    status, _ = req("PUT", base + "/api/maps/x", {"data": {"沒有nodeData": 1}, "base_mtime": None})
    assert status == 400


def test_MUST_外部改動重載時不准把視角拉回正中間():
    """使用者的回報(2026-08-11):「心智圖只要從行程那邊有改動東西,他就會跳回到正中間,
    能不能讓他不要跳回去啊?」

    使用者在 300 個節點的圖上找到位置正在看某一支,結果 /day 拖一下、或排程的程式改一下,
    就整個彈回正中間 —— 等於每次都要重找。
    ⚠️ 平移在 map 的 transform、縮放另外記在 scaleVal,**兩個都要還原**。
    """
    js = (main.static_file("app.js")).read_text(encoding="utf-8")
    assert "function viewState()" in js and "function applyView(" in js
    assert "await openMap(currentName, true)" in js, "外部改動重載要保留視角"
    body = js[js.index("function applyView("):js.index("function panBy(")]
    assert "scaleVal" in body and "transform" in body, "平移與縮放都要還原"
    # 手動換圖(選單/hash)仍然要置中,不然新開一張圖會停在莫名其妙的位置
    assert "else recenter();" in js
