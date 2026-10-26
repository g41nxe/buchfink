"""Versuch zu #69 (ADR 43): Hält eine geschärfte Anweisung die Regeln besser?

Dieselben acht Bücher an der Schwelle wie im zweiten Durchgang von
``mehrheit.py``: dort liegen je sechs Steckbriefe nach der Anweisung vom
26.09.2026 — das ist die Messung vorher, sie kostet nichts mehr. Hier kommen je
sechs nach der heutigen ``TEMPLATE`` dazu (erst drei: zu verrauscht, um
über die Streuung zu entscheiden). Verglichen werden die Regelverstöße
(alle, und „nur N Dimensionen“ für sich) und die Streuung des Urteils: der
mittlere Abstand zweier Steckbriefe desselben Buchs und wie oft zwei auf
verschiedenen Seiten der Schwelle landen.

Die neue Anweisung gilt nur, wenn Verstöße **und** Streuung sinken (ADR 43).

    uv run python docs/research/prototyp/regeln.py
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from itertools import combinations
from pathlib import Path

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.judging.judge import load_judge
from ebook_watchlist.judging.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.judging.portrayer import build_portrayer
from ebook_watchlist.store import Store

VORHER = Path(paths.data_dir()) / "experimente" / "mehrheit"
NACHHER = Path(paths.data_dir()) / "experimente" / "regeln"
SCHWELLE = 40
NEUE = 6


def lade(datei: Path) -> Portrait:
    d = json.loads(datei.read_text(encoding="utf-8"))
    d = {k: v for k, v in d.items() if k in Portrait.__dataclass_fields__}
    return Portrait(**{**d, "traits": tuple(Trait(**t) for t in d["traits"]),
                       "violations": tuple(d["violations"])})


def buecher() -> list[tuple[str, str, str | None, str]]:
    """Die ISBNs aus dem Ordner von vorher, Titel und Text wie damals."""
    db = sqlite3.connect(f"file:{paths.db_path()}?mode=ro", uri=True)
    isbns = sorted({datei.name.split("-")[0] for datei in VORHER.glob("*-0.json")})
    auswahl = []
    for isbn in isbns:
        row = db.execute(
            "select title, author, blurb from observation where isbn = ? and blurb is not null "
            "and length(blurb) > 300 order by length(blurb) desc limit 1", (isbn,)).fetchone()
        if row:
            auswahl.append((isbn, *row))
    return auswahl


def streuung(prozent: list[int]) -> tuple[float, int, int]:
    paare = list(combinations(prozent, 2))
    abstand = statistics.mean(abs(x - y) for x, y in paare) if paare else 0.0
    kippt = sum((x >= SCHWELLE) != (y >= SCHWELLE) for x, y in paare)
    return abstand, kippt, len(paare)


def main() -> None:
    NACHHER.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    judge = load_judge(Store(paths.db_path()), settings.slug)
    portrayer = build_portrayer(settings.rating_model, load_vocabulary())
    auswahl = buecher()

    def frage(aufgabe: tuple[str, str, str | None, str, int]) -> None:
        isbn, titel, autor, text, i = aufgabe
        datei = NACHHER / f"{isbn}-{i}.json"
        if not datei.exists():
            p = portrayer.portray(titel, autor, text)
            datei.write_text(json.dumps(asdict(p), ensure_ascii=False), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(frage, [(*buch, i) for buch in auswahl for i in range(NEUE)]))

    summe = {"vorher": [], "nachher": []}
    for isbn, titel, _, _ in auswahl:
        print(titel[:50])
        for name, ordner, anzahl in (("vorher", VORHER, 6), ("nachher", NACHHER, NEUE)):
            alle = [lade(ordner / f"{isbn}-{i}.json") for i in range(anzahl)]
            urteile = [judge.verdict(p) for p in alle]
            prozent = [u.percent for u in urteile if u is not None]
            verstoesse = [len(p.violations) for p in alle]
            duenn = sum(any("Dimensionen" in v for v in p.violations) for p in alle)
            pitch = sum(any(v.startswith("Pitch") for v in p.violations) for p in alle)
            formen = [p.form for p in alle]
            abstand, kippt, paare = streuung(prozent)
            summe[name].append((alle, prozent))
            print(f"  {name:8} Verstöße {verstoesse} (Dimensionen {duenn}, Pitch {pitch}) "
                  f"| Urteil {prozent} ⌀ Abstand {abstand:.1f}, kippt {kippt}/{paare}"
                  + (f" | Form {formen}" if name == "nachher" else ""))

    print()
    for name, buchweise in summe.items():
        alle = [p for steckbriefe, _ in buchweise for p in steckbriefe]
        abstaende, kipp, paare = [], 0, 0
        for _, prozent in buchweise:
            a, k, n = streuung(prozent)
            abstaende.append(a)
            kipp, paare = kipp + k, paare + n
        duenn = sum(any("Dimensionen" in v for v in p.violations) for p in alle)
        print(f"{name:8} {len(alle)} Steckbriefe: mit Verstoß "
              f"{sum(bool(p.violations) for p in alle)}, ⌀ Verstöße "
              f"{statistics.mean(len(p.violations) for p in alle):.2f}, "
              f"zu wenige Dimensionen {duenn}, "
              f"⌀ Abstand {statistics.mean(abstaende):.1f}, kippt {kipp}/{paare}")


if __name__ == "__main__":
    main()
