# 千面录 · The Codex of a Thousand Faces

本地 SillyTavern 角色卡展览与管理应用。直接索引你硬盘上的卡文件，不复制；可查看人设、开场白、世界书、正则、脚本，可编辑，可让大模型评分并写一段给玩家看的总评。

- 读写 PNG / WebP / JSON 角色卡（V1 / V2 / V3）
- 首页 2:3 封面展墙，分类为 全部 / 未分类 / 收藏 + 自建分类
- 详情页：人设、开场白、世界书（位置、优先级、关键词、递归）、正则、脚本、点评
- 评分：10 分制，标准在 `backend/rating/rubric.json`，提示词在 `backend/rating/prompts/`
- 桌面窗口（pywebview，Edge 内核）；后端 FastAPI + SQLite

## 运行

需要 Python 3.14、Node 20+。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python app.py            # 弹出窗口
.\.venv\Scripts\python app.py --headless # 只起后端
```

## 数据与配置

应用数据在 `%LOCALAPPDATA%\qianmianlu\`（`config.json`、`library.db`、缩略图缓存）。环境变量 `QIANMIANLU_HOME` 可改位置。

评分用 OpenAI 兼容接口，在设置页填地址、Key、模型。Key 只存在上面的 `config.json`，不进仓库、日志和数据库。

改卡会直接改原文件，不做备份。第一次建议收录一份复制出来的文件夹。

## 测试

```powershell
.\.venv\Scripts\python -m pytest -q
```

评分测试里有几张第三方作者的真卡样本，没有随仓库发布，缺文件时对应测试自动跳过。

## 打包

```powershell
cd frontend; npm run build; cd ..
.\.venv\Scripts\pip install -r requirements-build.txt
.\.venv\Scripts\pyinstaller qianmianlu.spec --noconfirm   # 产物 dist\千面录.exe
```

## 目录

| 路径 | 内容 |
|---|---|
| `backend/card` | 卡的读写与格式转换 |
| `backend/library` | 扫描、数据库、监听、缩略图、来源 |
| `backend/rating` | 评分标准、提示词、统计、调用模型、算分 |
| `backend/api` | FastAPI 接口 |
| `frontend` | Vue 3 + Vite 前端 |
| `design` | 设计稿与字体、封面处理脚本（`D-千面录.html` 是最终稿） |
| `app.py` | 桌面入口 |

## 素材说明

- 字体来自 Google Fonts（SIL OFL）。
- `design/assets/covers/` 里的示例封面是博物馆公开图像，仅用于设计稿。
