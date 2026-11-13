# 千面录 · Qianmianlu

**The Codex of a Thousand Faces — a gallery and manager for your local SillyTavern character cards.**
**一本收着上千张面孔的册子：把本地 SillyTavern 角色卡当作展品来看、来改、来评分。**

[English](#english) · [简体中文](#简体中文)

![Home / 首页](docs/screenshots/home.jpg)

---

## English

Qianmianlu is a Windows desktop app that turns a folder of character cards into an exhibition wall. It indexes your original files in place (nothing is copied), shows what is inside each card, lets you edit it, and can ask an LLM to score it.

### Features

- **Exhibition wall.** 2:3 cover grid in the style of a game library. Hover a card and its cover becomes a softly blurred, slowly zooming backdrop; the UI accent color follows the cover. A random zodiac star map drifts across the background.
- **Reads everything.** PNG / WebP / JSON cards, V1 / V2 / V3, Chinese and emoji safe. Broken files are flagged instead of stopping the scan.
- **Card details.** Persona fields, greetings, lorebook (position, priority, keywords, recursion flags, token estimate), regex scripts and scripts. Click an entry to edit it in place.
- **Edit in place.** Edits are written straight to the original file. If another program changed the file in the meantime, saving is refused instead of overwriting.
- **LLM rating, 10-point scale.** Weighted rubric, bonus and penalty rules, and a short review written for players. You can override the total score. Works with any OpenAI-compatible API and your own key.
- **Your own shelves.** All / Unsorted / Favorites plus categories you name yourself. Duplicate cards (same content) are shown once.
- **Local first.** The backend only listens on `127.0.0.1`. The API key is stored in your user profile, never in the repository, logs or database.

### Screenshots

| Hover a card | Card page |
|---|---|
| ![Hover](docs/screenshots/hover.jpg) | ![Detail](docs/screenshots/detail.jpg) |

| Lorebook | Greetings |
|---|---|
| ![Lorebook](docs/screenshots/worldbook.jpg) | ![Greetings](docs/screenshots/greetings.jpg) |

Demo cards are original characters (OC) by the author.

### Run from source

Requires Python 3.14 and Node 20+.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python app.py             # desktop window
.\.venv\Scripts\python app.py --headless  # backend only
```

Click **收录 (Import)** on the home page, then pick a folder or cards. Rating needs an API address, key and model in Settings.

### Data and safety

- App data lives in `%LOCALAPPDATA%\qianmianlu\` (`config.json`, `library.db`, thumbnail cache). Set `QIANMIANLU_HOME` to move it.
- **Editing changes your original files and no backup is made.** Try it on a copy of your folder first.
- "Clear library" only deletes scan data. Files on disk are untouched; ratings, favorites and categories are kept.

### Build an exe

```powershell
cd frontend; npm run build; cd ..
.\.venv\Scripts\pip install -r requirements-build.txt
.\.venv\Scripts\pyinstaller qianmianlu.spec --noconfirm   # dist\千面录.exe
```

### Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

Rating tests that need real third-party cards are skipped when the sample files are absent.

### Layout

| Path | What it holds |
|---|---|
| `backend/card` | Reading and writing cards |
| `backend/library` | Scanner, SQLite index, watcher, thumbnails, sources |
| `backend/rating` | Rubric, prompts, statistics, LLM client, scoring |
| `backend/api` | FastAPI routes |
| `frontend` | Vue 3 + Vite UI |
| `design` | Design mock-ups, fonts and helper scripts |
| `app.py` | Desktop entry point (pywebview) |

Stack: Python, FastAPI, SQLite (FTS5), Pillow, watchdog, pywebview, Vue 3, Vite.

---

## 简体中文

千面录是一个 Windows 桌面应用，把一个文件夹的角色卡变成展览墙。它直接索引你的原文件（不复制），能看卡里的内容、直接改，也能让大模型给卡打分。

### 功能

- **展览墙。** 2:3 竖封面网格，参考 Steam 库。鼠标放在卡上，封面轻度模糊后铺成背景并慢慢放大，界面主题色跟着封面变。背景里随机浮现黄道十二宫星图。
- **什么都能读。** PNG / WebP / JSON，V1 / V2 / V3，中文和 emoji 不乱码。坏卡会被标出来，不会中断扫描。
- **卡片详情。** 人设、开场白、世界书（位置、优先级、触发关键词、递归开关、token 估算）、正则、脚本。点一下条目就能原地修改。
- **直接改原文件。** 保存时写回原文件。如果文件被别的软件改过，会拒绝保存，不会覆盖。
- **大模型评分，10 分制。** 有权重、加分和扣分规则，还会写一段给玩家看的总评。总分可以由你自己改。支持任意 OpenAI 兼容接口，用你自己的 Key。
- **自己的分类。** 全部 / 未分类 / 收藏，加上自建分类。内容相同的卡只显示一张。
- **本地优先。** 后端只监听 `127.0.0.1`。API Key 存在用户目录里，不进仓库、日志和数据库。

### 截图

截图见上方英文部分。演示用的是作者自己的原创角色卡（OC）。

### 从源码运行

需要 Python 3.14 和 Node 20+。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python app.py             # 打开桌面窗口
.\.venv\Scripts\python app.py --headless  # 只起后端
```

在首页点「收录」，选择文件夹或卡片。评分需要先在设置页填接口地址、Key 和模型。

### 数据与安全

- 应用数据在 `%LOCALAPPDATA%\qianmianlu\`（`config.json`、`library.db`、缩略图缓存），环境变量 `QIANMIANLU_HOME` 可改位置。
- **编辑会直接改你的原文件，不做备份。** 第一次请先用复制出来的文件夹试。
- 「清空卡库」只删扫描数据，不删硬盘上的文件，评分、收藏和分类会保留。

### 打包成 exe

```powershell
cd frontend; npm run build; cd ..
.\.venv\Scripts\pip install -r requirements-build.txt
.\.venv\Scripts\pyinstaller qianmianlu.spec --noconfirm   # 产物 dist\千面录.exe
```

### 测试

```powershell
.\.venv\Scripts\python -m pytest -q
```

需要第三方真卡样本的评分测试，在缺文件时自动跳过。

### 目录

| 路径 | 内容 |
|---|---|
| `backend/card` | 卡的读写 |
| `backend/library` | 扫描、SQLite 索引、监听、缩略图、来源 |
| `backend/rating` | 评分标准、提示词、统计、调用模型、算分 |
| `backend/api` | FastAPI 接口 |
| `frontend` | Vue 3 + Vite 界面 |
| `design` | 设计稿、字体和辅助脚本 |
| `app.py` | 桌面入口（pywebview） |

技术栈：Python、FastAPI、SQLite（FTS5）、Pillow、watchdog、pywebview、Vue 3、Vite。

---

## Credits / 素材

Fonts come from Google Fonts (SIL OFL). Sample covers in `design/assets/covers/` are public-domain museum images used only by the design mock-up.
字体来自 Google Fonts（SIL OFL）。`design/assets/covers/` 里的示例封面是博物馆公开图像，只用于设计稿。
