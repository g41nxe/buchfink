"""Laufjournal, Zustände und Quellen: was ein Lauf über sich festhält (#103)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import (
    select,
)

from ..catalog.series import series_from_title
from ..models import Observation
from .core import StoreCore
from .rows import (
    ENTRY_TRIGGER,
    BookRow,
    ObservationRow,
    RunRow,
    SourceRow,
    StateRow,
    WorkEntryRow,
    _file_bisac,
    _file_series,
    _file_work,
)


class RunsMixin(StoreCore):
    """Laufjournal, Zustände und Quellen: was ein Lauf über sich festhält (#103)."""

    def start_run(
        self,
        profile_slug: str,
        trigger: str,
        started_at: datetime,
        pid: int | None = None,
    ) -> int:
        with self.session() as session:
            run = RunRow(
                profile_slug=profile_slug,
                trigger=trigger,
                started_at=started_at,
                status="running",
                pid=pid,
            )
            session.add(run)
            session.commit()
            return run.id

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        delta_count: int,
        finished_at: datetime,
        error: str | None = None,
    ) -> None:
        with self.session() as session:
            run = session.get(RunRow, run_id)
            if run is None:  # pragma: no cover - only reachable if the row was deleted
                raise LookupError(f"run {run_id} vanished")
            run.status = status
            run.delta_count = delta_count
            run.finished_at = finished_at
            run.error = error
            session.commit()

    def abandon_unfinished(self, profile_slug: str) -> int:
        """Zeilen, die noch auf „läuft“ stehen, als abgebrochen kennzeichnen.

        Nur aufrufen, wer die Lauf-Sperre hält: dann lebt kein anderer Lauf,
        und was noch läuft, ist ein Prozess, der nie zum Abschluss kam —
        abgeschossen, oder der Rechner ging aus (ADR 40). Bis dahin stand dafür
        die Prozessnummer; die trägt nicht über Container hinweg.

        ``finished_at`` bleibt leer: fertig ist der Lauf nicht geworden, und
        alles, was nach dem letzten fertigen Lauf fragt, soll ihn weiter
        übergehen.
        """
        with self.session() as session:
            rows = session.scalars(
                select(RunRow).where(
                    RunRow.profile_slug == profile_slug,
                    RunRow.finished_at.is_(None),
                    RunRow.status == "running",
                )
            ).all()
            for row in rows:
                row.status = "abandoned"
            session.commit()
            return len(rows)

    def recent_runs(self, profile_slug: str, limit: int = 20) -> list[RunRow]:
        """The Run journal, newest first — what the Dashboard shows.

        Ohne die engen Laeufe aus Ticket 51: ein "Lauf" heisst hier *jemand
        hat alles angesehen*. Ein einzelner Eintrag, den die Leserin gerade
        selbst angestossen hat, ist kein Rundgang — er wuerde das Journal mit
        Einzeilern fuellen und im Panel als *der* letzte Lauf erscheinen.
        Seine Zeile bleibt trotzdem stehen: die Beobachtung haengt daran.
        """
        with self.session() as session:
            stmt = (
                select(RunRow)
                .where(
                    RunRow.profile_slug == profile_slug,
                    RunRow.trigger != ENTRY_TRIGGER,
                )
                .order_by(RunRow.id.desc())
                .limit(limit)
            )
            rows = list(session.scalars(stmt))
            for row in rows:
                session.expunge(row)
            return rows

    def latest_run(self, profile_slug: str) -> RunRow | None:
        """The most recent Run, finished or not — what "Run now" reports on."""
        runs = self.recent_runs(profile_slug, limit=1)
        return runs[0] if runs else None

    def last_finished_run(self, profile_slug: str, before_run_id: int) -> RunRow | None:
        """The previous completed Run — what the Digest means by 'last check'."""
        with self.session() as session:
            stmt = (
                select(RunRow)
                .where(
                    RunRow.profile_slug == profile_slug,
                    RunRow.id < before_run_id,
                    RunRow.finished_at.is_not(None),
                    # Sonst datierte "seit dem letzten Check" auf einen
                    # einzelnen Eintrag, den die Leserin selbst angesehen hat.
                    RunRow.trigger != ENTRY_TRIGGER,
                )
                .order_by(RunRow.id.desc())
                .limit(1)
            )
            row = session.scalars(stmt).first()
            if row is not None:
                session.expunge(row)
            return row

    def get_state(self, profile_slug: str, key: str) -> datetime | None:
        with self.session() as session:
            row = session.get(StateRow, (profile_slug, key))
            return row.value if row is not None else None

    def clear_state(self, profile_slug: str, key: str) -> None:
        with self.session() as session:
            row = session.get(StateRow, (profile_slug, key))
            if row is not None:
                session.delete(row)
                session.commit()

    def set_state(self, profile_slug: str, key: str, value: datetime) -> None:
        with self.session() as session:
            row = session.get(StateRow, (profile_slug, key))
            if row is None:
                row = StateRow(profile_slug=profile_slug, key=key)
                session.add(row)
            row.value = value
            session.commit()

    # --- Quellen-Zustand (Ticket 03) ---------------------------------------

    def sources(self) -> list[SourceRow]:
        """Alle bekannten Quellen, alphabetisch — was das Dashboard zeigt."""
        with self.session() as session:
            rows = list(session.scalars(select(SourceRow).order_by(SourceRow.name)))
            for row in rows:
                session.expunge(row)
            return rows

    def source(self, name: str) -> SourceRow | None:
        with self.session() as session:
            row = session.get(SourceRow, name)
            if row is not None:
                session.expunge(row)
            return row

    def is_enabled(self, name: str) -> bool:
        """Eine unbekannte Quelle ist eingeschaltet.

        Die Zeile entsteht erst beim ersten Lauf; bis dahin wäre ein
        vorenthaltenes Ja gleichbedeutend damit, dass eine frisch
        konfigurierte Quelle stillschweigend nichts tut.
        """
        row = self.source(name)
        return True if row is None else row.enabled

    def set_enabled(self, name: str, enabled: bool, *, now: datetime) -> None:
        with self.session() as session:
            row = session.get(SourceRow, name)
            if row is None:
                row = SourceRow(name=name, enabled=True, consecutive_failures=0)
                session.add(row)
            row.enabled = enabled
            row.updated_at = now
            session.commit()

    def record_probe(
        self, name: str, *, ok: bool, error: str | None, now: datetime
    ) -> None:
        """Das Ergebnis eines Selbsttests festhalten statt es auszudrucken.

        ``consecutive_failures`` zählt hoch und wird bei jedem Erfolg auf null
        gesetzt: erst daran ist zu erkennen, ob eine Quelle gerade kaputtging
        oder seit Tagen kaputt ist.
        """
        with self.session() as session:
            row = session.get(SourceRow, name)
            if row is None:
                row = SourceRow(name=name, enabled=True, consecutive_failures=0)
                session.add(row)
            row.last_probe_at = now
            row.last_probe_ok = ok
            row.last_error = None if ok else error
            row.consecutive_failures = 0 if ok else (row.consecutive_failures or 0) + 1
            row.updated_at = now
            session.commit()

    def _remember_blurbs(self, observations: Sequence[Observation]) -> None:
        """Den Klappentext am Buch festhalten, wo eins dahintersteht.

        Ueberschrieben wird nur, was laenger geworden ist: die Kachel einer
        Suchseite traegt einen Anriss, die Detailseite den ganzen Text, und
        welche von beiden zuerst kommt, entscheidet der Zufall des Laufs.

        Seit Ticket 56 liefert auch die Bibliothek einen — zwei *Haeuser* statt
        zweier Fassungen desselben. Die Regel bleibt trotzdem die alte: 2 von 23
        zugeordneten Buechern haengen an beiden, und 52 der 53 Buch-Zeilen
        tragen ueberhaupt keinen Klappentext. Ein Vorrang fuer zwei Faelle waere
        geraten; gemessen wird er, wenn die Zahl nach dem naechsten Lauf steht.
        """
        found: dict[int, str] = {}
        for observation in observations:
            if observation.book_id and observation.blurb:
                before = found.get(observation.book_id, "")
                if len(observation.blurb) > len(before):
                    found[observation.book_id] = observation.blurb
        if not found:
            return
        with self.session() as session:
            for book_id, blurb in found.items():
                row = session.get(BookRow, book_id)
                if row is not None and len(blurb) > len(row.blurb or ""):
                    row.blurb = blurb
            session.commit()

    def append(
        self,
        run_id: int,
        profile_slug: str,
        observations: Sequence[Observation],
        observed_at: datetime,
    ) -> None:
        if not observations:
            return
        # Der Klappentext eines Buches gehoert an die ``book``-Zeile, nicht in
        # jede Beobachtung: er aendert sich nicht, sie wiederholt sich taeglich
        # (Ticket 52). Eine Entdeckung hat keine Buch-Zeile und behaelt ihn.
        self._remember_blurbs(observations)
        with self.session() as session:
            session.add_all(
                ObservationRow(
                    run_id=run_id,
                    profile_slug=profile_slug,
                    source=obs.source,
                    source_item_id=obs.source_item_id,
                    match_reason=str(obs.match_reason),
                    watchlist_key=obs.watchlist_key,
                    book_id=obs.book_id,
                    title=obs.title,
                    author=obs.author,
                    price_cents=obs.price_cents,
                    original_price_cents=obs.original_price_cents,
                    availability=str(obs.availability) if obs.availability else None,
                    reservation_count=obs.reservation_count,
                    available_from=obs.available_from,
                    category=obs.category,
                    url=obs.url,
                    blurb=None if obs.book_id else obs.blurb,
                    cover_url=obs.cover_url,
                    rating=obs.rating,
                    rating_votes=obs.rating_votes,
                    pages=obs.pages,
                    subtitle=obs.subtitle,
                    isbn=obs.isbn,
                    series=obs.series,
                    observed_at=obs.observed_at or observed_at,
                )
                for obs in observations
            )
            for obs in observations:
                if obs.isbn and obs.series:
                    _file_series(session, obs.isbn, obs.series, obs.author,
                                 obs.series_index, obs.source, obs.series_ref)
                # Der Titel als Zeuge (ADR 38), auch neben der Quelle: wer
                # vorgeht, entscheidet die Rangfolge beim Lesen, nicht das
                # Schreiben — ein Name der Quelle ohne Band lässt den Band
                # vom Titel gelten (Review 06.10.2026).
                if obs.isbn:
                    if witness := series_from_title(obs.title, obs.subtitle):
                        _file_series(session, obs.isbn, witness[0], obs.author,
                                     witness[1], "title")
                if obs.isbn and session.get(WorkEntryRow, (obs.isbn, "title")) is None:
                    _file_work(session, obs.isbn, obs.author, obs.title, "title")
                if obs.isbn and obs.bisac:
                    _file_bisac(session, obs.isbn, obs.source, obs.bisac)
            session.commit()


