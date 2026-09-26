"""Versuch zu #81: Macht eine Mehrheit aus drei Steckbriefen das Urteil stabil?

Je Werk sechs Steckbriefe aus demselben deutschen Titel und Klappentext (drei
aus ``sprachfassungen.py``, drei neue). Verglichen wird, wie weit zwei
**einzelne** Steckbriefe im Urteil auseinanderliegen, mit dem Abstand zweier
**Mehrheiten** aus je drei (Durchgang 1–3 gegen 4–6). Eine Mehrheit übernimmt
ein Merkmal, wenn es in mindestens zwei von drei Steckbriefen steht, mit dem
häufigsten Gewicht.

    uv run python docs/research/prototyp/mehrheit.py
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from itertools import combinations
from pathlib import Path

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.judging import load_judge
from ebook_watchlist.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.portrayer import build_portrayer
from ebook_watchlist.store import Store

ORDNER = Path(paths.data_dir()) / "experimente" / "sprachfassungen"
WERKE = [("dark-matter", "Blake Crouch"), ("recursion", "Blake Crouch"), ("we", "Yevgeny Zamyatin")]


def lade(schluessel: str) -> Portrait:
    datei = ORDNER / f"steckbrief-{schluessel}.json"
    d = json.loads(datei.read_text(encoding="utf-8"))["portrait"]
    return Portrait(**{**d, "traits": tuple(Trait(**t) for t in d.get("traits") or ()),
                       "violations": tuple(d.get("violations") or ())})


def mehrheit(steckbriefe: list[Portrait]) -> Portrait:
    zaehler = Counter(t.term for p in steckbriefe for t in p.traits)
    behalten = []
    for term, n in zaehler.items():
        if n * 2 <= len(steckbriefe):
            continue
        vorkommen = [t for p in steckbriefe for t in p.traits if t.term == term]
        gewicht = Counter(t.weight for t in vorkommen).most_common(1)[0][0]
        erstes = vorkommen[0]
        behalten.append(Trait(term, erstes.sentence, erstes.evidence, gewicht))
    return Portrait(**{**{f: getattr(steckbriefe[0], f) for f in steckbriefe[0].__slots__},
                       "traits": tuple(behalten)})


def main() -> None:
    settings = load_settings()
    judge = load_judge(Store(paths.db_path()), settings.slug)
    portrayer = build_portrayer(settings.rating_model, load_vocabulary())
    einzeln, mehrheiten = [], []
    for werk, autor in WERKE:
        ergebnis = json.loads((ORDNER / "ergebnis.json").read_text(encoding="utf-8"))
        zeile = next(z for z in ergebnis["werke"]
                     if z["werk"].lower().replace("'", "-").replace(" ", "-") == werk)
        text = None
        for i in range(3, 6):
            datei = ORDNER / f"steckbrief-{werk}-de-{i}.json"
            if not datei.exists():
                if text is None:
                    text = _text(zeile)
                p = portrayer.portray(zeile["de_titel"], autor, text)
                from dataclasses import asdict

                inhalt = {"known": p.known, "terms": sorted({t.term for t in p.traits}),
                          "portrait": asdict(p)}
                datei.write_text(json.dumps(inhalt, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        alle = [lade(f"{werk}-de-{i}") for i in range(6)]
        prozent = [judge.verdict(p).percent for p in alle]
        a, b = mehrheit(alle[:3]), mehrheit(alle[3:])
        pa, pb = judge.verdict(a).percent, judge.verdict(b).percent
        paare = [abs(x - y) for x, y in combinations(prozent, 2)]
        einzeln += paare
        mehrheiten.append(abs(pa - pb))
        print(f"{werk}: einzeln {prozent} → Abstand ⌀ {statistics.mean(paare):.1f} | "
              f"Mehrheiten {pa} und {pb} → Abstand {abs(pa - pb)}")
    print(f"gesamt: zwei einzelne ⌀ {statistics.mean(einzeln):.1f} Punkte, "
          f"zwei Mehrheiten ⌀ {statistics.mean(mehrheiten):.1f} Punkte")


def _text(zeile: dict) -> str | None:
    """Den deutschen Text so holen wie beim ersten Versuch."""
    import sprachfassungen as sf  # noqa: PLC0415

    if zeile["de_quelle"] == "overdrive":
        from ebook_watchlist.http import HttpClient, build_user_agent

        client = HttpClient(user_agent=build_user_agent(load_settings().contact))
        return sf.suche(client, zeile["de_titel"].split(" (")[0], "de", zeile["autor"])["text"]
    isbn = {"recursion": "9783641253486", "we": "9783869926247"}.get(zeile["werk"].lower())
    return sf.aus_dem_speicher(Store(paths.db_path()), zeile["werk"], isbn)["text"]


# --- zweiter Durchgang: acht Bücher an der Schwelle, Kippen statt Abstand -------------

MEHR = Path(paths.data_dir()) / "experimente" / "mehrheit"
SCHWELLE = 40


def buecher_an_der_schwelle(judge, anzahl: int = 8) -> list[tuple[str, str, str, str]]:
    """Bücher mit Steckbrief und langem Klappentext, deren Urteil nahe 40 % liegt."""
    import sqlite3

    db = sqlite3.connect(f"file:{paths.db_path()}?mode=ro", uri=True)
    store = Store(paths.db_path())
    subs = [r[0] for r in db.execute(
        "select distinct subject from portrait where known and fingerprint=? "
        "and subject like 'isbn:%'", (judge.stamp,))]
    auswahl = []
    for subject, p in store.portraits_for(subs, judge.stamp).items():
        v = judge.verdict(p)
        if v is None or abs(v.percent - SCHWELLE) > 8:
            continue
        row = db.execute(
            "select title, author, blurb from observation where isbn = ? and blurb is not null "
            "and length(blurb) > 300 order by length(blurb) desc limit 1",
            (subject[5:],)).fetchone()
        if row:
            auswahl.append((subject, *row))
        if len(auswahl) == anzahl:
            break
    return auswahl


def zweiter_durchgang() -> None:
    from dataclasses import asdict

    MEHR.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    judge = load_judge(Store(paths.db_path()), settings.slug)
    portrayer = build_portrayer(settings.rating_model, load_vocabulary())
    kippt_einzeln = kippt_mehrheit = paare_einzeln = paare_mehrheit = 0
    abstand_e, abstand_m = [], []
    for subject, titel, autor, text in buecher_an_der_schwelle(judge):
        alle = []
        for i in range(6):
            datei = MEHR / f"{subject[5:]}-{i}.json"
            if not datei.exists():
                p = portrayer.portray(titel, autor, text)
                datei.write_text(json.dumps(asdict(p), ensure_ascii=False), encoding="utf-8")
            d = json.loads(datei.read_text(encoding="utf-8"))
            alle.append(Portrait(**{**d, "traits": tuple(Trait(**t) for t in d["traits"]),
                                    "violations": tuple(d["violations"])}))
        urteile = [judge.verdict(p) for p in alle]
        if any(u is None for u in urteile):
            # Auch das ist Streuung: dasselbe Buch mal bekannt, mal nicht.
            print(f"{titel[:40]:40} unbekannt in {sum(u is None for u in urteile)} von 6 — "
                  f"übrige {[u.percent for u in urteile if u]}", flush=True)
            continue
        prozent = [u.percent for u in urteile]
        a, b = judge.verdict(mehrheit(alle[:3])).percent, judge.verdict(mehrheit(alle[3:])).percent
        for x, y in combinations(prozent, 2):
            paare_einzeln += 1
            kippt_einzeln += (x >= SCHWELLE) != (y >= SCHWELLE)
            abstand_e.append(abs(x - y))
        paare_mehrheit += 1
        kippt_mehrheit += (a >= SCHWELLE) != (b >= SCHWELLE)
        abstand_m.append(abs(a - b))
        print(f"{titel[:40]:40} einzeln {prozent} | Mehrheiten {a} / {b}", flush=True)
    print(f"Kippen an der Schwelle: einzeln {kippt_einzeln}/{paare_einzeln} "
          f"({kippt_einzeln / paare_einzeln:.0%}), Mehrheiten {kippt_mehrheit}/{paare_mehrheit} "
          f"({kippt_mehrheit / paare_mehrheit:.0%})")
    print(f"Abstand: einzeln ⌀ {statistics.mean(abstand_e):.1f}, "
          f"Mehrheiten ⌀ {statistics.mean(abstand_m):.1f}")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    main() if "--zwei" not in sys.argv else zweiter_durchgang()
