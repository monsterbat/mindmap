"""/day 拖拉排程器的把關測試。

使用者的需求(2026-08-11):「我想設計一個更好讓我去做拖拉行程的工具…右邊放還沒排進行程的任務,
固定行程拉到左邊後右邊的原始區塊不會消失。」

測的是「拖了會不會存壞、會不會把別人的東西蓋掉」——那是這頁唯一會造成實害的地方。
"""

import json
import pathlib

import pytest

import main


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """⛔ 一律寫進 tmp,不准碰正式圖。"""
    maps = tmp_path / "mindmaps"
    maps.mkdir()
    data = {"nodeData": {"id": "root", "topic": "圖", "children": [
        {"id": "dom", "topic": "💼 Work", "children": [
            {"id": "t1", "topic": "⏳ 做一件事", "todo": True, "tags": ["P1"],
             "detail": {"due": "2026-08-20", "effort": "2h", "explain": "別動我"}},
            {"id": "t2", "topic": "✅ 做完的", "todo": True, "tags": ["P2"]},
        ]},
    ]}}
    (maps / "全局總覽圖.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "MAPS_DIR", maps)
    monkeypatch.setattr(main, "DAY_DIR", maps / "排程設定" / "每日行程")
    monkeypatch.setattr(main, "DAILY_TPL_PATH", maps / "排程設定" / "日常區塊.json")
    return maps


def read_node(maps, nid):
    data = json.loads((maps / "全局總覽圖.json").read_text(encoding="utf-8"))
    for node in data["nodeData"]["children"][0]["children"]:
        if node["id"] == nid:
            return node
    raise AssertionError(nid)


# ── PATCH:一次只動一個節點 ────────────────────────────────────────


def test_patch_只改指定欄位_不碰其他內容(sandbox):
    main.patch_node("全局總覽圖", "t1", {"detail": {"plannedAt": "2026-08-11T09:00",
                                                "plannedMin": 90}})
    d = read_node(sandbox, "t1")["detail"]
    assert d["plannedAt"] == "2026-08-11T09:00"
    assert d["plannedMin"] == 90
    assert d["explain"] == "別動我"  # ⛔ 其他欄位不准被洗掉
    assert d["due"] == "2026-08-20"


def test_MUST_patch_擋掉沒開放的欄位(sandbox):
    """⛔ 這支沒有衝突偵測,能改的範圍越小誤傷越小。"""
    for bad in ({"topic": "偷改標題"}, {"explain": "偷改說明"}, {"children": []}):
        with pytest.raises(main.ApiError) as e:
            main.patch_node("全局總覽圖", "t1", {"detail": bad})
        assert e.value.status == 400
    assert read_node(sandbox, "t1")["detail"]["explain"] == "別動我"


def test_patch_傳空值等於拿掉那個欄位(sandbox):
    main.patch_node("全局總覽圖", "t1", {"detail": {"plannedAt": "2026-08-11T09:00"}})
    main.patch_node("全局總覽圖", "t1", {"detail": {"plannedAt": None}})
    assert "plannedAt" not in read_node(sandbox, "t1")["detail"]


def test_MUST_patch_標成使用者改的_不是_AI_改的(sandbox):
    """紫圈的意思是「AI 動過、你還沒看」。自己拖的也圈起來,那個圈就沒有訊息量了。"""
    node = read_node(sandbox, "t1")
    node["aiEdited"] = "2026-08-10 AI 改的"
    path = sandbox / "全局總覽圖.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["nodeData"]["children"][0]["children"][0]["aiEdited"] = "2026-08-10 AI 改的"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    main.patch_node("全局總覽圖", "t1", {"detail": {"plannedAt": "2026-08-11T09:00"}})
    after = read_node(sandbox, "t1")
    assert "aiEdited" not in after
    assert after["scEdited"]


def test_patch_找不到節點會講清楚(sandbox):
    with pytest.raises(main.ApiError) as e:
        main.patch_node("全局總覽圖", "沒這個", {"detail": {"plannedAt": "2026-08-11T09:00"}})
    assert e.value.status == 404


def test_MUST_連續_patch_不會互相蓋掉(sandbox):
    """/day 拖一下存一次。PUT 整張圖會 409,這支不該會 —— 這就是它存在的理由。"""
    for hour in range(9, 14):
        main.patch_node("全局總覽圖", "t1", {"detail": {"plannedAt": f"2026-08-11T{hour:02d}:00"}})
    assert read_node(sandbox, "t1")["detail"]["plannedAt"] == "2026-08-11T13:00"
    assert read_node(sandbox, "t1")["detail"]["explain"] == "別動我"


# ── /api/day:池子 / 已排 / 日常 ──────────────────────────────────


def day(view, iso):
    return next(d for d in view["days"] if d["date"] == iso)


def test_MUST_排進行程之後還留在池子裡(sandbox):
    """使用者的需求(2026-08-30):「一旦我把這個任務拉到左半邊的時間軸上的話,他並不會消失掉,
    他還是會繼續在右邊的部分可以繼續讓我拉動。」
    ⛔ 舊行為(排滿時數就從池子移走)已作廢 —— 只有按完成才會離開。"""
    before = main.day_view("date=2026-08-11&days=1")
    assert [t["id"] for t in before["pool"]] == ["t1"]
    assert day(before, "2026-08-11")["scheduled"] == []

    main.patch_node("全局總覽圖", "t1", {"detail": {
        "planned": [{"uid": "a", "at": "2026-08-11T09:00", "min": 120}]}})
    after = main.day_view("date=2026-08-11&days=1")
    assert [t["id"] for t in day(after, "2026-08-11")["scheduled"]] == ["t1"]
    assert [t["id"] for t in after["pool"]] == ["t1"]
    assert after["pool"][0]["used"] == 120
    assert "remaining" not in after["pool"][0], "⛔ 沒有「還剩多少」這個概念了"


def test_MUST_一次回連續幾天_可以左右捲(sandbox):
    """使用者的需求:「所以他只能排一天喔,好爛喔…不如就設定為一個禮拜吧。」"""
    view = main.day_view("date=2026-08-11&days=7")
    assert [d["date"] for d in view["days"]][:3] == ["2026-08-11", "2026-08-12", "2026-08-13"]
    assert len(view["days"]) == 7
    assert day(view, "2026-08-11")["weekday"] == "二"


def test_MUST_排在別天也照樣留在池子裡(sandbox):
    """使用者要的就是「還可以放到其他天」→ 排過一次不代表這件事處理完了。"""
    main.patch_node("全局總覽圖", "t1", {"detail": {
        "planned": [{"uid": "a", "at": "2026-08-12T09:00", "min": 120}]}})
    view = main.day_view("date=2026-08-11&days=7")
    assert [t["id"] for t in view["pool"]] == ["t1"]
    assert [t["id"] for t in day(view, "2026-08-12")["scheduled"]] == ["t1"]
    assert day(view, "2026-08-11")["scheduled"] == []


def test_排在視窗外的那幾天_池子照樣看得到它(sandbox):
    """排到看不見的未來,不該讓它從右邊消失 —— 那正是他之前找不到任務的原因。"""
    main.patch_node("全局總覽圖", "t1", {"detail": {
        "planned": [{"uid": "a", "at": "2026-09-30T09:00", "min": 120}]}})
    view = main.day_view("date=2026-08-11&days=7")
    assert [t["id"] for t in view["pool"]] == ["t1"]


def test_完成的不會出現在池子裡(sandbox):
    assert "t2" not in [t["id"] for t in main.day_view("date=2026-08-11")["pool"]]


def test_池子照_P1_到_P4_排(sandbox):
    path = sandbox / "全局總覽圖.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    kids = data["nodeData"]["children"][0]["children"]
    kids.append({"id": "t3", "topic": "⏳ 低優先", "todo": True, "tags": ["P4"]})
    kids.append({"id": "t4", "topic": "⏳ 也是最高", "todo": True, "tags": ["P1"]})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert [t["pri"] for t in main.day_view("date=2026-08-11")["pool"]] == ["P1", "P1", "P4"]


def test_date_擋得住亂輸入(sandbox):
    for bad in ("date=昨天", "days=abc"):
        with pytest.raises(main.ApiError) as e:
            main.day_view(bad)
        assert e.value.status == 400


def test_日常區塊存得起來也讀得回來(sandbox):
    blocks = [{"uid": "meal-1", "tpl": "meal", "start": "12:00", "min": 60}]
    main.put_day_blocks("2026-08-11", {"blocks": blocks})
    view = main.day_view("date=2026-08-11&days=2")
    assert day(view, "2026-08-11")["blocks"] == blocks
    assert day(view, "2026-08-12")["blocks"] == []


def test_MUST_日常區塊不會變成心智圖節點(sandbox):
    """⛔ 吃飯/通勤變成待辦節點的話,圖會被日常瑣事淹掉。"""
    main.put_day_blocks("2026-08-11", {"blocks": [{"uid": "x", "tpl": "meal",
                                                   "start": "12:00", "min": 60}]})
    data = json.loads((sandbox / "全局總覽圖.json").read_text(encoding="utf-8"))
    assert len(data["nodeData"]["children"][0]["children"]) == 2


def test_日常區塊的日期擋得住亂輸入(sandbox):
    with pytest.raises(ValueError):
        main.put_day_blocks("../偷跑", {"blocks": []})


def test_沒有範本檔就用預設的五塊(sandbox):
    tpls = main.day_view("date=2026-08-11")["templates"]
    assert {t["id"] for t in tpls} >= {"meal", "lang", "read", "sport", "commute"}
    assert all(t.get("color") and t.get("min") for t in tpls)


# ── 頁面本身 ──────────────────────────────────────────────────────


def test_四個視圖互相到得了():
    """⛔ 連不到的頁面等於不存在 —— /day 剛做好時就是誰也連不過去。

    ⚠️ 2026-09-08 兩處變動:`/plan` 行程表退休(見 test_plan_route.py),
       `/topics` 待辦事項上線。四個是:圖 / 待辦事項 / 板 / 排行程。
    ⭐ 2026-09-09 起連結**不再寫在各頁的 HTML 裡**,由共用的 `nav.js` 產生
       (使用者抱怨「介面都長得不一樣、位置跳來跳去」的解法)。所以這裡改成驗兩件事:
       ①四頁都接上了那份共用導覽 ②那份導覽裡四個目標都在。
    """
    for name in ("index.html", "board.html", "day.html", "topics.html"):
        html = main.static_file(name).read_text(encoding="utf-8")
        assert 'id="scnav"' in html, f"{name} 沒有放共用導覽列的容器"
        assert "/static/js/nav.js" in html, f"{name} 沒有載入共用導覽列"
        assert "/static/css/nav.css" in html, f"{name} 沒有載入共用導覽列的樣式"

    nav = (main.static_file("nav.js")).read_text(encoding="utf-8")
    for target in ('"/"', '"/topics"', '"/board"', '"/day"'):
        assert target in nav, f"共用導覽列少了 {target}"


def test_MUST_分頁連結只有一份正本():
    """⛔ 這正是使用者 2026-09-08 抱怨的根因:四頁各寫各的,每加一頁就多歪一次。
    有人在某一頁自己補一顆分頁按鈕,四頁就又不一樣了 —— 而且沒有人會發現。"""
    for name in ("index.html", "board.html", "day.html", "topics.html"):
        html = main.static_file(name).read_text(encoding="utf-8")
        for other in ('href="/board"', 'href="/day"', 'href="/topics"'):
            assert other not in html, (
                f"{name} 自己寫了 {other} —— 分頁連結一律交給 nav.js")


def test_MUST_當前頁不准從第一排消失():
    """⛔ 拿掉當前頁的話,剩下幾顆的位置每頁都不一樣 —— 那正是他抱怨的「跳來跳去」。"""
    nav = (main.static_file("nav.js")).read_text(encoding="utf-8")
    assert "cur" in nav, "沒有把當前頁標記出來"
    assert "preventDefault" in nav, "當前頁那顆按下去應該不動作,不是重新載入整頁"


def test_MUST_排今天這頁不出現主線雜項那套分軌():
    """使用者:「為什麼你要幫我排什麼主線雜項那些東西」—— 手拖的時候分軌只會礙事。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    body = js.split("*/", 1)[1]  # 檔頭註解在解釋為什麼不要,不算
    assert "主線" not in body and "雜項" not in body


def test_MUST_排今天不存第二份任務資料():
    """⛔ 任務與排程一律回寫心智圖。localStorage 只准放「面板收合了沒」這種介面偏好 ——
    一旦拿它存任務或時間,就會跟圖 drift,而且沒有人會發現。"""
    import re
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    for store in ("sessionStorage", "indexedDB"):
        assert store not in js
    # ⚠️ 2026-08-18 改成看「存的 key 是什麼」而不是比對某一行的寫法 ——
    #    舊版要求每一行都含 "box.open"/"toggle",換個寫法就會誤擋,
    #    而它真正要防的是「拿 localStorage 存任務或時間」。
    keys = set(re.findall(r'localStorage\.\w+\(\s*["\']([\w.-]+)["\']', js))
    keys |= {"<變數>"} if re.search(r"localStorage\.\w+\(\s*[a-zA-Z]", js) else set()
    # 介面偏好白名單。⛔ 要加新的 key 之前先問一次:「這是偏好,還是資料?」
    #   day.tab      = 上次看哪個分頁
    #   day.showDone = 要不要顯示已完成(完成日本身寫在圖上,這裡只存「要不要看」)
    allowed = {"day.tab", "day.showDone"}
    assert keys, "沒用到就更好"
    assert keys <= allowed, f"localStorage 只准存介面偏好,這些 key 不在白名單:{keys - allowed}"
    assert 'method: "PATCH"' in js  # 任務的排程走單節點 PATCH,不是整張圖重寫


def test_MUST_排行程不准再出現要花多久的算法():
    """使用者的需求(2026-08-30):「我根本沒有辦法知道我要花幾個小時完成,那我就變成會限制
    我在安排時間的長度。」→ 這一頁不准再有「總時數 / 還剩多少」那一套。
    ⚠️ effort 欄位本身刻意留著(心智圖、任務板、/plan 還在用),只有這一頁不看它。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    for banned in ("leftOf", "totalOf", "EFFORT_MIN", "remaining"):
        assert banned not in js, f"⛔ {banned} 已經從排行程退休了,不要加回來"
    assert "DEFAULT_BLOCK_MIN = 60" in js, "拖進去預設一小時"
    import plan_week
    assert plan_week.planned_slots({"plannedAt": "2026-08-11T09:00", "plannedMin": 60}) == [
        {"uid": "s0", "at": "2026-08-11T09:00", "min": 60}]


def test_MUST_可以一直往後滑_不是只給幾個固定天數():
    """使用者的需求:「它能不能變成可以一直往後滑?不需要單純去選擇看多少,我一直往後看就可以了;
    然後當我選擇『今天』,它就會跳回來。」"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    html = (main.static_file("day.html")).read_text(encoding="utf-8")
    assert "extend(" in js and 'addEventListener("scroll"' in js
    assert "scrollToDate" in js
    assert 'id="span"' not in html, "「看幾天」的下拉已經被無限往後滑取代"
    assert "MAX_DAYS" in js, "⛔ 要有上限,不然滑一整晚會把幾百欄堆在 DOM 裡"


def test_MUST_時間線用背景畫不是每小時一個div():
    """⚠️ 無限往後滑的前提:一欄 49 條線 × 60 天 ≈ 3000 個 div,捲起來會頓。"""
    css = (main.static_file("day.css")).read_text(encoding="utf-8")
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    assert "repeating-linear-gradient" in css
    assert 'el("div", "hour"' not in js


def test_池子回報已排了多久_行程也看得到那一段(sandbox):
    """used = 已經放上去的總分鐘,純粹是回報,不拿來決定它留不留在池子裡。"""
    main.patch_node("全局總覽圖", "t1", {"detail": {
        "planned": [{"uid": "a", "at": "2026-08-11T09:00", "min": 45}]}})
    view = main.day_view("date=2026-08-11&days=2")
    assert [t["id"] for t in view["pool"]] == ["t1"]
    assert view["pool"][0]["used"] == 45
    placed = day(view, "2026-08-11")["scheduled"]
    assert len(placed) == 1 and placed[0]["slot"]["min"] == 45


def test_MUST_只有標完成才會離開池子(sandbox):
    """這是新設計裡唯一的出口 —— 使用者:「什麼時候這一個任務要結束呢?
    就是當我對這個任務按下完成之後,右半邊的這個任務就會結束了。」"""
    main.patch_node("全局總覽圖", "t1", {"detail": {
        "planned": [{"uid": "a", "at": "2026-08-11T09:00", "min": 120}]}})
    assert [t["id"] for t in main.day_view("date=2026-08-11&days=2")["pool"]] == ["t1"]
    # ⚠️ patch_node 只碰 detail,標題要直接改檔(前端是走整張圖的 PUT)
    data = json.loads((sandbox / "全局總覽圖.json").read_text(encoding="utf-8"))
    data["nodeData"]["children"][0]["children"][0]["topic"] = "✅ 排進去的事"
    (sandbox / "全局總覽圖.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert main.day_view("date=2026-08-11&days=2")["pool"] == []


def test_MUST_同一件事可以切成好幾段排在不同天(sandbox):
    main.patch_node("全局總覽圖", "t1", {"detail": {"planned": [
        {"uid": "a", "at": "2026-08-11T09:00", "min": 60},
        {"uid": "b", "at": "2026-08-12T14:00", "min": 30},
    ]}})
    view = main.day_view("date=2026-08-11&days=3")
    assert len(day(view, "2026-08-11")["scheduled"]) == 1
    assert len(day(view, "2026-08-12")["scheduled"]) == 1
    assert view["pool"][0]["used"] == 90


def test_日常區塊的預設長度_運動90_通勤30(sandbox):
    tpls = {t["id"]: t["min"] for t in main.day_view("date=2026-08-11")["templates"]}
    assert tpls["sport"] == 90 and tpls["commute"] == 30


def test_MUST_池子可以直接編輯與篩選():
    """使用者的需求:「不知道能不能讓我連這個地方也能直接編輯裡面的內容?」「能不能改成可以
    自訂其他篩選或排序方式?例如我只想看在 Work 或 Finance 專案」"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    html = (main.static_file("day.html")).read_text(encoding="utf-8")
    assert "setStatus" in js and "setPri" in js and "visiblePool" in js
    for control in ('id="f-domain"', 'id="f-sort"', 'id="f-q"', 'id="f-due"', 'id="f-part"'):
        assert control in html
    # 2026-08-18 起改成分頁(使用者:「像是 Excel 的那一種分頁」)——
    # 一次只顯示一種,那一種就拿到整個高度。⛔ 不再是五疊摺疊區互相擠。
    for tab in ("tab-pool", "tab-reps", "tab-duty", "tab-tpl", "tab-ai", "tab-legend"):
        assert f'id="{tab}"' in html, f"少了分頁 {tab}"
    assert 'id="tabs"' in html and "showTab" in js


def test_MUST_池子收起來時等級就要看得見():
    """⛔ 2026-08-11 出過的問題:把等級塞進「✎ 改這件事」裡面,使用者立刻反應
    「他其他的東西被擋住了看不太到…至少把等級 P1~4 還是要能夠顯示出來」。
    池子預設照等級排,看不到等級就看不懂排序。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    body = js[js.index("function poolItem"):js.index("function lab(")]
    head = body.split('const row1 = el("div", "row");', 1)[0]
    assert '"pill " + (t.pri' in head, "等級要畫在收起來也看得到的那一行"
    # 編輯列本身不准是 <details>:它的 summary 一定獨立一行,擠掉的正是他要看的資訊
    assert 'el("details"' not in body


def test_MUST_拖拉要保留抓在區塊哪裡的位移():
    """使用者的需求:「現在的拖拉他是看滑鼠的位置,可是 Google 行事曆是根據我顯示的那個區塊的
    上端的部分去對應。」⛔ 沒有這個位移,抓區塊中間拖它會突然往上跳到滑鼠底下。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    assert "grabMin" in js and "grabMinOf" in js
    body = js[js.index("function yToMin"):js.index("function grabMinOf")]
    assert "- offset" in body, "算落點時要把抓的位移扣掉"
    # 兩種可拖的區塊(任務、日常)都要記位移,漏一個就只有一半的手感是對的
    assert js.count("grabMin: grabMinOf(e, box)") == 2


def test_MUST_重疊要並排不是互相蓋住():
    """使用者 2026-08-11 改變主意:「我覺得可以讓不同的行程可以疊加,就是同一塊裡面
    可以放幾個不同的行程,因為有時候就是確實會同時處理不同的事情。」
    ⛔ 開放重疊之後**一定要並排**,不然後畫的會整個蓋住先畫的 = 有一件事憑空消失。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    assert "function layout(" in js, "要有算並排欄位的函式"
    assert "clashes(" not in js, "不再擋重疊"
    assert "overlapsWith(" in js, "但拖曳預覽仍要提示會疊幾件"
    # frame 要吃 col/cols 才畫得出並排
    assert "function frame(startMin, mins, color, col, cols)" in js


def test_MUST_三種東西各進各的選單(monkeypatch, tmp_path):
    """使用者的需求(2026-08-18):「周期性的或者是會一直要需要去做的東西,我們可能需要另外一個選單。」
    ⛔ 混在同一個池子裡就分不出哪些是真的要他動手。"""
    import main
    monkeypatch.setattr(main, "MAPS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(main, "DAY_DIR", tmp_path / "每日行程", raising=False)
    monkeypatch.setattr(main, "DAILY_TPL_PATH", tmp_path / "無.json", raising=False)
    kid = lambda i, extra: {"id": i, "topic": "⏳ " + i, "todo": True,
                            "tags": ["P2"], "detail": {**extra}}
    data = {"nodeData": {"id": "root", "topic": "圖", "children": [
        {"id": "d", "topic": "Work", "children": [
            kid("一次性", {}),
            kid("週期的", {"repeat": "每週"}),
            kid("AI的", {"owner": "ai"}),
            {"id": "職責", "topic": "♾️ 職責", "detail": {"duty": True}},
            {"id": "AI職責", "topic": "♾️ AI職責", "detail": {"duty": True, "owner": "ai"}},
        ]}]}}
    monkeypatch.setattr(main, "get_map", lambda *_: {"data": data, "mtime": 1.0})
    out = main.day_view("date=2026-08-18&days=1")
    assert [t["id"] for t in out["pool"]] == ["一次性"]
    assert [t["id"] for t in out["repeats"]] == ["週期的"]
    assert {t.get("id") for t in out["aiTasks"]} == {"AI的", "duty:AI職責"}
    duties = [t for t in out["templates"] if t.get("kind") == "duty"]
    assert [t["node"] for t in duties] == ["職責"], "⛔ AI 的常設職責不進他的可拖清單"


# ── ⏰ 排過去了沒做(2026-08-24)─────────────────────────────────────
# 使用者的回報:「為什麼我在心智圖裡面有看到這個項目,但是我在我的排行程卻沒有?」
# 那顆已經排滿了時數 → 不在「待辦事項」;又躺在過去的日子上 → 在畫面外。
# **兩個地方都合理,合起來就是查無此人。** 當天盤點有 8 件是這個狀態。

def _map_with(planned, **extra):
    node = {"id": "s1", "topic": "⏳ 排過去的事", "todo": True, "tags": ["P3"],
            "detail": {"effort": "2h", "planned": planned, **extra}}
    return {"id": "root", "topic": "圖", "children": [
        {"id": "dom", "topic": "✍️ Blog", "children": [node]}]}


def test_排滿了又排在過去的事要被撈出來():
    root = _map_with([{"uid": "a", "at": "2026-08-20T20:30", "min": 120}])
    out = main.stale_tasks(root, "2026-08-24")
    assert [t["topic"] for t in out] == ["排過去的事"]
    assert out[0]["lastAt"] == "2026-08-20T20:30"


def test_排在今天或以後的不算():
    root = _map_with([{"uid": "a", "at": "2026-08-24T20:30", "min": 120}])
    assert main.stale_tasks(root, "2026-08-24") == []


def test_不看時數_排在過去沒完成就算():
    """⚠️ 2026-08-30 起不再拿「排滿了沒」當判準 —— 那個概念沒了。
    只問三件事:有排、最後一段在過去、沒標完成。"""
    root = _map_with([{"uid": "a", "at": "2026-08-20T20:30", "min": 60}])
    assert [t["id"] for t in main.stale_tasks(root, "2026-08-24")] == ["s1"]


def test_標完成的不算():
    root = _map_with([{"uid": "a", "at": "2026-08-20T20:30", "min": 120}])
    root["children"][0]["children"][0]["topic"] = "✅ 排過去的事"
    assert main.stale_tasks(root, "2026-08-24") == []


def test_AI的不進他的清單():
    """AI 的不佔他的時間,掉了是我的事。"""
    root = _map_with([{"uid": "a", "at": "2026-08-20T20:30", "min": 120}], owner="ai")
    assert main.stale_tasks(root, "2026-08-24") == []


def test_排今天API要回這一區(sandbox, monkeypatch):
    data = json.loads((sandbox / "全局總覽圖.json").read_text(encoding="utf-8"))
    node = data["nodeData"]["children"][0]["children"][0]
    node["detail"]["effort"] = "2h"
    node["detail"]["planned"] = [{"uid": "a", "at": "2020-01-01T20:30", "min": 120}]
    (sandbox / "全局總覽圖.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "CAL_PATH", sandbox / "行事曆快取.json")
    view = main.day_view("days=1")
    assert [t["id"] for t in view["stale"]] == ["t1"]
    # ⚠️ 2026-08-30 起它**同時也**在待辦事項那一區(按完成才離開)。
    # 這一區的意思從「不看就消失」變成「你排了卻沒做」,所以兩邊都出現是對的。
    assert "t1" in [t["id"] for t in view["pool"]]


def test_網頁要給得出出口():
    """⛔ 只列出來讓他自己想辦法 = 沒解決。這一區的卡片一定要有按鈕。"""
    js = (pathlib.Path(__file__).resolve().parent.parent / "static" / "js" / "day.js").read_text(
        encoding="utf-8")
    assert "function staleItem" in js
    assert "搬到今天" in js and "丟回待辦" in js
    html = (pathlib.Path(__file__).resolve().parent.parent / "static" / "pages" / "day.html").read_text(
        encoding="utf-8")
    assert 'id="tab-stale"' in html
    # 2026-08-24 使用者要求改名;⛔ 路徑 /day 不改(書籤與工具裡寫死的網址會壞)
    assert "排行程" in html and "排今天" not in html


# ── ✅ 完成日一定要在按下去的當下寫(2026-08-24)──────────────────────
# 使用者的回報:「按下完成任務的時候他就不見了…那這樣子好像有點是變成就沒有辦法看到
# 我到底這個東西是什麼時候做完的?」
# 查下去發現不只是看不到 —— 這一頁**根本沒有把完成日寫下來**(任務板一直有寫)。

def test_排行程按完成要當場寫下日期():
    """⛔ 少了這段,完成日要等 7 天後 janitor 補一個「今天」—— 那個日期是錯的。"""
    js = (pathlib.Path(__file__).resolve().parent.parent / "static" / "js" / "day.js").read_text(
        encoding="utf-8")
    setter = js[js.index("async function setStatus"):]
    setter = setter[:setter.index("\n}\n")]
    assert "doneOn" in setter, "在排行程標完成沒有記完成日"
    assert "delete det.doneOn" in setter, "取消完成沒有把舊日期清掉"


def test_完成的事要能被叫出來看(sandbox, monkeypatch):
    data = json.loads((sandbox / "全局總覽圖.json").read_text(encoding="utf-8"))
    node = data["nodeData"]["children"][0]["children"][1]      # ✅ 做完的
    node["detail"] = {"effort": "1h", "doneOn": "2026-08-22",
                      "planned": [{"uid": "a", "at": "2026-08-22T10:00", "min": 60}]}
    (sandbox / "全局總覽圖.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "CAL_PATH", sandbox / "行事曆快取.json")
    view = main.day_view("date=2026-08-22&days=1")
    day = view["days"][0]
    assert [t["id"] for t in day["done"]] == ["t2"]
    assert day["done"][0]["doneOn"] == "2026-08-22"
    # ⛔ 完成的不准混進 scheduled —— 那一欄的時數統計刻意不算已完成的
    assert all(t["id"] != "t2" for t in day["scheduled"])


def test_MUST_預設就顯示已完成():
    """使用者的需求(2026-08-30):「其實沒有必要這麼做…我們只要在完成的項目前面畫上一個勾勾
    並且變成暗暗的就好了,這個東西沒有必要把它隱藏起來。」
    ⚠️ 推翻 08-24 的「預設關」。開關要留著(他關得掉),只是預設反過來 ——
    所以判準是 `!== "0"`(沒設定過 = 開),⛔ 不是 `=== "1"`(沒設定過 = 關)。"""
    js = (pathlib.Path(__file__).resolve().parent.parent / "static" / "js" / "day.js").read_text(
        encoding="utf-8")
    assert 'localStorage.getItem("day.showDone") !== "0"' in js
    assert 'localStorage.getItem("day.showDone") === "1"' not in js
    assert "function doneBlock" in js
    html = (pathlib.Path(__file__).resolve().parent.parent / "static" / "pages" / "day.html").read_text(
        encoding="utf-8")
    assert 'id="f-done"' in html and "顯示已完成" in html


def test_MUST_已完成的方塊也能開能改能拿掉():
    """使用者的需求(2026-09-17):「如果我今天這個任務完成的話,他就不能動到他了也不能刪除,
    如果是已經寫在排行程那邊的話,他完全打不開。」
    舊版刻意鎖死(draggable=false、沒有 ✎ ✕),而且 ✎ 找方塊時只找 scheduled。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    body = js[js.index("function doneBlock"):js.index("function dayColumn")]
    assert "taskBlock(" in body, "已完成的方塊要沿用一般方塊(才有 ✎ ✕ 拖曳 拉長度)"
    assert "draggable = false" not in body, "⛔ 又把已完成的方塊鎖死了"
    find = js[js.index("function findSlot"):js.index("function placePop")]
    assert "d.done" in find, "⛔ ✎ 只找 scheduled 的話,已完成的方塊永遠打不開"


def test_MUST_往左長日子不會把打開的面板關掉():
    """往左補日子時整排先右移,面板黏的那一塊瞬間跑出畫面就被關掉 ——
    捲到左邊附近按 ✎ 會「打不開」。要在捲軸補回去之後再貼一次。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    ext = js[js.index("async function extend"):js.index("function fillDomains")]
    assert "const keep = editing" in ext and "renderEditor()" in ext


def test_MUST_清單卡片直接看得到領域():
    """使用者的需求(2026-09-17):「我會希望我在直接看的時候,我會知道這個東西是屬於什麼領域的。」
    08-17 只放專案、說「顏色已經在講了」—— 他看不出顏色代表哪個領域。"""
    js = (main.static_file("day.js")).read_text(encoding="utf-8")
    for fn, nxt in (("function poolItem", "function "), ("function waitItem", "function "),
                    ("function tplItem", "function ")):
        start = js.index(fn)
        body = js[start:js.index("\n" + nxt, start + 10)]
        assert "domTag(" in body, f"{fn} 的卡片上沒有領域標籤"
