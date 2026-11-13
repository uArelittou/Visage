# PyInstaller 打包配置：先在 frontend 里 npm run build，再在项目根执行
#   .\.venv\Scripts\pyinstaller qianmianlu.spec --noconfirm
# 产物：dist\千面录.exe（单文件、无控制台窗口）
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("frontend/dist", "frontend/dist"),
    ("backend/rating/rubric.json", "backend/rating"),
    ("backend/rating/prompts", "backend/rating/prompts"),
]

a = Analysis(
    ["app.py"],
    pathex=["."],
    datas=datas,
    # uvicorn 按字符串名动态加载协议和事件循环实现，静态分析看不到
    hiddenimports=collect_submodules("uvicorn"),
    excludes=["pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="千面录",
    console=False,
    upx=False,
    icon="assets/qianmian.ico",
)
