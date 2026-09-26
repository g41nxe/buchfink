"""Sammelausgaben erkennen (ADR 24).

Eine Sammelausgabe ist ein eigenes Buch, das mehrere anderswo einzeln
erhältliche Bände enthält — ONIX nennt das ``EditionType = CMB``. Für uns sind
zwei Dinge daran wichtig, und sie sind verschieden schwer:

*Dass* es eine ist, verrät oft schon der Name. Das reicht für das Abzeichen und
dafür, den Einzelband im Rang vorzuziehen.

*Welche* Bände drinstecken, verrät der Name nur in der Schrägstrich-Form. Bei
"David Hunter: 3in1 Bundle" steht es allein im Klappentext, und geraten wird
hier nicht: gemessen an 19 Sammelausgaben im Bestand liest ein Zähler am Titel
mindestens drei falsch — "5 Cottages - Haus der dunklen Geister" und "7 Momente
in Angst" sind einzelne Romane.

Deshalb gibt ``volume_titles`` nur die *Vorschläge* aus der Schrägstrich-Form
zurück. Ob es wirklich Bände sind, entscheidet der Aufrufer, indem er jeden
Teil gegen die bekannten Bücher hält. Das ist die Selbstkorrektur, die eine
Stoppwortliste ersetzt: "28m² - Die Probandenstudie / Psychothriller /
Verlagsbestseller" zerfällt in Teile, von denen zwei nirgends als Buch
auftauchen — und damit ist es keine Sammelausgabe.
"""

from __future__ import annotations

import re

#: Namen, die eine Sammelausgabe ausdrücklich benennen. Deckungsgleich mit dem
#: Muster in ``junk.py``, das dieselben Formen für den Müllfilter braucht —
#: dort aber nur auf Themenregalen greift.
_MARKERS = re.compile(
    r"""
      Sammelband | Sammelausgabe | Gesamtausgabe | Gesamtwerk
    | \bBundle\b | \d \s* in \s* 1
    | ^ \s* \d+ \s+ \w+ (?:[-\s]\w+)? \s* :
    | ^ \s* (?:Zwei|Drei|Vier|Fünf|Sechs|Sieben|Acht|Neun|Zehn|Zwölf) (?:mal|f?\s)
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Die von ONIX ausdrücklich vorgesehene Kurzform: die Einzeltitel mit
#: Schrägstrichen aneinandergereiht.
_SLASH = re.compile(r"\s+/\s+")

#: Die Ankündigung vor den Bandtiteln: "2 Gruselkrimis: ", "3 Spuk Thriller: ".
_COUNT_PREFIX = re.compile(r"^\s*\d+\s+\w+(?:[-\s]\w+)?\s*:\s*")

#: Kürzer als das ist kein Buchtitel, sondern ein Bruchstück.
_MIN_PART = 3


def looks_like_bundle(title: str | None) -> bool:
    """Sieht der Name nach einer Sammelausgabe aus?

    Bewusst großzügig: die Antwort trägt keine Meldung, sie sorgt nur für ein
    Abzeichen und dafür, dass der Einzelband im Rang gewinnt. Ein zu Unrecht
    demütigter Kandidat verliert nichts, solange kein exakter Treffer daneben
    steht — und steht einer daneben, ist er ohnehin der bessere.
    """
    if not title:
        return False
    if _MARKERS.search(title):
        return True
    return len(volume_titles(title)) >= 2


def volume_titles(title: str | None) -> tuple[str, ...]:
    """Die Titel, die in der Schrägstrich-Form drinstehen — als Vorschlag.

    Leer, wenn der Name keine hergibt. Das ist der Normalfall: "3in1 Bundle"
    nennt keinen einzigen Bandtitel.
    """
    if not title:
        return ()
    # "2 Gruselkrimis: Blutige Tränen / Tiberius Elroy" — die Ankündigung
    # gehoert nicht an den ersten Bandtitel.
    title = _COUNT_PREFIX.sub("", title, count=1)
    parts = [part.strip() for part in _SLASH.split(title)]
    if len(parts) < 2:
        return ()
    if any(len(part) < _MIN_PART for part in parts):
        return ()
    return tuple(parts)
