"""给正式前端下载完整的 ZCOOL XiaoWei / Noto Serif SC。

正式版的卡名是任意汉字，设计稿那种按页面用字裁出来的子集会让没收录的字掉回系统字体。
这里取 Google Fonts 官方按 unicode-range 切好的全部分片（每片几十 KB），写成本地文件，
浏览器只会按页面实际用到的字去加载对应分片，覆盖全部汉字又不用一次载入整套字体。

用法：python design/tools/fetch_full_fonts.py
产物：frontend/src/assets/fonts.css 与 frontend/src/assets/fonts/
西文字体（UnifrakturMaguntia、Cinzel Decorative）与小薇体补丁直接沿用 design/assets 里的文件。
"""
import re
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_FONTS = ROOT / "design" / "assets" / "fonts"
OUT = ROOT / "frontend" / "src" / "assets"
OUT_FONTS = OUT / "fonts"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

# (Google 查询串, 本地文件前缀)
TARGETS = [
    ("family=ZCOOL+XiaoWei", "ZCOOLXiaoWei"),
    ("family=Noto+Serif+SC:wght@400;900", "NotoSerifSC"),
]
KEEP_LOCAL = [
    "UnifrakturMaguntia-0.woff2", "CinzelDecorative-0.woff2", "CinzelDecorative-1.woff2",
    "ZCOOLXiaoWei-patch.woff2",
]
LATIN_AND_PATCH = """\
/* latin */
@font-face {
  font-family: 'UnifrakturMaguntia';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url(./fonts/UnifrakturMaguntia-0.woff2) format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}

/* latin-ext */
@font-face {
  font-family: 'Cinzel Decorative';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url(./fonts/CinzelDecorative-0.woff2) format('woff2');
  unicode-range: U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF;
}
/* latin */
@font-face {
  font-family: 'Cinzel Decorative';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url(./fonts/CinzelDecorative-1.woff2) format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}

/* ZCOOL XiaoWei 里「囗」被涂黑的 8 个字，用修好的字形补上（design/tools/build_xiaowei_patch.py 生成；回是 Master 手绘）。
   必须放在整套小薇体分片之后：同名同字重后声明的优先。 */
@font-face {
  font-family: 'ZCOOL XiaoWei';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url(./fonts/ZCOOLXiaoWei-patch.woff2) format('woff2');
  unicode-range: U+56DE, U+5703, U+5704, U+570A, U+5D2E, U+5F8A, U+75FC, U+86D4;
}
"""


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def slices(query: str):
    css = get(f"https://fonts.googleapis.com/css2?{query}&display=swap").decode()
    for block in re.findall(r"@font-face\s*\{[^}]*\}", css):
        family = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        url = re.search(r"url\((https://[^)]+)\)", block).group(1)
        rng = re.search(r"unicode-range:\s*([^;]+);", block).group(1)
        yield family, weight, url, rng


def main() -> None:
    OUT_FONTS.mkdir(parents=True, exist_ok=True)
    jobs, blocks = [], []
    for query, prefix in TARGETS:
        counter: dict[str, int] = {}
        for family, weight, url, rng in slices(query):
            n = counter[weight] = counter.get(weight, -1) + 1
            name = f"{prefix}-{weight}-{n}.woff2"
            jobs.append((url, OUT_FONTS / name))
            blocks.append(
                f"@font-face {{\n  font-family: '{family}';\n  font-style: normal;\n  font-weight: {weight};\n"
                f"  font-display: swap;\n  src: url(./fonts/{name}) format('woff2');\n  unicode-range: {rng};\n}}\n"
            )
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda j: j[1].write_bytes(get(j[0])), jobs))
    for name in KEEP_LOCAL:
        shutil.copyfile(SRC_FONTS / name, OUT_FONTS / name)
    (OUT / "fonts.css").write_text(
        "/* 由 design/tools/fetch_full_fonts.py 生成，勿手改 */\n" + "\n".join(blocks) + "\n" + LATIN_AND_PATCH,
        encoding="utf-8",
    )
    total = sum(f.stat().st_size for f in OUT_FONTS.iterdir())
    print(f"{len(jobs)} 个分片，字体目录共 {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
