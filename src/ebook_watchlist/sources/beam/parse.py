"""Turning beam-shop listing HTML into values. Pure functions.

One parser serves search results, category listings and author hubs — Shopware
renders the same product tile on all three.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ...cleaning import without_teaser
from ..base import SourceStructureError
from . import selectors as sel

#: de-DE money: "." groups thousands, "," is the decimal point.
_PRICE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})")
_TRAILING_ID = re.compile(r"/(\d+)/[^/]*$")
#: Bestellnummern haben die Form SW + ISBN-13 + optionalem Lieferantensuffix.
_ORDER_ISBN = re.compile(r"^SW(97[89]\d{10})")

NO_RESULTS_MARKER = "keine Artikel gefunden"


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def parse_price(text: str) -> int | None:
    """``"9,99 €"`` → ``999``. Returns ``None`` when there is no price at all."""
    match = _PRICE.search(text.replace("\xa0", " "))
    if match is None:
        return None
    return int(match.group(1).replace(".", "")) * 100 + int(match.group(2))


def canonical_url(href: str, base: str = sel.BASE) -> str:
    """Product links carry a ``?c=<category>`` context param; the path is the identity."""
    parts = urlsplit(urljoin(base, href))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _cover_from(node: Tag | None) -> str | None:
    """Die erste Adresse aus einem ``srcset``.

    Ein srcset ist ``url 1x, url 2x`` — die erste ist die Normalaufloesung, und
    die reicht: 200x200 auf der Kachel, 600x600 auf der Detailseite. Das
    ``src``-Attribut ist bei diesen Bildern ein Platzhalterpixel, weil das Theme
    sie erst beim Scrollen nachlaedt.
    """
    if node is None:
        return None
    for attribute in (sel.ATTR_SRCSET, "srcset", "src"):
        value = node.get(attribute)
        if not isinstance(value, str) or not value.strip():
            continue
        first = value.split(",")[0].strip().split(" ")[0]
        if first.startswith("http"):
            return first
    return None


@dataclass(frozen=True, slots=True)
class Tile:
    """One product as it appears in any listing."""

    product_id: str
    order_number: str
    title: str
    author: str | None
    price_cents: int | None
    url: str
    subtitle: str | None = None
    #: Teaser von der Trefferseite - kostet keinen eigenen Request (ADR 17).
    blurb: str | None = None
    #: Adresse des Titelbilds, direkt aus der Kachel (Ticket 15).
    cover_url: str | None = None
    category_id: str | None = None
    badges: frozenset[str] = frozenset()

    @property
    def isbn(self) -> str | None:
        """Die ISBN-13 aus der Bestellnummer.

        Kostet keine Detailseite - sie steht in jeder Kachel. Nicht jede
        Bestellnummer traegt eine: Buendel und Sammelausgaben haben eigene
        Nummern ohne ISBN-Form.
        """
        return _isbn_from_order_number(self.order_number)

    @property
    def is_preorder(self) -> bool:
        return sel.BADGE_PREORDER in self.badges

    @property
    def is_new(self) -> bool:
        return sel.BADGE_NEW in self.badges


def _title_of(link: Tag) -> tuple[str, str | None]:
    """The clean title plus its subtitle.

    The link's text runs the two together — ``"Krieg der Klone Die Trilogie"`` —
    so the ``title`` attribute, which holds the title alone, is the better source.
    """
    subtitle_node = link.select_one(sel.TILE_SUBTITLE)
    subtitle = subtitle_node.get_text(" ", strip=True) if subtitle_node else None

    attr = link.get("title")
    if isinstance(attr, str) and attr.strip():
        return attr.strip(), subtitle

    if subtitle_node is not None:
        subtitle_node.extract()
    return link.get_text(" ", strip=True), subtitle


def _product_id(tile: Tag, url: str) -> str | None:
    note = tile.select_one(sel.TILE_NOTE_BUTTON)
    if note is not None:
        value = note.get(sel.ATTR_PRODUCT_ID)
        if isinstance(value, str) and value.strip():
            return value.strip()
    match = _TRAILING_ID.search(urlsplit(url).path)
    return match.group(1) if match else None


def _parse_tile(tile: Tag, base: str) -> Tile | None:
    link = tile.select_one(sel.TILE_TITLE)
    order_number = tile.get(sel.ATTR_ORDER_NUMBER)
    if link is None or not isinstance(order_number, str):
        return None

    href = link.get("href")
    if not isinstance(href, str) or not href:
        return None
    url = canonical_url(href, base)

    product_id = _product_id(tile, url)
    if product_id is None:
        return None

    title, subtitle = _title_of(link)
    if not title:
        return None

    author_node = tile.select_one(sel.TILE_AUTHOR)
    author = None
    if author_node is not None:
        author = author_node.get_text(" ", strip=True)
        if author.startswith(sel.AUTHOR_PREFIX):
            author = author[len(sel.AUTHOR_PREFIX) :]
        author = author or None

    price_node = tile.select_one(sel.TILE_PRICE)
    price_cents = parse_price(price_node.get_text(" ", strip=True)) if price_node else None

    category_id = tile.get(sel.ATTR_CATEGORY_ID)
    description = tile.select_one(sel.TILE_DESCRIPTION)
    blurb = description.get_text(" ", strip=True) if description else None

    return Tile(
        product_id=product_id,
        order_number=order_number,
        title=title,
        author=author,
        price_cents=price_cents,
        url=url,
        subtitle=subtitle,
        blurb=blurb or None,
        cover_url=_cover_from(tile.select_one(sel.TILE_IMAGE)),
        category_id=category_id if isinstance(category_id, str) else None,
        # Badges repeat inside a tile once per layout slot.
        badges=frozenset(node.get_text(strip=True) for node in tile.select(sel.TILE_BADGE)),
    )


def parse_tiles(html: str, base: str = sel.BASE) -> list[Tile]:
    """Products from any beam listing page.

    An empty list means the shop said so in as many words. Tiles that will not
    parse mean the theme changed, and that raises.
    """
    page = soup(html)
    boxes = page.select(sel.TILE)

    if not boxes:
        if NO_RESULTS_MARKER in page.get_text(" ", strip=True):
            return []
        raise SourceStructureError(
            "beam-shop: no product tiles and no 'keine Artikel gefunden' message — "
            "the listing markup changed"
        )

    # A product can occupy several layout slots; the order number is its identity.
    tiles: dict[str, Tile] = {}
    for box in boxes:
        parsed = _parse_tile(box, base)
        if parsed is None:
            raise SourceStructureError(
                "beam-shop: a product tile is missing its title, link or id"
            )
        tiles.setdefault(parsed.order_number, parsed)
    return list(tiles.values())


@dataclass(frozen=True, slots=True)
class Detail:
    title: str | None
    price_cents: int | None
    isbn: str | None = None
    cover_url: str | None = None
    #: Only the tile normally carries the author, and whoever arrives by
    #: product id alone never sees a tile (Ticket 17).
    author: str | None = None
    #: The speaking address the shop itself gives this page. Coming in through
    #: the numeric detail route, this is the only way to learn it.
    url: str | None = None
    #: Der ganze Klappentext. Die Kachel traegt nur einen Anriss — gemessen
    #: 197 Zeichen im Median gegen 1931 auf der Detailseite —, und 85 % der
    #: Anrisse sind abgeschnitten. Er wurde hier bisher nicht gelesen, obwohl
    #: die Seite fuer jeden Watchlist-Titel ohnehin geholt wird.
    blurb: str | None = None
    #: Die Leseprobe als EPUB, fuer den Bewerter (#17).
    sample_url: str | None = None
    #: Die Schlagwoerter des Shops, ohne Autor und Titel (#17).
    keywords: tuple[str, ...] = ()
    #: Der Verlag, fuer den Abzug bei Selbstverlag (#28).
    publisher: str | None = None


def _isbn_from_order_number(order_number: str | None) -> str | None:
    """``SW9783104911854450914`` → ``9783104911854``, or nothing.

    Bundles and collections carry order numbers that are not ISBNs at all, so
    the shape is checked rather than assumed.
    """
    if not order_number:
        return None
    match = _ORDER_ISBN.match(order_number)
    return match.group(1) if match else None


def parse_detail(html: str) -> Detail:
    """The pinned product's own page — the authoritative current price."""
    page = soup(html)
    scope = page.select_one(sel.DETAIL_SCOPE)
    if scope is None:
        raise SourceStructureError(
            f"beam-shop: no {sel.DETAIL_SCOPE} block on the product page — "
            "the detail markup changed"
        )

    meta = scope.select_one(sel.DETAIL_PRICE_META)
    content = meta.get("content") if meta else None
    if not isinstance(content, str):
        raise SourceStructureError("beam-shop: product page carries no machine-readable price")
    try:
        # The meta price uses a decimal point, unlike the visible de-DE one.
        price_cents = int(round(float(content) * 100))
    except ValueError as exc:
        raise SourceStructureError(f"beam-shop: unreadable price {content!r}") from exc

    order_input = scope.select_one(sel.DETAIL_ORDER_NUMBER)
    order_number = order_input.get("value") if order_input is not None else None
    isbn = _isbn_from_order_number(order_number if isinstance(order_number, str) else None)

    title_node = scope.select_one(sel.DETAIL_TITLE)
    # Der Autorenlink wird *im Produktblock* gesucht: die Seite haengt weiter
    # unten hundertfach Empfehlungen an, und jede bringt ihren eigenen mit.
    author_node = scope.select_one(sel.DETAIL_AUTHOR)
    author = author_node.get_text(" ", strip=True) if author_node else None

    # Der Klappentext steht ausserhalb des Produktblocks, deshalb ``page``.
    blurb = _description(page)

    # Die kanonische Adresse steht im Kopf der Seite, nicht im Produktblock.
    canonical = page.select_one(sel.DETAIL_CANONICAL)
    href = canonical.get("href") if canonical is not None else None

    title = title_node.get_text(" ", strip=True) if title_node else None
    sample = page.select_one(sel.DETAIL_SAMPLE)
    sample_href = sample.get("href") if sample is not None else None

    return Detail(
        title=title,
        price_cents=price_cents,
        isbn=isbn,
        cover_url=_detail_cover(scope),
        author=author or None,
        url=canonical_url(href) if isinstance(href, str) and href else None,
        blurb=blurb,
        sample_url=sample_href if isinstance(sample_href, str) and sample_href else None,
        keywords=_keywords(page, leave_out=(author, title)),
        publisher=_fact(page, "Verlag"),
    )


def _fact(page, label: str) -> str | None:
    """Ein Wert aus der Angabenliste der Detailseite, gesucht ueber seine Marke."""
    for eintrag in page.select(sel.DETAIL_FACT):
        marke = eintrag.select_one(sel.DETAIL_FACT_LABEL)
        wert = eintrag.select_one(sel.DETAIL_FACT_VALUE)
        if marke and wert and marke.get_text(strip=True) == label:
            # Vor dem Namen steht ein Symbol als Ligatur ("find_in_page"):
            # Text fuer die Schrift, nicht fuer uns.
            for symbol in wert.select(".material-icons"):
                symbol.decompose()
            return wert.get_text(" ", strip=True) or None
    return None


def _keywords(page, *, leave_out) -> tuple[str, ...]:
    """Die Schlagwoerter aus dem Kopf der Seite (#17).

    Autor und Titel stehen auch darin; die kennt der Bewerter schon, und sie
    als "Schlagwort" noch einmal zu nennen, hiesse ihm Gewicht zu geben.
    """
    meta = page.select_one(sel.DETAIL_KEYWORDS)
    content = meta.get("content") if meta is not None else None
    if not isinstance(content, str):
        return ()
    bekannt = {wort.casefold() for wort in leave_out if wort}
    woerter = (wort.strip() for wort in content.split(","))
    return tuple(dict.fromkeys(w for w in woerter if w and w.casefold() not in bekannt))


def _detail_cover(scope) -> str | None:
    """Das Titelbild der Detailseite.

    Eine Einzelausgabe traegt es mit ``srcset``; das ``src`` daneben ist ein
    Platzhalterpixel, deshalb zuerst das. Eine Paketseite zeigt dagegen die
    Bilder ihrer Baende mit schlichtem ``src`` und ohne ``srcset`` — der
    *Wayward Pines-Trilogie* fehlte deshalb das Bild, obwohl drei auf der Seite
    standen. Dann gilt das erste: es ist der erste Band.
    """
    gefunden = _cover_from(scope.select_one(sel.DETAIL_IMAGE))
    if gefunden:
        return gefunden
    for bild in scope.select(sel.DETAIL_IMAGE_PLAIN):
        adresse = bild.get("src")
        if isinstance(adresse, str) and adresse.startswith("http"):
            return adresse
    return None


def _description(page) -> str | None:
    """Der Klappentext einmal, nicht zweimal (Ticket 40).

    Unter ``[itemprop=description]`` haengen zwei Kinder — der sichtbare
    Anriss und der eingeklappte volle Text. Der Browser zeigt immer nur eins
    davon; ``get_text()`` ueber den Elternknoten nahm beides und schrieb den
    Anfang doppelt in die Datenbank. Gemessen: 110 der 116 langen
    Klappentexte, im Median ein Drittel Ballast, 71.313 Zeichen insgesamt —
    und die gehen in jeden Bewertungs-Prompt.

    Gegriffen wird deshalb der **Knoten**, nicht der Text: ein Klassenname im
    Seitengeruest aendert sich seltener als ein deutsches Wort auf einem
    Knopf, und wenn doch, bricht er zusammen mit allen anderen Selektoren.
    Kurze Klappentexte haben kein ``--full`` — dort bleibt der Anriss, und er
    *ist* der ganze Text (kein einziger der 1911 kurzen traegt den Knopf).
    """
    node = page.select_one(sel.DETAIL_DESCRIPTION)
    if node is None:
        return None
    # Der erste Knoten, der auch wirklich etwas traegt. Nur auf "ist da" zu
    # pruefen reichte nicht: ein leerer ``--full``-Knoten haette den
    # Klappentext ganz verschluckt — und ein Buch ohne Klappentext wird von
    # ``_with_evidence`` bei **jedem** Lauf erneut geholt.
    kandidaten = (
        node.select_one(sel.DETAIL_DESCRIPTION_FULL),
        node.select_one(sel.DETAIL_DESCRIPTION_PREVIEW),
        node,
    )
    texte = (kandidat.get_text(" ", strip=True) for kandidat in kandidaten if kandidat is not None)
    gewaehlt = next((text for text in texte if text), "")
    # ``without_teaser`` faengt den Fall ab, dass der Shop die Klassen
    # umbenennt: dann steht wieder beides im Text, und der Schnitt am Knopf
    # ist zwar die schwaechere, aber immer noch verlustfreie Regel.
    return without_teaser(gewaehlt) or None


def total_pages(html: str) -> int | None:
    """``data-pages`` on the listing — how far ``?p=`` can usefully go."""
    listing = soup(html).select_one(sel.LISTING)
    if listing is None:
        return None
    value = listing.get(sel.ATTR_PAGES)
    return int(value) if isinstance(value, str) and value.isdigit() else None
