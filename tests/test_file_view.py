"""/file/ 唯讀檢視的把關測試。

它會讀資料根目錄底下的真實檔案給瀏覽器看,所以重點跟 /api/project 一樣:
**跨不出根目錄、只收 .md、不寫任何東西**。
"""

import pytest

import main


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROJECTS_ROOT", tmp_path / "data")
    monkeypatch.setattr(main, "CONFIG_ROOT", tmp_path / "conf")
    (tmp_path / "conf").mkdir()
    (tmp_path / "conf" / "core.md").write_text("# 全域核心規則\n", encoding="utf-8")
    tmp_path = tmp_path / "data"
    tmp_path.mkdir()
    notes = tmp_path / "notes"
    notes.mkdir(parents=True)
    (notes / "guide.md").write_text(
        "# Guide\n\n<script>alert(1)</script> 三層:設施/行為/內容\n", encoding="utf-8"
    )
    (tmp_path / "secret.key").write_text("machine-key", encoding="utf-8")
    return tmp_path


def test_讀得到md並輸出成頁面(fake_root):
    html = main.file_view("notes/guide.md")
    assert "三層:設施/行為/內容" in html
    assert "唯讀" in html  # 頁面要講明白這裡改不了,正本在檔案裡


def test_MUST_內容要跳脫_不能把筆記當HTML執行(fake_root):
    """筆記裡的 <script> 若原樣輸出,開一頁筆記=執行任意程式。"""
    html = main.file_view("notes/guide.md")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize("bad", ["../../../etc/passwd.md", "notes/../../x.md"])
def test_MUST_跨不出根目錄(fake_root, bad):
    with pytest.raises(main.ApiError) as e:
        main.file_view(bad)
    assert e.value.status == 400


def test_MUST_非md一律拒絕(fake_root):
    """根目錄底下也有密鑰類檔案,白名單只開 .md。"""
    with pytest.raises(main.ApiError) as e:
        main.file_view("secret.key")
    assert e.value.status == 400


def test_找不到回404(fake_root):
    with pytest.raises(main.ApiError) as e:
        main.file_view("notes/missing.md")
    assert e.value.status == 404


def test_不會寫任何東西(fake_root):
    p = fake_root / "notes" / "guide.md"
    before = (p.read_text(encoding="utf-8"), p.stat().st_mtime)
    main.file_view("notes/guide.md")
    assert (p.read_text(encoding="utf-8"), p.stat().st_mtime) == before


def test_規則正本住在另一個根_也讀得到(fake_root):
    """全域規則與 skill 的正本在 ~/claude-config,不在資料根目錄底下。"""
    html = main.file_view("@config/core.md")
    assert "全域核心規則" in html


def test_MUST_symlink指到規則根的檔案不能被自己的防護擋掉(fake_root, tmp_path):
    """領域的 CLAUDE.md 是 symlink 指到 claude-config —— 只認 PROJECTS_ROOT
    的話,點下去會變成「路徑不合法」,規則指針節點等於全壞。"""
    dom = fake_root / "Finance"
    dom.mkdir()
    (dom / "CLAUDE.md").symlink_to(tmp_path / "conf" / "core.md")
    assert "全域核心規則" in main.file_view("Finance/CLAUDE.md")


@pytest.mark.parametrize("bad", ["@config/../../etc/passwd.md", "@config/../x.md"])
def test_MUST_config根一樣跨不出去(fake_root, bad):
    with pytest.raises(main.ApiError):
        main.file_view(bad)
