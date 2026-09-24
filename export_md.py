"""把心智圖 JSON 轉成 markdown 快照。

**為什麼有這支:** 正本是心智圖(使用者只在圖上操作),但 JSON 不好 grep、diff 也難讀。
這支產出一份純衍生的 markdown 給 AI 與 git diff 用,使用者不需要看它。

**兩條硬規則(使用者的需求,2026-08-03:「不能有幻覺、流程要固定化」):**

1. **只做映射,不做詮釋。** 每一行文字都直接來自 JSON 的欄位,不補字、不推論、不摘要。
2. **同樣的輸入必產出同樣的輸出。** 沒有時間戳、沒有隨機順序 —— 資料沒變,檔案就一個位元都不會變,
   git 上看到 diff 就代表圖真的改了。

用法::

    python3 export_md.py                 # 全部重產
    python3 export_md.py 全局總覽圖       # 只產一張
"""

import json
import os
import pathlib
import sys

MAPS_DIR = pathlib.Path(
    os.environ.get("MINDMAP_MAPS_DIR", pathlib.Path.home() / "mindmaps")
)
PRIORITIES = ("P1", "P2", "P3", "P4")


def walk(node, depth=0, path=()):
    """深度優先走訪,回傳 (節點, 深度, 祖先標題)。順序=JSON 裡的順序,不排序。"""
    yield node, depth, path
    for child in node.get("children") or []:
        yield from walk(child, depth + 1, path + (node.get("topic", ""),))


def priority_of(node):
    for tag in node.get("tags") or []:
        if tag in PRIORITIES:
            return tag
    return ""


def free_tags(node):
    return [t for t in (node.get("tags") or []) if t not in PRIORITIES]


def suffix(node):
    """節點標題後面要接的記號。順序固定:等級 → 截止日 → 自由標籤 → AI 圈記。"""
    bits = []
    if p := priority_of(node):
        bits.append(f"`{p}`")
    if due := (node.get("detail") or {}).get("due"):
        bits.append(f"⏰{due}")
    bits += [f"`{t}`" for t in free_tags(node)]
    if node.get("aiEdited"):
        bits.append(f"⭕AI改過({node['aiEdited']})")
    return (" " + " ".join(bits)) if bits else ""


def render(data, name):
    root = data["nodeData"]
    nodes = list(walk(root))
    todos = [(n, path) for n, _, path in nodes if n.get("todo")]
    arrows = data.get("arrows") or []
    topics = {n["id"]: n.get("topic", "") for n, _, _ in nodes}

    out = [
        f"# {root.get('topic', name)}",
        "",
        f"> ⚠️ **這份是 `{name}.json` 的自動產出,不要手改** —— 下次重跑會被蓋掉。正本是心智圖。",
        f"> 節點 {len(nodes)} · 待辦 {len(todos)} · 關聯線 {len(arrows)}",
        "",
        "## 結構",
        "",
    ]

    for node, depth, _ in nodes:
        if depth == 0:
            continue
        pad = "  " * (depth - 1)
        kind = "☑ " if node.get("todo") else ""
        out.append(f"{pad}- {kind}{node.get('topic', '')}{suffix(node)}")
        explain = ((node.get("detail") or {}).get("explain") or "").strip()
        for line in explain.splitlines():
            out.append(f"{pad}  > {line}" if line.strip() else f"{pad}  >")

    out += ["", "## 待辦一覽(依優先序,同級照圖上順序)", ""]
    buckets = {p: [] for p in PRIORITIES}
    buckets["(沒等級)"] = []
    for node, path in todos:
        buckets[priority_of(node) or "(沒等級)"].append((node, path))
    for key in (*PRIORITIES, "(沒等級)"):
        rows = buckets[key]
        if not rows:
            continue
        out += [f"### {key}", ""]
        for node, path in rows:
            where = path[-1] if path else ""
            due = (node.get("detail") or {}).get("due")
            out.append(
                f"- {node.get('topic', '')}"
                + (f" ⏰{due}" if due else "")
                + (f" — 在「{where}」" if where else "")
            )
        out.append("")

    out += ["## 關聯線(箭頭 = 資料流向:從產生的地方指向用到的地方)", ""]
    for arrow in arrows:
        src = topics.get(arrow.get("from"), f"?{arrow.get('from')}")
        dst = topics.get(arrow.get("to"), f"?{arrow.get('to')}")
        sign = "⇄" if arrow.get("bidirectional") else "──>"
        out.append(f"- {src} ──[{arrow.get('label', '')}]{sign} {dst}")

    return "\n".join(out).rstrip() + "\n"


def export(name):
    src = MAPS_DIR / f"{name}.json"
    dst = MAPS_DIR / f"{name}.md"
    dst.write_text(render(json.loads(src.read_text()), name), encoding="utf-8")
    return dst


def main(argv):
    names = argv[1:] or sorted(p.stem for p in MAPS_DIR.glob("*.json"))
    for name in names:
        if name.startswith("_"):  # 沙盒不產
            continue
        print(f"✅ {export(name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
