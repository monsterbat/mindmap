# vendor 修補紀錄

vendor 檔是第三方發行版,原則上不改。**這裡列出的是刻意的例外**——升版時要重新套用。

## MindElixir.iife.js(mind-elixir 5.14.0)

**2026-08-03 — 樹狀連線要標出「連到哪個節點」**

原碼把所有連線畫進共用的 `<svg class="lines">` / `subLines`,**path 上沒有任何識別**,所以外部完全無法針對某一條線上色或隱藏。

需求:待辦節點的線要跟一般結構線長得不一樣(SC 2026-08-03:「這條線比較特別,他就是專門為待辦而設計的線段」),而且整批隱藏待辦時線也要一起藏。

修法:兩個 `appendChild` 的 call site 包一層,把**目標節點的 id** 寫進 `data-nodeid`。

```js
// linkDiv(主分支線)
this.lines.appendChild((_p=>(_p.setAttribute("data-nodeid",a.nodeObj.id),_p))(ze(m,g,"3")))
// qe(子分支線)
t.appendChild((_p=>(_p.setAttribute("data-nodeid",v.firstChild.nodeObj.id),_p))(ze(N,E,"2")))
```

**純加標記,不改幾何也不改顏色**——原本的行為一模一樣。

複查指令(應該要輸出 2):

```bash
python3 -c "print(open('MindElixir.iife.js').read().count('data-nodeid'))"
```

## node-menu.umd.js(@mind-elixir/node-menu 5.0.1)

**2026-08-02 — 自訂顏色會讓面板炸掉**

原碼三處在選到節點時,拿節點的顏色去面板調色盤找對應色塊並標選取:

```js
u.querySelector('.palette[data-color="'+t.style.background+'"]').className = "palette nmenu-selected"
```

⚠️ 節點顏色只要**不在內建 18 色盤裡**(我們用 JSON 寫的自訂色、或別的工具設的色),`querySelector` 回 `null`,直接 `TypeError: Cannot set properties of null`。後果:面板停在上一個節點的狀態、看起來像「設定跳回去了」。

修法:查詢結果補 `||{}`,找不到就寫進暫時物件、不影響畫面。

```js
(u.querySelector('.palette[data-color="'+t.style.background+'"]')||{}).className = "palette nmenu-selected"
```

三處(background 分頁、font 分頁、面板初始化)全部套用。

**2026-08-02(同日追加)— 字級與粗體也一樣會炸**

同款問題不只顏色:面板初始化時也拿 `t.style.fontSize` 去找 `.size[data-size="…"]`、拿 `.bold`。**節點字級只要不是它內建的幾個預設值(例:我們便條樣式用的 12px),選到就 `TypeError`**。已同樣補 `||{}`,共 5 處。

複查指令(應該要沒有輸出):

```bash
python3 -c "import re;s=open('node-menu.umd.js').read();print([m.group(0) for m in re.finditer(r'querySelector\([^)]{0,80}\)\.className', s)])"
```
