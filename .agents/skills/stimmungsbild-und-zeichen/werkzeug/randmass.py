"""Misst den Creme-Rand je Seite (in Prozent) für alle Bilder eines Ordners (#55).

Gezählt wird wie in rand.py: eine Zeile oder Spalte gehört zum Motiv, wenn
mehr als `dichte` ihrer Pixel sich vom Papier abheben.
Aufruf: randmass.py ordner [dichte]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

src = Path(sys.argv[1])
density = float(sys.argv[2]) if len(sys.argv) > 2 else 0.004
cream = np.array((244, 236, 221))
for path in sorted(src.glob("*.jpg")):
    a = np.array(Image.open(path).convert("RGB")).astype(float)
    ink = np.linalg.norm(a - cream, axis=2) > 28
    n = ink.shape[0]
    rows = np.where(ink.mean(axis=1) > density)[0]
    cols = np.where(ink.mean(axis=0) > density)[0]
    top, bottom = rows.min() / n, (n - 1 - rows.max()) / n
    left, right = cols.min() / n, (n - 1 - cols.max()) / n
    sides = [top, right, bottom, left]
    spread = max(sides) - min(sides)
    flag = "  <--" if spread > 0.03 else ""
    print(f"{path.stem:20s} o {top:5.1%} r {right:5.1%} u {bottom:5.1%} l {left:5.1%}{flag}")
