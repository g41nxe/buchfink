"""The Onleihe Library Source — the VÖBB runs it at voebb.onleihe.de.

v1 is entirely login-free: copy counts and queue lengths are public. Personal
holds need an authenticated scrape and are deferred to v2 (ADR 6).
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urljoin

from ...config import Settings, WatchlistEntry
from ...http import HttpClient, NotFound
from ...matching import Candidate, Confidence, Query, Resolution, match
from ...models import MatchReason, Observation
from ..base import Item, LibrarySource, RunContext, SourceStructureError
from . import parse
from . import selectors as sel
from .parse import OnleiheList

SOURCE_NAME = "onleihe"

#: Results paginate 20 to a page; resolution never needs to go deep.
CARDS_PER_PAGE = 20
MAX_RESOLUTION_PAGES = 2


def title_id_from_url(url: str) -> str | None:
    """The stable id inside ``mediaInfo,0-0-<ID>-200-…`` — our ``source_item_id``."""
    tail = url.rsplit("/", 1)[-1]
    if not tail.startswith("mediaInfo,"):
        return None
    parts = tail.split(",", 1)[1].split("-")
    return parts[2] if len(parts) > 2 and parts[2].isdigit() else None


def require_title_id(url: str) -> str:
    """The Snapshot is keyed on this, so a URL we cannot key must not slip through
    under a made-up identity — that would silently split one title's history."""
    title_id = title_id_from_url(url)
    if title_id is None:
        raise SourceStructureError(
            f"Onleihe: cannot read a title id out of {url!r} — expected a mediaInfo path"
        )
    return title_id


class OnleiheSource(LibrarySource):
    name = SOURCE_NAME

    def __init__(
        self,
        client: HttpClient,
        name: str = SOURCE_NAME,
        base: str = sel.BASE,
        media: Sequence[str] = sel.DEFAULT_MEDIA,
        lists: Sequence[OnleiheList] = (),
    ) -> None:
        self.client = client
        self.name = name
        self.base = base
        self.media = tuple(media)
        #: Listen, aus denen Vorschläge kommen (#74), etwa „zuletzt zurückgegeben".
        self.lists = tuple(lists)

    def collect(
        self, settings: Settings, watchlist: Sequence[WatchlistEntry], context: RunContext
    ) -> list[Observation]:
        """Die Watchlist wie jede Bibliothek, dazu die erste Seite jeder Liste.

        Eine Anfrage je Liste und Lauf: die Onleihe hat ein eigenes Tempolimit.
        Was die Watchlist schon abdeckt oder verworfen ist, kommt nicht noch
        einmal — dieselbe Regel wie beim Shop.
        """
        observations = self.watch(watchlist, context)
        seen = {o.source_item_id for o in observations}
        for onleihe_list in self.lists:
            html = self.client.get(urljoin(self.base, onleihe_list.path))
            for found_item in parse.parse_list(
                html, onleihe_list, media=self.media, base=self.base, source=self.name
            ):
                if found_item.source_item_id in seen or context.is_dismissed(found_item):
                    continue
                seen.add(found_item.source_item_id)
                observations.append(found_item)
        return observations

    def check(self, entry: WatchlistEntry) -> Observation | None:
        """Availability for an entry whose detail page is already pinned.

        An unpinned entry is skipped here; resolving title+author to a detail
        page is ticket 04's job (ADR 9).
        """
        link = entry.resolved_links.get(self.name)
        if not link:
            return None

        url = urljoin(self.base, link)
        try:
            html = self.client.get(url)
        except NotFound:
            # The title left the catalogue. That is news about one entry, not a
            # broken Source — the other entries must still be checked.
            return None
        detail = parse.parse_detail(html)

        return Observation(
            source=self.name,
            source_item_id=require_title_id(url),
            # The *scraped* title, not the watchlist one — a wrong auto-resolve
            # has to be visible in the Digest (ADR 9).
            title=detail.title or entry.title,
            author=detail.author or entry.author,
            match_reason=MatchReason.WATCHLIST,
            watchlist_key=entry.key,
            series=detail.series,
            isbn=detail.isbn,
            availability=detail.availability,
            reservation_count=detail.reservations,
            available_from=detail.available_from,
            cover_url=detail.cover_url,
            blurb=detail.blurb,
            rating=detail.rating,
            rating_votes=detail.votes,
            url=url,
        )

    # --- resolution (ADR 9) ------------------------------------------------

    def _search_page(self, query: str, page: int) -> str:
        params = dict(sel.SEARCH_PARAMS, pText=query)
        path = sel.SEARCH_PATH if page == 0 else sel.SEARCH_PAGE_PATH.format(page=page)
        # The paged path needs the query re-supplied, otherwise the Onleihe
        # wants a session cookie and answers "Ihre Sitzung ist abgelaufen".
        return self.client.get(urljoin(self.base, path), params=params)

    def _query_for(self, entry: WatchlistEntry) -> str:
        """One free-text box has to carry both fields.

        Only the surname goes in: the Onleihe ranks on a single relevance score
        across title, author and blurb, and a full given name mostly adds noise.
        """
        if not entry.author:
            return entry.title
        surname = entry.author.split(",")[0].strip() if "," in entry.author else None
        surname = surname or entry.author.split()[-1]
        return f"{entry.title} {surname}"

    def _preferred(self, found: list[parse.Candidate]) -> list[parse.Candidate]:
        """Keep only the formats we want — but never filter everything away."""
        if not self.media:
            return found
        wanted = [card for card in found if card.medium in self.media]
        return wanted or found

    def resolve(self, entry: WatchlistEntry) -> Resolution | None:
        query = Query(title=entry.title, author=entry.author)
        seen: list[Candidate] = []

        for page in range(MAX_RESOLUTION_PAGES):
            found = parse.parse_search_results(self._search_page(self._query_for(entry), page))
            if found is None:
                # "keine Titeltreffer" — an answer, not a malfunction.
                return None if page == 0 else match(query, seen)

            seen.extend(
                Candidate(
                    title=card.title,
                    author=card.author,
                    cover_url=card.cover_url,
                    payload=card.url,
                )
                for card in self._preferred(found)
            )
            resolution = match(query, seen)
            if resolution.confidence is Confidence.AUTO_ACCEPT or len(found) < CARDS_PER_PAGE:
                return resolution

        return match(query, seen)

    def item(self, source_item_id: str) -> Item | None:
        """Die Detailseite hinter einer Kennung — fuer Klappentext und Leseprobe (#17)."""
        url = urljoin(self.base, sel.DETAIL_PATH.format(title_id=source_item_id))
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
            url=url,
            blurb=detail.blurb,
            cover_url=detail.cover_url,
            sample_url=detail.sample_url,
            publisher=detail.publisher,
        )

    def probe(self) -> None:
        """Known-good pages must still parse. Values are free to change."""
        parse.parse_detail(self.client.get(urljoin(self.base, sel.PROBE_DETAIL_PATH)))
        candidates = parse.parse_search_results(self._search_page(sel.PROBE_QUERY, 0))
        if not candidates:
            raise SourceStructureError(
                f"Onleihe: the probe query {sel.PROBE_QUERY!r} returned no parseable hits"
            )
