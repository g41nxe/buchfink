"""Belege für den `Portrayer` — zusammengetragen unmittelbar vor einem Urteil (#17).

Eine Stelle für Lauf und Buchseite: beide sollen dieselbe Frage mit derselben
Grundlage beantworten. Vorher urteilte die Buchseite ohne Detailseite, und
dasselbe Buch bekam von zwei Stellen zwei verschieden gut begründete Urteile.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime

from .config import Settings
from .dnb import Record
from .http import RateLimited
from .models import Observation
from .store import ENTRY_TRIGGER, Store


def gather(store: Store, settings: Settings, observations, sources):
    """Was der `Portrayer` zu sehen bekommt — zusammengetragen unmittelbar davor.

    Nur fuer die Buecher, die gleich ein Urteil bekommen; alles hier kostet
    Anfragen, und das Budget des Tors begrenzt, wie viele es sind.

    Zwei Belege neben dem Klappentext (#17): die Schlagwoerter der Detailseite
    und was die DNB schon gesagt hat (Originaltitel, Schlagwoerter des Verlags).
    Die DNB wird hier nicht gefragt — das tut der Lauf an seiner eigenen Stelle,
    mit ihrem eigenen Budget.
    """
    observations = _with_details(store, settings, observations, sources)
    dnb = store.dnb_facts(o.isbn for o in observations if o.isbn)
    belegt = []
    for observation in observations:
        fakten = dnb.get(observation.isbn or "", Record())
        belegt.append(
            replace(
                observation,
                keywords=tuple(dict.fromkeys((*observation.keywords, *fakten.keywords))),
                original_title=fakten.original_title,
                # Die Detailseite zuerst: sie ist frisch geholt, die DNB hat
                # zu einem neuen Fund vielleicht noch gar nicht geantwortet.
                publisher=observation.publisher or fakten.publisher,
            )
        )
    return belegt


def _with_details(store: Store, settings: Settings, observations, sources):
    """Die Detailseite holen — eine Anfrage je Buch, und nur hier.

    Fuer den ganzen Klappentext und die Schlagwoerter. Die Leseprobe wird seit
    #68 nicht mehr geholt: der Steckbrief liest sie nicht, und die Funde im Stapel
    (Kleinverlage, Selbstverlag) tragen ohnehin keine — gemessen an acht von
    acht. Trägt eine Quelle sie wieder, ist das ein neues Ticket.

    Angehängt statt überschrieben: der Snapshot wird nie umgeschrieben
    (ADR 5). Der Shop *hat* das gesagt, nur auf einer anderen Seite, und damit
    ist es eine Beobachtung wie jede andere. Preis und Verfügbarkeit kommen
    ebenfalls von dort — weicht der Preis ab, ist das eine echte Änderung und
    keine erfundene.

    Frueher wurde nur geholt, was keinen ganzen Klappentext trug. Seit die
    Seite auch Schlagwoerter liefert, wird sie fuer jedes Buch
    geholt, das beurteilt wird (#17) — ins Journal kommt sie nur, wenn sich
    Klappentext oder Titelbild geaendert haben.
    """
    by_name = {source.name: source for source in sources}
    offen = [o for o in observations if o.source in by_name]
    if not offen:
        return observations

    print(f"{len(offen)} Detailseiten holen …")
    now = datetime.now()
    # Als Eintrag, nicht als Rundgang: die Beobachtungen brauchen eine Zeile
    # im Journal, aber diese Zeile darf nicht als *der* letzte Lauf gelten.
    # Seit das Tor die Klappentexte mitten im Lauf nachlaedt, waere sie sonst
    # genau das — frueher fertig als der Rundgang, der sie angestossen hat,
    # und die Startseite meldete "zuletzt geprueft … 0 Aenderungen"
    # (dieselbe Unterscheidung wie beim engen Lauf, Ticket 51).
    run_id = store.start_run(settings.slug, ENTRY_TRIGGER, now, pid=os.getpid())
    geholt: dict[tuple[str, str], Observation] = {}
    frisch: list[Observation] = []
    for observation in offen:
        source = by_name.get(observation.source)
        if source is None:
            continue
        try:
            item = source.item(observation.source_item_id)
        except RateLimited:
            # 429 heisst Halt, und zwar fuer alles Weitere — dieselbe Regel wie
            # bei den Titelbildern und bei der DNB (ADR 7). Seit das Tor die
            # Texte mitten im Lauf nachlaedt, waeren es sonst vierzig
            # abgelehnte Anfragen hintereinander an dieselbe Quelle.
            print("Klappentexte: die Quelle drosselt — Rest übersprungen", file=sys.stderr)
            break
        except Exception as exc:  # noqa: BLE001 - ein Buch, nicht der Stapel
            print(f"  {observation.title[:44]}: {type(exc).__name__}", file=sys.stderr)
            continue
        if item is None:
            continue
        # Die Detailseite traegt auch das groessere Titelbild (600x600 statt
        # 200x200 auf der Kachel). Sie ist schon geholt — es hier fallen zu
        # lassen hiesse, sie fuer dasselbe Bild ein zweites Mal zu holen.
        voller = replace(
            observation,
            blurb=item.blurb or observation.blurb,
            cover_url=item.cover_url or observation.cover_url,
            keywords=item.keywords,
            publisher=item.publisher,
            pages=item.pages or observation.pages,
            sample_url=item.sample_url,
        )
        geholt[observation.key] = voller
        # Auch der Umfang kommt ins Journal: der Stapel liest die letzte
        # Beobachtung und erkennt daran Kurzgeschichten (#73).
        before = (observation.blurb, observation.cover_url, observation.pages)
        if (voller.blurb, voller.cover_url, voller.pages) != before:
            frisch.append(replace(voller, observed_at=now))

    if frisch:
        store.append(run_id, settings.slug, frisch, now)
    store.finish_run(run_id, status="ok", delta_count=0, finished_at=datetime.now())
    return [geholt.get(o.key, o) for o in observations]
