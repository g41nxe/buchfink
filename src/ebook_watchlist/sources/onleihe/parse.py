"""Turning Onleihe HTML into values. Pure functions — no network, no config.

Every parser here raises :class:`SourceStructureError` when the markup stops
looking like what the research documented. That loudness is the point: a
silently empty result is indistinguishable from "nothing new today" (ADR 7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ...models import Availability
from ..base import SourceStructureError
from . import selectors as sel

_INT = re.compile(r"\d+")
_DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _leading_int(node: Tag | None, what: str) -> int:
    if node is None:
        raise SourceStructureError(f"Onleihe detail page: no {what} element")
    match = _INT.search(node.get_text(" ", strip=True))
    if match is None:
        raise SourceStructureError(f"Onleihe detail page: {what} holds no integer")
    return int(match.group())


@dataclass(frozen=True, slots=True)
class Detail:
    """What a ``mediaInfo`` page says about one title."""

    title: str | None
    author: str | None
    copies: int
    available_copies: int
    reservations: int
    available_from: str | None
    #: Die Onleihe benennt die Reihe ausdruecklich - eine der wenigen Quellen,
    #: die das tut (ADR 17).
    series: str | None = None
    isbn: str | None = None
    #: Adresse des Titelbilds. Kostet keine eigene Anfrage — es steht auf der
    #: Seite, die ohnehin fuer die Verfuegbarkeit geholt wird.
    cover_url: str | None = None
    #: Was die Leserschaft der Bibliothek im Schnitt vergeben hat, 0 bis 5.
    rating: int | None = None
    #: Auf wie vielen Stimmen dieser Schnitt ruht.
    votes: int | None = None
    #: Der Klappentext. Kostet wie das Titelbild keine eigene Anfrage.
    blurb: str | None = None
    #: Die Leseprobe als EPUB, fuer den Bewerter (#17).
    sample_url: str | None = None
    #: Der Verlag, fuer den Abzug bei Selbstverlag (#28).
    publisher: str | None = None

    @property
    def availability(self) -> Availability:
        return Availability.AVAILABLE if self.available_copies >= 1 else Availability.UNAVAILABLE


def _labelled_value(page: BeautifulSoup, label: str) -> str | None:
    """Read a ``<b>LABEL:</b><span>VALUE</span>`` bibliographic row."""
    for row in page.select(sel.DESCRIPTION_ROW):
        bold = row.find("b")
        if bold and bold.get_text(strip=True) == label:
            value = row.find("span")
            if value:
                return value.get_text(" ", strip=True).strip(";").strip() or None
    return None


#: Die Onleihe schreibt sie mal mit, mal ohne Bindestriche.
_ISBN13 = re.compile(r"(?<!\d)(97[89]\d{10})(?!\d)")


def _isbn(page: BeautifulSoup) -> str | None:
    """Die Onleihe nennt sie in derselben Beschriftungszeile wie Autor und Reihe."""
    raw = _labelled_value(page, sel.LABEL_ISBN)
    if not raw:
        return None
    match = _ISBN13.search(raw.replace("-", ""))
    return match.group(1) if match else None


def parse_detail(html: str) -> Detail:
    """Read the *Exemplarinformationen* block — the reliable availability signal."""
    page = soup(html)

    copies = _leading_int(page.select_one(sel.EXEMPLAR_COUNT), "Exemplare")
    available = _leading_int(page.select_one(sel.AVAILABILITY_COUNT), "Verfügbar")
    # A title with no queue can omit the block entirely, so this one is optional.
    reservation_node = page.select_one(sel.RESERVATION_COUNT)
    reservations = _leading_int(reservation_node, "Vormerker") if reservation_node else 0

    title_node = page.select_one(sel.DETAIL_TITLE)
    title = title_node.get_text(" ", strip=True) if title_node else None

    available_from = None
    raw_date = _labelled_value(page, sel.LABEL_AVAILABLE_FROM)
    if raw_date:
        match = _DATE.search(raw_date)
        available_from = match.group(1) if match else None

    return Detail(
        title=title,
        series=_labelled_value(page, sel.LABEL_SERIES),
        isbn=_isbn(page),
        author=_labelled_value(page, sel.LABEL_AUTHOR),
        copies=copies,
        available_copies=available,
        reservations=reservations,
        available_from=available_from,
        cover_url=_cover(page),
        rating=_rating(page),
        votes=_votes(page),
        blurb=_blurb(page),
        sample_url=_sample(page),
        publisher=_publisher(page),
    )


def _publisher(page) -> str | None:
    marke = page.select_one(sel.PUBLISHER_LABEL)
    wert = marke.find_next_sibling() if marke is not None else None
    return wert.get_text(" ", strip=True) or None if wert is not None else None


def _sample(page) -> str | None:
    """Die EPUB-Datei hinter dem Knopf "Leseprobe".

    Der Knopf zeigt auf den Webreader, ``reader.onleihe.de/#/read?url=…``; die
    Datei steht im Fragment, wo ``urlsplit`` keine Abfrage sucht. Deshalb der
    Schnitt am ``url=``.
    """
    link = page.select_one(sel.SAMPLE_LINK)
    href = link.get("href") if link is not None else None
    if not isinstance(href, str):
        return None
    datei = href.split("url=", 1)[1].strip()
    return datei if datei.startswith("https://") else None


def _rating(page) -> int | None:
    """Der Durchschnitt der Leserstimmen, als Zahl gefuellter Sterne.

    Die Seite zeigt ihn **nur** als Sternbild und rundet dabei: die
    Trefferkarte nannte fuer *Autoritaet* 2.8, hier stehen 2 von 5. Fuer eine
    Regel mit dem Angelpunkt "3 ist Durchschnitt" kann das den Ausschlag geben
    — der genauere Wert steht auf der Karte und liesse sich bei der Zuordnung
    mitnehmen (Ticket 51).
    """
    block = page.select_one(sel.DETAIL_RATING)
    if block is None:
        return None
    if not block.select(sel.DETAIL_RATING_STAR):
        return None
    return len(block.select(sel.DETAIL_RATING_FILLED))


def _votes(page) -> int | None:
    """Wie viele Stimmen dahinterstehen. Ohne sie ist der Schnitt wertlos."""
    label = page.select_one(sel.DETAIL_VOTES)
    wert = label.find_next("dd") if label is not None else None
    if wert is None:
        return None
    ziffern = re.sub(r"[^0-9]", "", wert.get_text(" ", strip=True))
    return int(ziffern) if ziffern else None


def _blurb(page) -> str | None:
    """Der Klappentext, den die Onleihe selbst mitliefert (Ticket 56).

    Ein Buch, das nur die Bibliothek fuehrt, hatte bisher keinen: gemessen ueber
    alle gespeicherten Beobachtungen kamen 2674 Klappentexte aus dem Shop und 0
    von hier — dabei steht er auf der Seite, die fuer die Verfuegbarkeit ohnehin
    geholt wird.

    Gegriffen wird das ``dd`` der Beschreibungsliste, nicht der Reiter
    ``#tabContent_1_``: die Nummer darin ist eine Position und altert so
    schlecht wie jeder Zaehler im Markup. Der Reiter waere auch zu weit — er
    haelt die Biografie der Autorin in derselben Lade, in der abgelegten
    Beispielseite 383 Zeichen davon.

    Abgeschnitten wird nichts: die Beschriftung "Inhalt:" bleibt im ``dt``, und
    die Pressestimmen, die eine der beiden Seiten voranstellt (584 von 1372
    Zeichen), sind zu duenn belegt fuer eine Regel — die Guillemets, an denen
    sie haengen, gebraucht derselbe Text auch fuer den Buchtitel. Die
    Leerzeichen zieht ``clean_blurb`` zusammen, fuer jede Quelle an einer
    Stelle (Ticket 16).
    """
    label = page.select_one(sel.DETAIL_ABSTRACT)
    # Das eigene ``dd``, nicht das naechstbeste: ``find_next`` laeuft durch das
    # ganze Dokument weiter und holte bei einer Beschriftung ohne eigenen Text
    # den Inhalt einer fremden Liste - im Zweifel die Biografie, um die es
    # hier gerade nicht geht.
    text = label.find_next_sibling("dd") if label is not None else None
    if text is None:
        return None
    return text.get_text(" ", strip=True) or None


def _cover(page) -> str | None:
    """Die Adresse des Titelbilds, falls die Seite eins nennt.

    Ein Buch, das es nur in der Bibliothek gibt, hatte bis dahin nie ein Bild:
    Cover kamen ausschliesslich aus dem Shop, und dort steht nicht jeder Titel.
    Bei *Autoritaet* und *Akzeptanz* — beide sofort ausleihbar — fiel es auf.
    """
    node = page.select_one(sel.DETAIL_COVER)
    if node is None:
        return None
    src = node.get("src")
    return src if isinstance(src, str) and src.strip() else None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One result card, ready for the matcher (ticket 04)."""

    title: str
    author: str | None
    subtitle: str | None
    medium: str | None
    url: str
    blurb: str | None = None
    #: Das Vorschaubild der Karte, fuer die Auswahl bei einer offenen
    #: Zuordnung (Ticket 41).
    cover_url: str | None = None


def _card_text(card: Tag, selector: str) -> str | None:
    node = card.select_one(selector)
    if node is None:
        return None
    return node.get_text(" ", strip=True) or None


def _medium_of(card: Tag) -> str | None:
    """The format icon — cards also carry rating stars, so match by name."""
    for icon in card.select(sel.CARD_MEDIUM_ICON):
        name = icon.get("test-id")
        if isinstance(name, str) and name in sel.MEDIUM_ICONS:
            return name
    return None


def parse_search_results(html: str, base: str = sel.BASE) -> list[Candidate] | None:
    """Candidates from a results page.

    Returns ``None`` for a genuine "no hits" — that is an answer, not a failure.
    Raises when the page claims hits but yields no parseable cards.
    """
    page = soup(html)
    text = page.get_text(" ", strip=True)

    if sel.SESSION_EXPIRED_MARKER in text:
        raise SourceStructureError(
            "Onleihe search: session expired — pagination must re-supply the query params"
        )

    cards = page.select(sel.CARD)
    if not cards:
        if sel.NO_HITS_MARKER in text:
            return None
        raise SourceStructureError(
            "Onleihe search: no result cards and no 'keine Titeltreffer' marker — "
            "the results markup changed (or a captcha was served)"
        )

    candidates: list[Candidate] = []
    for card in cards:
        title = _card_text(card, sel.CARD_TITLE)
        link = card.select_one(sel.CARD_DETAIL_LINK)
        href = link.get("href") if link else None
        if not title or not href:
            raise SourceStructureError(
                "Onleihe search: a result card is missing its title or detail link"
            )
        candidates.append(
            Candidate(
                title=title,
                author=_card_text(card, sel.CARD_AUTHOR),
                subtitle=_card_text(card, sel.CARD_SUBTITLE),
                blurb=_card_text(card, sel.CARD_ABSTRACT),
                medium=_medium_of(card),
                url=urljoin(base, str(href)),
                cover_url=_card_cover(card, base),
            )
        )
    return candidates


def _card_cover(card: Tag, base: str) -> str | None:
    bild = card.select_one(sel.CARD_COVER)
    quelle = bild.get("src") if bild is not None else None
    return urljoin(base, quelle) if isinstance(quelle, str) and quelle else None


def total_hits(html: str) -> int | None:
    """The ``… ergab 49 Titeltreffer`` count, when the page states one."""
    text = soup(html).get_text(" ", strip=True)
    if sel.NO_HITS_MARKER in text:
        return 0
    match = re.search(rf"(\d+)\s+{sel.HITS_MARKER}", text)
    return int(match.group(1)) if match else None
