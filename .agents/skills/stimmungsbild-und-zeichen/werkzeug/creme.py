"""Gleicht den Papierton aller Bilder auf Creme #F4ECDD an.

Der Hintergrund wird je Bild aus den hellsten, häufigsten Tönen geschätzt; Pixel
nahe diesem Ton werden voll, Übergänge anteilig verschoben. Motive bleiben unberührt.
Aufruf: creme.py quelle_dir ziel_dir id [id ...]   (ohne ids: alle *.jpg)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
ids = sys.argv[3:] or [p.stem for p in src.glob("*.jpg")]
cream = np.array([244.0, 236.0, 221.0])
for k in ids:
    a = np.array(Image.open(src / f"{k}.jpg").convert("RGB")).astype(float)
    lum = a.mean(axis=2)
    light = a[lum > np.percentile(lum, 70)]
    # häufigster heller Ton, auf 4er-Stufen gerundet
    q = (light // 4).astype(int)
    vals, counts = np.unique(q, axis=0, return_counts=True)
    bg = vals[counts.argmax()] * 4 + 2
    dist = np.linalg.norm(a - bg, axis=2)
    w = np.clip(1 - (dist - 14) / 30, 0, 1)[..., None]
    a = a + (cream - bg) * w
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(dst / f"{k}.jpg", quality=92)
    print(f"{k:18s} Papier {tuple(int(v) for v in bg)}  Anteil {float((w > .99).mean()):.2f}")
