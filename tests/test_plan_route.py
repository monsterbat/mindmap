"""行程表 /plan 已於 2026-09-08 退休 —— 這支現在守的是「退休有沒有退乾淨」。

定案收掉的理由有兩條:
① 使用者自己說過「這個我覺得不用管他,反正我好像也都沒有在用他的」;
② 「行程表 /plan」跟「排行程 /day」名字只差一個字,分不出來。

⚠️ **退休的是網頁那一頁,不是 `plan_week.py`。**
`plan_week.py` 是 /day、mm.py 與每週死線警報的共用核心,砍了那三個都會壞。

⭐ 這支最重要的是最後一組:**驗「能力」還在,不是驗「檔案刪掉了」。**
   (Workspace 的血淚:退役舊工具要對能力,清單搬完了功能還是會靜靜地掉,而且不會報錯。)
"""

import os
import pathlib

import main

MAIN_SRC = pathlib.Path(main.__file__).read_text(encoding="utf-8")


# ── 退乾淨了嗎 ────────────────────────────────────────────────

def test_plan_網頁三個檔都不在了():
    for name in ("plan.html", "plan.js", "plan.css"):
        assert not main.static_file(name).exists(), f"{name} 又跑回來了"


def test_plan_路由與_API_都拿掉了():
    assert '"/plan"' not in MAIN_SRC, "/plan 路由又被加回來了"
    assert '"/api/plan"' not in MAIN_SRC, "/api/plan 又被加回來了"
    assert not hasattr(main, "weekly_plan"), "weekly_plan 又被加回來了"


def test_沒有頁面還連著行程表():
    """一個點下去 404 的連結,比沒有連結更糟。"""
    for html in main.STATIC_DIR.glob("*.html"):
        assert 'href="/plan"' not in html.read_text(encoding="utf-8"), html.name


# ── ⭐ 能力還在嗎(這組才是重點)────────────────────────────────

def test_MUST_plan_week_沒有被一起砍掉():
    """⛔ 它不是 /plan 的附屬品 —— main.py 有 6 處、mm.py 有 2 處在 import 它。"""
    assert (pathlib.Path(main.__file__).parent / "plan_week.py").is_file()
    import plan_week
    for fn in ("collect_tasks", "load_rhythm", "merged_busy", "load_calendar", "strip_mark"):
        assert hasattr(plan_week, fn), f"plan_week.{fn} 不見了"
    for const in ("EFFORT_HOURS", "PRIS", "DONE"):
        assert hasattr(plan_week, const), f"plan_week.{const} 不見了"


def test_MUST_排行程還在用_plan_week():
    """/day 的「哪幾天排不了事」「行事曆卡住的時段」全部走它。"""
    assert "import plan_week" in MAIN_SRC
    for fn in ("plan_week.merged_busy", "plan_week.collect_tasks", "plan_week.load_rhythm"):
        assert fn in MAIN_SRC, f"{fn} 不見了 → /day 會壞"


def test_MUST_死線警報還有一條路():
    """⛔ 使用者唯一會看到「哪幾件趕不上死線」的地方,現在只剩每週的排程這一條。
    /plan 收掉之後如果連它也斷了,那個能力就**安靜地**消失了。"""
    sh = pathlib.Path(os.environ.get(
        "MINDMAP_WEEKLY_SCRIPT",
        pathlib.Path.home() / "planning/weekly.sh"))
    if not sh.is_file():         # 沒設或不存在時不該讓測試變紅
        return
    text = sh.read_text(encoding="utf-8")
    assert "plan_week.py" in text, "每週的排程不再跑 plan_week → 死線警報整個消失了"
    assert "趕不上死線" in text, "每週的排程不再回報趕不上死線的那幾件"


def test_MUST_plan_week_指令列版自己跑得起來():
    """網頁沒了,指令列版就是唯一的入口 —— 它必須自己是可執行的。"""
    src = (pathlib.Path(main.__file__).parent / "plan_week.py").read_text(encoding="utf-8")
    assert "__main__" in src, "plan_week.py 沒有指令列入口了"
