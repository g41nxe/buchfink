"""PNG-Icon (dunkel auf weiß) -> SVG mit Pfad in currentColor, viewBox 0 0 24 24."""
import sys
from pathlib import Path

import numpy as np
import potrace
from PIL import Image, ImageDraw, ImageFilter, ImageOps

src, dst = Path(sys.argv[1]), Path(sys.argv[2])

raw = Image.open(src).convert("RGBA")
white = Image.new("RGBA", raw.size, (255, 255, 255, 255))
flat = Image.alpha_composite(white, raw).convert("L")
# Rand leeren: Gemini setzt manchmal Eckmarken; die Icons halten Abstand.
m = int(min(flat.size) * 0.08)
_d = ImageDraw.Draw(flat)
w, h = flat.size
for box in ((0, 0, w, m), (0, h - m, w, h), (0, 0, m, h), (w - m, 0, w, h)):
    _d.rectangle(box, fill=255)
im = ImageOps.expand(flat, border=400, fill=255)
# auf den Inhalt beschneiden, quadratisch mit Rand
a = np.array(im) < 128
ys, xs = np.where(a)
y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
side = max(y1 - y0, x1 - x0)
pad = int(side * 0.06)
cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
half = side // 2 + pad
box = (cx - half, cy - half, cx + half, cy + half)
im = im.crop(box).resize((480, 480), Image.LANCZOS)
# Strich auf ein festes Maß bringen (Standard 1,2 von 24): Stärke schätzen
# (Fläche / halber Umfang), dünne Striche wachsen lassen, dicke ausdünnen.
# Drittes Argument "fest" lässt Flächenzeichen unverändert.
dark = np.array(im) < 128
edges = (dark ^ np.roll(dark, 1, 0)).sum() + (dark ^ np.roll(dark, 1, 1)).sum()
stroke = 2 * dark.sum() / max(edges, 1)
arg = sys.argv[3] if len(sys.argv) > 3 else "1.2"
target = stroke if arg == "fest" else 480 * float(arg) / 24
grow = max(-6, min(5, int(round((target - stroke) / 2))))
if grow > 0:
    im = im.filter(ImageFilter.MinFilter(2 * grow + 1))
elif grow < 0:
    im = im.filter(ImageFilter.MaxFilter(-2 * grow + 1))
print("Strich", round(stroke, 1), "->", round(target, 1), "wachsen", grow)
bm = potrace.Bitmap(np.array(im) >= 128)
path = bm.trace(turdsize=20, opttolerance=0.4)
s = 24 / 480
def p(pt): return f"{pt.x*s:.2f} {pt.y*s:.2f}"
d = []
for curve in path:
    d.append(f"M{p(curve.start_point)}")
    for seg in curve.segments:
        if seg.is_corner:
            d.append(f"L{p(seg.c)}L{p(seg.end_point)}")
        else:
            d.append(f"C{p(seg.c1)} {p(seg.c2)} {p(seg.end_point)}")
    d.append("Z")
svg = f'<path fill="currentColor" fill-rule="evenodd" d="{"".join(d)}"/>'
dst.write_text(svg, encoding="utf-8")
print(dst, len("".join(d)))
