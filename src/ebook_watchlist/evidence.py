"""Belege für den Bewerter — zusammengetragen unmittelbar vor einem Urteil (#17).

Eine Stelle für Lauf und Buchseite: beide sollen dieselbe Frage mit derselben
Grundlage beantworten. Vorher urteilte die Buchseite ohne Detailseite, und
dasselbe Buch bekam von zwei Stellen zwei verschieden gut begründete Urteile.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime

from .config import Profile
from .http import RateLimited
from .models import Observation
from .store import ENTRY_TRIGGER, Store


def gather(store: Store, profile: Profile, observations, sources):
    """Was der Bewerter zu sehen bekommt — zusammengetragen unmittelbar davor.

    Nur fuer die Buecher, die gleich ein Urteil bekommen; alles hier kostet
    Anfragen, und das Budget des Tors begrenzt, wie viele es sind.

    Drei Belege neben dem Klappentext (#17): die Schlagwoerter der Detailseite,
    die Leseprobe dahinter und was die DNB schon gesagt hat (Originaltitel,
    Schlagwoerter des Verlags). Die DNB wird hier nicht gefragt — das tut der
    Lauf an seiner eigenen Stelle, mit ihrem eigenen Budget.
    """
    observations = _with_details(store, profile, observations, sources)
    dnb = store.dnb_facts(o.isbn for o in observations if o.isbn)
    belegt = []
    for observation in observations:
        original, dnb_woerter = dnb.get(observation.isbn or "", (None, ()))
        belegt.append(
            replace(
                observation,
                keywords=tuple(dict.fromkeys((*observation.keywords, *dnb_woerter))),
                original_title=original,
            )
        )
    return belegt


def _with_details(store: Store, profile: Profile, observations, sources):
    """Die Detailseite holen — eine Anfrage je Buch, und nur hier.

    Fuer den ganzen Klappentext, die Schlagwoerter und die Leseprobe. Die
    Probe wird gleich mitgeholt, solange die Quelle zur Hand ist: eine Anfrage
    mehr, an dieselbe Quelle, mit derselben Hoeflichkeit.

    Angehängt statt überschrieben: der Snapshot wird nie umgeschrieben
    (ADR 5). Der Shop *hat* das gesagt, nur auf einer anderen Seite, und damit
    ist es eine Beobachtung wie jede andere. Preis und Verfügbarkeit kommen
    ebenfalls von dort — weicht der Preis ab, ist das eine echte Änderung und
    keine erfundene.

    Frueher wurde nur geholt, was keinen ganzen Klappentext trug. Seit die
    Seite auch Leseprobe und Schlagwoerter liefert, wird sie fuer jedes Buch
    geholt, das beurteilt wird (#17) — ins Journal kommt sie nur, wenn sich
    Klappentext oder Titelbild geaendert haben.
    """
    from .sample import fetch_opening

    by_name = {source.name: source for source in sources}
    offen = [o for o in observations if o.source in by_name]
    if not offen:
        return observations

    print(f"{len(offen)} Detailseiten und Leseproben holen …")
    now = datetime.now()
    # Als Eintrag, nicht als Rundgang: die Beobachtungen brauchen eine Zeile
    # im Journal, aber diese Zeile darf nicht als *der* letzte Lauf gelten.
    # Seit das Tor die Klappentexte mitten im Lauf nachlaedt, waere sie sonst
    # genau das — frueher fertig als der Rundgang, der sie angestossen hat,
    # und die Startseite meldete "zuletzt geprueft … 0 Aenderungen"
    # (dieselbe Unterscheidung wie beim engen Lauf, Ticket 51).
    run_id = store.start_run(profile.slug, ENTRY_TRIGGER, now, pid=os.getpid())
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
        probe = None
        client = getattr(source, "client", None)
        if item.sample_url and client is not None:
            try:
                probe = fetch_opening(client, item.sample_url)
            except RateLimited:
                print("Leseproben: die Quelle drosselt — Rest übersprungen", file=sys.stderr)
                break
        # Die Detailseite traegt auch das groessere Titelbild (600x600 statt
        # 200x200 auf der Kachel). Sie ist schon geholt — es hier fallen zu
        # lassen hiesse, sie fuer dasselbe Bild ein zweites Mal zu holen.
        voller = replace(
            observation,
            blurb=item.blurb or observation.blurb,
            cover_url=item.cover_url or observation.cover_url,
            keywords=item.keywords,
            sample=probe,
        )
        geholt[observation.key] = voller
        if (voller.blurb, voller.cover_url) != (observation.blurb, observation.cover_url):
            frisch.append(replace(voller, observed_at=now))

    if frisch:
        store.append(run_id, profile.slug, frisch, now)
    store.finish_run(run_id, status="ok", delta_count=0, finished_at=datetime.now())
    return [geholt.get(o.key, o) for o in observations]
