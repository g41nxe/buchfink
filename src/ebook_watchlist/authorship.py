"""Wer seine Texte von einer Maschine schreiben lässt (#31).

Ein KI-erzeugtes Buch ist kein Kandidat — und zwar **bevor** es ein Urteil
kostet, wie ein Fund in fremder Sprache (#10). Gemessen am Bestand vom
23.09.2026: ein einziger Autor, 32 Titel, 5 % aller Titel mit Autorenangabe.
Sechsundzwanzig davon hatten bereits je einen Modellaufruf verbraucht, im
Schnitt für 1,8 Sterne.

**Die Auskunft gilt der Autorenschaft, nicht dem Buch.** Sie lautet im
Wortlaut: „Der Autor verwendet zum Erstellen seiner Texte meistens künstliche
Intelligenz (und muss das angeben, was er hiermit macht)!" Das ist eine Aussage
über seine Arbeitsweise, und sie erlaubt den Schluss auf alle seine Titel —
zehn der zweiunddreißig haben bis heute nur den kurzen Kacheltext, in dem
nichts davon steht.

**Abgeleitet statt gespeichert** (ADR 16): die Selbstauskunft liegt in den
Beobachtungen, die ohnehin aufbewahrt werden. Ein eigener Vermerk wäre ein
zweiter Ort, der veralten kann, und bräuchte eine Migration für eine Tatsache,
die schon dasteht.
"""

from __future__ import annotations

import re

from .models import MatchReason, Observation
from .store import Store

#: Nur Behauptungen über die **Herstellung**, nie über den Inhalt. „Künstliche
#: Intelligenz" allein taugt nicht: der Pandora-Zyklus von Frank Herbert
#: handelt von einer, und zwei seiner Bände fielen einem groberen Muster zum
#: Opfer. Gemessen trennt dieses hier sauber — 32 Treffer, alle derselbe Autor,
#: kein Fehlgriff.
_MADE_BY_AI = re.compile(
    r"KI-Autor(in)?\b"
    r"|\bKI[- ](generiert|erzeugt|erstellt|geschrieben)"
    r"|zum Erstellen (sein|ihr)\w* Texte"
    r"|mit (Hilfe von )?(KI|künstlicher Intelligenz) (erstellt|erzeugt|geschrieben|verfasst)"
    r"|AI[- ](generated|assisted|written)",
    re.IGNORECASE,
)


def declares_ai(text: str | None) -> bool:
    """Ob dieser Text die Herstellung durch eine KI angibt."""
    return bool(text and _MADE_BY_AI.search(text))


#: Grobe Vorauswahl fuer die Datenbank, damit nicht jede je gespeicherte
#: Beobachtung gelesen wird. Jede Alternative des Musters oben enthaelt eines
#: dieser Woerter — wer das Muster erweitert, prueft das hier mit.
_NEEDLES = ("KI", "AI", "Erstellen")


def ai_authors(store: Store) -> frozenset[str]:
    """Wer es irgendwo selbst angegeben hat — einmal gelesen, dann gilt es.

    Die Angabe steht auf der **Detailseite**, und die wird nur für Bücher
    geholt, die gleich beurteilt werden. Von 232 Kacheltexten trug keiner sie,
    von 25 Detailseiten alle. Eine gesehene Seite reicht deshalb für das ganze
    Werk: sonst spart der Filter genau dort nichts, wo er greifen soll.
    """
    return frozenset(
        author
        for author, blurb in store.authors_and_blurbs(_NEEDLES)
        if declares_ai(blurb)
    )


def is_ai_authored(observation: Observation, authors: frozenset[str]) -> bool:
    """Ob dieser Fund von einer erkannten KI-Autorenschaft stammt.

    Ein Watchlist-Titel ist nie betroffen: was die Leserin selbst auf die Liste
    setzt, bleibt dort — dieselbe Ausnahme wie bei der Sprache (#10).

    Ohne Autorenangabe gilt nichts. Zu raten, wo niemand etwas gesagt hat,
    wäre hier der teure Fehler: ein zu Unrecht gefiltertes Buch erscheint nie,
    und niemand erfährt davon.
    """
    if observation.match_reason is MatchReason.WATCHLIST or not observation.author:
        return False
    return observation.author in authors or declares_ai(observation.blurb)
