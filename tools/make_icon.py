r"""Draws cratedig.ico (rounded blue tile with white waveform bars). Run: .venv\Scripts\python tools\make_icon.py"""
import os
from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / (S - 1)
    gd.line([(0, y), (S, y)], fill=(int(0x3a + (0x14 - 0x3a) * t), int(0xa8 + (0x4f - 0xa8) * t), int(0xff + (0xc4 - 0xff) * t), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=210, fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)
heights = [0.22, 0.42, 0.66, 0.92, 0.58, 0.80, 0.46, 0.30, 0.18]
n, bw, gap = len(heights), 62, 30
x0 = (S - (n * bw + (n - 1) * gap)) // 2
for i, h in enumerate(heights):
    half = int(h * 300)
    x = x0 + i * (bw + gap)
    d.rounded_rectangle([x, S // 2 - half, x + bw, S // 2 + half], radius=bw // 2, fill=(255, 255, 255, 255))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cratedig.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(os.path.join(os.path.dirname(out), "docs", "icon.png")) if os.path.isdir(os.path.join(os.path.dirname(out), "docs")) else None
print("wrote", out)
