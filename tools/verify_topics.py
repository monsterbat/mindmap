"""待辦事項(/topics):真的開一個瀏覽器把它點過一輪。

**為什麼要有這支:** 這一頁是使用者「檢視自己還有什麼沒做」的地方,所以它最不能犯的錯
是**安靜地漏掉幾件**。而「漏掉」在畫面上長得跟「本來就沒有」一模一樣 ——
沒有錯誤訊息、沒有紅字、數字看起來也很合理。

⭐ 第一項就是分母對帳(Workspace CLAUDE.md「⛔ 要掃過全部的工具不准用白名單」那條):
   **把圖上真正有幾件待辦印出來,跟畫面上看得到幾件對。** 對不上就是漏了。

⛔ 全程用正式圖的**複本**(temp 目錄)+ 自己起的臨時埠,絕不碰正本、也不佔 8030。

跑法:make verify-topics  (或 uv run --with playwright python verify_topics.py)
⚠️ 需要 Chromium,所以刻意**不放進 `make check`** —— 沒有瀏覽器的機器不該因此變紅。
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent
REAL = pathlib.Path(os.environ.get(
    "MINDMAP_MAPS_DIR", pathlib.Path.home() / "mindmaps"))
OUT = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "mindmap-verify"
OUT.mkdir(parents=True, exist_ok=True)
MAP = "全局總覽圖"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def count_todos(maps_dir):
    """圖上真正有幾件待辦 —— 這是分母,⛔ 不准用畫面上的數字反推。"""
    data = json.loads((maps_dir / f"{MAP}.json").read_text(encoding="utf-8"))
    ids = set()

    def walk(node):
        if node.get("todo"):
            ids.add(node["id"])
        for child in node.get("children") or []:
            walk(child)

    walk(data["nodeData"])
    return ids


def view_orders(maps_dir):
    data = json.loads((maps_dir / f"{MAP}.json").read_text(encoding="utf-8"))
    got = {}

    def walk(node):
        vo = (node.get("detail") or {}).get("viewOrder")
        if vo is not None:
            got[node["id"]] = vo
        for child in node.get("children") or []:
            walk(child)

    walk(data["nodeData"])
    return got


# 全部展開之後,畫面上實際看得到哪幾條。⛔ 讀的是 DOM 不是內部變數 ——
# 內部變數對了而畫面漏掉,對使用者來說一樣是漏掉。
SHOWN_JS = """() => [...document.querySelectorAll('.item')].map(e => e.dataset.id)"""

# 一行的欄位順序(使用者定的,2026-09-08:優先區 → 分類 → 內容)
HEAD_JS = """() => {
  const h = document.querySelector('.topic .thead');
  return [...h.children].map(e => e.className.split(' ')[0]);
}"""

# 每張卡的「等級 + 主題名」,依畫面由上到下
CARDS_JS = """() => [...document.querySelectorAll('.topic')].map(t => ({
  id: t.dataset.id,
  pri: (t.querySelector('.pri') || {}).textContent,
  name: (t.querySelector('.tname') || {}).textContent,
}))"""


# 對比實算。⚠️ 這裡唯一的難點是**半透明背景**:等級色塊用的是
# rgba(255,107,107,.12) 這種疊色,如果直接把它當成背景色去算,
# 前景與背景會是同一個色相 → 算出來永遠是 1.0 → 每一顆都被誤報成「黑底黑字」。
# 正確做法是往上收集到第一個不透明的底,再由下往上疊回來。
CONTRAST_JS = """() => {
  const parse = (c) => { const m = (c || '').match(/[\\d.]+/g);
    if (!m) return null;
    return [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1]; };
  const lum = (rgb) => { const f = rgb.slice(0, 3).map(v => { v /= 255;
      return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); });
    return .2126 * f[0] + .7152 * f[1] + .0722 * f[2]; };
  const bgOf = (el) => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (!c || c[3] === 0) continue;
      stack.push(c);
      if (c[3] >= 1) break;
    }
    stack.push([255, 255, 255, 1]);           // 最底保底
    let base = stack[stack.length - 1];
    for (let i = stack.length - 2; i >= 0; i--) {
      const [r, g, b, a] = stack[i];
      base = [r * a + base[0] * (1 - a), g * a + base[1] * (1 - a), b * a + base[2] * (1 - a)];
    }
    return base;
  };
  const bad = [];
  document.querySelectorAll('.tname,.pri,.tdomain,.it,.fname,.pcount,.next b')
    .forEach(el => { if (!el.textContent.trim()) return;
      const fg = parse(getComputedStyle(el).color);
      if (!fg) return;
      const a = lum(fg), b = lum(bgOf(el));
      const r = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      if (r < 3) bad.push([el.className, +r.toFixed(2), el.textContent.slice(0, 18)]);
    });
  return bad.slice(0, 6);
}"""


def main():
    from playwright.sync_api import sync_playwright

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mmtopics-"))
    shutil.copytree(REAL, tmp / "mindmaps")
    maps = tmp / "mindmaps"
    port = free_port()
    env = {**os.environ, "MINDMAP_MAPS_DIR": str(maps),
           "MINDMAP_PORT": str(port), "MINDMAP_HOST": "127.0.0.1"}
    srv = subprocess.Popen(["/usr/bin/python3", "main.py"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    fails, notes = [], []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/api/maps", timeout=1).read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            sys.exit("❌ 伺服器沒起來")

        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 1440, "height": 1000})
            pg.goto(f"{base}/topics", wait_until="networkidle")
            pg.wait_for_selector(".topic")

            # ── ① 分母對帳:圖上有幾件 vs 畫面看得到幾件 ──────────────
            if pg.is_checked("#chk-open"):
                pg.uncheck("#chk-open")          # 已完成的也要數
            pg.click("#expand-all")
            pg.wait_for_timeout(600)
            shown = set(pg.evaluate(SHOWN_JS))
            on_map = count_todos(maps)
            notes.append(f"分母對帳:圖上 {len(on_map)} 件／畫面 {len(shown)} 件")
            missing = on_map - shown
            extra = shown - on_map
            if missing:
                fails.append(f"⛔ 有 {len(missing)} 件待辦在畫面上看不到(他會漏掉):"
                             f"{sorted(missing)[:8]}")
            if extra:
                fails.append(f"⛔ 畫面上有 {len(extra)} 件圖上找不到的:{sorted(extra)[:8]}")

            # ── ② 欄位順序:優先區 → 分類 → 內容(使用者定的,2026-09-08)────
            pg.click("#collapse-all")
            order = pg.evaluate(HEAD_JS)
            want = ["grip", "pri", "tdomain", "tname", "tduecell", "prog"]
            if order != want:
                fails.append(f"⛔ 一行的欄位順序不對。要的是「優先區 → 分類 → 內容」,"
                             f"應該是 {want},實際 {order}")

            # ── ③ 預設排序:等級高的在前(艾森豪:重要先於緊急)────────
            cards = pg.evaluate(CARDS_JS)
            seq = [c["pri"] for c in cards if c["pri"] in ("P1", "P2", "P3", "P4")]
            if seq != sorted(seq):
                bad = next((i for i in range(1, len(seq)) if seq[i] < seq[i - 1]), None)
                fails.append(f"⛔ 預設沒有按等級排:第 {bad} 張是 {seq[bad]},"
                             f"卻排在 {seq[bad - 1]} 後面")

            # ── ④ 拖曳排序:把最後一張拖到第一張前面,而且要存得住 ────
            before = pg.evaluate(CARDS_JS)
            if len(before) < 3:
                fails.append("主題不到 3 個,測不了拖曳")
            else:
                # ⚠️ 用第 3 張不用最後一張:22 個主題的最後一張在 viewport 外面,
                #    而 mouse.move 吃的是 viewport 座標 —— 拖一個看不見的東西必定失敗。
                src = pg.locator(".topic").nth(2)
                src_id = before[2]["id"]
                grip = src.locator(".grip").bounding_box()
                first = pg.locator(".topic").first.bounding_box()
                pg.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
                pg.mouse.down()
                # 分好幾步移動:一步到位的話 pointermove 只發一次,
                # 5px 的抖動容差會把它整個吃掉,看起來就像「拖了沒反應」
                pg.mouse.move(first["x"] + 60, first["y"] + first["height"] * 0.7, steps=12)
                pg.mouse.move(first["x"] + 60, first["y"] + 4, steps=8)
                pg.mouse.up()
                pg.wait_for_timeout(900)
                after = pg.evaluate(CARDS_JS)
                if after[0]["id"] != src_id:
                    fails.append(f"⛔ 拖到最上面沒生效:期待 {src_id},實際 {after[0]['id']}")
                # 存進圖了嗎(不是只有畫面動)
                saved = view_orders(maps)
                if not saved:
                    fails.append("⛔ 順序沒寫進圖 —— 重新整理就會跑掉")
                else:
                    notes.append(f"順序寫進圖:{len(saved)} 個節點有 viewOrder")
                    pg.reload(wait_until="networkidle")
                    pg.wait_for_selector(".topic")
                    again = pg.evaluate(CARDS_JS)
                    if again[0]["id"] != src_id:
                        fails.append(f"⛔ 重新整理之後順序跑掉了:{again[0]['id']}")

            # ── ⑤ 順序改回自動:⛔ 一個只進不出的排序,使用者不敢亂拖 ────────
            pg.on("dialog", lambda d: d.accept())
            pg.click("#reset-order")
            pg.wait_for_timeout(800)
            left = view_orders(maps)
            if left:
                fails.append(f"⛔「改回自動」沒清乾淨,還剩 {len(left)} 個 viewOrder")

            # ── ⑥ 打勾:要寫回圖,而且完成日要當場寫 ──────────────
            pg.click("#expand-all")
            pg.wait_for_timeout(500)
            box = pg.locator(".item:not(.done)").first
            item_id = box.get_attribute("data-id")
            box.locator(".box").click()
            pg.wait_for_timeout(900)
            data = json.loads((maps / f"{MAP}.json").read_text(encoding="utf-8"))
            hit = []

            def find(node):
                if node.get("id") == item_id:
                    hit.append(node)
                for child in node.get("children") or []:
                    find(child)

            find(data["nodeData"])
            if not hit:
                fails.append(f"⛔ 打勾之後圖上找不到 {item_id}")
            else:
                node = hit[0]
                if not (node.get("topic") or "").startswith("✅"):
                    fails.append(f"⛔ 打勾沒寫回圖:{node.get('topic')!r}")
                today = time.strftime("%Y-%m-%d")
                if (node.get("detail") or {}).get("doneOn") != today:
                    fails.append("⛔ 完成日沒有在按下去的當下寫"
                                 f"(/day 曾經出過這個問題):{node.get('detail')}")
                if "在待辦事項頁" not in (node.get("scEdited") or ""):
                    fails.append("⛔ 沒蓋上「使用者自己按的」章 → 會被當成 AI 改的")
                if node.get("aiEdited"):
                    fails.append("⛔ 還留著 aiEdited —— 紫圈的意思是「AI 動過你還沒看」")

            # ── ⑦ 直接新增:少掉「回去叫 AI 加」那兩步 ────────────
            NEW = "【verify】這條是測試加的"
            row = pg.locator(".addrow").first
            row.locator("input").fill(NEW)
            row.locator("button").click()
            pg.wait_for_timeout(900)
            data = json.loads((maps / f"{MAP}.json").read_text(encoding="utf-8"))
            found = []

            def look(node, parent):
                if NEW in (node.get("topic") or ""):
                    found.append((node, parent))
                for child in node.get("children") or []:
                    look(child, node)

            look(data["nodeData"], None)
            if not found:
                fails.append("⛔ 在頁面上新增的那條沒有進圖")
            else:
                node, parent = found[0]
                if not node.get("todo"):
                    fails.append("⛔ 新增的沒有標成待辦 → 任務板與排行程都看不到它")
                if not (node.get("detail") or {}).get("explain"):
                    fails.append("⛔ 新增的沒有寫說明 → 一個月後他不知道那是什麼")
                notes.append(f"新增掛在:[{parent['id']}] {parent.get('topic')}")

            # ── ⑧ 兩種配色都截圖 + 抓「同色壓同色」──────────────
            for scheme in ("dark", "light"):
                pg2 = br.new_page(viewport={"width": 1440, "height": 1100},
                                  color_scheme=scheme)
                pg2.goto(f"{base}/topics", wait_until="networkidle")
                pg2.wait_for_selector(".topic")
                shot = OUT / f"topics-{scheme}.png"
                pg2.screenshot(path=str(shot))
                notes.append(f"截圖:{shot}")
                low = pg2.evaluate(CONTRAST_JS)
                if low:
                    fails.append(f"[{scheme}] ⛔ 對比不足(讀 CSS 抓不到的那種 bug):{low}")
                pg2.close()
            br.close()
    finally:
        srv.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n".join("· " + n for n in notes))
    if fails:
        print("\n".join("❌ " + f for f in fails))
        sys.exit(1)
    print("✅ /topics 全部通過(正本沒被碰過,測的是複本)")


if __name__ == "__main__":
    main()
