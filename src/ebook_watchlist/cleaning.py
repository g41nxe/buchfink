"""Was eine Quelle geliefert hat, in vorzeigbarer Form (Ticket 16).

Zu unterscheiden von ``matching.normalize``: das dort erzeugt einen
*Vergleichsschlüssel* — kleingeschrieben, akzentfrei, Untertitel abgeschnitten.
Hier entsteht die Form, die eine Leserin zu sehen bekommt und die in einen
Prompt geht. Beides aus einer Funktion zu bedienen ginge schief, weil der
Schlüssel absichtlich Information wegwirft.

Der Schlüssel aus ``matching.normalize`` wird trotzdem gebraucht: er sagt,
welche Schreibweisen dieselbe Person meinen.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .matching.normalize import normalize_author

#: Der Shop rendert seinen Aufklapp-Knopf als Material-Icon und die Ligatur
#: landet im Text: jeder der 316 Klappentexte eines echten Laufs endet auf
#: "… Mehr navigate_next". Ohne das steht der Icon-Name in jedem Digest und in
#: jedem Prompt, den das Bewertungstor verschickt.
_ICON_LIGATURES = (
    "navigate_next",
    "navigate_before",
    "expand_more",
    "expand_less",
    "chevron_right",
    "arrow_forward",
    "more_horiz",
)
#: Das "..." davor bleibt ausdruecklich stehen - der Text *ist* abgeschnitten.
_TRAILING_MORE = re.compile(
    r"\s*(?:Mehr|Weiterlesen|mehr lesen)?\s*(?:" + "|".join(_ICON_LIGATURES) + r")\s*$",
    re.IGNORECASE,
)
_LOOSE_LIGATURE = re.compile(r"\s*\b(?:" + "|".join(_ICON_LIGATURES) + r")\b\s*")
_WHITESPACE = re.compile(r"\s+")
#: Die Beschriftung eines Aufklapp-Knopfs, ohne seine Ligatur. Ticket 40 hat
#: den Knopf zum **Aufklappen** erwischt ("alles anzeigen"), den zum Zuklappen
#: nicht: der steht am Ende des vollen Textes, und dort blieben nach dem
#: Abstreifen der Ligatur die blossen Woerter stehen — in 110 von 2674
#: gespeicherten Texten.
_TRAILING_CONTROL = re.compile(
    r"\s*(?:alles anzeigen|weniger anzeigen|mehr anzeigen|weiterlesen)\s*$",
    re.IGNORECASE,
)


def clean_blurb(blurb: str | None) -> str | None:
    """Den Teaser ohne die Bedienelemente, die mit hineingerutscht sind.

    Das abschliessende "…" bleibt stehen: der Text *ist* abgeschnitten, und das
    zu verschweigen wuerde einen Torso wie einen vollstaendigen Klappentext
    aussehen lassen.
    """
    if not blurb:
        return None
    text = _TRAILING_MORE.sub("", blurb)
    text = _LOOSE_LIGATURE.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    # Erst nach dem Zusammenziehen der Leerzeichen: die Ligatur stand hinter
    # der Beschriftung, und solange sie dort klebte, war die Beschriftung
    # nicht das Ende der Zeichenkette.
    return _TRAILING_CONTROL.sub("", text).strip() or None


#: Der Aufklapp-Knopf zwischen Anriss und vollem Text. Er steht in allen 110
#: doppelten Klappentexten genau **einmal** — und in keinem der 1911 kurzen.
_TEASER_CUT = re.compile(r"\s*(?:\.\.\.|…)?\s*alles anzeigen\s*(?:expand_more)?\s*", re.IGNORECASE)


def without_teaser(blurb: str | None) -> str | None:
    """Den Klappentext einmal, nicht zweimal (Ticket 40).

    Das Sicherheitsnetz, nicht der Hauptweg: geschnitten wird im Parser am
    richtigen Knoten (``description--full``), weil ein Klassenname im
    Seitengeruest stabiler ist als ein deutsches Wort im Fliesstext. Bleibt
    trotzdem ein Doppel stehen — weil der Shop den Knoten umbenannt hat, oder
    weil die Zeile aus der Zeit davor stammt —, faengt das hier es auf.

    Der Schnitt ist nachweislich verlustfrei: in 110 von 110 gespeicherten
    Doppeln beginnt der volle Text mit dem Anriss, und in keinem einzigen ist
    er kuerzer. Was vor dem Knopf steht, ist deshalb entbehrlich.
    """
    if not blurb:
        return None
    hit = _TEASER_CUT.search(blurb)
    if hit is None:
        return blurb
    rest = blurb[hit.end() :].strip()
    if not rest:
        return blurb
    # Geschnitten wird nur, wenn der Rest den Anriss auch wirklich
    # wiederholt. Ohne diese Probe verstuemmelt ein Klappentext, in dem
    # "alles anzeigen" als Fliesstext vorkommt: "Die Ausstellung will alles
    # anzeigen, was die Stadt verbirgt" wurde zu ", was die Stadt verbirgt".
    # Damit ist der Schnitt verlustfrei **von Bauart**, nicht nur an den 110
    # gemessenen Faellen.
    teaser = _WHITESPACE.sub(" ", blurb[: hit.start()]).strip().rstrip(". …")
    if not _WHITESPACE.sub(" ", rest).startswith(teaser[:60]):
        return blurb
    return rest


def is_truncated(blurb: str | None) -> bool:
    """Ob die Quelle den Text abgeschnitten hat.

    Wichtig fuer die Bewertung: ein Urteil ueber 219 Zeichen Anriss ist etwas
    anderes als eines ueber einen ganzen Klappentext (ADR 19).
    """
    return bool(blurb) and blurb.rstrip().endswith(("...", "…"))


# --- Schreibweisen von Namen ----------------------------------------------


def _diacritics(name: str) -> int:
    """Wieviel Information die Schreibweise noch traegt.

    "Jo Nesbø" gegen "Jo Nesbo": beide meinen denselben Menschen, aber nur eine
    schreibt ihn richtig.
    """
    decomposed = unicodedata.normalize("NFD", name)
    accents = sum(1 for char in decomposed if unicodedata.combining(char))
    # NFD zerlegt diese nicht - sie brauchen eine eigene Liste, wie in fold().
    letters = sum(1 for char in name if char in "øØłŁæÆœŒðÐþÞđĐßẞ")
    return accents + letters


def author_key(name: str) -> str:
    """Woran sich entscheidet, ob zwei Schreibweisen dieselbe Person sind."""
    return normalize_author(name).full


def preferred_spelling(names: Iterable[str]) -> str | None:
    """Die beste unter mehreren beobachteten Schreibweisen einer Person.

    In einem einzigen Lauf stand derselbe Autor als "Jo Nesbø" (33 Titel),
    "Jo Nesbo" (15) und "Nesbø, Jo" (1). Gewaehlt wird nach: Vorname zuerst
    (kein Komma), dann die Schreibweise mit den meisten erhaltenen
    Sonderzeichen, dann die laengere — und zuletzt alphabetisch, damit
    dieselbe Eingabe immer dieselbe Ausgabe ergibt.

    Haeufigkeit entscheidet ausdruecklich *nicht*: eine falsche Schreibweise
    wird nicht dadurch richtig, dass ein Shop sie oefter verwendet.
    """
    candidates = [name.strip() for name in names if name and name.strip()]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda name: ("," in name, -_diacritics(name), -len(name), name),
    )
