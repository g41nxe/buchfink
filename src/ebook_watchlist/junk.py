"""Was gar nicht erst vorgeschlagen wird (ADR 19).

Bündel, Sammelausgaben und Gratis-Füllmaterial sind Ramsch der Form nach, nicht
des Inhalts nach — dafür braucht es kein Urteil, nur ein Muster. Sie fliegen
raus, *bevor* das Bewertungstor Geld für die Erkenntnis ausgibt.

Aussortiert wird erst bei der Meldung, nie beim Sammeln: der Snapshot bleibt
vollständig, damit eine zu scharfe Regel hier keine Geschichte kostet.

Betroffen sind nur Entdeckungen. Ein Watchlist-Titel, den die Leserin selbst
ausgewählt hat, geht immer durch — wer eine Gesamtausgabe beobachten will, darf
das.
"""

from __future__ import annotations

import re

from .models import MatchReason, Observation

#: Sammelwörter, die ein Bündel benennen, plus das Muster "Zahl + Genre +
#: Doppelpunkt" ("2 Gruselkrimis: …", "4 Spuk Thriller: …").
#:
#: Bewusst *nicht* "Zahl am Anfang" allein: "5 Cottages - Haus der dunklen
#: Geister", "7 Momente in Angst" und "21 - Fremder Schatten" (Wulf Dorn) sind
#: reguläre Titel, die daran zerbrochen wären.
_BUNDLE = re.compile(
    r"""
      Sammelband | Sammelausgabe | Gesamtausgabe | Gesamtwerk
    | \bBundle\b | \d \s* in \s* 1
    | ^ \s* \d+ \s+ \w+ (?:[-\s]\w+)? \s* :
    | ^ \s* (?:Zwei|Drei|Vier|Fünf|Sechs|Sieben|Acht|Neun|Zehn|Zwölf) (?:mal|f?\s)
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Fortsetzungshefte. Ganze Serien davon stehen zu 0,99 € in den Themenregalen
#: und würden die Preisgrenze mühelos unterlaufen.
_EPISODE = re.compile(r"\b(?:Episode|Folge)\s*\d+", re.IGNORECASE)

BUNDLE = "Sammelband"
EPISODE = "Fortsetzungsheft"
FREE = "gratis"


def junk_reason(observation: Observation) -> str | None:
    """Warum dieses Buch Ramsch ist — oder ``None``, wenn es keiner ist.

    Die Form allein entscheidet das nicht. Ein Sammelband von jemandem, den die
    Leserin liest, ist keiner: *David Hunter: 3in1 Bundle* ist Simon Beckett,
    *Achtsam morden (5in1)* ist Karsten Dusse — beides Referenzautor:innen,
    beides genau die Gelegenheit, eine Reihe am Stück zu bekommen. Auf einem
    Themenregal dagegen ist ein Bündel fast immer Massenware.

    Gratis gilt überall: alle zehn Gratistitel eines echten Laufs waren Bündel
    oder Werbebeigaben.
    """
    if observation.price_cents == 0:
        return FREE

    # Formfilter nur dort, wo nichts sonst für das Buch spricht.
    if observation.match_reason is not MatchReason.GENRE_CATEGORY:
        return None

    title = observation.title or ""
    if _BUNDLE.search(title):
        return BUNDLE
    if _EPISODE.search(title):
        return EPISODE
    return None


def is_junk(observation: Observation) -> bool:
    return junk_reason(observation) is not None


#: Ab wie vielen Seiten ein Fund ein Buch ist und keine Kurzgeschichte (#73).
#: Die gängige Einteilung nach Wörtern: Kurzgeschichte bis 7.500 (rund 30
#: Seiten), Novelette bis 17.500 (rund 70), Novelle bis 40.000 (rund 160),
#: darüber Roman. Heftromane haben um die 64 Seiten. Unter 80 fällt also, was
#: eine einzelne Erzählung oder ein Heft ist; eine Novelle bleibt ein Buch.
SHORT_STORY_PAGES = 80


def is_short_story(observation: Observation) -> bool:
    """Eine Kurzgeschichte: ein Fund mit bekanntem Umfang unter der Schwelle.

    Nur nach dem Umfang, den die Detailseite nennt. Wörter im Text taugen
    nicht: „Kurzgeschichten" steht meist in der Autorenbiografie („über 100
    Kurzgeschichten"), und die kurzen *BattleTech*-Titel sagen es nirgends
    (gemessen an 370 Funden, 26.09.2026). Ohne Umfang ist nichts eine
    Kurzgeschichte. Ein Watchlist-Titel geht immer durch.
    """
    if observation.match_reason is MatchReason.WATCHLIST:
        return False
    return observation.pages is not None and observation.pages < SHORT_STORY_PAGES
