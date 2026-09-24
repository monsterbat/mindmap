"""心智圖 ↔ 專案 TODO.md 的連動。**文字單向、打勾雙向。**

使用者提的問題(2026-08-03):「我在其他專案更新 TODO,會不會跟心智圖衝突?
沒有辦法我一邊修改完另外一邊就變更嗎?」

## 為什麼不做全面雙向

雙向同步的難題是「兩邊同時改同一條、改成不同的東西」。但使用者在兩邊做的事不一樣:
**打勾**是唯一兩邊都高頻的動作,而它剛好最好合併(狀態是有限的幾個值)。
文字/新增/刪除如果也雙向,衝突面會爆炸而收益極低 —— 沒有人會在兩個地方各打一次同樣的字。

## 規則(刻意寫死,不猜)

- **文字、新增、刪除:心智圖說了算。** 同步區每次重新生成。
- **打勾:專案那邊勾了 → 回寫心智圖成 ✅** 並標 `aiEdited` 圈起來。
- **專案那邊「取消」打勾 → 不自動回寫**,只列進報告。取消很可能是誤觸,而心智圖是正本。
- **`mm:begin`/`mm:end` 之外一個字都不碰。** 專案自己的細項照舊。
- 找不到標記 → 插在第一個 `# ` 標題後面;標記不成對 → **跳過這個檔並報告**,不亂猜。

## 安全

預設 **dry-run**,印出「我要改什麼」;要真的寫必須加 `--apply`。

⚠️ **Blog / Finance / Work / Language 這幾個資料夾不在 git 裡**(2026-08-03 查證),
所以不能靠版本控制救。**每次寫入前一定先備份**到
`mindmaps/.history/todo_sync/<路徑>/<時間戳>.md`(留 10 份),
放在心智圖的歷史區而不是專案資料夾裡,才不會弄髒使用者的專案。

用法::

    python3 sync_todos.py              # 只看要改什麼(不寫)
    python3 sync_todos.py --apply      # 真的寫
"""

import json
import os
import pathlib
import re
import shutil
import sys
from datetime import datetime

MAPS_DIR = pathlib.Path(
    os.environ.get("MINDMAP_MAPS_DIR", pathlib.Path.home() / "mindmaps")
)
PROJECTS_ROOT = pathlib.Path(
    os.environ.get("MINDMAP_PROJECTS_ROOT", pathlib.Path.home() / "projects")
)
BACKUP_DIR = MAPS_DIR / ".history" / "todo_sync"
# 每次 --apply 都記一筆「這個專案什麼時候對過帳」。心智圖靠它顯示「同步:3 天前」——
# ⚠️ 這是把「規則」變成「機制」的關鍵:AI 忘了跑,使用者看圖就會發現(規則沒人查等於沒有)。
STATE_FILE = BACKUP_DIR / "_last_sync.json"
KEEP_BACKUPS = 10
# ⚠️ 這行字是給「在專案裡工作的那條 AI」看的唯一說明,措辭是指令不是許可 ——
# 2026-08-04 抓到某個專案定案了一項決定卻寫在自己的手寫區、沒來這裡打勾,
# 心智圖因此過時而 sync 回報「兩邊一致」。舊字「可以打勾」只說允許,沒說這是義務。
BEGIN = "<!-- mm:begin ⚠️ 心智圖產生。這裡的事做完/定案了→在這裡打勾（會回寫心智圖）。不要改文字或新增 -->"
BEGIN_PREFIX = "<!-- mm:begin"  # 讀取用寬容比對:舊措辭的標記也要認得,不然既有同步區會失聯
END = "<!-- mm:end -->"
ID_RE = re.compile(r"<!--mm:([\w-]+)-->")
DONE = "✅"
PRIORITIES = ("P1", "P2", "P3", "P4")


def backup(path, rel):
    """寫入前先留一份。⚠️ 這幾個專案資料夾**不在 git 裡**,備份是唯一的救命索。"""
    dest = BACKUP_DIR / rel.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    shutil.copy2(path, dest / f"{stamp}.md")
    olds = sorted(dest.glob("*.md"))
    for old in olds[:-KEEP_BACKUPS]:
        old.unlink()
    return dest


def stamp_synced(rels):
    """記錄這幾個專案剛對過帳。**不論有沒有改動都要記** —— 我們要證明的是
    「有跑過」,不是「有改過」。"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    now = datetime.now().astimezone().replace(microsecond=0).isoformat()
    for rel in rels:
        state[rel] = now
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def walk(node, owner=None):
    """走訪整棵樹,回傳 (節點, 它歸屬的專案路徑)。

    歸屬 = **最近的**有 `source` 的祖先(或自己)。沒有就是 None,代表這條只活在心智圖裡。
    """
    owner = node.get("source") or owner
    yield node, owner
    for child in node.get("children") or []:
        yield from walk(child, owner)


def priority_of(node):
    for tag in node.get("tags") or []:
        if tag in PRIORITIES:
            return tag
    return ""


def is_done(node):
    return (node.get("topic") or "").strip().startswith(DONE)


def collect(map_data):
    """每個專案 → 它底下的待辦節點(照圖上的順序)。

    ⚠️ 連「一條待辦都不剩」的專案也要有一筆(空 list)。少了它,待辦從圖上刪掉之後
    專案的同步區會留著孤兒行,而且工具會回報「兩邊一致」—— 那是騙人的
    (2026-08-07 實際發生:某個專案的 4 條併進管道後,TODO.md 還留著)。"""
    groups = {}
    for node, owner in walk(map_data["nodeData"]):
        if not owner:
            continue
        groups.setdefault(owner, [])
        if node.get("todo"):
            groups[owner].append(node)
    return groups


def render_block(nodes):
    lines = [BEGIN]
    for n in nodes:
        box = "[x]" if is_done(n) else "[ ]"
        pri = f" `{priority_of(n)}`" if priority_of(n) else ""
        due = (n.get("detail") or {}).get("due")
        lines.append(
            f"- {box} {(n.get('topic') or '').strip()}{pri}"
            + (f" ⏰{due}" if due else "")
            + f" <!--mm:{n['id']}-->"
        )
    lines.append(END)
    return "\n".join(lines)


def read_block(text):
    """回傳 (區塊起點, 區塊終點, {id: 有沒有打勾})。找不到標記回 (None, None, {})。

    起點用 BEGIN_PREFIX 寬容比對:標記的說明文字改過措辭(2026-08-04),
    但舊措辭的同步區必須照樣認得 —— 重寫時會換成新的 BEGIN。"""
    start = text.find(BEGIN_PREFIX)
    if start < 0:
        return None, None, {}
    end = text.find(END, start)
    if end < 0:
        raise ValueError("有 mm:begin 卻沒有 mm:end —— 不亂猜,跳過這個檔")
    end += len(END)
    ticks = {}
    for line in text[start:end].splitlines():
        m = ID_RE.search(line)
        if m:
            ticks[m.group(1)] = line.strip().startswith(("- [x]", "- [X]"))
    return start, end, ticks


def splice(text, block):
    """把同步區放回去。沒有標記就插在第一個 `# ` 標題後面(沒有標題就放最前面)。"""
    start, end, _ = read_block(text)
    if start is not None:
        return text[:start] + block + text[end:]
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            head = lines[: i + 1]
            tail = lines[i + 1 :]
            return "\n".join(head + ["", block] + tail) + ("\n" if text.endswith("\n") else "")
    return block + "\n\n" + text


def sync(map_data, projects_root, apply=False):
    """回傳報告 dict。apply=False 時什麼都不寫。"""
    report = {"ticked_back": [], "stale_file": [], "graduated_ignored": [],
              "written": [], "skipped": [], "missing": []}
    by_id = {n["id"]: n for n, _ in walk(map_data["nodeData"])}

    for rel, nodes in sorted(collect(map_data).items()):
        todo_path = pathlib.Path(projects_root) / rel / "TODO.md"
        if not todo_path.is_file():
            report["missing"].append(rel)
            continue
        text = todo_path.read_text(encoding="utf-8")
        try:
            start, _, ticks = read_block(text)
        except ValueError as e:
            report["skipped"].append(f"{rel}: {e}")
            continue
        # 沒待辦、本來也沒同步區 → 不要無中生有插一個空區塊進去
        if not nodes and start is None:
            continue

        # ① 專案 → 心智圖:只回寫「勾起來了但圖上還沒完成」的
        for nid, ticked in ticks.items():
            node = by_id.get(nid)
            if not node:
                continue
            # ⛔ 已經不是待辦節點的,不准回寫。
            # 2026-08-07 差點出問題:做完的東西照三分法「畢業」成現況節點(例:某個每日報告從
            # ✅ 待辦變成綠色的設施節點)之後,專案 TODO.md 那行舊的 `- [x]` 還在,
            # 這裡就會判成「打勾了但圖上沒完成」,把 ✅ 硬塞回標題,把畢業整個撤銷。
            # 那一行會在下面第②步整段重寫時自然消失,所以這裡直接跳過就好。
            if not node.get("todo"):
                report["graduated_ignored"].append(f"{rel}: {node.get('topic')}")
                continue
            if ticked and not is_done(node):
                topic = (node.get("topic") or "").strip()
                topic = re.sub(r"^[⏳🔜⏸️⏸🎯]\s*", "", topic)
                node["topic"] = f"{DONE} {topic}"
                node["aiEdited"] = f"同步:在 {rel}/TODO.md 打勾了"
                report["ticked_back"].append(f"{rel}: {topic}")
            elif not ticked and is_done(node):
                # ⛔ 這不是「取消打勾」(2026-09-23 更正)。
                # 下面第 ② 步會把同步區整段照心智圖重畫,而 render_block 對已完成的
                # 節點就是寫 `[x]` —— 所以這個狀態**這一輪自己就會被補好**。
                # ⭐ 舊版把它報成「⚠️ 專案那邊取消打勾了」,像是有人動了什麼;
                #   實測一次重排報 11 條,其中 9 條來自同一個專案,
                #   全部都只是專案檔還沒跟上。每週都來一次,而且每次都要人去看一遍。
                # ⚠️ 真正的「使用者取消打勾」在這個設計下看不出來,也不需要看 ——
                #   心智圖是正本,專案檔每輪都會被重畫成跟它一樣。
                report["stale_file"].append(f"{rel}: {node.get('topic')}")

        # ② 心智圖 → 專案:同步區整段重新生成(文字以圖為準)
        new_text = splice(text, render_block(nodes))
        if new_text != text:
            report["written"].append(f"{rel}({len(nodes)} 條)")
            if apply:
                backup(todo_path, rel)  # ⛔ 先備份再寫,順序不能顛倒
                todo_path.write_text(new_text, encoding="utf-8")
    if apply:
        stamp_synced(sorted(collect(map_data)))
    return report


def main(argv):
    apply = "--apply" in argv
    src = MAPS_DIR / "全局總覽圖.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    report = sync(data, PROJECTS_ROOT, apply=apply)
    if apply and report["ticked_back"]:
        src.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    labels = {
        "ticked_back": "✅ 專案那邊打勾了 → 已回寫心智圖(圖上會圈起來)",
        "stale_file": "ℹ️ 專案檔還沒跟上心智圖 → 加 --apply 就會自動補上 [x],不用你做什麼",
        "graduated_ignored": "ℹ️ 這些已經不是待辦了(畢業成現況節點),同步區的舊行會被清掉",
        "written": "📝 同步區有更新",
        "skipped": "⛔ 跳過(標記不成對)",
        "missing": "❓ 找不到 TODO.md",
    }
    empty = True
    for key, label in labels.items():
        if report[key]:
            empty = False
            print(f"\n{label}")
            for line in report[key]:
                print(f"   • {line}")
    if empty:
        print("兩邊一致,沒事。")
    elif not apply:
        print("\n（這是 dry-run,什麼都沒寫。要真的寫請加 --apply）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
