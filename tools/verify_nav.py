"""四頁的第一排導覽列:真的開瀏覽器點過一輪(2026-09-09)。

**為什麼要有這支:** 使用者的需求(2026-09-08):「我按了心智圖、按了待辦事項、按了排行程,
他的介面都長得不一樣,然後會跳來跳去,他的擺放位置也會跳來跳去,這樣真的很奇怪。」
根因是導覽列**四份各寫各的**;解法是抽成共用的 `nav.js` + `nav.css`。

⭐ 這支守兩件讀程式碼看不出來的事:
① **四頁的第一排在畫面上真的長得一樣嗎** —— 比的是渲染後的 DOM 順序與**像素座標**,
   不是比原始碼。同一份 nav.js 被某頁的 CSS 蓋掉位置,原始碼是看不出來的。
② **心智圖那 8 個工具搬到第二排之後,還按得動嗎** —— 這是整輪風險最高的一步:
   按鈕失效**不會報錯**,畫面看起來一模一樣,只是按了沒反應。

⛔ 全程用正式圖的複本 + 臨時埠,絕不碰正本、也不佔 8030。
跑法:make verify-nav
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

PAGES = [("/", "心智圖"), ("/topics", "待辦事項"), ("/board", "任務板"), ("/day", "排行程")]

# 第一排每一顆的文字與**左邊界座標** —— 座標才看得出「跳來跳去」
NAV_JS = """() => [...document.querySelectorAll('#scnav .np')].map(a => ({
  name: a.textContent.trim(),
  href: a.getAttribute('href'),
  cur: a.classList.contains('cur'),
  x: Math.round(a.getBoundingClientRect().left),
  y: Math.round(a.getBoundingClientRect().top),
}))"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    from playwright.sync_api import sync_playwright

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mmnav-"))
    shutil.copytree(REAL, tmp / "mindmaps")
    port = free_port()
    env = {**os.environ, "MINDMAP_MAPS_DIR": str(tmp / "mindmaps"),
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
            pg = br.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))

            # ── ① 四頁的第一排,文字與座標都要一模一樣 ──────────────
            shots = {}
            for path, label in PAGES:
                pg.goto(base + path, wait_until="networkidle")
                pg.wait_for_selector("#scnav .np")
                shots[path] = pg.evaluate(NAV_JS)

            names = [[k["name"] for k in v] for v in shots.values()]
            if len({tuple(n) for n in names}) != 1:
                fails.append("⛔ 四頁的第一排順序不一樣(這正是他抱怨的那件事):\n      "
                             + "\n      ".join(f"{p}: {n}"
                                               for (p, _), n in zip(PAGES, names)))
            else:
                notes.append("四頁第一排順序一致:" + " → ".join(names[0]))

            xs = [[k["x"] for k in v] for v in shots.values()]
            if len({tuple(x) for x in xs}) != 1:
                fails.append(f"⛔ 同一顆按鈕在不同頁的左邊界不同(位置會跳):{xs}")
            else:
                notes.append(f"每一顆的橫向位置四頁相同:{xs[0]}")

            # 當前頁要亮著,而且只有一顆
            for (path, label), rows in zip(PAGES, shots.values()):
                cur = [k for k in rows if k["cur"]]
                if len(cur) != 1:
                    fails.append(f"⛔ {path} 亮起來的有 {len(cur)} 顆,應該剛好 1 顆")
                elif cur[0]["href"] != path:
                    fails.append(f"⛔ {path} 亮錯顆:亮的是 {cur[0]['href']}")
                if len(rows) != 4:
                    fails.append(f"⛔ {path} 第一排有 {len(rows)} 顆,應該固定 4 顆"
                                 "(當前頁不准拿掉)")

            # ── ② 心智圖:8 個工具搬到第二排之後還按得動嗎 ────────────
            pg.goto(base + "/", wait_until="networkidle")
            pg.wait_for_selector("#toolbar")
            errs.clear()

            # 每一顆都要在第二排(#toolbar),⛔ 不准還留在第一排
            in_nav = pg.evaluate(
                """() => ['btn-detail','btn-style-mode','btn-arrows','btn-layers',
                          'map-select','btn-new','btn-save','search-box']
                     .filter(id => { const e = document.getElementById(id);
                       return !e || !e.closest('#toolbar'); })""")
            if in_nav:
                fails.append(f"⛔ 這幾個工具沒有在第二排:{in_nav}")

            checks = [
                # ⚠️ 詳情面板的 id 是 drawer 不是 detail(app.js:1697 openDrawer)。
                #    第一版我照按鈕名字猜成 #detail,結果報「按了沒反應」—— 是測試自己錯了。
                ("btn-detail", "📝 詳情",
                 "() => !document.getElementById('drawer').hidden"),
                ("btn-arrows", "🔗 線",
                 "() => document.getElementById('btn-arrows').textContent"),
                ("btn-layers", "🗂 圖層",
                 "() => !document.getElementById('layer-panel').hidden"),
                ("btn-style-mode", "🎨 外觀",
                 # 這兩行是故意串成一段 JavaScript,不是漏了逗號。加括號讓意圖明確。
                 ("() => document.getElementById('btn-style-mode').className "
                  "+ '|' + document.body.className")),
            ]
            for btn_id, label, probe in checks:
                before = pg.evaluate(probe)
                pg.click(f"#{btn_id}")
                pg.wait_for_timeout(320)
                after = pg.evaluate(probe)
                if before == after:
                    fails.append(f"⛔ 心智圖的「{label}」按了沒反應"
                                 f"(搬 DOM 搬壞了,而且不會報錯):{before!r}")
                else:
                    notes.append(f"「{label}」按得動:{before!r} → {after!r}")
            if errs:
                fails.append(f"⛔ 心智圖有 JS 錯誤:{errs[:3]}")

            # ── ③ 多一排之後,畫布有沒有被切掉 ─────────────────────
            geo = pg.evaluate("""() => {
              const w = document.getElementById('workarea').getBoundingClientRect();
              return { bottom: Math.round(w.bottom), vh: window.innerHeight,
                       scroll: document.documentElement.scrollHeight,
                       navH: Math.round(document.getElementById('scnav').getBoundingClientRect().height),
                       toolH: Math.round(document.getElementById('toolbar').getBoundingClientRect().height) };
            }""")
            notes.append(f"心智圖高度:第一排 {geo['navH']}px + 第二排 {geo['toolH']}px,"
                         f"畫布底部 {geo['bottom']} / 視窗 {geo['vh']}")
            if abs(geo["bottom"] - geo["vh"]) > 2:
                fails.append(f"⛔ 畫布底部對不上視窗底部(差 {geo['bottom'] - geo['vh']}px)"
                             " —— 多一排之後高度沒算對")
            if geo["scroll"] > geo["vh"] + 2:
                fails.append(f"⛔ 心智圖整頁跑出捲軸({geo['scroll']} > {geo['vh']})")

            # ── ⑤ 右下角「＋」隨手記(2026-09-17)────────────────────────
            # 使用者的需求是:「突然想到一些任務…好像就沒有辦法直接加在我們這個上面。」
            # ⭐ 要驗的是「使用者按了會不會出事」,不是「按鈕在不在」:
            #    位置四頁一樣、加得進去、失敗時字不會不見、選字的 Enter 不誤送、連點不加兩筆。
            def map_todos():
                data = json.loads((tmp / "mindmaps" / "全局總覽圖.json").read_text(encoding="utf-8"))
                found = []
                def walk(n, inbox=False):
                    here = inbox or n.get("id") == "inbox"
                    if n.get("todo") and "【verify】" in (n.get("topic") or ""):
                        found.append((n["topic"], here))
                    for c in n.get("children") or []:
                        walk(c, here)
                walk(data["nodeData"])
                return found

            fab_boxes = []
            for path, label in PAGES:
                pg.goto(base + path, wait_until="networkidle")
                pg.wait_for_selector("#qa-fab")
                if path == "/":
                    pg.wait_for_timeout(1500)     # 心智圖要先載完圖
                b = pg.locator("#qa-fab").bounding_box()
                fab_boxes.append((round(b["x"]), round(b["y"])))
                pg.click("#qa-fab")
                if not pg.is_visible("#qa-dlg"):
                    fails.append(f"⛔ {path} 按「＋」沒有跳出小框")
                    continue
                focused = pg.evaluate("() => document.activeElement && document.activeElement.id")
                if focused != "qa-text":
                    fails.append(f"⛔ {path} 小框打開後游標不在輸入框(在 {focused})")
                before = len(map_todos())
                pg.fill("#qa-text", f"【verify】{label} 隨手記")
                pg.keyboard.press("Enter")
                pg.wait_for_function("() => /加進/.test(document.getElementById('qa-msg').textContent)"
                                     " || /沒存進去/.test(document.getElementById('qa-msg').textContent)", timeout=10000)
                note = pg.inner_text("#qa-msg")
                after = map_todos()
                if len(after) != before + 1:
                    fails.append(f"⛔ {path} 按 Enter 之後圖上沒有多一筆({before}→{len(after)}):{note}")
                elif not after[-1][1] and not any(t.endswith(f"{label} 隨手記") and inb for t, inb in after):
                    fails.append(f"⛔ {path} 新的那筆沒有進收件匣:{after}")
                if pg.input_value("#qa-text"):
                    fails.append(f"⛔ {path} 存成功之後框裡的字沒有清掉")
                if path == "/":
                    pg.wait_for_timeout(1200)
                    if pg.is_visible("#banner"):
                        fails.append("⛔ 心智圖頁按完「＋」跳出衝突橫幅(圖被別人改過了)")
            if len(set(fab_boxes)) != 1:
                fails.append(f"⛔ 「＋」四頁的位置不一樣:{fab_boxes}")
            else:
                notes.append(f"「＋」四頁位置相同 {fab_boxes[0]},四頁都加得進收件匣")

            # 收件匣在待辦事項頁要排第一
            pg.goto(base + "/topics", wait_until="networkidle")
            pg.wait_for_selector(".topic")
            first = pg.evaluate("() => document.querySelector('.topic').innerText.split('\\n').slice(0,4).join(' ')")
            if "收件匣" not in first:
                fails.append(f"⛔ 待辦事項頁第一包不是收件匣:{first[:60]}")

            # 失敗時:字要留在框裡
            pg.route("**/quick-todo", lambda route: route.fulfill(
                status=500, content_type="application/json", body='{"detail": "測試用的假錯誤"}'))
            pg.click("#qa-fab")
            pg.fill("#qa-text", "【verify】存失敗的這句不能不見")
            pg.click("#qa-go")
            pg.wait_for_function("() => /沒存進去/.test(document.getElementById('qa-msg').textContent)", timeout=8000)
            if pg.input_value("#qa-text") != "【verify】存失敗的這句不能不見":
                fails.append("⛔ 存失敗之後框裡的字不見了 —— 他突然想到的東西就這樣丟了")
            else:
                notes.append("存失敗時字留在框裡,並顯示「沒存進去」")
            pg.unroute("**/quick-todo")

            # 注音/拼音選字按的 Enter 不能送出
            sent = []
            pg.on("request", lambda r: sent.append(r.url) if r.url.endswith("/quick-todo") else None)
            pg.evaluate("""() => {
              const i = document.getElementById('qa-text');
              i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true}));
            }""")
            pg.wait_for_timeout(600)
            if sent:
                fails.append("⛔ 選字時按的 Enter 被當成送出了(打中文會被截斷)")

            # 連點兩下只加一筆
            before = len(map_todos())
            pg.fill("#qa-text", "【verify】連點兩下")
            pg.evaluate("() => { const b = document.getElementById('qa-go'); b.click(); b.click(); }")
            pg.wait_for_timeout(1500)
            added = len(map_todos()) - before
            if added != 1:
                fails.append(f"⛔ 連點兩下加了 {added} 筆")
            else:
                notes.append("選字的 Enter 不會誤送;連點兩下只加一筆")

            # 待辦事項頁自己的「＋ 加進…」框也不能被選字的 Enter 送出
            pg.click("#expand-all")
            pg.wait_for_timeout(400)
            sent.clear()
            pg.evaluate("""() => {
              const i = document.querySelector('.addrow input');
              i.value = '【verify】選字中';
              i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true}));
            }""")
            pg.wait_for_timeout(800)
            if any("【verify】選字中" in t for t, _ in map_todos()):
                fails.append("⛔ 待辦事項頁的「＋ 加進」框,選字的 Enter 也被當成送出")

            # 心智圖頁:有沒存的改動、又一直存不進去 → 不能硬送,要講清楚
            pg.goto(base + "/", wait_until="networkidle")
            pg.wait_for_timeout(1500)
            pg.evaluate("() => { window.isDirty = () => true; window.saveMap = () => {}; }")
            before = len(map_todos())
            pg.click("#qa-fab")
            pg.fill("#qa-text", "【verify】心智圖還沒存")
            pg.click("#qa-go")
            pg.wait_for_function("() => /沒存進去/.test(document.getElementById('qa-msg').textContent)", timeout=10000)
            if len(map_todos()) != before:
                fails.append("⛔ 心智圖有沒存的改動時還是硬送了 —— 他之後存檔會撞衝突")
            elif "儲存" not in pg.inner_text("#qa-msg"):
                fails.append(f"⛔ 心智圖沒存時的訊息沒講要先按儲存:{pg.inner_text('#qa-msg')}")
            else:
                notes.append("心智圖有沒存的改動時,先擋下來並叫他按儲存")

            # ── ④ 四頁各截一張,兩種配色 ───────────────────────────
            for scheme in ("dark", "light"):
                pg2 = br.new_page(viewport={"width": 1280, "height": 300},
                                  color_scheme=scheme)
                for path, label in PAGES:
                    pg2.goto(base + path, wait_until="networkidle")
                    pg2.wait_for_selector("#scnav .np")
                    shot = OUT / f"nav-{label}-{scheme}.png"
                    pg2.screenshot(path=str(shot), clip={
                        "x": 0, "y": 0, "width": 1280, "height": 96})
                notes.append(f"截圖({scheme}):{OUT}/nav-*-{scheme}.png")
                pg2.close()
            br.close()
    finally:
        srv.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n".join("· " + n for n in notes))
    if fails:
        print("\n".join("❌ " + f for f in fails))
        sys.exit(1)
    print("✅ 四頁的第一排一致、心智圖的工具都還按得動(正本沒被碰過)")


if __name__ == "__main__":
    main()
