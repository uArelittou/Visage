"""生成 ZCOOL XiaoWei 坏字补丁 assets/fonts/ZCOOLXiaoWei-patch.woff2。

坏字：回 圃 圄 圊 崮 徊 痼 蛔。原字形里「囗」的内框轮廓方向和外框相同，
按非零环绕规则会被填成实心。
- 圃圄圊崮徊痼蛔：把内框轮廓反向，镂空即恢复，字形仍是小薇体原样。
- 回：外框、内框都要镂空，原字形缺内孔，改用 Master 手绘的字形（HUI_TTF）。

用法：python design/tools/build_xiaowei_patch.py <完整 ZCOOL XiaoWei ttf> <手绘回字 ttf>
完整字体可从 Google Fonts API 带 &text=回圃圄圊崮徊痼蛔 取得 woff2，再转 ttf。
需要 fonttools、brotli。
"""
import sys
from pathlib import Path

from fontTools import subset
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

OUT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "ZCOOLXiaoWei-patch.woff2"
BAD = "圃圄圊崮徊痼蛔"
ADVANCE = 1024  # 小薇体字宽 1024，upem 1000


def reverse_inner_box(font: TTFont, ch: str) -> None:
    glyf = font["glyf"]
    gl = glyf[font.getBestCmap()[ord(ch)]]
    coords, ends, flags = gl.getCoordinates(glyf)
    coords, flags = list(coords), list(flags)
    start = 0
    for end in ends:
        pts = coords[start : end + 1]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        # 内框是 4~5 点的矩形，宽高都明显大于笔画
        if len(pts) <= 5 and max(xs) - min(xs) >= 200 and max(ys) - min(ys) >= 200:
            idx = list(range(start, end + 1))
            for dst, src in zip(idx, idx[::-1]):
                coords[dst], flags[dst] = pts[src - start], flags[src]
        start = end + 1
    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

    gl.coordinates = GlyphCoordinates(coords)
    gl.flags = bytearray(flags)
    gl.recalcBounds(glyf)


def main(full_ttf: str, hui_ttf: str) -> None:
    font = TTFont(full_ttf)
    for ch in BAD:
        reverse_inner_box(font, ch)

    hui = TTFont(hui_ttf)
    src = hui.getGlyphSet()[hui.getBestCmap()[0x56DE]]
    pen = TTGlyphPen(font.getGlyphSet())
    # 手绘字宽 1000，居中到 1024 字宽
    src.draw(TransformPen(pen, (1, 0, 0, 1, (ADVANCE - 1000) / 2, 0)))
    name = font.getBestCmap()[0x56DE]
    glyph = pen.glyph()
    font["glyf"][name] = glyph
    glyph.recalcBounds(font["glyf"])
    font["hmtx"][name] = (ADVANCE, glyph.xMin)

    # 去掉 hinting：改过的轮廓配旧指令，部分渲染器会画错
    opt = subset.Options()
    opt.layout_features = []
    opt.hinting = False
    opt.notdef_outline = False
    opt.name_IDs = [1, 2]
    sub = subset.Subsetter(opt)
    sub.populate(text="回" + BAD)
    sub.subset(font)
    font.flavor = "woff2"
    font.save(OUT)
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main(*sys.argv[1:3])
