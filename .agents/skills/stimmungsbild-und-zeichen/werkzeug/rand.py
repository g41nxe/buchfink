"""Einheitlicher Creme-Rand für alle Stimmungsbilder (#55).

Das Motiv wird auf seinen Inhalt zugeschnitten (alles, was sich vom Papier
abhebt) und mit festem Abstand mittig ins Quadrat gesetzt. Randlose Bilder
bekommen so ihren Rand, kleine Motive werden größer.
Szenen mit harter Rechteckkante (Landschaft im Kasten) sähen mit breitem Streifen
oben und unten schief aus; sie werden mittig aufs Quadrat beschnitten und füllen
den Rahmen bis auf den Rand (QUADRAT). Ein blasses Papierfeld hinter dem Motiv
wird zu reinem Papier (Abstand unter GLATT), sonst bleibt seine Kante stehen.
Aufruf: rand.py quelle_dir ziel_dir groesse [rand_anteil]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

src, dst, size = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
margin = float(sys.argv[4]) if len(sys.argv) > 4 else 0.06
cream = (244, 236, 221)
# Nicht: adventure (Karte), sacrifice (Kerze) und dramatic (Vorhang) verlören
# beim Beschnitt ihr Motiv.
QUADRAT = {"big_world", "brooding", "quest", "transformation", "rivalry", "descension",
           "complex"}
# Szenen mit offenem Himmel: das Papier geht oben in den Himmel über und liest
# sich als breiter Rand. Hier ein fester Ausschnitt (Quellpixel), der an der
# Felskante beginnt.
AUSSCHNITT = {"big_world": (30, 190, 835, 995)}
# Bühne: jeder Beschnitt nimmt Vorhang oder Bühnenkante; sie wird auf das
# Quadrat gestreckt (in der Höhe ~16 %), was die flachen Formen vertragen.
STRECKEN = {"dramatic"}
GLATT = 14
dst.mkdir(parents=True, exist_ok=True)
for path in sorted(src.glob("*.jpg")):
    im = Image.open(path).convert("RGB")
    a = np.array(im).astype(float)
    dist = np.linalg.norm(a - np.array(cream), axis=2)
    a[dist < GLATT] = cream
    im = Image.fromarray(a.astype(np.uint8))
    ink = dist > 28
    # vereinzelte Körnchen im Papier zählen nicht
    rows = np.where(ink.mean(axis=1) > 0.004)[0]
    cols = np.where(ink.mean(axis=0) > 0.004)[0]
    x0, y0, x1, y1 = cols.min(), rows.min(), cols.max() + 1, rows.max() + 1
    if path.stem in QUADRAT:
        side = min(x1 - x0, y1 - y0)
        x0 += (x1 - x0 - side) // 2
        y0 += (y1 - y0 - side) // 2
        x1, y1 = x0 + side, y0 + side
    box = AUSSCHNITT.get(path.stem, (x0, y0, x1, y1))
    motif = im.crop(box)
    inner = round(size * (1 - 2 * margin))
    scale = inner / max(motif.size)
    target = ((inner, inner) if path.stem in STRECKEN
              else (max(1, round(motif.width * scale)), max(1, round(motif.height * scale))))
    motif = motif.resize(target, Image.LANCZOS)
    out = Image.new("RGB", (size, size), cream)
    out.paste(motif, ((size - motif.width) // 2, (size - motif.height) // 2))
    out.save(dst / path.name, quality=88)
    print(f"{path.stem:18s} Inhalt {box}")
