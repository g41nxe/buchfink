"""Was eine Übersetzung und ihr Original gemeinsam haben: das Werk (ADR 36, #80).

*Gestohlene Erinnerung* und *Recursion* standen als zwei Bücher mit zwei
Steckbriefen und zwei Urteilen im Werkzeug, und das Modell würfelte je Ausgabe
neu. Ein Werk ist die Autor:in mit dem Titel des Originals: bei einer
Übersetzung nennt ihn die DNB (MARC 240), sonst ist der eigene Titel der
Originaltitel. Aus dem Steckbrief kommt er nie — das Modell hat dort schon
*Dark Matter* statt *Recursion* geschrieben.
"""

from __future__ import annotations

import re

from ..cleaning import author_key
from ..matching.normalize import fold

_NOT_A_WORD = re.compile(r"[^\w]+")
#: Eine Bandnummer am Ende des Titels: „Im dunklen Tal 1“, „… Teil 2“.
_VOLUME = re.compile(r"(?:(?:teil|band|bd|part|vol)\.?\s*)?(\d+)\s*$", re.IGNORECASE)


def work_title(title: str | None, original_title: str) -> str:
    """Der Originaltitel, der das Werk bestimmt — bei einem geteilten Band mit
    der Nummer der eigenen Ausgabe.

    Der deutsche Verlag teilt „Into the Narrowdark“ in „Im dunklen Tal 1“ und
    „… 2“, und die DNB nennt für beide denselben Originaltitel. Zwei Bücher,
    die man getrennt kauft und leiht, wären so ein Werk (gemessen am Bestand,
    28.10.2026: dreimal Tad Williams). Trägt das Original selbst eine Nummer,
    gilt sie: dann sind Übersetzung und Original dasselbe Buch.
    """
    if _VOLUME.search(original_title):
        return original_title
    volume = _VOLUME.search(title or "")
    return f"{original_title} {volume.group(1)}" if volume else original_title


def work_key(author: str | None, title: str | None) -> str | None:
    """„blake crouch|recursion" — oder nichts, wo Autor:in oder Titel fehlt.

    Der **ganze** Titel, nur ohne Groß- und Kleinschreibung, Akzente und
    Satzzeichen. Den Untertitel abzuschneiden, wie es die Zuordnung tut,
    machte aus „The Heritage Universe - Band 1: Gezeitensturm" und „… Band 2"
    ein Werk und aus einem Sammelband seinen ersten Band (gemessen am Bestand,
    03.10.2026). Übersetzung und Original treffen sich über den
    Originaltitel der DNB, nicht über einen gekürzten Titel.
    """
    if not author or not title:
        return None
    writer = author_key(author)
    name = " ".join(_NOT_A_WORD.sub(" ", fold(title)).split())
    if not writer or not name:
        return None
    return f"{writer}|{name}"
