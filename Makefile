check: lint test py39

lint:
	uv run ruff check .

py39:  # 執行環境是系統 python 3.9,語法不相容會在 launchd 下炸
	/usr/bin/python3 -m py_compile main.py

test:
	uv run pytest -q

fmt:
	uv run ruff format .

run:
	uv run python main.py

# 真的開瀏覽器把「排今天」點過一輪(用正式圖的複本+臨時埠,不碰正本、不佔 8030)。
# ⚠️ 需要 Chromium,所以刻意不在 `make check` 裡 —— 沒瀏覽器的機器不該因此變紅。
verify-day:
	uv run --with playwright python tools/verify_day.py

# 真的開瀏覽器把「待辦事項」點過一輪(複本+臨時埠,不碰正本)。⚠️ 需要 Chromium,同樣不進 make check。
verify-topics:
	uv run --with playwright python tools/verify_topics.py

# 真的開瀏覽器驗四頁的第一排一致 + 心智圖的工具還按得動(複本+臨時埠)。⚠️ 需要 Chromium。
verify-nav:
	uv run --with playwright python tools/verify_nav.py
