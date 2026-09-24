"""export_md 的把關測試。

使用者的需求(2026-08-03):「你要確認好你的轉換的程式是沒有問題的,
然後你的整個 SOP、你的整個操作流程要定性化要固定化,不能有幻覺。」

所以這裡驗的不是「好不好看」,是三件事:
① 不漏(每個節點/待辦/關聯線都在)
② 不編(輸出的每一行文字都找得到來源)
③ 不飄(同樣的輸入必產出同樣的輸出)
"""

import json

import export_md

SAMPLE = {
    "nodeData": {
        "id": "root",
        "topic": "測試圖",
        "children": [
            {
                "id": "a",
                "topic": "🔜 結構節點",
                "tags": ["P2", "自由標籤"],
                "detail": {"explain": "第一行\n第二行", "due": "2026-08-13"},
                "children": [
                    {"id": "a1", "topic": "⏳ 待辦一", "todo": True, "tags": ["P1"],
                     "detail": {"due": "2026-11-06"}},
                    {"id": "a2", "topic": "✅ 待辦二", "todo": True},
                ],
            },
            {"id": "b", "topic": "另一個", "aiEdited": "2026-08-03 補說明"},
        ],
    },
    "arrows": [
        {"id": "r1", "label": "餵給", "from": "a", "to": "b"},
        {"id": "r2", "label": "互相同步", "from": "b", "to": "a", "bidirectional": True},
    ],
}


def all_nodes(data):
    return [n for n, _, _ in export_md.walk(data["nodeData"])]


def test_每個節點都出現在結構段():
    md = export_md.render(SAMPLE, "測試圖")
    for node in all_nodes(SAMPLE):
        assert node["topic"] in md, f"節點漏了:{node['topic']}"


def test_每條待辦都出現在待辦一覽():
    md = export_md.render(SAMPLE, "測試圖")
    section = md.split("## 待辦一覽")[1].split("## 關聯線")[0]
    assert "待辦一" in section and "待辦二" in section
    # 依優先序分組,而且帶著截止日與所在位置
    assert "### P1" in section
    assert "⏰2026-11-06" in section
    assert "在「🔜 結構節點」" in section


def test_每條關聯線都出現而且雙向標得出來():
    md = export_md.render(SAMPLE, "測試圖")
    assert "🔜 結構節點 ──[餵給]──> 另一個" in md
    assert "另一個 ──[互相同步]⇄ 🔜 結構節點" in md


def test_說明逐行照抄不摘要():
    md = export_md.render(SAMPLE, "測試圖")
    assert "> 第一行" in md and "> 第二行" in md


def test_等級截止日標籤與AI圈記都標出來():
    md = export_md.render(SAMPLE, "測試圖")
    assert "`P2`" in md and "⏰2026-08-13" in md and "`自由標籤`" in md
    assert "⭕AI改過(2026-08-03 補說明)" in md


def test_不編造內容_每行的字都來自來源():
    """⛔ 防幻覺:除了固定的樣板字,輸出裡不該出現來源沒有的中文。"""
    md = export_md.render(SAMPLE, "測試圖")
    source = json.dumps(SAMPLE, ensure_ascii=False)
    template = (
        "這份是的自動產出不要手改下次重跑會被蓋掉正本是心智圖節點待辦關聯線結構"
        "一覽依優先序同級照圖上順序沒等級箭頭資料流向從產生的地方指向用到的地方在"
        "改過json"
    )
    for ch in md:
        if "一" <= ch <= "鿿":
            assert ch in source or ch in template, f"出現了來源沒有的字:{ch}"


def test_同樣的輸入必產出同樣的輸出():
    """⛔ 不能有時間戳之類每次都變的東西 —— 有 diff 就代表圖真的改了。"""
    assert export_md.render(SAMPLE, "測試圖") == export_md.render(SAMPLE, "測試圖")


def test_節點與待辦的數量寫在抬頭而且是真的():
    md = export_md.render(SAMPLE, "測試圖")
    nodes = all_nodes(SAMPLE)
    todos = [n for n in nodes if n.get("todo")]
    assert f"節點 {len(nodes)} · 待辦 {len(todos)} · 關聯線 2" in md


def test_指到不存在節點的線不會靜默消失():
    broken = json.loads(json.dumps(SAMPLE))
    broken["arrows"].append({"id": "r3", "label": "斷的", "from": "nope", "to": "a"})
    md = export_md.render(broken, "測試圖")
    assert "?nope" in md, "斷掉的線要看得出來,不能默默不見"
