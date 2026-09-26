"""Versuch: Kommen die deutsche und die englische Fassung desselben Buchs zum
selben Steckbrief — und wenn nicht, warum?

Anlass: *Recursion* und *Gestohlene Erinnerung* (Blake Crouch) standen am
26.09.2026 mit verschiedenen Sternen da. Zwei Fragen stecken darin: Wie weit
streut das Modell schon bei *derselben* Eingabe (Rauschen)? Und wie weit
liegen die Sprachfassungen darüber hinaus auseinander (Sprache und Text)?

Aufbau je Werkpaar, beide Fassungen aus **einer** Quelle (OverDrive), damit
nur die Sprache und der Verlagstext verschieden sind:

- DE: deutscher Titel und Klappentext, ``WIEDERHOLUNGEN``-mal
- EN: englischer Titel und Klappentext, ebenso oft
- DE ohne Text, EN ohne Text: je einmal — das Modell muss sich erinnern

Gemessen wird je Steckbrief: die Merkmale (Terme), ihre Familien, und das
Urteil der echten Geschmacksform (Sterne, Prozent). Verglichen wird die
Übereinstimmung (Jaccard) innerhalb einer Sprache mit der zwischen den
Sprachen.

Gespeichert wird nichts in der Datenbank: ``Portrayer.portray`` fragt nur.
Die Antworten von OverDrive und die Steckbriefe liegen unter
``data/experimente/`` (nicht in Git), ein zweiter Lauf fragt nicht noch einmal.

    uv run python docs/research/prototyp/sprachfassungen.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from itertools import combinations
from pathlib import Path

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.http import HttpClient, build_user_agent
from ebook_watchlist.judging import load_judge
from ebook_watchlist.portrait import Portrait, Trait, load_vocabulary
from ebook_watchlist.portrayer import build_portrayer
from ebook_watchlist.sources.overdrive import selectors as sel
from ebook_watchlist.store import Store

WIEDERHOLUNGEN = 3

#: (Autor:in, englische Suche, deutsche Suche) — Werke, die die Leserin kennt.
PAARE = [
    ("Blake Crouch", "Recursion", "Gestohlene Erinnerung"),
    ("Blake Crouch", "Dark Matter", "Der Zeitenläufer"),
    ("Gillian Flynn", "Sharp Objects", "Cry Baby"),
    ("Suzanne Collins", "The Hunger Games", "Die Tribute von Panem Tödliche Spiele"),
    ("Graeme Simsion", "The Rosie Project", "Das Rosie-Projekt"),
    ("Dave Eggers", "The Circle", "Der Circle"),
]

#: Zweiter Satz (26.09.2026): Der VÖBB-Katalog bei OverDrive führt viele
#: Ausgaben nur in einer Sprache — aus einer Quelle kam nur *Dark Matter*
#: zustande. Hier die deutsche Fassung aus dem eigenen Speicher (Klappentext
#: von beam, Originaltitel aus ihrem Steckbrief), die englische von OverDrive.
#: (Autor:in, englische Suche, deutsche ISBN)
PAARE_GEMISCHT = [
    ("Blake Crouch", "Recursion", "9783641253486"),
    ("John Scalzi", "Old Man's War", None),
    ("Joe Abercrombie", "The Blade Itself", None),
    ("Simon Beckett", "Hidden", None),
    ("O. J. Mullen", "The Guilty Husband", None),
    ("Lynda Renham", "Hunters Moon", None),
    ("Charles Sheffield", "Summertide", None),
    ("Charles Sheffield", "Divergence", None),
    # Der Steckbrief nennt den russischen Originaltitel „Мы", nicht „We".
    ("Yevgeny Zamyatin", "We", "9783869926247"),
    ("Michael Bray", "From the Deep", None),
    ("Greig Beck", "The Hell Gate", None),
]

ORDNER = Path(paths.data_dir()) / "experimente" / "sprachfassungen"


def _ohne_html(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip() or None


def suche(client: HttpClient, frage: str, sprache: str, autor: str) -> dict | None:
    """Der erste Treffer dieser Sprache von dieser Autorin — gemerkt, nicht neu gefragt."""
    datei = ORDNER / f"overdrive-{sprache}-{re.sub(r'[^a-z0-9]+', '-', frage.lower())}.json"
    if datei.exists():
        daten = json.loads(datei.read_text(encoding="utf-8"))
    else:
        text = client.get(
            sel.BASE + sel.SEARCH_PATH.format(library=sel.LIBRARY),
            params={"query": f"{frage} {autor}", "language": sprache, "perPage": "10",
                    **sel.SEARCH_PARAMS},
        )
        daten = json.loads(text)
        datei.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    nachname = autor.split()[-1].casefold()
    for item in daten.get("items") or []:
        if nachname in (item.get("firstCreatorName") or "").casefold() and item.get("description"):
            return {"titel": _ohne_html(item.get("title")), "text": _ohne_html(item["description"])}
    return None


def aus_dem_speicher(store: Store, original: str, isbn: str | None) -> dict | None:
    """Die deutsche Fassung: Titel und längster Klappentext von beam, gefunden
    über den Originaltitel ihres Steckbriefs (oder die ISBN)."""
    import sqlite3

    db = sqlite3.connect(f"file:{paths.db_path()}?mode=ro", uri=True)
    if isbn is None:
        row = db.execute(
            "select substr(subject, 6) from portrait where known and original_title = ? "
            "and subject like 'isbn:%' limit 1", (original,)).fetchone()
        if row is None:
            return None
        isbn = row[0]
    row = db.execute(
        "select title, blurb from observation where isbn = ? and source = 'beam' "
        "and blurb is not null order by length(blurb) desc limit 1", (isbn,)).fetchone()
    return {"titel": row[0], "text": row[1]} if row else None


def steckbrief(portrayer, titel: str, autor: str, text: str | None, schluessel: str) -> dict:
    datei = ORDNER / f"steckbrief-{schluessel}.json"
    if datei.exists():
        return json.loads(datei.read_text(encoding="utf-8"))
    p: Portrait = portrayer.portray(titel, autor, text)
    ergebnis = {
        "known": p.known,
        "original_title": p.original_title,
        "genre": p.genre,
        "terms": sorted({t.term for t in p.traits}),
        "portrait": _portrait_json(p),
    }
    datei.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
    return ergebnis


def _portrait_json(p: Portrait) -> dict:
    from dataclasses import asdict, is_dataclass

    return asdict(p) if is_dataclass(p) else {}


def _portrait_of(d: dict) -> Portrait:
    """Zurück aus dem JSON — wie ``store._portrait_of`` aus einer Zeile."""
    return Portrait(**{
        **d,
        "traits": tuple(Trait(**t) for t in d.get("traits") or ()),
        "violations": tuple(d.get("violations") or ()),
    })


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def mittel(werte: list[float]) -> float:
    return statistics.mean(werte) if werte else float("nan")


def main() -> int:
    ORDNER.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    vocabulary = load_vocabulary()
    portrayer = build_portrayer(settings.rating_model, vocabulary)
    if portrayer is None:
        print("Kein Weg zum Modell.", file=sys.stderr)
        return 1
    judge = load_judge(Store(paths.db_path()), settings.slug)
    client = HttpClient(user_agent=build_user_agent(settings.contact))

    def familien(terms: list[str]) -> set[str]:
        return {vocabulary.family_of(t).id for t in terms}

    def urteil(e: dict) -> tuple[int | None, int | None]:
        if not e["known"]:
            return None, None
        v = judge.verdict(_portrait_of(e["portrait"]))
        return (v.stars, v.percent) if v else (None, None)

    zeilen, alle = [], {"innen": [], "zwischen": [], "fam_innen": [], "fam_zwischen": []}
    store = Store(paths.db_path())
    reihen = [(a, en, lambda de=de, a=a: suche(client, de, "de", a), "overdrive")
              for a, en, de in PAARE]
    reihen += [(a, en, lambda en=en, i=i: aus_dem_speicher(store, en, i), "beam")
               for a, en, i in PAARE_GEMISCHT]
    for autor, en_frage, deutsch, de_quelle in reihen:
        en = suche(client, en_frage, "en", autor)
        de = deutsch() if en else None
        if not en or not de:
            print(f"{en_frage}: keine {'englische' if not en else 'deutsche'} Fassung mit Text")
            continue
        kurz = re.sub(r"[^a-z0-9]+", "-", en_frage.lower())
        runden = {
            sprache: [
                steckbrief(portrayer, f["titel"], autor, f["text"], f"{kurz}-{sprache}-{i}")
                for i in range(WIEDERHOLUNGEN)
            ]
            for sprache, f in (("de", de), ("en", en))
        }
        ohne = {
            sprache: steckbrief(portrayer, f["titel"], autor, None, f"{kurz}-{sprache}-ohne-text")
            for sprache, f in (("de", de), ("en", en))
        }
        sets = {s: [set(e["terms"]) for e in r] for s, r in runden.items()}
        fams = {s: [familien(e["terms"]) for e in r] for s, r in runden.items()}
        innen = [jaccard(a, b) for s in sets for a, b in combinations(sets[s], 2)]
        zwischen = [jaccard(a, b) for a in sets["de"] for b in sets["en"]]
        f_innen = [jaccard(a, b) for s in fams for a, b in combinations(fams[s], 2)]
        f_zwischen = [jaccard(a, b) for a in fams["de"] for b in fams["en"]]
        alle["innen"] += innen
        alle["zwischen"] += zwischen
        alle["fam_innen"] += f_innen
        alle["fam_zwischen"] += f_zwischen
        urteile = {s: [urteil(e) for e in r] for s, r in runden.items()}
        nur = {s: set.intersection(*sets[s]) - set.union(*sets["en" if s == "de" else "de"])
               for s in sets}
        zeilen.append({
            "werk": en_frage, "autor": autor, "de_quelle": de_quelle,
            "de_titel": de["titel"], "en_titel": en["titel"],
            "de_text_zeichen": len(de["text"]), "en_text_zeichen": len(en["text"]),
            "jaccard_innen": round(mittel(innen), 2),
            "jaccard_zwischen": round(mittel(zwischen), 2),
            "familien_innen": round(mittel(f_innen), 2),
            "familien_zwischen": round(mittel(f_zwischen), 2),
            "urteile": urteile,
            "immer_nur_de": sorted(nur["de"]), "immer_nur_en": sorted(nur["en"]),
            "ohne_text": {s: {"known": e["known"], "original_title": e["original_title"],
                              "terms": e["terms"], "urteil": urteil(e)} for s, e in ohne.items()},
        })
        print(f"{en_frage}: Terme innen {mittel(innen):.2f} zwischen {mittel(zwischen):.2f} | "
              f"Familien innen {mittel(f_innen):.2f} zwischen {mittel(f_zwischen):.2f} | "
              f"Urteile DE {urteile['de']} EN {urteile['en']}")

    gesamt = {k: round(mittel(v), 2) for k, v in alle.items()}
    (ORDNER / "ergebnis.json").write_text(
        json.dumps({"gesamt": gesamt, "werke": zeilen}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("gesamt", gesamt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
