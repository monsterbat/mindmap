"""排今天(/day):真的開一個瀏覽器把它點過一輪。

**為什麼要有這支:** 這一頁的 bug 幾乎都是「讀程式碼看不出來」的那種 ——
顏色在淺色模式下變成同色壓同色、面板浮到畫面外、重畫之後按鈕沒反應。
2026-08-17 就是靠它的截圖才發現右上兩個下拉在淺色模式是**黑底黑字**(寫死深色底
配 var(--text)),而那個 bug 已經在那裡很久了,讀 CSS 一輩子都抓不到。

⛔ 全程用正式圖的**複本**(temp 目錄)+ 自己起的臨時埠,絕不碰正本、
   也不佔用 8030 —— 專案 CLAUDE.md「測試不准碰正式的圖」那一條,就是從曾經出過的問題來的。

跑法:make verify-day  (或 uv run --with playwright python verify_day.py)
⚠️ 需要 Chromium,所以刻意**不放進 `make check`** —— 沒有瀏覽器的機器不該因此變紅。
"""
import datetime
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


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def seed(maps_dir, today):
    """在複本上種一天「什麼情況都有」的行程,測試才驗得到邊界。

    刻意種進去的:同一件事同一天切兩段、兩件事時段重疊、跨午夜、範本被刪掉的日常區塊。
    這四種各自都會讓「一天花了多少時間」算錯,而且錯得很安靜。
    """
    path = maps_dir / "全局總覽圖.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    picked = {}

    def walk(node, domain=None):
        for c in node.get("children") or []:
            dom = domain if domain else (c.get("topic") or "").strip()
            if domain and c.get("todo") and not c.get("children") and domain not in picked:
                picked[domain] = c
            walk(c, dom)

    walk(data["nodeData"])

    # ⚠️ 先把「今天」既有的排程全部清掉再種 —— 不清的話,碰到真圖本來就排很滿的那一天,
    #    算出來的時數是真資料+種子的總和,斷言就會莫名其妙地紅(2026-08-18 曾經出過的問題)。
    def clear(n):
        det = n.get("detail") or {}
        if det.get("planned"):
            det["planned"] = [s for s in det["planned"] if s.get("at", "")[:10] != today]
        for c in n.get("children") or []:
            clear(c)

    clear(data["nodeData"])
    doms = sorted(picked)[:3]
    if len(doms) < 3:
        sys.exit("❌ 複本裡湊不出三個領域的待辦,測不了分類統計")
    plan = {
        doms[0]: [{"uid": "vs1", "at": f"{today}T10:00", "min": 120},     # 同一件事兩段
                  {"uid": "vs2", "at": f"{today}T15:00", "min": 30}],
        doms[1]: [{"uid": "vs3", "at": f"{today}T11:00", "min": 60}],     # 跟上面重疊 60 分
        doms[2]: [{"uid": "vs4", "at": f"{today}T23:30", "min": 60}],     # 跨午夜,只該算 30
    }
    for dom, slots in plan.items():
        node = picked[dom]
        node["tags"] = ["P3"]   # 固定成非 P1:不然點 P1 是「再按一次拿掉」,測到的是相反的事
        det = node.setdefault("detail", {})
        det["planned"] = slots
        det["effort"] = "4h"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ⚠️ 複本的行事曆清空(2026-09-17 加):複本是從正式資料夾整包複製的,
    #    行事曆快取也跟著來 —— 那天真的有一件約好的事,今天的分類就多一類「🗓 行事曆」,
    #    「空的那天」也被另一個事件佔掉,兩條斷言跟著使用者的行程一起紅。測試不該看使用者的行事曆。
    cal = maps_dir / "排程設定" / "行事曆快取.json"
    if cal.exists():
        c = json.loads(cal.read_text(encoding="utf-8"))
        c["events"] = []
        cal.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    days = maps_dir / "排程設定" / "每日行程"
    days.mkdir(parents=True, exist_ok=True)
    (days / f"{today}.json").write_text(json.dumps({"blocks": [
        {"uid": "vb1", "tpl": "meal", "start": "12:00", "min": 60},
        {"uid": "vb2", "tpl": "ghost-tpl", "start": "13:00", "min": 45},   # 範本已被刪掉
    ]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 找一天「真的什麼都沒有」的:光把日常區塊清空不夠,圖上還可能排著任務
    booked = set()

    def scan(n):
        for s in ((n.get("detail") or {}).get("planned") or []):
            booked.add(s["at"][:10])
        for c in n.get("children") or []:
            scan(c)

    scan(data["nodeData"])
    blank = next((d for i in range(1, 11)
                  if (d := shift(today, i)) not in booked), None)
    if blank is None:
        sys.exit("❌ 接下來十天每天都排了東西,驗不到「空的那一天」")
    (days / f"{blank}.json").write_text('{"blocks": []}\n', encoding="utf-8")

    node = picked[doms[0]]
    return node["id"], (node.get("topic") or "").strip(), doms, blank


def shift(iso, n):
    y, m, d = (int(x) for x in iso.split("-"))
    return (datetime.date(y, m, d) + datetime.timedelta(days=n)).isoformat()


TALLY_JS = """() => {
  const cols = [...document.querySelectorAll('.daycol')];
  // ⚠️ 用 offsetTop 比會被 offsetParent 騙:.gutter 是 sticky(=已定位)所以是自己的
  //    offsetParent,.daycol 不是 → 兩邊的基準點差了一整條工具列。要比螢幕座標。
  const grids = cols.map(c => Math.round(c.querySelector('.grid').getBoundingClientRect().top));
  const cells = [...document.querySelector('.daycol[data-date="%s"] .tally').children]
    .map(c => ({ cls: c.className,
                 nm: (c.querySelector('.nm') || {}).textContent || c.textContent,
                 mn: (c.querySelector('.mn') || {}).textContent || '',
                 dot: c.querySelector('i') ? getComputedStyle(c.querySelector('i')).borderRadius : '',
                 cut: [...c.querySelectorAll('.nm')].some(n => n.scrollWidth > n.clientWidth + 1) }));
  const head = document.querySelector('.daycol > header');
  const empty = document.querySelector('.daycol[data-date="%s"] .tally');
  return {
    headHeights: [...new Set(cols.map(c => c.querySelector('header').offsetHeight))],
    gutterHead: document.querySelector('.gutter > header').offsetHeight,
    gridTops: [...new Set(grids)],
    rulerTop: Math.round(
      document.querySelector('.gutter .grid.ruler').getBoundingClientRect().top),
    cells,
    total: (document.querySelector('.daycol[data-date="%s"] .h') || {}).textContent,
    ov: (document.querySelector('.daycol[data-date="%s"] .ov') || {}).textContent,
    emptyText: empty ? empty.textContent : null,
    emptyH: empty ? empty.closest('header').offsetHeight : null,
    headPos: getComputedStyle(head).position,
  };
}"""


def main():
    from playwright.sync_api import sync_playwright

    today = time.strftime("%Y-%m-%d")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mmverify-"))
    shutil.copytree(REAL, tmp / "mindmaps")
    node_id, topic, doms, blank = seed(tmp / "mindmaps", today)
    port = free_port()
    env = {**os.environ, "MINDMAP_MAPS_DIR": str(tmp / "mindmaps"),
           "MINDMAP_PORT": str(port), "MINDMAP_HOST": "127.0.0.1"}
    srv = subprocess.Popen(["/usr/bin/python3", "main.py"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    fails = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/api/maps", timeout=1).read()
                break
            except OSError:   # 還沒開始聽,再等一下
                time.sleep(0.2)
        else:
            sys.exit("❌ 伺服器沒起來")

        with sync_playwright() as p:
            br = p.chromium.launch()
            for scheme in ("dark", "light"):
                # ⚠️ 每一輪都重種一次:第一輪的互動測試會改掉資料(等級、時段),
                #    不重種的話第二輪算出來的時數是被改過的,斷言會莫名其妙地紅。
                seed(tmp / "mindmaps", today)
                pg = br.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
                pg.goto(f"{base}/day", wait_until="networkidle")
                # ── 每日分類時數摘要 ──────────────────────────────
                t = pg.evaluate(TALLY_JS % (today, blank, today, today))
                if t["headHeights"] != [t["gutterHead"]]:
                    fails.append(f"[{scheme}] 欄頭高度沒有全部一致(含鐘點欄):"
                                 f"{t['headHeights']} vs 鐘點欄 {t['gutterHead']}")
                if len(t["gridTops"]) != 1 or t["gridTops"][0] != t["rulerTop"]:
                    fails.append(f"[{scheme}] ⛔ 時間軸對不齊鐘點刻度:"
                                 f"各欄 {t['gridTops']} / 鐘點欄 {t['rulerTop']}")
                if t["headPos"] != "sticky":
                    fails.append(f"[{scheme}] 欄頭不是 sticky,捲下去就看不到摘要了")
                got = {c["nm"].strip(): c["mn"] for c in t["cells"]}
                # 一欄只放 3 列:前兩名 + 「全部 N 類 ▸」。⛔ 其餘不准藏進 tooltip
                if len(t["cells"]) != 3:
                    fails.append(f"[{scheme}] 摘要應該固定 3 列,實際 {len(t['cells'])} 列")
                if not any("全部 5 類" in c["nm"] for c in t["cells"]):
                    fails.append(f"[{scheme}] 放不下的要有一列看得見的「全部 5 類 ▸」,實際 {got}")
                if got.get(doms[0]) != "2.5h":
                    fails.append(f"[{scheme}] 最大那類應該是 {doms[0]} 2.5h,實際 {got}")
                if t["total"] != "5.8h":
                    fails.append(f"[{scheme}] 這天的總時數應該是 5.8h(345 分),實際 {t['total']}")
                if t["ov"] != "⧉1h":
                    fails.append(f"[{scheme}] 重疊 60 分沒有標出來(⛔ 只給總數會讓他以為真花了那麼久),"
                                 f"實際 {t['ov']!r}")
                cut = [c["nm"] for c in t["cells"] if c["cut"]]
                if cut:
                    fails.append(f"[{scheme}] ⛔ 分類名被切掉了(他最討厭這個):{cut}")
                if t["emptyText"] != "還沒排東西":
                    fails.append(f"[{scheme}] 空的那天要講「還沒排東西」,實際 {t['emptyText']!r}")
                if t["emptyH"] != t["gutterHead"]:
                    fails.append(f"[{scheme}] 空的那天欄頭高度不一樣({t['emptyH']}),整排會歪掉")
                cut = [c["nm"] for c in t["cells"] if c["cut"]]
                if cut:
                    fails.append(f"[{scheme}] ⛔ 分類名被切掉了(他最討厭這個):{cut}")

                # 「全部 N 類」按下去 MUST 真的看得到全部 —— ⛔ tooltip 不算看得到
                pg.locator(f'.daycol[data-date="{today}"] .tally').click()
                sp = pg.locator("#sumpop")
                sp.wait_for(timeout=3000)
                names = sp.locator(".sumlist .cell .nm").all_text_contents()
                if len(names) != 5:
                    fails.append(f"[{scheme}] 面板應該列出全部 5 類,實際 {names}")
                if "⚠️ ghost-tpl" not in names or "🍴 吃飯" not in names:
                    fails.append(f"[{scheme}] 被收起來的那幾類沒出現在面板裡:{names}")
                pg.screenshot(path=str(OUT / f"day-sum-{scheme}.png"))
                foot = sp.locator(".sumfoot").inner_text()
                # 重疊要用「人看得懂的話」講,⛔ 不能只丟一個數字
                if "被算了兩次" not in foot or "真的被佔掉" not in foot:
                    fails.append(f"[{scheme}] 面板要講清楚重疊是怎麼回事:{foot!r}")
                pg.keyboard.press("Escape")

                # 右邊改成分頁之後:一次只顯示一個、那一個要拿到整個高度、太長要自己捲
                # (使用者的需求,2026-08-18:「像是 Excel 的那一種分頁…可以讓我整個條狀項目拉得更長」)
                tabs = pg.evaluate("""() => {
                  const bar = [...document.querySelectorAll('#tabs .tab')];
                  const vis = [...document.querySelectorAll('#right section')].filter(s => !s.hidden);
                  const box = vis[0] && vis[0].querySelector('div:last-child');
                  const cs = box && getComputedStyle(box);
                  return {tabs: bar.map(b => b.dataset.tab), on: bar.filter(b => b.classList.contains('on')).length,
                          visible: vis.length, listH: box ? Math.round(box.getBoundingClientRect().height) : 0,
                          scrolls: cs ? cs.overflowY : ''};
                }""")
                if tabs["visible"] != 1 or tabs["on"] != 1:
                    fails.append(f"[{scheme}] 分頁一次只能亮一個、顯示一個:{tabs}")
                if len(tabs["tabs"]) < 5:
                    fails.append(f"[{scheme}] 分頁少了:{tabs['tabs']}")
                if tabs["listH"] < 400:
                    fails.append(f"[{scheme}] ⛔ 清單只有 {tabs['listH']}px —— 分頁的重點就是"
                                 "讓那一種拿到整個高度")
                if tabs["scrolls"] not in ("auto", "scroll"):
                    fails.append(f"[{scheme}] ⛔ 清單不會捲({tabs['scrolls']}),東西一多就被切掉")
                # 每一個分頁都點得開,而且點了之後真的換人
                for tid in ("duty", "reps", "tpl", "ai", "pool"):
                    pg.click(f'#tabs [data-tab="{tid}"]')
                    if pg.evaluate(f"document.getElementById('tab-{tid}').hidden"):
                        fails.append(f"[{scheme}] 點了分頁 {tid} 卻沒顯示")

                # 卡片上要看得出「這是誰的事」——使用者的需求:光看標題不知道是哪個專案的排版優化
                doms_shown = pg.locator("#pool .item .dom").first.inner_text()
                if not doms_shown.strip():
                    fails.append(f"[{scheme}] 池子卡片沒顯示這件事屬於哪個專案")

                blk = pg.locator(".blk[data-slot='vs1']")
                blk.wait_for(timeout=10000)

                # ① 排進去的區塊上有 ✎
                pen = blk.locator(".pen")
                if pen.count() != 1:
                    fails.append(f"[{scheme}] 區塊上沒有 ✎")
                pen.click()

                pop = pg.locator("#editpop")
                pop.wait_for(timeout=3000)
                # ② 面板要完整落在畫面內(不然等於看不到)
                box = pop.bounding_box()
                if box["x"] < 0 or box["y"] < 0 or box["x"] + box["width"] > 1440:
                    fails.append(f"[{scheme}] 面板跑出畫面:{box}")
                # ③ 四組控制項都在
                for sel, name in [(".pri-btn", "等級"), ("input[type=date]", "日期/到期日"),
                                  ("input[type=time]", "開始時間"), ("select", "這一段多長"),
                                  (".st-btn", "狀態"), (".path", "這是哪個專案的"),
                                  (".why", "為什麼要做這件事")]:
                    if pop.locator(sel).count() == 0:
                        fails.append(f"[{scheme}] 面板少了{name}")
                pg.screenshot(path=str(OUT / f"day-edit-{scheme}.png"))

                if scheme == "dark":
                    # ④ 改等級之後:面板不能消失,而且要換成新資料
                    pop.locator(".pri-btn.P1").click()
                    pg.wait_for_timeout(1200)
                    if pop.count() == 0:
                        fails.append("改完等級面板就消失了(等於還是要重開)")
                    elif pop.locator(".pri-btn.P1.on").count() == 0:
                        fails.append("面板還停在舊資料,P1 沒亮起來")
                    saved = json.loads((tmp / "mindmaps/全局總覽圖.json").read_text())

                    def find(n):
                        if n.get("id") == node_id:
                            return n
                        for c in n.get("children") or []:
                            r = find(c)
                            if r:
                                return r
                        return None
                    if "P1" not in (find(saved["nodeData"]).get("tags") or []):
                        fails.append("等級沒有真的寫回圖")

                    # ⑤ 改開始時間 → 區塊要真的移動
                    pop.locator("input[type=time]").fill("15:30")
                    pop.locator("input[type=time]").dispatch_event("change")
                    pg.wait_for_timeout(1200)
                    saved = json.loads((tmp / "mindmaps/全局總覽圖.json").read_text())
                    slots = (find(saved["nodeData"]).get("detail") or {}).get("planned") or []
                    if not any(s["at"].endswith("T15:30") for s in slots):
                        fails.append(f"改時間沒寫回去:{slots}")
                    pg.screenshot(path=str(OUT / "day-edit-after.png"))

                    # ⑤-B 改標題要寫回圖,而且狀態圖示不准被洗掉
                    pop.locator(".rename").fill("改過的名字")
                    pop.locator(".rename").dispatch_event("change")
                    pg.wait_for_timeout(1200)
                    saved = json.loads((tmp / "mindmaps/全局總覽圖.json").read_text())
                    node = find(saved["nodeData"])
                    if "改過的名字" not in (node.get("topic") or ""):
                        fails.append(f"改標題沒寫回圖:{node.get('topic')!r}")
                    if not (node.get("topic") or "").startswith(("⏳", "🔜", "⏸️", "✅", "🎯")):
                        fails.append(f"⛔ 改標題把狀態圖示洗掉了:{node.get('topic')!r}")
                    if node.get("aiEdited"):
                        fails.append("使用者自己改的不該留 AI 的圈圈")

                    # ⑥ 右邊池子的 ✎ 沒被這次重構弄壞(兩邊共用同一組控制項)
                    pg.keyboard.press("Escape")
                    item = pg.locator("#pool .item").first
                    item.locator(".pen").click()
                    edit = item.locator(".edit.open")
                    if edit.count() == 0:
                        fails.append("池子的 ✎ 打不開了(重構弄壞了)")
                    else:
                        for sel, name in [(".pri-btn", "等級"),
                                          ("input[type=date]", "到期日"), (".st-btn", "狀態")]:
                            if edit.locator(sel).count() == 0:
                                fails.append(f"池子的編輯列少了{name}")
                        # ⛔ 使用者在 2026-08-30 把「要花多久」從這一頁拿掉了 —— 它不准回來
                        if edit.locator("select").count() != 0:
                            fails.append("池子的編輯列又冒出下拉了(「要花多久」不准回來)")

                    # ⑦ Esc 要關得掉
                    blk.locator(".pen").click()
                    pg.wait_for_timeout(200)
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(300)
                    if pg.locator("#editpop").count() != 0:
                        fails.append("Esc 關不掉面板")
                pg.close()

            # ── ⑧ 已完成的方塊也要能開、能改時間、能拿掉、能改回沒做完(2026-09-17)──
            # 使用者的需求是:「如果我今天這個任務完成的話,他就不能動到他了也不能刪除,
            # 如果是已經寫在排行程那邊的話,他完全打不開。」
            # 舊版刻意鎖死;而且 ✎ 找方塊時只找 scheduled,已完成的在 done,永遠打不開。
            def seed_done():
                path = tmp / "mindmaps" / "全局總覽圖.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                dom = data["nodeData"]["children"][0]
                dom["children"] = [c for c in dom.get("children") or [] if c.get("id") != "vdone-task"]
                dom["children"].append({
                    "id": "vdone-task", "topic": "✅ 驗證用:已完成的方塊", "todo": True, "tags": ["P3"],
                    "detail": {"doneOn": today, "explain": "verify_day 種的",
                               "planned": [{"uid": "vdone", "at": f"{today}T07:00", "min": 60}]}})
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            def done_node():
                data = json.loads((tmp / "mindmaps" / "全局總覽圖.json").read_text(encoding="utf-8"))
                dom = data["nodeData"]["children"][0]
                return next((c for c in dom.get("children") or [] if c.get("id") == "vdone-task"), None)

            seed_done()
            pg = br.new_page(viewport={"width": 1440, "height": 900})
            dbg = []
            pg.on("console", lambda m: dbg.append(m.text))
            pg.on("pageerror", lambda e: dbg.append("ERR " + str(e)))
            pg.goto(f"{base}/day", wait_until="networkidle")
            blk = pg.locator('.blk.done[data-slot="vdone"]')
            if blk.count() != 1:
                fails.append(f"⑧ 已完成的方塊沒畫出來(找到 {blk.count()} 個)")
            else:
                if blk.locator(".pen").count() != 1 or blk.locator(".x").count() != 1:
                    fails.append("⑧ ⛔ 已完成的方塊上沒有 ✎ 或 ✕ —— 他打不開也刪不掉")
                if blk.get_attribute("draggable") != "true":
                    fails.append("⑧ ⛔ 已完成的方塊拖不動")
                blk.scroll_into_view_if_needed()
                # ⚠️ 捲動會讓排行程長出後面的日子並整個重畫;馬上按會按到被換掉的舊方塊
                pg.wait_for_timeout(1200)
                blk = pg.locator('.blk.done[data-slot="vdone"]')
                blk.hover()
                blk.locator(".pen").click(force=True)
                pg.wait_for_timeout(300)
                pop = pg.locator("#editpop")
                if pop.count() == 0:
                    pg.screenshot(path=str(OUT / "day-done-fail.png"))
                    info = pg.evaluate("""() => { const b = document.querySelector('.blk.done[data-slot="vdone"]');
                      const r = b && b.getBoundingClientRect(); const L = document.getElementById('left').getBoundingClientRect();
                      return {blk: r && [Math.round(r.top), Math.round(r.bottom)], left: [Math.round(L.top), Math.round(L.bottom)]}; }""")
                    fails.append(f"⑧ ⛔ 已完成的方塊按 ✎ 打不開{info} 訊息:{dbg[:3]}")
                else:
                    if "已經完成" not in pop.inner_text():
                        fails.append("⑧ 面板沒講這件已經完成、怎麼改回來")
                    # 改時間:07:00 → 08:00
                    pop.locator("input[type=time]").fill("08:00")
                    pop.locator("input[type=time]").dispatch_event("change")
                    pg.wait_for_timeout(900)
                    at = [s["at"] for s in (done_node() or {}).get("detail", {}).get("planned", [])]
                    if at != [f"{today}T08:00"]:
                        fails.append(f"⑧ ⛔ 已完成的方塊改不了時間:{at}")
                    if not (done_node() or {}).get("topic", "").startswith("✅"):
                        fails.append("⑧ ⛔ 改時間把已完成的狀態弄掉了")
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(300)
                # 拿掉這一塊
                blk = pg.locator('.blk.done[data-slot="vdone"]')
                if blk.count() == 1:
                    blk.scroll_into_view_if_needed()
                    pg.wait_for_timeout(800)
                    blk = pg.locator('.blk.done[data-slot="vdone"]')
                    blk.hover()
                    blk.locator(".x").click(force=True)
                    pg.wait_for_timeout(900)
                    left = (done_node() or {}).get("detail", {}).get("planned", [])
                    if left:
                        fails.append(f"⑧ ⛔ 已完成的方塊按 ✕ 拿不掉:{left}")
                    if not (done_node() or {}).get("topic", "").startswith("✅"):
                        fails.append("⑧ ⛔ 拿掉時段把已完成的狀態弄掉了(應該只拿掉那一塊)")
            pg.close()

            # 改回沒做完:按 ✎ → 「⏳」→ 變回一般方塊、完成日清掉
            seed_done()
            pg = br.new_page(viewport={"width": 1440, "height": 900})
            pg.goto(f"{base}/day", wait_until="networkidle")
            blk = pg.locator('.blk.done[data-slot="vdone"]')
            if blk.count() == 1:
                # ⚠️ 07:00 在預設畫面上方 —— 方塊不在可視範圍時,編輯面板會自己關掉(placeEditor)
                blk.scroll_into_view_if_needed()
                pg.wait_for_timeout(1200)          # 等捲動引發的重畫做完(同上)
                blk = pg.locator('.blk.done[data-slot="vdone"]')
                blk.hover()
                blk.locator(".pen").click(force=True)
                pg.wait_for_timeout(300)
                btn = pg.locator("#editpop .st-btn", has_text="還沒開始")
                if btn.count() == 0:
                    fails.append("⑧ ⛔ 已完成的方塊打開面板後,找不到「⏳ 還沒開始」"
                                 f"(面板 {pg.locator('#editpop').count()} 個)")
                else:
                    btn.first.click(timeout=5000)
                pg.wait_for_timeout(1000)
                node = done_node() or {}
                if not node.get("topic", "").startswith("⏳"):
                    fails.append(f"⑧ ⛔ 按「⏳」沒有改回沒做完:{node.get('topic')}")
                if (node.get("detail") or {}).get("doneOn"):
                    fails.append("⑧ 改回沒做完,完成日沒有清掉")
                if pg.locator('.blk.done[data-slot="vdone"]').count() != 0:
                    fails.append("⑧ 改回沒做完之後,畫面上還是已完成的樣子")
                if pg.locator('.blk[data-slot="vdone"]').count() != 1:
                    fails.append("⑧ 改回沒做完之後,那一塊不見了(應該留在原時段)")
            pg.close()
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"目標任務:{topic}　截圖:{OUT}/day-edit-*.png")
    if fails:
        print("❌ " + "\n❌ ".join(fails))
        sys.exit(1)
    print("✅ 全過(深淺兩色各跑一輪)")
    print("   已完成的方塊:按 ✎ 打得開／能改時間／能按 ✕ 拿掉／按「⏳」改回沒做完(2026-09-17 加)")
    print("   編輯:區塊上有 ✎／面板完整在畫面內／控制項齊全／改完不消失且換新資料／"
          "等級與時間都寫得回圖／池子的 ✎ 沒壞／Esc 關得掉")
    print("   每日分類摘要:欄頭與鐘點欄等高／時間軸對得齊鐘點刻度／sticky／"
          "同任務多段會累加／跨午夜只算當天那截／重疊有另外標出來／"
          "任務排在日常前面且形狀不同／分類名沒被切掉／空的那天一樣高")
    print("⚠️ rc=0 只代表跑完了。截圖 MUST 自己用 Read 打開看 —— 顏色與版面的 bug 斷言抓不到。")


# ⛔ 要有守衛:別的驗證腳本 `import verify_day` 只是要借 free_port/REAL,
#    沒有守衛的話光是 import 就會把整輪瀏覽器測試再跑一次(2026-08-30 曾經出過的問題)。
if __name__ == "__main__":
    main()
