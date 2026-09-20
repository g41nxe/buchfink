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

from urllib.parse import urljoin

from ...config import WatchlistEntry
from ...http import HttpClient, NotFound
from ...matching import Candidate, Confidence, Query, Resolution, match
from ...models import MatchReason, Observation
from ..base import LibrarySource, SourceStructureError
from . import parse
from . import selectors as sel

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
    kennung = title_id_from_url(url)
    if kennung is None:
        raise SourceStructureError(
            f"OverDrive: aus {url!r} laesst sich keine Titelnummer lesen — erwartet /media/<nummer>"
        )
    return kennung


class OverdriveSource(LibrarySource):
    name = SOURCE_NAME

    def __init__(
        self,
        client: HttpClient,
        name: str = SOURCE_NAME,
        base: str = sel.BASE,
        library: str = sel.LIBRARY,
    ) -> None:
        self.client = client
        self.name = name
        self.base = base
        self.library = library

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

        kennung = require_title_id(link)
        try:
            text = self.client.get(self._url(sel.TITLE_PATH, title_id=kennung))
        except NotFound:
            # Der Titel hat den Katalog verlassen. Das ist eine Nachricht ueber
            # diesen einen Eintrag, keine kaputte Quelle — die uebrigen werden
            # weiter geprueft.
            return None
        detail = parse.parse_title(parse.payload(text))

        return Observation(
            source=self.name,
            source_item_id=kennung,
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
            url=sel.TITLE_URL.format(title_id=kennung),
        )

    # --- Zuordnung (ADR 9) -------------------------------------------------

    def _url(self, path: str, **kwargs: str) -> str:
        return urljoin(self.base, path.format(library=self.library, **kwargs))

    def _search_page(self, query: str, page: int) -> str:
        params = dict(sel.SEARCH_PARAMS, query=query, perPage=str(sel.PER_PAGE))
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
        nachname = entry.author.split(",")[0].strip() if "," in entry.author else None
        nachname = nachname or entry.author.split()[-1]
        return f"{entry.title} {nachname}"

    def resolve(self, entry: WatchlistEntry) -> Resolution | None:
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
        gesehen: list[Candidate] = []

        for page in range(MAX_RESOLUTION_PAGES):
            gefunden = parse.parse_search(self._search_page(self._query_for(entry), page))
            if gefunden is None:
                # Kein Treffer — eine Antwort, keine Stoerung.
                return None if page == 0 else match(query, gesehen)

            gesehen.extend(
                Candidate(
                    title=card.title,
                    author=card.author,
                    identifier=card.isbn,
                    cover_url=card.cover_url,
                    payload=sel.TITLE_URL.format(title_id=card.title_id),
                )
                for card in gefunden
            )
            resolution = match(query, gesehen)
            if resolution.confidence is Confidence.AUTO_ACCEPT or len(gefunden) < sel.PER_PAGE:
                return resolution

        return match(query, gesehen)

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
