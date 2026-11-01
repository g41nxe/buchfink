"""Färbt die zusammenhängende dunkle Fläche ab einem Saatpunkt in Petrol um (Körnung bleibt)."""
import sys
from collections import deque

import numpy as np
from PIL import Image

src, dst, sx, sy = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
a = np.array(Image.open(src).convert("RGB")).astype(float)
lum = a.mean(axis=2)
dark = lum < 110  # Tisch und Holzlinien; Creme und Orange liegen weit darüber
h, w = dark.shape
seen = np.zeros_like(dark)
q = deque([(sy, sx)])
seen[sy, sx] = True
while q:
    y, x = q.popleft()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ny, nx = y + dy, x + dx
        if 0 <= ny < h and 0 <= nx < w and dark[ny, nx] and not seen[ny, nx]:
            seen[ny, nx] = True
            q.append((ny, nx))
ref = np.median(lum[seen])
teal = np.array([46, 107, 104], float)
scale = (lum[seen] / ref)[:, None]
a[seen] = np.clip(teal * scale, 0, 255)
Image.fromarray(a.astype(np.uint8)).save(dst, quality=92)
print(seen.sum(), ref)
