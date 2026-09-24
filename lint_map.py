#!/usr/bin/env python3
"""心智圖體檢:把「項目就該是項目、待辦就該是待辦」這組規矩變成機器查得到的東西。

使用者定的判準(2026-08-07):
  「項目的標題不應該是任務本身。如果這個項目還沒完成、需要繼續進行,
    後面肯定會跟著待辦事項,那他本身就不會是一個待辦事項,不然邏輯不通順。」

⚠️ 為什麼要有這支:規則寫在 CLAUDE.md 沒人查等於沒有。2026-08-03 立過
「explain 不准藏待辦」,四天後再掃還是撈出 13 條 —— 靠自律不行,要靠工具。

用法::

    python3 lint_map.py                # 體檢正式圖
    python3 lint_map.py <圖名>          # 體檢指定的圖

⛔ 只讀不寫。發現問題印出來、回傳非 0,要怎麼改由人(或 AI 提案後由人)決定。
"""

import json
import os
import pathlib
import re
import sys

MAPS_DIR = pathlib.Path(
    os.environ.get("MINDMAP_MAPS_DIR", pathlib.Path.home() / "mindmaps")
)
PROJECTS_ROOT = pathlib.Path(
    os.environ.get("MINDMAP_PROJECTS_ROOT", pathlib.Path.home() / "projects")
)
CONFIG_ROOT = pathlib.Path(os.environ.get("MINDMAP_CONFIG_ROOT", pathlib.Path.home() / "claude-config"))

PRIORITIES = {"P1", "P2", "P3", "P4"}
STATUS_MARKS = "⏳🔜⏸✅"
# 說明裡出現這些字 = 那句話在講「還要做的事」,而不是「現在是什麼」
TASK_WORDS = re.compile(
    r"(還沒|尚未|未來要|之後要|下一步|找時間|需要去|要做|待研究|待評估|待決定|待補|應該要|打算|計畫要)"
)


def walk(node, path=""):
    here = f"{path} › {node['topic']}" if path else node["topic"]
    yield node, here
    for child in node.get("children") or []:
        yield from walk(child, here)


def priority_of(node):
    return next((t for t in (node.get("tags") or []) if t in PRIORITIES), None)


def lint(data):
    """回傳 {檢查項: [(id, 說明), ...]}。空的代表全過。"""
    out = {k: [] for k in (
        "待辦沒有優先序", "不是待辦卻掛著優先序", "待辦沒有狀態圖示",
        "長得像任務卻不是待辦", "待辦底下還掛著待辦", "說明裡疑似藏著待辦",
        "說明用了粗體星號", "指針指到不存在的檔", "待辦沒寫為什麼",
    )}
    for node, path in walk(data["nodeData"]):
        topic = (node.get("topic") or "").strip()
        nid = node["id"]
        todo = bool(node.get("todo"))
        pri = priority_of(node)
        marked = bool(topic) and topic[0] in STATUS_MARKS

        if todo and not pri:
            out["待辦沒有優先序"].append((nid, path))
        if not todo and pri:
            out["不是待辦卻掛著優先序"].append((nid, f"{pri} {path}"))
        if todo and not marked:
            out["待辦沒有狀態圖示"].append((nid, path))
        if marked and not todo:
            kids = [c for c in (node.get("children") or []) if c.get("todo")]
            hint = f"底下有 {len(kids)} 條子待辦 → 它是項目,標題別寫成任務" if kids else "底下沒有子待辦 → 它其實就是待辦"
            out["長得像任務卻不是待辦"].append((nid, f"{path}({hint})"))
        if todo and any(c.get("todo") for c in (node.get("children") or [])):
            out["待辦底下還掛著待辦"].append((nid, f"{path} → 它其實是項目"))

        explain = (node.get("detail") or {}).get("explain", "")
        if "**" in explain:
            out["說明用了粗體星號"].append((nid, path))
        # 使用者的需求(2026-08-17):「我應該要知道這個東西是為了什麼做的…不然我在拉動我的個人任務的時候
        # 我不知道這什麼東西。」標題在行程表上是單獨出現的,離開了父節點就沒有脈絡 ——
        # 「將本來的拆分出來」這種標題圖上有兩條,單看誰都不知道在講什麼。
        # ⚠️ 這一項刻意**不是** HARD:22 條舊帳一次全變紅會讓所有新增都寫不進去(罰錯人)。
        if todo and not explain.strip():
            out["待辦沒寫為什麼"].append((nid, path))
        # 只看「項目」的說明。待辦自己的說明本來就在講那件事;指針/設施的說明是在描述別的東西,
        # 都不算「藏」。底下已經有子待辦的也跳過 —— 那句話很可能就是在講那條待辦。
        looking = not todo and node.get("kind") not in ("sop", "tool", "infra") and not any(
            c.get("todo") for c in (node.get("children") or [])
        )
        if looking:
            for line in explain.splitlines():
                if TASK_WORDS.search(line):
                    out["說明裡疑似藏著待辦"].append((nid, f"{path}\n      「{line.strip()[:80]}」"))
                    break

        link = node.get("hyperLink", "")
        if link.startswith("/file/"):
            rel = link[len("/file/"):]
            target = (CONFIG_ROOT / rel[len("@config/"):]) if rel.startswith("@config/") else (PROJECTS_ROOT / rel)
            if not target.is_file():
                out["指針指到不存在的檔"].append((nid, f"{path} → {rel}"))
    return out


# 這幾項是「一定錯」,其餘是「請你看一眼」——後者不該讓 exit code 變紅,不然狼來了
HARD = ("待辦沒有優先序", "不是待辦卻掛著優先序", "待辦沒有狀態圖示",
        "待辦底下還掛著待辦", "說明用了粗體星號", "指針指到不存在的檔")


def main(argv):
    name = argv[1] if len(argv) > 1 else "全局總覽圖"
    data = json.loads((MAPS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    result = lint(data)
    total = sum(len(v) for v in result.values())
    if not total:
        print(f"✅ 「{name}」體檢全過")
        return 0
    for key, items in result.items():
        if not items:
            continue
        print(f"\n{'⛔' if key in HARD else '👀'} {key}({len(items)})")
        for nid, detail in items:
            print(f"   [{nid}] {detail}")
    hard = sum(len(result[k]) for k in HARD)
    print(f"\n⛔ 一定要修的 {hard} 項;👀 請你看一眼的 {total - hard} 項")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
