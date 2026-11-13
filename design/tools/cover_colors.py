"""给设计稿的每张封面取一个主题色，打印成 JS 数组，贴进 D-千面录.html 的 COL。

用法：.venv\\Scripts\\python design/tools/cover_colors.py
双击打开的 HTML 是 file:// 页面，浏览器不许 canvas 读本地图片像素，所以颜色只能预先算好。
正式版由后端在生成缩略图时算一次，存进数据库。
"""
import colorsys
import json
from pathlib import Path

from PIL import Image

COVERS = Path(__file__).resolve().parent.parent / "assets" / "covers"
BINS = 24


def hls_hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def theme(path: Path) -> list[str]:
    im = Image.open(path).convert("RGB")
    im.thumbnail((80, 80))
    acc = [[0.0, 0.0, 0.0, 0.0] for _ in range(BINS)]
    for r, g, b in im.get_flattened_data():
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.12:
            continue
        # 平均色会混成灰泥色；按色相分桶、偏向饱和的像素，取出“看起来是什么颜色”
        w = s * s * v + 0.01
        a = acc[int(h * BINS) % BINS]
        a[0] += w
        a[1] += r * w
        a[2] += g * w
        a[3] += b * w
    best = max(range(BINS), key=lambda k: acc[k - 1][0] + acc[k][0] + acc[(k + 1) % BINS][0])
    pick = [acc[best - 1], acc[best], acc[(best + 1) % BINS]]
    tw = sum(p[0] for p in pick) or 1
    r, g, b = (sum(p[i] for p in pick) / tw / 255 for i in (1, 2, 3))
    h, _, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.1:  # 近黑白的封面：给一个冷银色，不硬染色
        return [hls_hex(h, 0.72, 0.12), hls_hex(h, 0.2, 0.12)]
    return [hls_hex(h, 0.64, min(max(s, 0.45), 0.78)), hls_hex(h, 0.22, min(max(s, 0.4), 0.7))]


def main() -> None:
    out = {int(p.stem): theme(p) for p in sorted(COVERS.glob("*.jpg"))}
    print("const COL=" + json.dumps([out[k] for k in sorted(out)]) + ";")


if __name__ == "__main__":
    main()
