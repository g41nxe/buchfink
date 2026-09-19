"""The beam-shop Shop Source.

Shopware's search is deliberately fuzzy — a query for "Redshirts" happily
returns an Amazon Redshift cookbook — so ranking is never trusted and every
tile is re-matched before anything is pinned.
"""

from __future__ import annotations

from urllib.parse import urljoin

from ...config import WatchlistEntry
from ...http import HttpClient, NotFound
from ...matching import Candidate, Query, Resolution, author_matches, match
from ...models import MatchReason, Observation
from ..base import Item, ShopSource, SourceStructureError
from . import parse
from . import selectors as sel

SOURCE_NAME = "beam"

#: A prolific author fills two or three pages of 100; past that it is
#: back-catalogue we have already seen.
MAX_AUTHOR_PAGES = 3

#: Sorted by release date, the front of a shelf is all that can be new. Going
#: deeper only re-reads the back-catalogue.
MAX_CATEGORY_PAGES = 1

#: Shopware transliterates umlauts rather than stripping them.
_SLUG_FOLDS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def author_slug(author: str) -> str:
    """``"John Scalzi"`` → ``"john-scalzi"``.

    Periods survive (``j.r.r.-tolkien``) and the name stays in given-name-first
    order, which is how the shop builds these URLs.
    """
    name = author.strip()
    if "," in name:
        surname, _, given = name.partition(",")
        name = f"{given.strip()} {surname.strip()}".strip()
    name = name.casefold()
    for source, target in _SLUG_FOLDS.items():
        name = name.replace(source, target)
    return "-".join(name.split())


class BeamSource(ShopSource):
    name = SOURCE_NAME

    def __init__(self, client: HttpClient, name: str = SOURCE_NAME, base: str = sel.BASE) -> None:
        self.client = client
        self.name = name
        self.base = base

    # --- fetching ----------------------------------------------------------

    def search(
        self, query: str, page_size: int = sel.SEARCH_PAGE_SIZE, page: int | None = None
    ) -> list[parse.Tile]:
        """Search results as tiles. Short queries are refused before the request:
        Shopware silently returns nothing for fewer than four characters."""
        if len(query.strip()) < sel.MIN_QUERY_LENGTH:
            return []
        params = {"sSearch": query, "n": str(min(page_size, sel.MAX_PAGE_SIZE))}
        if page is not None:
            params["p"] = str(page)
        return parse.parse_tiles(
            self.client.get(urljoin(self.base, sel.SEARCH_PATH), params=params), self.base
        )

    # --- resolution --------------------------------------------------------

    def resolve(self, entry: WatchlistEntry) -> Resolution | None:
        query = " ".join(part for part in (entry.title, entry.author) if part)
        tiles = self.search(query)
        if not tiles:
            return None

        # Die ISBN steht in jeder Bestellnummer und kostet nichts extra. Sie
        # loest keinen offenen Titel — sie entsteht erst aus einer gelungenen
        # Zuordnung —, aber sie deckt Widersprueche auf: zwei verschiedene
        # ISBNs heisst zwei verschiedene Buecher (Ticket 36).
        resolution = match(
            Query(title=entry.title, author=entry.author, identifier=entry.isbn),
            [
                Candidate(
                    title=tile.title,
                    author=tile.author,
                    identifier=tile.isbn,
                    cover_url=tile.cover_url,
                    payload=tile.url,
                )
                for tile in tiles
            ],
        )
        return resolution

    # --- author discovery (ticket 06) --------------------------------------

    def _author_hub(self, author: str) -> list[parse.Tile] | None:
        """The shop keeps hand-curated pages for about thirty authors.

        Where one exists it is authoritative — every tile on it is that author.
        Everyone else 404s, which is the signal to fall back to search.
        """
        path = sel.AUTHOR_HUB_PATH.format(slug=author_slug(author))
        tiles: list[parse.Tile] = []
        for page in range(1, MAX_AUTHOR_PAGES + 1):
            params = {"n": str(sel.MAX_PAGE_SIZE)}
            if page > 1:
                params["p"] = str(page)
            try:
                html = self.client.get(urljoin(self.base, path), params=params)
            except NotFound:
                return None if page == 1 else tiles
            found = parse.parse_tiles(html, self.base)
            tiles.extend(found)
            if len(found) < sel.MAX_PAGE_SIZE:
                break
        return tiles

    def _author_search(self, author: str) -> list[parse.Tile]:
        """Search and keep only what is really by this author.

        Shopware's fuzzy search answers "Scalzi" with Scali, Scalzo and
        H. Beam Piper, so half the tiles get discarded here.
        """
        tiles: list[parse.Tile] = []
        for page in range(1, MAX_AUTHOR_PAGES + 1):
            found = self.search(author, page_size=sel.MAX_PAGE_SIZE, page=page)
            tiles.extend(found)
            if len(found) < sel.MAX_PAGE_SIZE:
                break
        return [tile for tile in tiles if author_matches(author, tile.author)]

    def by_author(self, author: str) -> list[Observation]:
        tiles = self._author_hub(author)
        if tiles is None:
            tiles = self._author_search(author)

        seen: set[str] = set()
        observations = []
        for tile in tiles:
            if tile.product_id in seen:
                continue
            seen.add(tile.product_id)
            observations.append(
                Observation(
                    source=self.name,
                    source_item_id=tile.product_id,
                    title=tile.title,
                    author=tile.author,
                    match_reason=MatchReason.PROFILE_AUTHOR,
                    price_cents=tile.price_cents,
                    original_price_cents=None,
                    blurb=tile.blurb,
                    subtitle=tile.subtitle,
                    isbn=tile.isbn,
                    cover_url=tile.cover_url,
                    url=tile.url,
                )
            )
        return observations

    # --- genre discovery (ticket 07) ---------------------------------------

    def by_category(self, category_path: str) -> list[Observation]:
        """New arrivals on one of the shop's own shelves.

        v1 trusts the shop's shelving rather than classifying anything: sort the
        category by release date and read the front of it (ADR 11). What counts
        as *new* is decided later, by the diff against past Observations.
        """
        path = category_path.strip("/") + "/"
        seen: set[str] = set()
        observations: list[Observation] = []

        for page in range(1, MAX_CATEGORY_PAGES + 1):
            params = {"o": sel.SORT_BY_RELEASE_DATE, "n": str(sel.MAX_PAGE_SIZE)}
            if page > 1:
                params["p"] = str(page)
            tiles = parse.parse_tiles(
                self.client.get(urljoin(self.base, path), params=params), self.base
            )
            for tile in tiles:
                if tile.product_id in seen:
                    continue
                seen.add(tile.product_id)
                observations.append(
                    Observation(
                        source=self.name,
                        source_item_id=tile.product_id,
                        title=tile.title,
                        author=tile.author,
                        match_reason=MatchReason.GENRE_CATEGORY,
                        price_cents=tile.price_cents,
                        original_price_cents=None,
                        blurb=tile.blurb,
                        subtitle=tile.subtitle,
                        isbn=tile.isbn,
                        cover_url=tile.cover_url,
                        category=category_path,
                        url=tile.url,
                    )
                )
            if len(tiles) < sel.MAX_PAGE_SIZE:
                break
        return observations

    # --- observation -------------------------------------------------------

    def check(self, entry: WatchlistEntry) -> Observation | None:
        link = entry.resolved_links.get(self.name)
        if not link:
            return None

        url = parse.canonical_url(link, self.base)
        try:
            detail = parse.parse_detail(self.client.get(url))
        except NotFound:
            # Delisted. One title going away must not blind the rest.
            return None

        return Observation(
            source=self.name,
            source_item_id=_product_id_from_url(url),
            title=detail.title or entry.title,
            author=entry.author,
            isbn=detail.isbn,
            cover_url=detail.cover_url,
            # Der Klappentext kommt mit — aber er landet nicht in der
            # Beobachtung: ``Store.append`` legt ihn an der ``book``-Zeile ab
            # und laesst die Spalte der Beobachtung leer. Damit steht er
            # einmal statt taeglich neu, und die Buchseite hat ihn (Ticket 52).
            #
            # Bis dahin wurde er hier verworfen, mit der Begruendung, niemand
            # lese ihn. Das stimmte, solange es die Stelle nicht gab.
            blurb=detail.blurb,
            match_reason=MatchReason.WATCHLIST,
            watchlist_key=entry.key,
            price_cents=detail.price_cents,
            # Fixed-book-price law: this shop never renders a struck price, so
            # the Deal tier can only ever fire on an observed drop (ADR 5).
            original_price_cents=None,
            url=url,
        )

    def item(self, source_item_id: str) -> Item | None:
        """The product page behind a bare product number (Ticket 17).

        One request, no search: the number is exact, so there is nothing to
        match and nothing to be unsure about. A number the shop has delisted
        answers 404, and that is an answer worth reporting rather than a
        failure.
        """
        url = urljoin(self.base, sel.DETAIL_PATH.format(product_id=source_item_id))
        try:
            detail = parse.parse_detail(self.client.get(url))
        except NotFound:
            return None
        if not detail.title:
            return None
        return Item(
            source_item_id=source_item_id,
            title=detail.title,
            author=detail.author,
            isbn=detail.isbn,
            # Die sprechende Adresse, die die Seite selbst nennt — die
            # Nummernadresse ist nur der Weg dorthin und gehoert nicht in die
            # Datenbank, wo sie spaeter jemand als Link zu lesen bekommt.
            url=detail.url or url,
            blurb=detail.blurb,
            cover_url=detail.cover_url,
            sample_url=detail.sample_url,
            keywords=detail.keywords,
            publisher=detail.publisher,
        )

    def probe(self) -> None:
        tiles = self.search(sel.PROBE_QUERY)
        if not tiles:
            raise SourceStructureError(
                f"beam-shop: the probe query {sel.PROBE_QUERY!r} returned no parseable tiles"
            )
        if all(tile.price_cents is None for tile in tiles):
            raise SourceStructureError("beam-shop: no tile carried a parseable price")


def _product_id_from_url(url: str) -> str:
    """``…/606983/krieg-der-klone`` → ``606983``. The Snapshot is keyed on it."""
    parts = [part for part in url.split("?")[0].split("/") if part]
    for part in reversed(parts):
        if part.isdigit():
            return part
    raise SourceStructureError(f"beam-shop: no product id in {url!r}")
