"""Every Onleihe-specific string in one place (ADR 7).

When the Onleihe redesigns, this module is the whole diff. Nothing else in the
codebase may hard-code a selector or a German label for this Source.

Sourced from ``docs/research/voebb-search-interface.md``.
"""

from __future__ import annotations

BASE = "https://voebb.onleihe.de/berlin/frontend/"

SEARCH_PATH = "search,0-0-0-0-0-0-0-0-0-0-0.html"
#: Paged results. ``{page}`` is a 0-based index (0 = page 1).
SEARCH_PAGE_PATH = "search,0-0-0-700-0-0-{page}-1000-0-0-0.html"

#: The form declares POST but honours GET, which keeps pagination stateless.
SEARCH_PARAMS = {
    "cmdId": "703",  # "new search"
    "sK": "1000",  # search-context key, echoed into pagination URLs
    "pMediaType": "-1",  # all media; we filter client-side
}

# --- results page ---------------------------------------------------------

CARD = '[test-id="mediaCard"]'
CARD_TITLE = '[test-id="cardTitle"]'
CARD_SUBTITLE = '[test-id="cardSubTitle"]'
CARD_AUTHOR = '[test-id="cardAuthor"]'
CARD_DETAIL_LINK = 'a[test-id="mediaInfoLink"]'
#: Cards carry several ``ic_*`` icons (rating stars among them), so the medium
#: is picked by name rather than by position.
CARD_MEDIUM_ICON = 'svg[test-id^="ic_"]'
#: Friendly names for ``profile.yaml``, mapped to the icon the markup uses.
MEDIUM_BY_NAME = {
    "ebook": "ic_ebook",
    "hoerbuch": "ic_eaudio",
    "hörbuch": "ic_eaudio",
    "hoerspiel": "ic_ehoerspiel",
    "epaper": "ic_epaper",
    "emagazine": "ic_emagazine",
    "evideo": "ic_evideo",
    "elearning": "ic_elearning",
}
MEDIUM_ICONS = frozenset(MEDIUM_BY_NAME.values())

#: The Onleihe lists the ebook and the audiobook of a novel as two separate
#: titles with the same title and author. Without a preference the matcher
#: cannot tell them apart and every such entry would need a human — so a
#: watchlist means ebooks unless it says otherwise.
DEFAULT_MEDIA: tuple[str, ...] = ("ic_ebook",)
CARD_ABSTRACT = '[test-id="cardAbstract"]'
CARD_AVAILABILITY = '[test-id="cardAvailability"]'
CARD_AVAILABILITY_LABEL = '[test-id="cardLabelAvailability"]'

# --- detail page ----------------------------------------------------------

EXEMPLAR_COUNT = ".exemplar-count"
AVAILABILITY_COUNT = ".availability-count"
RESERVATION_COUNT = ".reservation-count"
DETAIL_TITLE = '[test-id="cardTitle"]'
DETAIL_SUBTITLE = "h4.headline.subtitle"
#: Das Titelbild. Die Onleihe liefert eins — die abgelegten Beispielseiten
#: zeigten keines, weil sie aus der Zeit vor einem Umbau der Seite stammen.
#: Bis dahin bekam ein Buch, das es nur in der Bibliothek gibt, nie ein Bild.
DETAIL_COVER = "img.img-thumbnail[src]"
#: Was die Leserschaft der Bibliothek sagt. Der Durchschnitt steht nur als
#: Sternbild — gefuellte Sterne zaehlen; die Suchkarte nennt ihn genauer
#: (``cardAverageVote``), aber die sehen wir nur bei der Zuordnung.
DETAIL_RATING = '[test-id="rating"]'
DETAIL_RATING_STAR = ".ic_star"
DETAIL_RATING_FILLED = ".ic_star.active"
#: Die Anzahl steht in einer eigenen Beschreibungsliste, nicht in den
#: ``horizontalDescription``-Zeilen wie Autor:in und Reihe.
DETAIL_VOTES = "dt.user-vote"
#: Der Klappentext. Der Reiter darueber heisst ``#tabContent_1_`` — eine
#: Position, kein Name, und er traegt ausserdem die Biografie der Autorin: 1755
#: Zeichen statt 1372 in der abgelegten Beispielseite. Die Beschreibungsliste
#: darunter trennt beides sauber, und die Beschriftung "Inhalt:" bleibt im
#: ``dt`` zurueck, wo sie niemanden stoert.
DETAIL_ABSTRACT = "dt.abstract"
#: Bibliographic rows are ``<b>LABEL:</b><span>VALUE</span>`` pairs.
DESCRIPTION_ROW = "p.horizontalDescription"

# --- German literals ------------------------------------------------------

HITS_MARKER = "Titeltreffer"
NO_HITS_MARKER = "keine Titeltreffer"
SESSION_EXPIRED_MARKER = "Ihre Sitzung ist abgelaufen"
LABEL_AVAILABLE_FROM = "Voraussichtlich verfügbar ab:"
LABEL_AUTHOR = "Autor*in:"
LABEL_YEAR = "Jahr:"
LABEL_SERIES = "Reihe:"
LABEL_ISBN = "ISBN:"

# --- doctor probe ---------------------------------------------------------

#: A query and a title that must stay parseable. We assert the *fields* parse,
#: never their values — copies and queue lengths change by the hour.
PROBE_QUERY = "Die sieben Schwestern"
PROBE_DETAIL_PATH = "mediaInfo,0-0-373164461-200-0-0-0-0-0-0-0.html"

#: Die Detailseite zu einer Kennung. Dieselbe Form wie die Probe oben; die
#: Nullen sind Suchzustand, den die Seite nicht braucht (#17).
DETAIL_PATH = "mediaInfo,0-0-{title_id}-200-0-0-0-0-0-0-0.html"

#: Der Knopf "Leseprobe" — ein Link auf den Webreader, die EPUB-Datei steht
#: in dessen Adresse hinter ``url=`` (#17).
SAMPLE_LINK = 'a[href*="reader.onleihe.de"][href*="url="]'
