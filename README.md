# Mindmap

[English](#english) | [繁體中文](#繁體中文)

<a id="english"></a>

## English

A planning tool built around one idea: **a task list and an architecture diagram are the same
document, and both a person and an assistant should be able to edit it.**

One JSON file holds everything — projects, tasks, the reasons behind decisions, how the system is
put together. A person drags nodes around in the browser. A command-line tool (`mm.py`) lets an AI
assistant read and change the same file, without either side overwriting the other.

### Four views of one file

There is exactly one source of truth. Every page is a view of it, not a copy.

| Page | Answers |
|---|---|
| **Mind map** | What is connected to what, and why it was decided that way |
| **Task board** | What state is everything in |
| **Day planner** | Which hour am I actually doing this |
| **Topics** | For this one subject, what is still left |

Adding a fifth view means writing a renderer, not another list to keep in sync.

### Design decisions worth reading

- **Both editors leave a mark.** Nodes the assistant touched get an `aiEdited` stamp and a circle
  in the UI; nodes the person changed by hand get `scEdited`. The command-line tool refuses to
  overturn a hand-made status change from the last seven days unless forced. Without that, an
  assistant that "knows better" silently undoes what the person just decided.
- **Deadlines are only for dates someone else imposed.** A wished-for date is not a deadline. An
  early version allowed both; 32 items carried a deadline and only 6 were real, so the schedule
  printed 13 red overdue lines every run — and a screen that is always red is a screen nobody
  reads. Wishes are expressed with priority instead.
- **Estimated effort was removed from planning.** Being asked "how many hours will this take"
  before starting is a question most people cannot answer, and a wrong answer then constrains the
  plan. Blocks are dragged onto the calendar at whatever size makes sense, and one task can occupy
  several blocks across several days.
- **Some things are never finished.** Ongoing responsibilities (practise, review, maintenance) are
  a separate node type: no checkbox, no deadline, just a reusable block. Ticking something that
  recurs forever is meaningless, so the model does not offer it.
- **Waiting on a condition is not the same as waiting for a date.** "After I change jobs" has no
  date. Those items leave the todo list and live in a waiting tab until the condition is released
  by name. Forcing a date there would mean inventing one.
- **The guard tests are about not crying wolf.** A drift checker that fires on every project is
  noise, and noise gets ignored, which is worse than not having the check. Several tests exist
  purely to assert that a warning does *not* fire in the normal case.

### Two-way sync with project files

A node can point at a project folder. That project's `TODO.md` is then read live and shown in the
detail panel, and a generated block inside it mirrors the map. Ticking a box in the project file
marks the node done; the map stays authoritative for the wording.

A drift checker reports the ways the two can disagree — an item waiting on someone that exists
only in the project file, a decision in a changelog that never reached the map, a completed node
whose hand-written copy in a project file is still unticked.

### Layout

```
main.py            HTTP server and JSON API, atomic writes, conflict detection
mm.py              command-line interface — the way an assistant edits the map
plan_week.py       weekly planning: capacity, hard deadlines, hand-placed slots
sync_todos.py      two-way sync with project TODO.md files
drift_check.py     reports the ways the map and the project files disagree
cal_cache.py       reads a calendar cache so events block time
lint_map.py        structural rules, run before every write
export_md.py       renders the map as Markdown
static/
├── pages/         one HTML file per view
├── css/  js/      one pair per view, plus a shared nav
└── vendor/        the mind map widget, pinned and patched
tools/             browser smoke tests that drive the real pages
examples/          a generated demo map, so all four pages work on a fresh clone
tests/             332 tests
docs/DESIGN.md     why it is built this way
```

The eight modules at the top level are the entry points: each one is runnable on its
own and is called that way by the surrounding automation, so they stay where they are
rather than being buried in a package.

### Getting started

Requires Python 3.10+ to develop (the server itself stays compatible with the system Python 3.9).

```bash
python3 examples/make_example.py       # build a demo map, dated from today
MINDMAP_MAPS_DIR=examples python3 main.py
# open http://127.0.0.1:8030
```

Point `MINDMAP_MAPS_DIR` at your own folder to use it for real. `MINDMAP_PROJECTS_ROOT` is where
project folders are looked up for the two-way sync.

```bash
make check                             # ruff + pytest (332 tests)
make verify-day                        # drives the planner in a real browser
```

### Licence

MIT. See `LICENSE`.

---

<a id="繁體中文"></a>

## 繁體中文

一個規劃工具,想法只有一個:**待辦清單跟架構圖其實是同一份文件,而且人跟 AI 都要改得動它。**

一個 JSON 檔裝下全部 —— 專案、待辦、某個決定當初為什麼這樣定、系統是怎麼組起來的。
人在瀏覽器裡拖節點;AI 用指令列工具 `mm.py` 讀寫同一個檔,兩邊不會互相蓋掉。

### 同一份檔案,四個看法

正本只有一份,每一頁都是它的視圖,不是副本。

| 頁面 | 回答什麼 |
|---|---|
| **心智圖** | 什麼跟什麼有關,以及當初為什麼這樣定 |
| **任務板** | 每件事現在是什麼狀態 |
| **排行程** | 這件事幾點做 |
| **待辦事項** | 這一個主題還剩什麼沒做 |

要加第五個看法,是寫一個新的畫法,不是再養一份要同步的清單。

### 幾個值得一讀的設計決定

- **兩邊改過都會留記號。** AI 動過的節點蓋 `aiEdited` 並在畫面上圈起來;人手動改的蓋 `scEdited`。
  指令列工具對七天內的手動狀態變更會直接擋下來,要強制才改得動。
  沒有這個,一個「自以為知道得更清楚」的 AI 會安靜地翻掉人剛剛做的決定。
- **死線只留給外力給的日期。** 「我希望這天做完」不是死線。早期兩種都能填,結果 32 件有死線的
  只有 6 件是真的,行程表每次跑都噴 13 條紅字 —— 而**一片都是紅的畫面就等於沒有紅字**。
  願望改用優先等級表示。
- **排行程拿掉了「要花幾小時」。** 動手之前先問「這要花多久」,多數人根本答不出來,
  而答錯之後又反過來限制自己怎麼排。改成把方塊拖到日曆上、想多大就多大,
  一件事可以分成好幾塊、跨好幾天。
- **有些事永遠不會完成。** 一直要做的(練習、複習、維護)是另一種節點:沒有打勾框、沒有死線,
  就是一塊可以重複拖的積木。對一件永遠做不完的事打勾沒有意義,所以資料模型乾脆不提供。
- **「等某件事發生」跟「等某個日期」是兩回事。** 「等換到新工作之後」沒有日期。
  這種會離開待辦清單、住進「等條件」分頁,等條件被指名放行。硬要填日期就只能用編的。
- **把關測試在測的是「不要亂叫」。** 一個每個專案都會報的偵測器就是白噪音,
  而白噪音會被忽略 —— 那比沒有這個功能更糟。所以有好幾個測試單純在主張:
  正常情況下那個警告**不准**出現。

### 跟專案檔的雙向同步

節點可以指向一個專案資料夾。那個專案的 `TODO.md` 會被即時讀出來顯示在詳情面板,
檔案裡也有一段由心智圖生成的區塊。在專案檔打勾會讓節點變成完成;文字以心智圖為準。

另有一支偵測器,專門報兩邊對不起來的情況 —— 在等別人的事只寫在專案檔、
變更紀錄裡有決定卻沒進圖、圖上已完成但專案檔那份手寫副本還沒打勾。

### 資料夾怎麼分

```
main.py            HTTP 伺服器與 JSON 介面:原子寫入、衝突偵測
mm.py              指令列介面 —— AI 就是用這支改圖
plan_week.py       每週排程:容量、硬死線、手排過的時段
sync_todos.py      跟各專案 TODO.md 的雙向同步
drift_check.py     報告圖跟專案檔哪裡對不起來
cal_cache.py       讀行事曆快取,讓事件擋住時段
lint_map.py        結構規則,每次寫入前都會跑
export_md.py       把圖輸出成 Markdown
static/
├── pages/         一個視圖一個 HTML
├── css/  js/      一個視圖一組,外加共用的導覽列
└── vendor/        心智圖元件,版本釘死並記錄改過什麼
tools/             真的開瀏覽器把頁面點過一輪的檢查
examples/          範例圖產生器,clone 下來四頁就都是活的
tests/             332 項測試
docs/DESIGN.md     為什麼這樣設計
```

最上層那八支是**入口**:每一支都可以自己跑,外面的自動化也是這樣叫它們的,
所以刻意留在最上層,⛔ 不埋進套件裡。

### 開始用

開發需要 Python 3.10 以上(伺服器本身仍相容系統內建的 3.9)。

```bash
python3 examples/make_example.py       # 產一份範例圖,日期從今天往後算
MINDMAP_MAPS_DIR=examples python3 main.py
# 開 http://127.0.0.1:8030
```

`MINDMAP_MAPS_DIR` 指到自己的資料夾就能正式用。`MINDMAP_PROJECTS_ROOT` 是雙向同步要去哪裡找專案。

```bash
make check                             # ruff + pytest(332 項測試)
make verify-day                        # 真的開瀏覽器把排行程點過一輪
```

### 授權

MIT,見 `LICENSE`。
