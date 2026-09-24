"""/api/project 的把關測試 —— 專案進度是「拉」不是「推」。

使用者提出的問題(2026-08-03):「我在其他專案更新 TODO/DESIGN,會同步回饋到心智圖嗎?
會不會又變成文件各自散亂、進度沒辦法對齊?」

答案是**只讀不寫**:伺服器即時去讀專案檔算摘要,一個字都不寫回心智圖的 JSON。
這裡驗的是:算得準、跨不出根目錄、專案不存在也不會爆。
"""

import pytest

import main


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROJECTS_ROOT", tmp_path)
    proj = tmp_path / "Program" / "demo"
    proj.mkdir(parents=True)
    (proj / "TODO.md").write_text(
        "# TODO\n"
        "- [ ] 還沒做的一\n"
        "- [ ] ⏳ 2026-08-01 卡在使用者身上\n"
        "- [x] 做完了\n"
        "- [X] 大寫也算做完\n"
        "  - [ ] 縮排的也要算\n"
        "純文字不算\n"
        "- 沒有方框不算\n",
        encoding="utf-8",
    )
    (proj / "CHANGELOG.md").write_text(
        "# CHANGELOG\n\n## 2026-08-01 — 最近這次做了什麼\n\n內文\n\n## 2026-07-30 — 更早的\n",
        encoding="utf-8",
    )
    return tmp_path


def test_數得出未完成與完成(fake_root):
    out = main.project_status("Program/demo")
    assert out["exists"] is True
    assert out["open"] == 3  # 兩條頂層 + 一條縮排
    assert out["done"] == 2


def test_數得出卡在使用者身上的(fake_root):
    """⏳ 是「等你」的記號 —— 最容易漏的不是 AI 的進度,是等使用者的輸入。"""
    assert main.project_status("Program/demo")["waiting"] == 1


def test_抓得到最近一次CHANGELOG標題(fake_root):
    assert main.project_status("Program/demo")["last"] == "2026-08-01 — 最近這次做了什麼"


def test_專案不存在不會爆_只是回exists_false(fake_root):
    out = main.project_status("Program/根本沒這個")
    assert out["exists"] is False and out["open"] == 0


def test_沒有TODO或CHANGELOG也不會爆(fake_root, tmp_path):
    (tmp_path / "空專案").mkdir()
    out = main.project_status("空專案")
    assert out["exists"] is True and out["open"] == 0 and out["last"] == ""


@pytest.mark.parametrize("bad", ["../../../etc", "Program/../../..", "a/../../.."])
def test_跨不出根目錄(fake_root, bad):
    """⛔ 這支會讀磁碟上的檔,路徑一定要關在使用者的資料根目錄底下。"""
    with pytest.raises(main.ApiError) as e:
        main.project_status(bad)
    assert e.value.status == 400


def test_絕對路徑會被當成相對路徑_不會讀到系統檔(fake_root):
    """`/etc` 開頭的斜線會被剝掉 → 變成根目錄底下的 `etc`,讀不到就回 exists:False。
    這比直接報錯好:行為可預期,而且一樣跨不出去。"""
    out = main.project_status("/etc")
    assert out["path"] == "etc" and out["exists"] is False


def test_沒給路徑就報錯(fake_root):
    with pytest.raises(main.ApiError):
        main.project_status("")


def test_讀不懂格式時要老實說_不能假裝沒事(fake_root, tmp_path):
    """⛔ 有 TODO.md 卻一個 `- [ ]` 都沒有,代表**我讀不懂**,不是「都做完了」。
    靜默回 0 會讓圖上顯示「這個專案沒事」——最傷的一種錯。"""
    proj = tmp_path / "老格式"
    proj.mkdir()
    (proj / "TODO.md").write_text("# TODO\n\n- 用純項目符號寫的\n- 沒有方框\n", encoding="utf-8")
    out = main.project_status("老格式")
    assert out["open"] == 0 and out["unreadable"] is True


def test_讀得懂的時候不要誤報讀不懂(fake_root):
    assert main.project_status("Program/demo")["unreadable"] is False


def test_MUST_同步區整段不算_不然是自己數自己(fake_root, tmp_path):
    """⛔ 同步區是心智圖生成的**回音**:那幾條本來就以待辦節點掛在同一分支上,
    算進 open 就變成雙重計算(2026-08-04 抓到 Finance 徽章被灌水 26 條)。
    `⏳` 同理:專案慣例=「等使用者的輸入」,心智圖=「還沒開始」,整段跳過一起解決。"""
    proj = tmp_path / "有同步區"
    proj.mkdir()
    (proj / "TODO.md").write_text(
        "# TODO\n"
        "<!-- mm:begin x -->\n"
        "- [ ] ⏳ 心智圖來的,還沒開始 <!--mm:t1-->\n"
        "- [x] ✅ 心智圖來的,做完了 <!--mm:t2-->\n"
        "<!-- mm:end -->\n"
        "- [ ] ⏳ 2026-08-01 這條才是真的在等使用者\n"
        "- [x] 專案自己做完的\n",
        encoding="utf-8",
    )
    out = main.project_status("有同步區")
    assert out["open"] == 1, "只算專案自己的未完成"
    assert out["done"] == 1, "只算專案自己的完成"
    assert out["waiting"] == 1, "只有手寫區那條算「等你」"


def test_整份都是同步區不算讀不懂_是真的沒有自己的事(fake_root, tmp_path):
    """同步區外沒有任何清單 → 不是格式讀不懂,是專案自己沒另外的事。"""
    proj = tmp_path / "純同步區"
    proj.mkdir()
    (proj / "TODO.md").write_text(
        "# TODO\n<!-- mm:begin x -->\n- [ ] ⏳ 圖來的 <!--mm:t1-->\n<!-- mm:end -->\n",
        encoding="utf-8",
    )
    out = main.project_status("純同步區")
    assert out["open"] == 0 and out["unreadable"] is False


def test_同步區外只剩老格式清單_還是要老實說讀不懂(fake_root, tmp_path):
    """voice_to_text 的實例:同步區有方框,但專案自己的 backlog 是純項目符號。
    同步區的方框不能拿來遮掉「自己的部分讀不懂」這件事。"""
    proj = tmp_path / "混格式"
    proj.mkdir()
    (proj / "TODO.md").write_text(
        "# TODO\n<!-- mm:begin x -->\n- [ ] ⏳ 圖來的 <!--mm:t1-->\n<!-- mm:end -->\n"
        "- 純項目符號的 backlog\n",
        encoding="utf-8",
    )
    out = main.project_status("混格式")
    assert out["unreadable"] is True


def test_不會寫任何東西(fake_root):
    """⛔ 這是整個設計的重點:拉不推。跑完檔案內容與 mtime 都不能變。"""
    todo = fake_root / "Program" / "demo" / "TODO.md"
    before = (todo.read_text(encoding="utf-8"), todo.stat().st_mtime)
    main.project_status("Program/demo")
    assert (todo.read_text(encoding="utf-8"), todo.stat().st_mtime) == before


def test_連內容一起回傳_不只數字(fake_root):
    """使用者的需求(2026-08-08):「我所有專案都是直接看這個心智圖」——只給數字就得離開圖翻檔案。"""
    st = main.project_status("Program/demo")
    assert st["items"], "要回傳未完成項目的文字"
    assert all(isinstance(x, str) and x for x in st["items"])
    assert len(st["items"]) == st["open"]


def test_內容要去掉markdown裝飾(fake_root, tmp_path):
    (tmp_path / "Program" / "demo" / "TODO.md").write_text(
        "# T\n- [ ] **粗體的事** 用 `tool.py` 跑 <!--mm:x-->\n", encoding="utf-8"
    )
    st = main.project_status("Program/demo")
    assert st["items"] == ["粗體的事 用 tool.py 跑"]


def test_MUST_同步區的行不算專案自己的待辦(fake_root, tmp_path):
    """同步區是心智圖的回音,列進來等於在圖上看到自己的東西兩次。"""
    (tmp_path / "Program" / "demo" / "TODO.md").write_text(
        "# T\n<!-- mm:begin -->\n- [ ] 圖上來的 <!--mm:a-->\n<!-- mm:end -->\n- [ ] 專案自己的\n",
        encoding="utf-8",
    )
    st = main.project_status("Program/demo")
    assert st["items"] == ["專案自己的"]


def test_太多條只給前幾條_剩下的用數字表示(fake_root, tmp_path):
    lines = "\n".join(f"- [ ] 第 {i} 件" for i in range(1, 20))
    (tmp_path / "Program" / "demo" / "TODO.md").write_text(f"# T\n{lines}\n", encoding="utf-8")
    st = main.project_status("Program/demo")
    assert st["open"] == 19
    assert len(st["items"]) == main.ITEM_LIMIT  # 圖是門戶不是倉庫


def test_專案可以明確宣告自己沒有待辦_就不再報格式問題(fake_root, tmp_path):
    """同步區外的條列有兩種(寫錯格式的待辦 / 純說明),程式分不出來 → 不猜,要專案自己宣告。
    使用者的需求(2026-08-08):「不要有些專案讀到沒感覺,有些讀到會做」—— 每個專案都要有明確狀態。"""
    (tmp_path / "Program" / "demo" / "TODO.md").write_text(
        "# T\n<!-- mm:no-own-todos 這個專案的待辦全在心智圖,以下是說明 -->\n"
        "- 它是什麼:一個轉錄工具\n- 終極目的:賺錢\n",
        encoding="utf-8",
    )
    st = main.project_status("Program/demo")
    assert not st["unreadable"]
    assert st["declared_no_own"]


def test_MUST_整份都沒有方框才算讀不懂(fake_root, tmp_path):
    """這才是真的危險:AI 用了別的格式寫待辦,圖上卻顯示「這個專案沒事了」。"""
    (tmp_path / "Program" / "demo" / "TODO.md").write_text(
        "# T\n- 要修 A\n- 要修 B\n- 要修 C\n", encoding="utf-8"
    )
    assert main.project_status("Program/demo")["unreadable"]
