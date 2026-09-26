"""Die OverDrive-Bibliothek — der VÖBB betreibt sie unter voebb.overdrive.com.

Zwei Plattformen, zwei Bestaende: was die Onleihe nicht fuehrt, steht hier
mitunter sehr wohl, und umgekehrt. "Dark Matter" von Blake Crouch war der Fall,
an dem das auffiel — bei der Onleihe nicht im Katalog, hier als "Der
Zeitenläufer (Dark Matter)" mit acht Vormerkungen.

Wie die Onleihe vollstaendig ohne Anmeldung: Lizenzzahlen und Warteschlangen
sind oeffentlich. Die eigenen Ausleihen haengen hinter einem OIDC-Anmeldeweg
und bleiben v2 (ADR 6).

**Sparsam.** Geholt wird nur, was auf der Watchlist steht, und je Titel einmal
am Tag — das ist weniger Last als ein einziger Seitenaufruf im Browser, der
dieselben Daten plus Skripte und Bilder zieht. Der User-Agent nennt eine
Kontaktadresse, und bei 429 haelt der HttpClient hart an.
"""

from __future__ import annotations

import sys
from urllib.parse import urljoin

from ...config import WatchlistEntry
from ...http import HttpClient, NotFound, RateLimited
from ...matching import Candidate, Confidence, Query, Resolution, author_matches, match
from ...models import MatchReason, Observation
from ..base import LibrarySource, SourceStructureError
from . import parse
from . import selectors as sel
from .parse import Collection

__all__ = ["Collection", "OverdriveSource", "require_title_id", "title_id_from_url"]

SOURCE_NAME = "overdrive"

#: Tiefer als zwei Seiten sucht keine Zuordnung. Wer auf Seite drei steht, ist
#: nicht der gemeinte Titel (dieselbe Grenze wie bei der Onleihe).
MAX_RESOLUTION_PAGES = 2


def title_id_from_url(url: str) -> str | None:
    """Die Nummer aus ``…/media/3222096`` — unser ``source_item_id``."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail.isdigit() else None


def require_title_id(url: str) -> str:
    """Der Snapshot ist darauf geschluesselt, also darf nichts durchrutschen,
    dessen Identitaet wir nur raten koennten."""
    item_id = title_id_from_url(url)
    if item_id is None:
        raise SourceStructureError(
            f"OverDrive: aus {url!r} laesst sich keine Titelnummer lesen — erwartet /media/<nummer>"
        )
    return item_id


class OverdriveSource(LibrarySource):
    name = SOURCE_NAME

    def __init__(
        self,
        client: HttpClient,
        name: str = SOURCE_NAME,
        base: str = sel.BASE,
        library: str = sel.LIBRARY,
        collections: tuple[Collection, ...] = (),
    ) -> None:
        self.client = client
        self.name = name
        self.base = base
        self.library = library
        #: Sammlungen, aus denen Vorschläge kommen (#74), etwa „Lucky Day".
        self.collections = tuple(collections)

    # --- Vorschläge (#74) --------------------------------------------------

    def _finds(self, params: dict, reason: MatchReason, category: str | None = None):
        query = dict(sel.SEARCH_PARAMS, perPage=str(sel.PER_PAGE), **sel.LANGUAGE_PARAMS,
                     **sel.AVAILABLE_ONLY, **params)
        text = self.client.get(self._url(sel.SEARCH_PATH), params=query)
        return parse.parse_finds(
            parse.payload(text), source=self.name, reason=reason, category=category
        )

    def by_author(self, author: str) -> list[Observation]:
        """Was die Bibliothek jetzt von dieser Autorin verleihen kann — nur, wo sie
        wirklich die Autorin ist (die Suche findet auch Nennungen im Text)."""
        return [
            fund
            for fund in self._finds({"query": author}, MatchReason.PROFILE_AUTHOR)
            if author_matches(author, fund.author)
        ]

    def by_category(self, category_path: str) -> list[Observation]:
        """Die Neuzugänge zu einem Thema der Leserin, frei und auf Deutsch."""
        slug = category_path.strip("/").rsplit("/", 1)[-1]
        subject = next((sid for word, sid in sel.GENRE_SUBJECTS if word in slug), None)
        if subject is None:
            return []
        return self._finds(
            {"subject": subject, **sel.NEWLY_ADDED}, MatchReason.GENRE_CATEGORY, category_path
        )

    def extra_discoveries(self) -> list[Observation]:
        """Die Titel der Sammlungen, etwa „Lucky Day". Eine Sammlung, die die
        Bibliothek zurückzieht, kostet nur sich (Review)."""
        found: list[Observation] = []
        for collection in self.collections:
            try:
                text = self.client.get(self._url(sel.COLLECTION_PATH, collection=collection.id))
                found += parse.parse_collection(
                    parse.payload(text), collection, source=self.name
                )
            except RateLimited:
                raise
            except Exception as exc:  # noqa: BLE001 - eine Sammlung, nicht die Bibliothek
                print(f"{self.name}: Sammlung {collection.name} übersprungen: "
                      f"{type(exc).__name__}", file=sys.stderr)
        return found

    # --- Pruefung ----------------------------------------------------------

    def check(self, entry: WatchlistEntry) -> Observation | None:
        """Verfuegbarkeit fuer einen Eintrag, dessen Titel schon zugeordnet ist.

        Ein nicht zugeordneter Eintrag wird hier uebersprungen; Titel und
        Autor:in auf eine Nummer abzubilden ist Sache von :meth:`resolve`
        (ADR 9).
        """
        link = entry.resolved_links.get(self.name)
        if not link:
            return None

        item_id = require_title_id(link)
        try:
            text = self.client.get(self._url(sel.TITLE_PATH, title_id=item_id))
        except NotFound:
            # Der Titel hat den Katalog verlassen. Das ist eine Nachricht ueber
            # diesen einen Eintrag, keine kaputte Quelle — die uebrigen werden
            # weiter geprueft.
            return None
        detail = parse.parse_title(parse.payload(text))

        return Observation(
            source=self.name,
            source_item_id=item_id,
            # Der Titel, wie *OverDrive* ihn nennt, nicht der von der Watchlist:
            # eine falsche Zuordnung muss im Tagesbericht sichtbar werden
            # (ADR 9). Hier ist das keine Feinheit — die deutsche Ausgabe heisst
            # "Der Zeitenläufer (Dark Matter)".
            title=detail.title,
            author=detail.author or entry.author,
            match_reason=MatchReason.WATCHLIST,
            watchlist_key=entry.key,
            isbn=detail.isbn,
            availability=detail.availability,
            reservation_count=detail.holds,
            cover_url=detail.cover_url,
            blurb=detail.blurb,
            url=sel.TITLE_URL.format(title_id=item_id),
        )

    # --- Zuordnung (ADR 9) -------------------------------------------------

    def _url(self, path: str, **kwargs: str) -> str:
        return urljoin(self.base, path.format(library=self.library, **kwargs))

    def _search_page(self, query: str, page: int, *, any_language: bool = False) -> str:
        params = dict(sel.SEARCH_PARAMS, query=query, perPage=str(sel.PER_PAGE))
        if not any_language:
            params.update(sel.LANGUAGE_PARAMS)
        if page:
            # Seiten sind 1-basiert; ``page=1`` ist die Voreinstellung und wird
            # deshalb gar nicht erst mitgeschickt.
            params["page"] = str(page + 1)
        return self.client.get(self._url(sel.SEARCH_PATH), params=params)

    def _query_for(self, entry: WatchlistEntry) -> str:
        """Ein Feld traegt beides, wie bei der Onleihe.

        Nur der Nachname: OverDrive rankt ueber Titel, Personen und Klappentext
        auf einen Relevanzwert, und ein Vorname bringt dabei mehr Rauschen als
        Trennschaerfe.
        """
        if not entry.author:
            return entry.title
        surname = entry.author.split(",")[0].strip() if "," in entry.author else None
        surname = surname or entry.author.split()[-1]
        return f"{entry.title} {surname}"

    def resolve(self, entry: WatchlistEntry) -> Resolution | None:
        return self._resolve(entry, any_language=False)

    def resolve_in_any_language(self, entry: WatchlistEntry) -> Resolution | None:
        """Dieselbe Suche ohne ``language=de`` (#77).

        *Scythe* fuehrt diese Bibliothek als englisches E-Book, "1 von 3
        Exemplaren verfuegbar" — und die deutsche Suche konnte es nie sehen.
        Das Format bleibt: ein Hoerbuch ist auch in jeder Sprache kein E-Book.
        """
        return self._resolve(entry, any_language=True)

    def _resolve(self, entry: WatchlistEntry, *, any_language: bool) -> Resolution | None:
        # ``identifier``: der Matcher nimmt eine uebereinstimmende Kennung als
        # Zuordnung ("Kennung stimmt ueberein") — dieselbe Mechanik, mit der
        # beam dieses Buch findet. Hier traegt sie die Quelle: der deutsche
        # Titel bei OverDrive heisst "Der Zeitenläufer (Dark Matter)", und der
        # Titel-Normalisierer streicht die Klammer als Ausgabenrauschen. Uebrig
        # bleiben "dark matter" und "zeitenlaufer" — Wert 26, kein Treffer.
        #
        # Dreizehn der fuenfzehn beobachteten Buecher tragen eine ISBN, und alle
        # dreizehn sind bei der Onleihe *nicht* zugeordnet: die Kennung kommt
        # vom Shop, nicht aus einer Bibliothekszuordnung. Sie kostet nichts —
        # sie steht in derselben Antwort, die wir ohnehin holen.
        query = Query(title=entry.title, author=entry.author, identifier=entry.isbn)
        seen: list[Candidate] = []

        for page in range(MAX_RESOLUTION_PAGES):
            found = parse.parse_search(
                self._search_page(self._query_for(entry), page, any_language=any_language)
            )
            if found is None:
                # Kein Treffer — eine Antwort, keine Stoerung.
                return None if page == 0 else match(query, seen)

            seen.extend(
                Candidate(
                    title=card.title,
                    author=card.author,
                    identifier=card.isbn,
                    cover_url=card.cover_url,
                    language=card.language,
                    payload=sel.TITLE_URL.format(title_id=card.title_id),
                )
                for card in found
            )
            resolution = match(query, seen)
            if resolution.confidence is Confidence.AUTO_ACCEPT or len(found) < sel.PER_PAGE:
                return resolution

        return match(query, seen)

    # --- Selbsttest --------------------------------------------------------

    def probe(self) -> None:
        """Bekannte Antworten muessen weiter lesbar sein. Werte duerfen sich aendern."""
        parse.parse_title(
            parse.payload(self.client.get(self._url(sel.TITLE_PATH, title_id=sel.PROBE_TITLE_ID)))
        )
        if not parse.parse_search(self._search_page(sel.PROBE_QUERY, 0)):
            raise SourceStructureError(
                f"OverDrive: die Probeabfrage {sel.PROBE_QUERY!r} lieferte keine lesbaren Treffer"
            )
