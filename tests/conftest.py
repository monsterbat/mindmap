"""所有測試共用的安全網。

⛔ **測試不准碰正式資料**(專案 CLAUDE.md 的硬規則)。
以前只靠「每個測試自己記得 monkeypatch」——2026-08-17 就漏了一次:
`mm.py merge` 的測試沒有蓋掉 `RETIRED_PATH`,於是把測試用的假 id(t/t2/t3)
寫進了**真的** `Workspace/mindmaps/.retired_ids.json`。沒有任何錯誤訊息,
是事後手動看那個檔才發現的。

→ 改成 autouse:預設全部指向 tmp,個別測試要更精確再自己蓋一次。
"""

import pytest


@pytest.fixture(autouse=True)
def _never_touch_real_files(tmp_path, monkeypatch):
    """凡是會寫到磁碟的路徑,一律先改指到 tmp。"""
    monkeypatch.setenv("MINDMAP_PROJECTS_ROOT", str(tmp_path / "projects"))
    try:
        import mm
    except ImportError:  # 不是所有測試都用得到 mm
        return
    monkeypatch.setattr(mm, "RETIRED_PATH", tmp_path / ".retired_ids.json", raising=False)
    monkeypatch.setattr(mm, "ARCHIVE_PATH", tmp_path / "完成紀錄.md", raising=False)
