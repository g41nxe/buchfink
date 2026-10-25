"""Beobachtungen lesen: der letzte Stand je Fund, je Buch, je ISBN (#103)."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import (
    and_,
    func,
    or_,
    select,
)

from ..models import MatchReason, Observation
from .core import StoreCore
from .rows import (
    BookSourceRow,
    ObservationRow,
    _to_observation,
)


class ObservationsMixin(StoreCore):
    """Beobachtungen lesen: der letzte Stand je Fund, je Buch, je ISBN (#103)."""

    def latest_observations(
        self, profile_slug: str, keys: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], Observation]:
        """The most recent stored Observation for each ``(source, source_item_id)``.

        Resolved with a max-id-per-item subquery so the cost tracks the number of
        watched items, not the length of the append-only history.
        """
        wanted = set(keys)
        if not wanted:
            return {}
        sources = {source for source, _ in wanted}
        item_ids = {item_id for _, item_id in wanted}

        latest_ids = (
            select(func.max(ObservationRow.id))
            .where(
                ObservationRow.profile_slug == profile_slug,
                ObservationRow.source.in_(sources),
                ObservationRow.source_item_id.in_(item_ids),
            )
            .group_by(ObservationRow.source, ObservationRow.source_item_id)
        )

        found: dict[tuple[str, str], Observation] = {}
        with self.session() as session:
            stmt = select(ObservationRow).where(ObservationRow.id.in_(latest_ids))
            for row in session.scalars(stmt):
                key = (row.source, row.source_item_id)
                # in_() pairs the sets independently, so a cross-source id
                # collision can come back; keep only the pairs we asked for.
                if key in wanted:
                    found[key] = _to_observation(row)
        return found

    def latest_by_book(
        self, profile_slug: str, book_ids: Iterable[int]
    ) -> dict[int, list[Observation]]:
        """Die zuletzt gesehenen Beobachtungen je Buch — was die Watchlist zeigt.

        Eine Liste, neueste zuerst, mit **einer Zeile je Quelle**: welche davon
        einen Preis nennt und welche eine Verfuegbarkeit, entscheidet die
        Watchlist-Zeile selbst.

        Dieselbe max-id-Unterabfrage wie :meth:`latest_observations`, nur ueber
        ``book_id`` statt ueber das Quellen-Paar: die Kosten haengen an der Zahl
        der beobachteten Buecher, nicht an der Laenge der Historie.
        """
        wanted = set(book_ids)
        if not wanted:
            return {}
        latest_ids = (
            select(func.max(ObservationRow.id))
            .where(
                ObservationRow.profile_slug == profile_slug,
                ObservationRow.book_id.in_(wanted),
            )
            # Je Buch **und Quelle**, nicht je Buch: eine einzige Beobachtung je
            # Buch war die der zuletzt eingefuegten Quelle, also eine Frage der
            # Reihenfolge in ``settings.yaml``. Mit zwei Bibliotheken entschied
            # das darueber, welche von beiden die Zeile beschreibt — sagte die
            # eine "ausleihbar" und die andere "verliehen", stand in der
            # Watchlist die falsche von beiden.
            .group_by(ObservationRow.book_id, ObservationRow.source)
        )
        found: dict[int, list[Observation]] = {}
        with self.session() as session:
            stmt = select(ObservationRow).where(ObservationRow.id.in_(latest_ids)).order_by(
                ObservationRow.id.desc()
            )
            for row in session.scalars(stmt):
                if row.book_id is not None:
                    found.setdefault(row.book_id, []).append(_to_observation(row))
        return found

    def observations_for_book(
        self, profile_slug: str, book_id: int, limit: int = 200
    ) -> list[Observation]:
        """Die ganze Geschichte eines Buchs, neueste zuerst.

        Der Snapshot ist anhaengend (ADR 5), also *ist* das die Geschichte —
        sie muss nicht gesondert gefuehrt werden. Die Grenze schuetzt die Seite
        vor einem Buch, das seit Jahren jeden Tag beobachtet wird.

        Gefragt wird nach zweierlei: nach der ``book_id`` und nach den Nummern,
        unter denen die Quellen dieses Buch fuehren. Eine Entdeckung wird ohne
        ``book_id`` beobachtet — es gibt ja noch kein Buch (ADR 18) —, und wird
        spaeter eines daraus, haengt ihre ganze Vorgeschichte sonst in der
        Luft: die Buchseite sagte "Noch nichts gesehen" und die Kachel der
        Quelle nannte keinen Preis, obwohl elf Beobachtungen dazu dastanden.
        Nachgeschlagen statt nachgetragen — der Snapshot wird nicht
        umgeschrieben.
        """
        with self.session() as session:
            pairs = session.execute(
                select(BookSourceRow.source, BookSourceRow.source_item_id).where(
                    BookSourceRow.book_id == book_id,
                    BookSourceRow.source_item_id.is_not(None),
                )
            ).all()
            clauses = [ObservationRow.book_id == book_id]
            clauses += [
                and_(
                    ObservationRow.source == source,
                    ObservationRow.source_item_id == item_id,
                )
                for source, item_id in pairs
            ]
            stmt = (
                select(ObservationRow)
                .where(ObservationRow.profile_slug == profile_slug, or_(*clauses))
                .order_by(ObservationRow.id.desc())
                .limit(limit)
            )
            return [_to_observation(row) for row in session.scalars(stmt)]

    def sightings_by_isbn(
        self, profile_slug: str, isbns: Iterable[str]
    ) -> dict[str, list[Observation]]:
        """ISBN -> die letzte Sichtung je Quelle und Nummer, die sie trägt.

        Für die Seitenzahl, die eine andere Quelle zu derselben Ausgabe nennt
        (ADR 34).
        """
        wanted = {isbn for isbn in isbns if isbn}
        if not wanted:
            return {}
        latest_ids = (
            select(func.max(ObservationRow.id))
            .where(ObservationRow.profile_slug == profile_slug, ObservationRow.isbn.in_(wanted))
            .group_by(ObservationRow.source, ObservationRow.source_item_id)
        )
        found: dict[str, list[Observation]] = {}
        with self.session() as session:
            stmt = select(ObservationRow).where(ObservationRow.id.in_(latest_ids))
            for row in session.scalars(stmt):
                found.setdefault(row.isbn, []).append(_to_observation(row))
        return found

    def observations_for_item(
        self, profile_slug: str, source: str, source_item_id: str, limit: int = 200
    ) -> list[Observation]:
        """Die ganze Geschichte eines Funds, neueste zuerst.

        Dasselbe wie :meth:`observations_for_book`, nur am Paar aus Quelle und
        Nummer statt an einer ``book_id`` — ein Fund hat keine Buch-Zeile,
        solange nichts ueber ihn gesagt wurde (ADR 18). Die Grenze schuetzt
        vor einem Titel, der seit Monaten in jedem Lauf auftaucht.
        """
        with self.session() as session:
            stmt = (
                select(ObservationRow)
                .where(
                    ObservationRow.profile_slug == profile_slug,
                    ObservationRow.source == source,
                    ObservationRow.source_item_id == source_item_id,
                )
                .order_by(ObservationRow.id.desc())
                .limit(limit)
            )
            return [_to_observation(row) for row in session.scalars(stmt)]

    def latest_discoveries(
        self, profile_slug: str, limit: int | None = None
    ) -> list[Observation]:
        """Die zuletzt gesehene Fassung jeder Entdeckung.

        Der Snapshot ist anhaengend, also steht dasselbe Buch dort einmal je
        Lauf. Fuer die Triage zaehlt nur der letzte Stand — dieselbe
        max-id-je-Element-Unterabfrage wie ueberall sonst, damit die Kosten an
        der Zahl der Funde haengen und nicht an der Laenge der Geschichte.

        Ohne Grenze, und das ist der Punkt: hier standen 500, der Bestand bei
        397, und jeder Lauf legt zu. Zu langsam waere die Seite davon nicht
        geworden, sondern unvollstaendig — die aeltesten Funde waeren aus dem
        Stapel, aus der Zaehlung "N offen" und aus dem Bilderholen gefallen,
        ohne dass irgendwo etwas davon steht. Die Zahl der Entdeckungen
        waechst langsam (410 in drei Monaten) und die Abfrage kostet bei 400
        Zeilen 7 ms; wer sie doch einmal deckeln will, sagt es beim Aufruf.
        """
        latest_ids = (
            select(func.max(ObservationRow.id))
            .where(
                ObservationRow.profile_slug == profile_slug,
                ObservationRow.match_reason.in_(
                    [str(MatchReason.PROFILE_AUTHOR), str(MatchReason.GENRE_CATEGORY)]
                ),
            )
            .group_by(ObservationRow.source, ObservationRow.source_item_id)
        )
        with self.session() as session:
            stmt = (
                select(ObservationRow)
                .where(ObservationRow.id.in_(latest_ids))
                .order_by(ObservationRow.id.desc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            return [_to_observation(row) for row in session.scalars(stmt)]

    def latest_prices_by_title(self, profile_slug: str, source: str) -> dict[str, int]:
        """Titel -> zuletzt gesehener Preis, fuer eine Quelle.

        Die Auskunft, die der Buendelvorteil braucht: was kostet der Einzelband
        (ADR 24). Ueber den **Titel** und nicht ueber eine Kennung, weil genau
        das der Fall ist — "Der Kruzifix-Killer / Der Vollstrecker" nennt seine
        Baende beim Namen und sonst nichts.

        Nur diese eine Quelle: Preise zweier Shops zu addieren waere eine Summe,
        die niemand bezahlen kann.
        """
        latest_ids = (
            select(func.max(ObservationRow.id))
            .where(
                ObservationRow.profile_slug == profile_slug,
                ObservationRow.source == source,
                ObservationRow.price_cents.is_not(None),
            )
            .group_by(ObservationRow.source, ObservationRow.source_item_id)
        )
        with self.session() as session:
            stmt = select(ObservationRow.title, ObservationRow.price_cents).where(
                ObservationRow.id.in_(latest_ids)
            )
            prices: dict[str, int] = {}
            for title, price in session.execute(stmt):
                if not title or price is None or price <= 0:
                    continue
                # Der guenstigste gewinnt: derselbe Titel kann als mehrere
                # Ausgaben dastehen, und fuer den Vergleich zaehlt, was der
                # Einzelband mindestens kostet.
                if title not in prices or price < prices[title]:
                    prices[title] = price
            return prices

