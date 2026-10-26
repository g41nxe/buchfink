"""Bücher, DNB, Reihen, Werke und Kategorien — was es an Büchern gibt (#103)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime

from sqlalchemy import (
    case,
    delete,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..catalog.books import BookLike
from ..catalog.books import find as find_book
from ..catalog.series import SeriesOf, series_key, volume_span
from ..cleaning import author_key
from ..dnb import Record
from ..matching.bundles import looks_like_bundle, volume_titles
from ..matching.normalize import normalize_title
from ..models import LINK_OUTCOMES, Observation
from ..relations import RelationKind
from .observations import ObservationsMixin
from .rows import (
    BISAC_ORIGINS,
    DNB_READING,
    SERIES_ORIGINS,
    BisacEntryRow,
    BookRelationRow,
    BookRow,
    BookSourceRow,
    DnbContainsRow,
    DnbRecordRow,
    ObservationRow,
    SeriesEntry,
    SeriesEntryRow,
    SeriesNameRow,
    SeriesRow,
    SeriesWatchRow,
    SourceCategoryRow,
    WorkEntryRow,
    _better_spelling,
    _file_bisac,
    _file_series,
    _file_work,
    _work_book_subjects,
    _work_siblings,
)


class CatalogMixin(ObservationsMixin):
    """Bücher, DNB, Reihen, Werke und Kategorien — was es an Büchern gibt (#103)."""

    # --- was die DNB weiss (Ticket 42) -------------------------------------

    def isbns_without_dnb(self, profile_slug: str, limit: int) -> list[str]:
        """ISBNs, die wir gesehen, aber noch nie bei der DNB nachgeschlagen haben.

        Nach ISBN und nicht nach Buch: eine ``book``-Zeile entsteht erst durch
        eine Entscheidung, und ausgerechnet die Sammelausgabe, für die das
        gebaut wurde, ist ein blosser Fund.

        ``limit`` ist die Hoeflichkeit: die DNB dokumentiert keine zulaessige
        Anfragefrequenz, also wird der Rueckstand ueber mehrere Laeufe
        abgearbeitet statt an einem Tag.

        **Die ISBNs der eigenen Buecher zuerst**, dann die zuletzt gesehenen
        Funde. Vorher galt nur "zuletzt gesehen" — und jeder Lauf sieht
        Hunderte neuer Funde *nach* den Watchlist-Titeln. Die Buecher wurden
        so bei jedem Lauf wieder verdraengt: 34 mit ISBN, einer davon mit
        Datensatz (#10). Es sind wenige; der Vorrang kostet einmalig einen
        Lauf, danach geht das Budget wieder an die Funde.
        """
        with self.session() as session:
            # Ein Nein bleibt ein Nein; ein Ja, das ein aelterer Parser las,
            # wird einmal neu gefragt (#17).
            already = select(DnbRecordRow.isbn).where(
                or_(DnbRecordRow.found.is_(False), DnbRecordRow.reading >= DNB_READING)
            )
            own_isbns = select(BookRow.isbn).where(BookRow.isbn.is_not(None))
            books_first = case((ObservationRow.isbn.in_(own_isbns), 0), else_=1)
            stmt = (
                select(ObservationRow.isbn)
                .where(
                    ObservationRow.profile_slug == profile_slug,
                    ObservationRow.isbn.is_not(None),
                    ObservationRow.isbn.not_in(already),
                )
                .group_by(ObservationRow.isbn)
                .order_by(books_first, func.max(ObservationRow.id).desc())
                .limit(limit)
            )
            return [isbn for (isbn,) in session.execute(stmt) if isbn]

    def save_dnb(self, isbn: str, record, now: datetime) -> None:
        """Die Antwort festhalten — **auch wenn keine kam**.

        ``record is None`` heisst "gefragt, nichts gewusst". Ohne diese Zeile
        fragte jeder Lauf dieselben neun von dreissig erneut.
        """
        with self.session() as session:
            row = session.get(DnbRecordRow, isbn)
            if row is None:
                row = DnbRecordRow(isbn=isbn)
                session.add(row)
            row.checked_at = now
            row.found = record is not None
            if record is not None:
                row.title = record.title
                row.subtitle = record.subtitle
                row.author = record.author
                row.series = record.series
                row.series_index = record.series_index
                row.language = record.language
                row.original_title = record.original_title
                row.keywords = json.dumps(list(record.keywords), ensure_ascii=False)
                row.publisher = record.publisher
                row.pages = record.pages
                if record.series:
                    _file_series(session, isbn, record.series, record.author,
                                 record.series_index, "dnb")
                if record.original_title:
                    _file_work(session, isbn, record.author, record.original_title, "dnb")
                _file_bisac(session, isbn, "dnb", record.bisac)
                for contained in record.contains:
                    if session.get(DnbContainsRow, (isbn, contained)) is None:
                        session.add(DnbContainsRow(isbn=isbn, contained=contained))
            row.reading = DNB_READING
            session.commit()

    def dnb_facts(self, isbns: Iterable[str]) -> dict[str, Record]:
        """ISBN -> was die DNB fuer den `Portrayer` weiss, wo sie etwas davon weiss.

        Originaltitel und Schlagwoerter (#17): was der Verlag selbst an Motiven
        und Vergleichstiteln angibt, steht weder im Titel noch im Klappentext.
        Dazu der Verlag, als Rueckfall fuer den Abzug bei Selbstverlag (#28).
        """
        wanted = [isbn for isbn in isbns if isbn]
        if not wanted:
            return {}
        with self.session() as session:
            rows = session.execute(
                select(
                    DnbRecordRow.isbn,
                    DnbRecordRow.original_title,
                    DnbRecordRow.keywords,
                    DnbRecordRow.publisher,
                ).where(DnbRecordRow.isbn.in_(wanted), DnbRecordRow.found.is_(True))
            )
            facts = {}
            for isbn, original, subjects, publisher in rows:
                words = tuple(json.loads(subjects)) if subjects else ()
                if original or words or publisher:
                    facts[isbn] = Record(
                        original_title=original, keywords=words, publisher=publisher
                    )
            return facts

    def with_known_pages(self, observations: Sequence[Observation]) -> list[Observation]:
        """Die zuletzt bekannte Seitenzahl je Fund nachtragen (#73, #82).

        Die Trefferliste nennt keine Seitenzahl, nur die Detailseite; ohne das
        stünde eine Kurzgeschichte nach einem Tag wieder im Stapel, weil die
        neue Sichtung aus der Liste die ältere mit Seitenzahl überdeckt.

        Die Seitenzahl gehört der ISBN, nicht der Quelle (ADR 34): zuerst der
        Fund selbst, dann eine andere Quelle mit derselben ISBN, zuletzt die
        DNB — deren Angabe gehört manchmal zur gedruckten Ausgabe.
        """
        missing = [o for o in observations if o.pages is None]
        if not missing:
            return list(observations)
        wanted = {(o.source, o.source_item_id) for o in missing}
        isbns = {o.isbn for o in missing if o.isbn}
        with self.session() as session:
            rows = session.execute(
                select(
                    ObservationRow.source,
                    ObservationRow.source_item_id,
                    ObservationRow.isbn,
                    ObservationRow.pages,
                )
                .where(
                    ObservationRow.pages.is_not(None),
                    or_(
                        ObservationRow.source_item_id.in_({item for _, item in wanted}),
                        ObservationRow.isbn.in_(isbns),
                    ),
                )
                .order_by(ObservationRow.id)
            ).all()
            dnb = dict(
                session.execute(
                    select(DnbRecordRow.isbn, DnbRecordRow.pages).where(
                        DnbRecordRow.isbn.in_(isbns), DnbRecordRow.pages.is_not(None)
                    )
                ).all()
            )
        own = {(src, item): pages for src, item, _, pages in rows if (src, item) in wanted}
        by_isbn = {isbn: pages for _, _, isbn, pages in rows if isbn}

        def known(o: Observation) -> int | None:
            return own.get(o.key) or by_isbn.get(o.isbn or "") or dnb.get(o.isbn or "")

        return [replace(o, pages=known(o)) if o.pages is None else o for o in observations]

    def dnb_original_titles(self, isbns: Iterable[str]) -> dict[str, tuple[str, ...]]:
        """ISBN -> die Namen, die die DNB dem Buch gibt: Originaltitel und Titel.

        Fuer die Zuordnung eines Watchlist-Titels (#77). Der Titel gehoert dazu,
        weil nicht jeder Datensatz einer Uebersetzung den Originaltitel fuehrt:
        *Scythe* steht dort als „Scythe – Die Hueter des Todes", ohne Feld fuer
        das Original (gemessen am 26.09.2026). Anders als :meth:`dnb_facts` steht
        auch das Schweigen darin, als leeres Tupel: es ist eine Antwort, und wer
        sie hat, fragt nicht noch einmal. Was fehlt, ist unbekannt. Ein Ja, das
        ein aelterer Parser las, zaehlt als unbekannt — dieselbe Regel wie in
        :meth:`isbns_without_dnb`.
        """
        wanted = [isbn for isbn in isbns if isbn]
        if not wanted:
            return {}
        with self.session() as session:
            rows = session.execute(
                select(
                    DnbRecordRow.isbn,
                    DnbRecordRow.found,
                    DnbRecordRow.original_title,
                    DnbRecordRow.title,
                    DnbRecordRow.series_index,
                ).where(
                    DnbRecordRow.isbn.in_(wanted),
                    or_(DnbRecordRow.found.is_(False), DnbRecordRow.reading >= DNB_READING),
                )
            )
            # Der Titel eines späteren Bandes trägt oft nur die Reihe vorn
            # („Scythe – Der Zorn der Gerechten" ist Band 2): er zählt nur bei
            # Band 1 oder einem Buch ohne Reihe (Review, #77).
            return {
                isbn: tuple(
                    n
                    for n in (original, title if (index or "1").strip() in ("", "1") else None)
                    if n
                )
                if found
                else ()
                for isbn, found, original, title, index in rows
            }

    def _series_entries(
        self, isbns: Iterable[str] | None = None
    ) -> dict[str, tuple[int, str | None]]:
        """ISBN -> (Reihe, Band), nach Herkunft entschieden.

        Die Reihe von der ersten Herkunft, die eine nennt; der Band von der
        ersten, die einen nennt — ein DNB-Satz ohne Band lässt OverDrives Band
        gelten (ADR 35).
        """
        rank = {origin: i for i, origin in enumerate(SERIES_ORIGINS)}
        stmt = select(SeriesEntryRow.isbn, SeriesEntryRow.origin,
                      SeriesEntryRow.series_id, SeriesEntryRow.volume)
        if isbns is not None:
            stmt = stmt.where(SeriesEntryRow.isbn.in_({i for i in isbns if i}))
        with self.session() as session:
            rows = sorted(session.execute(stmt).all(),
                          key=lambda row: rank.get(row[1], len(rank)))
        known: dict[str, tuple[int, str | None]] = {}
        for isbn, _, series_id, volume in rows:
            if isbn not in known:
                known[isbn] = (series_id, volume)
            elif known[isbn][1] is None and volume:
                known[isbn] = (known[isbn][0], volume)
        return known

    def series_entries_of(self, isbn: str) -> list[SeriesEntry]:
        """Jede Zuordnung dieser ISBN mit ihrer Herkunft — was die Rangfolge
        entscheidet, bleibt sichtbar (ADR 35)."""
        with self.session() as session:
            rows = session.scalars(
                select(SeriesEntryRow).where(SeriesEntryRow.isbn == isbn)
                .order_by(SeriesEntryRow.origin)
            )
            return [SeriesEntry(row.isbn, row.origin, row.series_id, row.volume) for row in rows]

    def title_index(self, profile_slug: str) -> dict[tuple[str, str], str]:
        """(Autor:in, Titel) -> ISBN, beide in Vergleichsform, über alle Sichtungen.

        Die Stelle, an der eine Sammelausgabe ihre Bände findet: die Teile ihres
        Namens sind Titel, und ein Titel ist nur ein Band, wenn dieselbe
        Autor:in ihn irgendwo einzeln hat (ADR 24, 38). Die jüngste Sichtung
        gewinnt, damit eine gewechselte ISBN nicht an der alten hängt.
        """
        stmt = (
            select(ObservationRow.isbn, ObservationRow.title, ObservationRow.author)
            .where(ObservationRow.profile_slug == profile_slug,
                   ObservationRow.isbn.is_not(None), ObservationRow.author.is_not(None))
            .order_by(ObservationRow.id)
        )
        with self.session() as session:
            return {
                (author_key(author), normalize_title(title)): isbn
                for isbn, title, author in session.execute(stmt)
                if not looks_like_bundle(title)
            }

    def contained_volumes(
        self, profile_slug: str, isbn: str | None, title: str, author: str | None,
        index: dict[tuple[str, str], str] | None = None,
    ) -> list[tuple[str, str]]:
        """(ISBN, Titel) je Band eines Sammelausgabe — oder leer (ADR 38).

        Die DNB zuerst: nennt sie die enthaltenen ISBNs, ist nichts zu raten.
        Sonst zerfällt der Name an Schrägstrichen, und jeder Teil muss bei
        derselben Autor:in ein Buch sein — ein Teil, der keins ist, macht den
        Namen zu keinem Sammelausgabe (dieselbe Selbstkorrektur wie ADR 24).
        ``index`` kommt mit, wo viele Sammelausgaben nacheinander fragen.
        """
        if isbn:
            from_library = self.contained_isbns(isbn)
            # Zwei oder mehr, wie beim Preisvergleich (ADR 24): ein 770-Satz
            # mit einer ISBN beschreibt keine Sammelausgabe.
            if len(from_library) >= 2:
                titles = self._titles_of(from_library)
                return [(contained, titles.get(contained, contained)) for contained in from_library]
        parts = volume_titles(title)
        if len(parts) < 2 or not author:
            return []
        if index is None:
            index = self.title_index(profile_slug)
        writer = author_key(author)
        found = [(index.get((writer, normalize_title(part))), part) for part in parts]
        if any(found_isbn is None for found_isbn, _ in found):
            return []
        return [(found_isbn, part) for found_isbn, part in found if found_isbn]

    def _titles_of(self, isbns: Iterable[str]) -> dict[str, str]:
        """ISBN -> Titel, aus der jüngsten Sichtung, sonst aus der DNB."""
        isbns = set(isbns)
        with self.session() as session:
            titles = dict(session.execute(
                select(DnbRecordRow.isbn, DnbRecordRow.title).where(
                    DnbRecordRow.isbn.in_(isbns), DnbRecordRow.title.is_not(None))
            ).all())
            for found_isbn, title in session.execute(
                select(ObservationRow.isbn, ObservationRow.title)
                .where(ObservationRow.isbn.in_(isbns)).order_by(ObservationRow.id)
            ):
                titles[found_isbn] = title
        return titles

    def series_from_bundles(self, profile_slug: str) -> int:
        """Jeder Sammelausgabe unter den Funden erbt die Reihe seiner Bände (ADR 38).

        Abgeleitet aus dem, was gespeichert ist, bei jedem Lauf neu und ohne
        Anfrage — wie ``series_from_dnb``. Hängt mindestens ein Band an einer
        Reihe, bekommt die Sammelausgabe eine Zuordnung mit Herkunft ``bundle``
        und dem Band als Spanne („2–3"). Gibt zurück, wie viele neu dazukamen
        oder sich änderten.
        """
        bundles = [
            o for o in self.latest_discoveries(profile_slug)
            if o.isbn and looks_like_bundle(o.title)
        ]
        if not bundles:
            return 0
        index = self.title_index(profile_slug)
        changed = 0
        with self.session() as session:
            for bundle in bundles:
                volumes = self.contained_volumes(
                    profile_slug, bundle.isbn, bundle.title, bundle.author, index
                )
                entries = self._series_entries(found_isbn for found_isbn, _ in volumes)
                if not entries:
                    continue
                series_ids = [sid for sid, _ in entries.values()]
                series_id = max(set(series_ids), key=series_ids.count)
                span = volume_span(
                    volume for sid, volume in entries.values() if sid == series_id
                )
                row = session.get(SeriesEntryRow, (bundle.isbn, "bundle"))
                if row is None:
                    session.add(SeriesEntryRow(isbn=bundle.isbn, origin="bundle",
                                               series_id=series_id, volume=span))
                    changed += 1
                elif (row.series_id, row.volume) != (series_id, span):
                    row.series_id, row.volume = series_id, span
                    changed += 1
            session.commit()
        return changed

    def series_known(self) -> dict[str, tuple[int, str | None]]:
        """ISBN -> (Reihe, Band), für `series.MidSeries`."""
        return self._series_entries()

    def series_names(self) -> dict[tuple[str, str], int]:
        """(Schlüssel, Autor:in) -> Reihe — der Name gilt je Autor:in (ADR 35)."""
        with self.session() as session:
            return {
                (key, writer): series_id
                for key, writer, series_id in session.execute(
                    select(SeriesNameRow.key, SeriesNameRow.author_key, SeriesNameRow.series_id)
                )
            }

    def series_of(self, isbns: Iterable[str]) -> dict[str, SeriesOf]:
        """ISBN -> Reihe und Band, wie die Oberfläche sie zeigt (#85)."""
        entries = self._series_entries(isbns)
        with self.session() as session:
            names = dict(session.execute(
                select(SeriesRow.id, SeriesRow.name).where(
                    SeriesRow.id.in_({sid for sid, _ in entries.values()})
                )
            ).all())
        return {isbn: SeriesOf(sid, names[sid], volume)
                for isbn, (sid, volume) in entries.items()}

    def series_refs(self, key: str) -> dict[str, str]:
        """Quelle -> die eigene Nummer der Reihe dort, für den Schlüssel ``key``."""
        with self.session() as session:
            ids = list(session.scalars(
                select(SeriesNameRow.series_id).where(SeriesNameRow.key == key)
            ))
            refs: dict[str, str] = {}
            for row in session.scalars(select(SeriesRow).where(SeriesRow.id.in_(ids))):
                if row.overdrive_ref:
                    refs["overdrive"] = row.overdrive_ref
                if row.onleihe_ref:
                    refs["onleihe"] = row.onleihe_ref
            return refs

    def series_volumes(
        self, series_id: int
    ) -> list[tuple[str, str, str | None, str | None]]:
        """Die bekannten Bände einer Reihe: ISBN, Titel, Autor:in, Bildadresse.

        Titel und Autor:in von der letzten Sichtung, sonst aus der DNB — eine
        ISBN, die keine von beiden beim Namen nennt, wird kein Buch. Die
        Bildadresse nur von einer Sichtung: wer den Band aufs Watchlist setzt,
        sieht damit nach, ob das Bild schon auf der Platte liegt (06.10.2026).
        """
        with self.session() as session:
            isbns = set(session.scalars(
                select(SeriesEntryRow.isbn).where(SeriesEntryRow.series_id == series_id)
            ))
            named: dict[str, tuple[str, str | None, str | None]] = {}
            covers: dict[str, str] = {}
            for isbn, title, author, cover_url in session.execute(
                select(ObservationRow.isbn, ObservationRow.title, ObservationRow.author,
                       ObservationRow.cover_url)
                .where(ObservationRow.isbn.in_(isbns))
                .order_by(ObservationRow.id)
            ):
                if cover_url:
                    covers[isbn] = cover_url
                named[isbn] = (title, author, covers.get(isbn))
            for isbn, title, author in session.execute(
                select(DnbRecordRow.isbn, DnbRecordRow.title, DnbRecordRow.author).where(
                    DnbRecordRow.isbn.in_(isbns - set(named)), DnbRecordRow.title.is_not(None)
                )
            ):
                named[isbn] = (title, author, None)
        return [(isbn, *rest) for isbn, rest in sorted(named.items())]

    def set_series_watch(
        self, profile_slug: str, series_id: int, *, active: bool, now: datetime
    ) -> None:
        with self.session() as session:
            row = session.get(SeriesWatchRow, (profile_slug, series_id))
            if row is None:
                session.add(SeriesWatchRow(profile_slug=profile_slug, series_id=series_id,
                                           active=active, since=now))
            elif row.active != active:
                row.active, row.since = active, now
            session.commit()

    def watched_series(self, profile_slug: str) -> set[int]:
        with self.session() as session:
            return set(session.scalars(
                select(SeriesWatchRow.series_id).where(
                    SeriesWatchRow.profile_slug == profile_slug,
                    SeriesWatchRow.active.is_(True),
                )
            ))

    def series_row(self, series_id: int) -> SeriesRow | None:
        with self.session() as session:
            return session.get(SeriesRow, series_id)

    def file_series(self, observations: Iterable[Observation]) -> None:
        """Reihe, Band und Adresse festhalten, ohne die Sichtung ins Journal zu
        schreiben — für das Fegen einer beobachteten Reihe (#85)."""
        with self.session() as session:
            for obs in observations:
                if obs.isbn and obs.series:
                    _file_series(session, obs.isbn, obs.series, obs.author,
                                 obs.series_index, obs.source, obs.series_ref)
            session.commit()

    def series_rows(self) -> list[SeriesRow]:
        with self.session() as session:
            return list(session.scalars(select(SeriesRow)))

    def series_ids_for(
        self, books: Iterable[tuple[str | None, str | None, str | None]]
    ) -> frozenset[int]:
        """Die Reihen dieser Bücher, je (ISBN, Reihenname, Autor:in).

        Über die ISBN, sonst über den Namen *dieser* Autor:in — „Die Chroniken"
        zweier Leute bleiben zwei Reihen (ADR 35, Review 04.10.2026).
        """
        books = list(books)
        isbns = {isbn for isbn, _, _ in books if isbn}
        named = {
            (series_key(name), author_key(author or "")) for _, name, author in books if name
        }
        with self.session() as session:
            ids = set(session.scalars(
                select(SeriesEntryRow.series_id).where(SeriesEntryRow.isbn.in_(isbns))
            ))
            names = self.series_names() if named else {}
        return frozenset(ids | {names[n] for n in named if n in names})

    def note_categories(
        self, source: str, categories: Iterable[tuple[str, str]], *, example: str | None,
        now: datetime,
    ) -> None:
        """Die Quellkategorien einer Detailseite mitzählen (#92)."""
        wanted = dict(categories)
        if not wanted:
            return
        # In einer Anweisung: Lauf und Oberfläche können dieselbe neue Nummer
        # gleichzeitig sehen; lesen-dann-einfügen stieße dann auf den
        # Schlüssel (Review 04.10.2026).
        statement = sqlite_insert(SourceCategoryRow).values([
            {"source": source, "number": number, "name": name, "count": 1,
             "last_seen": now, "example": example}
            for number, name in wanted.items()
        ])
        statement = statement.on_conflict_do_update(
            index_elements=["source", "number"],
            set_={
                "name": statement.excluded.name,
                "count": SourceCategoryRow.count + 1,
                "last_seen": statement.excluded.last_seen,
                "example": func.coalesce(statement.excluded.example, SourceCategoryRow.example),
            },
        )
        with self.session() as session:
            session.execute(statement)
            session.commit()

    def source_categories(self) -> list[SourceCategoryRow]:
        """Alle gesammelten Quellkategorien, je Quelle nach Nummer."""
        with self.session() as session:
            rows = list(session.scalars(select(SourceCategoryRow)))
        return sorted(rows, key=lambda r: (r.source, int(r.number) if r.number.isdigit()
                                           else 0, r.number))

    def bisac_codes(self, isbns: Iterable[str]) -> dict[str, tuple[str, ...]]:
        """ISBN -> ihre BISAC-Codes, die der DNB zuerst, ohne Doppelte (#88)."""
        wanted = {isbn for isbn in isbns if isbn}
        if not wanted:
            return {}
        rank = {origin: i for i, origin in enumerate(BISAC_ORIGINS)}
        with self.session() as session:
            rows = session.execute(
                select(BisacEntryRow.isbn, BisacEntryRow.origin, BisacEntryRow.code,
                       BisacEntryRow.rank).where(BisacEntryRow.isbn.in_(wanted))
            ).all()
        rows.sort(key=lambda r: (rank.get(r.origin, len(rank)), r.origin, r.rank))
        codes: dict[str, list[str]] = {}
        for isbn, _, code, _ in rows:
            if code not in codes.setdefault(isbn, []):
                codes[isbn].append(code)
        return {isbn: tuple(found) for isbn, found in codes.items()}

    def work_siblings(self, isbns: Iterable[str]) -> dict[str, set[str]]:
        """ISBN -> alle ISBNs desselben Werks, sie selbst eingeschlossen."""
        with self.session() as session:
            return _work_siblings(session, isbns)

    def owned_as(self, profile_slug: str, isbns: Iterable[str]) -> dict[str, str]:
        """ISBN -> Titel einer *anderen* Ausgabe desselben Werks, die sie besitzt.

        Für „hast du schon als …" auf der Watchlist (ADR 36).
        """
        wanted = {isbn for isbn in isbns if isbn}
        with self.session() as session:
            siblings = _work_siblings(session, wanted)
            others = {o for group in siblings.values() for o in group} - wanted
            owned = dict(session.execute(
                select(BookRow.isbn, BookRow.title)
                .join(BookRelationRow, BookRelationRow.book_id == BookRow.id)
                .where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.kind == "owned",
                    BookRelationRow.active.is_(True),
                    BookRow.isbn.in_(others),
                )
            ).all())
        out = {}
        for isbn, group in siblings.items():
            title = next((owned[o] for o in sorted(group) if o != isbn and o in owned), None)
            if title is not None:
                out[isbn] = title
        return out

    def decided_works(self, profile_slug: str) -> set[str]:
        """Die ISBNs aller Ausgaben eines Werks, das sie hat, mag, doof fand
        oder ausgeschlossen hat — für den Stapel (ADR 36)."""
        with self.session() as session:
            isbns = set(session.scalars(
                select(BookRow.isbn)
                .join(BookRelationRow, BookRelationRow.book_id == BookRow.id)
                .where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.kind.in_(("owned", "liked", "disliked", "dismissed")),
                    BookRelationRow.active.is_(True),
                    BookRow.isbn.is_not(None),
                )
            ))
            return {o for group in _work_siblings(session, isbns).values() for o in group}

    def work_book_subjects(self, subject: str) -> set[str]:
        """``book:<id>`` -> die Buchschlüssel aller Ausgaben seines Werks, es
        selbst eingeschlossen."""
        with self.session() as session:
            return _work_book_subjects(session, [subject])[subject]

    def forget_work_entries(self) -> None:
        """Nur für Tests: der Stand vor ADR 36."""
        with self.session() as session:
            session.execute(delete(WorkEntryRow))
            session.commit()

    def forget_series_entries(self) -> None:
        """Nur für Tests: der Stand vor der Reihen-Tabelle."""
        with self.session() as session:
            session.execute(delete(SeriesEntryRow))
            session.commit()

    def dnb_languages(self) -> dict[str, str]:
        """ISBN -> Sprache, fuer jede ISBN, zu der die DNB eine nennt (#10)."""
        with self.session() as session:
            return dict(
                session.execute(
                    select(DnbRecordRow.isbn, DnbRecordRow.language).where(
                        DnbRecordRow.found.is_(True), DnbRecordRow.language.is_not(None)
                    )
                ).all()
            )

    def authors_and_blurbs(self, needles: Sequence[str]) -> list[tuple[str, str]]:
        """Autor:in und Klappentext, wo der Text eines der Woerter enthaelt (#31).

        ``needles`` ist eine grobe Vorauswahl, keine Entscheidung: wer genau
        gemeint ist, sagt der Aufrufer. Ohne sie und ohne ``distinct`` las
        diese Abfrage alle 3899 Beobachtungen und kostete 97 ms — ein Viertel
        der Stapelseite, und wachsend, denn Beobachtungen werden nie geloescht
        (ADR 5). Mit beidem sind es 150 Zeilen und 45 ms.
        """
        with self.session() as session:
            stmt = select(ObservationRow.author, ObservationRow.blurb).where(
                ObservationRow.author.is_not(None),
                ObservationRow.blurb.is_not(None),
                or_(*(ObservationRow.blurb.ilike(f"%{word}%") for word in needles)),
            # Dasselbe Buch wird taeglich neu gesehen, und der Klappentext
            # aendert sich dabei fast nie: von 720 Zeilen bleiben 150.
            ).distinct()
            return [(author, blurb) for author, blurb in session.execute(stmt).all()]

    def contained_isbns(self, isbn: str) -> tuple[str, ...]:
        """Die Baende einer Sammelausgabe, aus ``770 $i Enthaelt`` (ADR 24)."""
        with self.session() as session:
            stmt = select(DnbContainsRow.contained).where(DnbContainsRow.isbn == isbn)
            return tuple(session.scalars(stmt))

    def prices_by_isbn(self, profile_slug: str, source: str) -> dict[str, int]:
        """ISBN -> guenstigster zuletzt gesehener Preis.

        Der Gegenstueck zu :meth:`latest_prices_by_title`, nur exakt: wo die
        DNB die enthaltenen Baende als ISBN nennt, gibt es nichts zu raten.
        """
        latest_ids = (
            select(func.max(ObservationRow.id))
            .where(
                ObservationRow.profile_slug == profile_slug,
                ObservationRow.source == source,
                ObservationRow.isbn.is_not(None),
                ObservationRow.price_cents.is_not(None),
            )
            .group_by(ObservationRow.source, ObservationRow.source_item_id)
        )
        with self.session() as session:
            stmt = select(ObservationRow.isbn, ObservationRow.price_cents).where(
                ObservationRow.id.in_(latest_ids)
            )
            prices: dict[str, int] = {}
            for isbn_value, price in session.execute(stmt):
                if not isbn_value or price is None or price <= 0:
                    continue
                if isbn_value not in prices or price < prices[isbn_value]:
                    prices[isbn_value] = price
            return prices

    def decided_items(self, profile_slug: str) -> set[tuple[str, str]]:
        """``(Quelle, Item-Id)``, zu denen es schon ein Buch mit **aktiver**
        Beziehung gibt.

        Ueber ``book_source``, weil dort steht, unter welcher Nummer eine
        Quelle ein Buch fuehrt. Das ist der Weg, auf dem eine Entscheidung
        *buchweit* wirkt statt nur fuer eine Produktnummer (ADR 18).

        Nur aktive: eine zurueckgenommene Entscheidung ist keine, und der Fund
        gehoert wieder in den Stapel — dieselbe Lesart wie ``dismissed_keys``.
        """
        with self.session() as session:
            stmt = (
                select(BookSourceRow.source, BookSourceRow.source_item_id)
                .join(BookRelationRow, BookRelationRow.book_id == BookSourceRow.book_id)
                .where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.active.is_(True),
                    BookSourceRow.source_item_id.is_not(None),
                )
            )
            return {(row[0], row[1]) for row in session.execute(stmt)}

    def dismissed_keys(self, profile_slug: str) -> tuple[set[tuple[str, str]], set[str]]:
        """``(Quelle, Nummer)`` und ISBNs aller aktiven Ablehnungen.

        Zwei Abfragen, nicht zwei je Ablehnung. Der naheliegende Weg — ueber
        die Beziehungen laufen und je Buch nachschlagen — kostet bei
        dreihundert Ablehnungen rund zweieinhalb Sekunden **pro Lauf**, und
        genau diese Sorte Wachstum hat schon einmal eine Tabelle gekostet
        (ADR 16, ``seeded_scope``).
        """
        with self.session() as session:
            dismissed = (
                select(BookRelationRow.book_id)
                .where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.kind == str(RelationKind.DISMISSED),
                    BookRelationRow.active.is_(True),
                )
                .scalar_subquery()
            )
            items = {
                (row[0], row[1])
                for row in session.execute(
                    select(BookSourceRow.source, BookSourceRow.source_item_id).where(
                        BookSourceRow.book_id.in_(dismissed),
                        BookSourceRow.source_item_id.is_not(None),
                    )
                )
            }
            isbns = {
                row[0]
                for row in session.execute(
                    select(BookRow.isbn).where(
                        BookRow.id.in_(dismissed), BookRow.isbn.is_not(None)
                    )
                )
            }
        return items, isbns

    def books_with_relations(self, profile_slug: str) -> dict[str, int]:
        """ISBN -> Buch-Id, aber nur fuer Buecher, zu denen etwas gesagt wurde
        — und noch gilt.

        So verschwindet ein Fund auch dann aus dem Stapel, wenn eine *andere*
        Quelle dasselbe Buch unter einer anderen Nummer fuehrt — die ISBN ist
        der Schluessel, an dem sich beide treffen (ADR 18).
        """
        with self.session() as session:
            stmt = (
                select(BookRow.isbn, BookRow.id)
                .join(BookRelationRow, BookRelationRow.book_id == BookRow.id)
                .where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.active.is_(True),
                    BookRow.isbn.is_not(None),
                )
            )
            return {row[0]: row[1] for row in session.execute(stmt)}

    # --- Bücher (Ticket 04) ------------------------------------------------

    def _book_index(self, session: Session) -> list[BookLike]:
        rows = session.execute(
            select(BookRow.id, BookRow.isbn, BookRow.title, BookRow.author)
        )
        return [BookLike(id=r[0], isbn=r[1], title=r[2], author=r[3]) for r in rows]

    def find_book(
        self, *, isbn: str | None, title: str, author: str | None = None
    ) -> BookRow | None:
        """Das Buch zu diesem Fund, falls es schon eines gibt."""
        with self.session() as session:
            found = find_book(self._book_index(session), isbn=isbn, title=title, author=author)
            if found is None:
                return None
            row = session.get(BookRow, found.book_id)
            if row is not None:
                session.expunge(row)
            return row

    def find_or_create_book(
        self,
        *,
        isbn: str | None,
        title: str,
        author: str | None = None,
        series: str | None = None,
        now: datetime,
    ) -> BookRow:
        """Ein Buch anlegen — aber erst nachsehen, ob es schon da ist.

        Jede Anlage sucht zuerst, weil sonst derselbe Titel unter zwei Quellen
        zweimal in der Tabelle stünde und die Beziehungen der Leserin sich auf
        zwei Zeilen verteilen würden.
        """
        with self.session() as session:
            found = find_book(self._book_index(session), isbn=isbn, title=title, author=author)
            if found is not None:
                row = session.get(BookRow, found.book_id)
                if row is not None:
                    # Was wir noch nicht wussten, tragen wir nach; was schon
                    # dasteht, wird nicht überschrieben - eine spätere Quelle
                    # ist nicht automatisch die bessere.
                    if row.isbn is None and isbn:
                        row.isbn = isbn
                    if row.series is None and series:
                        row.series = series
                    row.author = _better_spelling(row.author, author)
                    session.commit()
                    session.refresh(row)
                    session.expunge(row)
                    return row

            row = BookRow(
                isbn=isbn or None,
                title=title,
                author=author,
                series=series,
                created_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    def series_from_dnb(self) -> int:
        """Reihe und Band aus der DNB auf die Buecher schreiben — nur in Luecken.

        Die DNB lieferte die Reihe fuer 33 von 101 ISBNs, auf einer Buch-Zeile
        landete sie nie: 0 von 70 (#10). Die Buchseite hat ein Feld dafuer,
        das deshalb immer leer blieb.

        Ueberschrieben wird nichts: steht an einem Buch schon eine Reihe, gilt
        die. Und weil nur aus der Datenbank gelesen wird, kostet der Schritt
        keine Anfrage und darf bei jedem Lauf ueber alle Buecher gehen — so
        erreichen auch die Auskuenfte, die vor ihm geholt wurden, ihr Buch.
        Gibt zurueck, wie viele Buecher eine Reihe bekamen.
        """
        with self.session() as session:
            filled = 0
            rows = session.execute(
                select(BookRow, DnbRecordRow)
                .join(DnbRecordRow, DnbRecordRow.isbn == BookRow.isbn)
                .where(
                    BookRow.series.is_(None),
                    DnbRecordRow.found.is_(True),
                    DnbRecordRow.series.is_not(None),
                )
            ).all()
            for book, record in rows:
                book.series = record.series
                book.series_index = record.series_index
                filled += 1
            # Antworten von vor der Reihen-Tabelle (ADR 35): ohne neue Frage
            # zugeordnet, einmal und dann nie wieder.
            filed = select(SeriesEntryRow.isbn).where(SeriesEntryRow.origin == "dnb")
            for record in session.scalars(
                select(DnbRecordRow).where(
                    DnbRecordRow.found.is_(True),
                    DnbRecordRow.series.is_not(None),
                    DnbRecordRow.isbn.not_in(filed),
                )
            ).all():
                _file_series(session, record.isbn, record.series, record.author,
                             record.series_index, "dnb")
            # Ebenso das Werk (ADR 36): Originaltitel aus der DNB, eigene Titel
            # aus dem Journal — je ISBN einmal.
            known = select(WorkEntryRow.isbn).where(WorkEntryRow.origin == "dnb")
            for record in session.scalars(
                select(DnbRecordRow).where(
                    DnbRecordRow.found.is_(True),
                    DnbRecordRow.original_title.is_not(None),
                    DnbRecordRow.isbn.not_in(known),
                )
            ).all():
                _file_work(session, record.isbn, record.author, record.original_title, "dnb")
            titled = select(WorkEntryRow.isbn).where(WorkEntryRow.origin == "title")
            latest = (
                select(func.max(ObservationRow.id))
                .where(ObservationRow.isbn.is_not(None), ObservationRow.isbn.not_in(titled))
                .group_by(ObservationRow.isbn)
            )
            for isbn, title, author in session.execute(
                select(ObservationRow.isbn, ObservationRow.title, ObservationRow.author)
                .where(ObservationRow.id.in_(latest))
            ).all():
                _file_work(session, isbn, author, title, "title")
            session.commit()
            return filled

    def set_cover(self, book_id: int, file_name: str) -> None:
        with self.session() as session:
            row = session.get(BookRow, book_id)
            if row is None:
                return
            row.cover_file = file_name
            session.commit()

    def learn_isbn(self, book_id: int, isbn: str) -> bool:
        """Die ISBN nachtragen, die ein Watchlist-Eintrag selbst nicht mitbrachte.

        Ein Eintrag entsteht aus Titel und Autor:in; die ISBN erfaehrt erst die
        Beobachtung. Eine vorhandene wird nicht ueberschrieben - eine zweite
        ISBN bedeutet eine andere Ausgabe, und die stillschweigend zu
        uebernehmen wuerde die Identitaet des Buchs verschieben (ADR 18).

        Gibt zurueck, ob wirklich etwas gelernt wurde.
        """
        with self.session() as session:
            row = session.get(BookRow, book_id)
            if row is None or row.isbn or not isbn:
                return False
            # Eine andere Buch-Zeile kann dieselbe ISBN schon tragen: dann sind
            # es zwei Zeilen fuer ein Buch, und das Zusammenfuehren ist eine
            # eigene Entscheidung, keine Nebenwirkung eines Laufs.
            taken = session.scalars(
                select(BookRow.id).where(BookRow.isbn == isbn, BookRow.id != book_id)
            ).first()
            if taken is not None:
                return False
            row.isbn = isbn
            session.commit()
            return True

    def book(self, book_id: int) -> BookRow | None:
        with self.session() as session:
            row = session.get(BookRow, book_id)
            if row is not None:
                session.expunge(row)
            return row

    def rename_book(self, book_id: int, *, title: str, author: str | None = None) -> bool:
        """Den Titel berichtigen, unter dem die Leserin ein Buch fuehrt (ADR 27).

        Umbenannt wird die **bestehende** Zeile. Notiz, Beziehung, Urteile und
        die ganze Geschichte haengen an ihrer Nummer; ein neu angelegtes Buch
        liesse all das am alten Eintrag zurueck.

        Die Zuordnungen fallen dabei weg — sie galten fuer den alten Titel und
        waeren danach eine Behauptung ueber etwas anderes. Damit sucht der
        naechste Lauf neu, und genau das ist der Zweck der Uebung.
        """
        blank = title.strip()
        if not blank:
            return False
        with self.session() as session:
            row = session.get(BookRow, book_id)
            if row is None:
                return False
            if row.title == blank and (author is None or row.author == author):
                return False
            row.title = blank
            if author is not None:
                row.author = author.strip() or None
            session.execute(
                delete(BookSourceRow).where(BookSourceRow.book_id == book_id)
            )
            session.commit()
            return True

    def books(self) -> list[BookRow]:
        with self.session() as session:
            rows = list(session.scalars(select(BookRow).order_by(BookRow.title)))
            for row in rows:
                session.expunge(row)
            return rows

    def get_book_source(self, book_id: int, source: str) -> BookSourceRow | None:
        with self.session() as session:
            row = session.get(BookSourceRow, (book_id, source))
            if row is not None:
                session.expunge(row)
            return row

    def books_by_id(self, book_ids: Iterable[int]) -> dict[int, BookRow]:
        """Mehrere Buecher auf einmal — eine Abfrage statt einer je Zeile.

        Die Watchlist stellte fuer neunzehn Eintraege neunzehn Fragen; gemessen
        kosteten die 4,8 ms, die gebuendelte Fassung eine.
        """
        wanted = list(dict.fromkeys(book_ids))
        if not wanted:
            return {}
        with self.session() as session:
            rows = list(session.scalars(select(BookRow).where(BookRow.id.in_(wanted))))
            for row in rows:
                session.expunge(row)
            return {row.id: row for row in rows}

    def book_sources_of(self, book_ids: Iterable[int]) -> dict[int, list[BookSourceRow]]:
        """Die Quellen-Verknuepfungen mehrerer Buecher, nach Buch geordnet.

        Wie :meth:`book_sources`, nur gebuendelt. Die Reihenfolge je Buch
        bleibt dieselbe (nach Quellenname), damit die Zeile ueberall gleich
        aussieht.
        """
        wanted = list(dict.fromkeys(book_ids))
        if not wanted:
            return {}
        found: dict[int, list[BookSourceRow]] = {book_id: [] for book_id in wanted}
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(BookSourceRow)
                    .where(BookSourceRow.book_id.in_(wanted))
                    .order_by(BookSourceRow.book_id, BookSourceRow.source)
                )
            )
            for row in rows:
                session.expunge(row)
                found[row.book_id].append(row)
            return found

    def book_sources(self, book_id: int) -> list[BookSourceRow]:
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(BookSourceRow)
                    .where(BookSourceRow.book_id == book_id)
                    .order_by(BookSourceRow.source)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def book_by_source_item(self, source: str, source_item_id: str) -> int | None:
        """Welches Buch diese Quelle unter dieser Nummer fuehrt, falls bekannt.

        Der Weg zurueck von der Nummer zum Buch. Ohne ihn muesste jede
        Aufloesung noch einmal beim Shop nachfragen, obwohl die Antwort schon
        in der Datenbank steht (Ticket 17).
        """
        with self.session() as session:
            return session.scalars(
                select(BookSourceRow.book_id).where(
                    BookSourceRow.source == source,
                    BookSourceRow.source_item_id == source_item_id,
                )
            ).first()

    def unsure_links(self, profile_slug: str) -> list[BookSourceRow]:
        """Zuordnungen, bei denen eine Quelle unsicher ist (Ticket 41).

        Ueber ``book_relation`` gefiltert: eine unklare Zuordnung zu einem Buch,
        das die Leserin gar nicht mehr beobachtet, ist keine Frage an sie.
        """
        with self.session() as session:
            observed = select(BookRelationRow.book_id).where(
                BookRelationRow.profile_slug == profile_slug,
                BookRelationRow.kind == str(RelationKind.WATCHING),
                BookRelationRow.active.is_(True),
            )
            stmt = (
                select(BookSourceRow)
                .where(
                    BookSourceRow.book_id.in_(observed),
                    BookSourceRow.details.like('%"unsure"%'),
                )
                .order_by(BookSourceRow.book_id)
            )
            rows = list(session.scalars(stmt))
            for row in rows:
                session.expunge(row)
            return rows

    def reject_candidates(self, book_id: int, source: str, urls: Iterable[str]) -> None:
        """Alle gezeigten Kandidaten ablehnen — „keiner davon" (Ticket 41).

        Festgehalten werden die **Adressen**, nicht bloss die Tatsache: dieselben
        Kandidaten werden nicht noch einmal vorgelegt, ein **neuer** schon.
        Einen einzelnen abzulehnen gibt es nicht mehr — waehlt man den
        richtigen, sind die anderen ohnehin erledigt.

        ``resolved_at`` bleibt unberuehrt (#39): die Spalte sagt, wann zuletzt
        *gesucht* wurde, und daran haengt das Wiederholfenster von sieben
        Tagen. Sie hier auf jetzt zu setzen schob jede Ablehnung die naechste
        Suche um eine weitere Woche — ausgerechnet in dem Fall, in dem die
        bisherigen Treffer nachweislich falsch waren.
        """
        with self.session() as session:
            row = session.get(BookSourceRow, (book_id, source))
            if row is None:
                return
            details = json.loads(row.details or '{}')
            rejected = list(details.get('rejected') or [])
            for url in urls:
                if url and url not in rejected:
                    rejected.append(url)
            details['rejected'] = rejected
            row.details = json.dumps(details, ensure_ascii=False)
            session.commit()

    def restore_candidates(self, book_id: int, source: str) -> None:
        """Eine Ablehnung zuruecknehmen — ein Irrtum beim Wegklicken darf nicht
        dauerhaft sein (ADR 18)."""
        with self.session() as session:
            row = session.get(BookSourceRow, (book_id, source))
            if row is None:
                return
            details = json.loads(row.details or '{}')
            details['rejected'] = []
            row.details = json.dumps(details, ensure_ascii=False)
            session.commit()

    def put_book_source(
        self,
        book_id: int,
        source: str,
        *,
        outcome: str,
        url: str | None = None,
        source_item_id: str | None = None,
        resolved_at: datetime,
        **details: object,
    ) -> None:
        """Wo eine Quelle dieses Buch führt — oder dass sie es nicht führt.

        ``outcome`` wird gegen die bekannten Werte geprüft und nicht geduldet,
        wenn er unbekannt ist: ein Tippfehler fiele sonst still aus jeder
        Abfrage heraus, die fragt, was noch Aufmerksamkeit braucht.
        """
        if outcome not in LINK_OUTCOMES:
            raise ValueError(
                f"unknown link outcome {outcome!r} (known: {', '.join(sorted(LINK_OUTCOMES))})"
            )
        with self.session() as session:
            row = session.get(BookSourceRow, (book_id, source))
            if row is None:
                row = BookSourceRow(book_id=book_id, source=source)
                session.add(row)
            row.url = url
            row.source_item_id = source_item_id
            row.resolved_at = resolved_at
            row.details = json.dumps({"outcome": outcome, **details}, ensure_ascii=False)
            session.commit()

