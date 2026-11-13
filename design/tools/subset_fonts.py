"""按设计稿里实际出现的汉字，重新下载 ZCOOL XiaoWei / Noto Serif SC 的子集字体。

用法：python design/tools/subset_fonts.py
页面加新文字后重跑一次，否则新字会掉回系统字体。
"""
import re
import urllib.parse
import urllib.request
from pathlib import Path

DESIGN = Path(__file__).resolve().parent.parent
FONTS = DESIGN / "assets" / "fonts"
CSS = DESIGN / "assets" / "fonts.css"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

# (CSS family 名, Google family 参数, 字重列表, 本地文件前缀)
TARGETS = [
    ("ZCOOL XiaoWei", "ZCOOL+XiaoWei", [400], "ZCOOLXiaoWei"),
    ("Noto Serif SC", "Noto+Serif+SC", [400, 900], "NotoSerifSC"),
]
MARK = "/* ↓ subset_fonts.py 生成，勿手改 ↓ */"
# 手写的补丁块，重跑脚本时原样保留在生成块之后
PATCH_MARK = "/* ZCOOL XiaoWei 里「囗」被涂黑的 8 个字"


def page_chars() -> str:
    text = "".join(p.read_text(encoding="utf-8") for p in DESIGN.glob("*.html"))
    return "".join(sorted({c for c in text if ord(c) >= 0x2E80}))


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main() -> None:
    chars = page_chars()
    q = urllib.parse.quote(chars)
    blocks = []
    for family, gname, weights, prefix in TARGETS:
        for w in weights:
            css = get(f"https://fonts.googleapis.com/css2?family={gname}:wght@{w}&text={q}").decode()
            url = re.search(r"url\((https://[^)]+)\)", css).group(1)
            name = f"{prefix}-{w}.woff2"
            (FONTS / name).write_bytes(get(url))
            blocks.append(
                f"@font-face {{\n  font-family: '{family}';\n  font-style: normal;\n  font-weight: {w};\n"
                f"  font-display: swap;\n  src: url(fonts/{name}) format('woff2');\n}}\n"
            )
            print(f"{name}: {(FONTS / name).stat().st_size} bytes")

    old = CSS.read_text(encoding="utf-8")
    patch = ""
    if PATCH_MARK in old:
        old, patch = old.split(PATCH_MARK)[0], PATCH_MARK + old.split(PATCH_MARK)[1]
    if MARK in old:
        old = old.split(MARK)[0]
    else:
        # 去掉旧的同名 @font-face，避免旧子集抢先匹配
        for family, *_ in TARGETS:
            old = re.sub(r"@font-face\s*\{[^}]*font-family:\s*'" + re.escape(family) + r"'[^}]*\}\s*", "", old)
    CSS.write_text(old.rstrip() + "\n\n" + MARK + "\n" + "\n".join(blocks) + ("\n" + patch if patch else ""), encoding="utf-8")
    print(f"{len(chars)} chars")


if __name__ == "__main__":
    main()
