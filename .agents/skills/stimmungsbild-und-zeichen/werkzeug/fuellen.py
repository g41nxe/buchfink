"""Füllt Flächen eines Icons per Flutfüllung (Saatpunkte als Argumente x,y)."""
import sys

from PIL import Image, ImageDraw

src, dst, *seeds = sys.argv[1:]
im = Image.open(src).convert("RGB")
teal = (46, 107, 104)
# Erst binarisieren, damit die Füllung an den Strichen sauber endet.
g = im.convert("L").point(lambda v: 0 if v < 160 else 255).convert("RGB")
g = Image.eval(g, lambda v: v)
px = g.load()
for y in range(g.height):
    for x in range(g.width):
        if px[x, y] == (0, 0, 0):
            px[x, y] = teal
for s in seeds:
    x, y = map(int, s.split(","))
    ImageDraw.floodfill(g, (x, y), teal, thresh=40)
g.save(dst)
