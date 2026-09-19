"""The Snapshot: an append-only SQLite log of Observations plus a Run journal (ADR 5).

Phase 1 keys rows by the profile *slug* — the ``profile`` and ``watchlist_entry``
tables arrive in Phase 2 when the UI takes ownership of configuration (ADR 10).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    and_,
    case,
    create_engine,
    delete,
    event,
    func,
    or_,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .books import BookLike
from .books import find as find_book
from .cleaning import author_key, preferred_spelling
from .migrations import migrate
from .models import LINK_OUTCOMES, Availability, MatchReason, Observation
from .ratings import PROFILE_BOUND, RATING_ORIGINS
from .relations import RelationKind, check_details, check_interest_key, check_relation_kind


class Base(DeclarativeBase):
    pass


#: Der Ausloeser eines **engen** Laufs — einer, der genau einen
#: Watchlist-Eintrag ansieht (Ticket 51). Er bekommt eine eigene Zeile, weil
#: seine Beobachtung eine braucht, zaehlt aber nirgends als "der letzte Lauf".
ENTRY_TRIGGER = "entry"


class RunRow(Base):
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String, index=True)
    trigger: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")
    delta_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The OS process doing the work. An unfinished row says nothing on its own
    #: — a killed Run never gets to write ``finished_at`` — so whoever asks
    #: "is a Run still going?" needs something it can check (Ticket 10).
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ObservationRow(Base):
    __tablename__ = "observation"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    profile_slug: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_item_id: Mapped[str] = mapped_column(String, index=True)
    match_reason: Mapped[str] = mapped_column(String)
    watchlist_key: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Gesetzt bei Watchlist-Pruefungen, NULL bei Entdeckungen. Ohne das haette
    #: eine Verfuegbarkeitsmeldung der Bibliothek keinen Bezugspunkt (ADR 18).
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[str | None] = mapped_column(String, nullable=True)
    reservation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_from: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    blurb: Mapped[str | None] = mapped_column(String, nullable=True)
    subtitle: Mapped[str | None] = mapped_column(String, nullable=True)
    isbn: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    series: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Die Adresse des Titelbilds beim Shop — **nicht** das Bild selbst und
    #: nicht der lokale Dateiname. Die Kachel der Trefferliste trägt sie schon
    #: mit, sie war nur nie gespeichert worden: bis hierher las der Parser sie
    #: aus, die Quelle setzte sie, und der Store warf sie weg. Für einen
    #: Watchlist-Titel fiel das nie auf, weil die Bilder im selben Lauf geholt
    #: werden; für eine Entdeckung ging sie jedes Mal verloren (Ticket 15).
    cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Der Schnitt der Leserstimmen dieser Quelle und ihre Anzahl (Ticket 54).
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_votes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    # Serves the max-id-per-item lookup that every diff starts with.
    __table_args__ = (
        Index("ix_observation_item", "profile_slug", "source", "source_item_id", "id"),
    )


class BookRow(Base):
    """A book the reader has a relationship with (ADR 18).

    A row exists because something was said about this book — watched, owned,
    liked, dismissed — never for a bare discovery. 243 items arrived on the
    first real Run, most of them duplicates of each other across sources and
    editions, and a table called ``book`` whose majority is unvetted duplicates
    would not deserve the name.

    Identity is the ISBN where there is one. It identifies an *edition*, not a
    work, and it is not a general key across sources: of the two books this
    watchlist has at both, one shares an ISBN and one does not. The matcher and
    its confidence gate carry the rest (ADR 8, ADR 18).
    """

    __tablename__ = "book"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: NULL for bundles, collections and single episodes, which carry no ISBN.
    isbn: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    series: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Der Band innerhalb der Reihe, wie die DNB ihn nennt — Text, nicht Zahl:
    #: "2", aber auch "2.5" oder "Sonderband" (#10).
    series_index: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Dateiname im Cover-Ordner, nicht die Adresse beim Shop: die Seite
    #: laedt nichts von einem Dritten nach (Ticket 15).
    cover_file: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Der Klappentext — **einmal**, am Buch und nicht an jeder Beobachtung.
    #:
    #: Er ist ein Stammdatum und kein Messwert: er aendert sich praktisch nie,
    #: im Gegensatz zu Preis und Verfuegbarkeit. Ihn in jede Beobachtung zu
    #: schreiben kostete rund zehn Megabyte im Jahr fuer denselben Text
    #: (Ticket 52). Eine Entdeckung hat keine ``book``-Zeile und traegt ihn
    #: deshalb weiterhin in ihrer Beobachtung — dort liest ihn das
    #: Bewertungstor.
    blurb: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (Index("ix_book_title", "title"),)


class DnbRecordRow(Base):
    """Was die DNB zu einer ISBN gesagt hat — auch das Schweigen (Ticket 42).

    An der **ISBN** und nicht an einem Buch: eine ``book``-Zeile entsteht erst
    durch eine Entscheidung der Leserin (ADR 18), ein Fund hat keine. Die
    Sammelausgabe "David Hunter: 3in1 Bundle" ist genau so ein Fund — an ein
    Buch geknuepft waere die Auskunft ausgerechnet dort nicht speicherbar,
    wofuer sie gebraucht wird.

    ``found`` haelt fest, dass gefragt wurde und nichts kam. Neun von dreissig
    Buechern kennt die DNB nicht; ohne diesen Vermerk fragte jeder Lauf sie
    erneut.
    """

    __tablename__ = "dnb_record"

    isbn: Mapped[str] = mapped_column(String, primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime)
    found: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    subtitle: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    series: Mapped[str | None] = mapped_column(String, nullable=True)
    series_index: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)


class DnbContainsRow(Base):
    """Die ISBNs der Baende einer Sammelausgabe, aus MARC ``770 $i Enthaelt``.

    Die Entsprechung zu ONIX "01 includes". Der enthaltene Band muss bei uns
    kein Buch sein — die ISBN bleibt richtig, auch wenn er nie eines wird.
    """

    __tablename__ = "dnb_contains"

    isbn: Mapped[str] = mapped_column(String, primary_key=True)
    contained: Mapped[str] = mapped_column(String, primary_key=True)


class BookSourceRow(Base):
    """Where one Source keeps this book — including the answer "nowhere".

    One row per Source: the Onleihe's title id and beam's product id are
    different values for the same book, so they are different rows rather than
    competing keys in one bag.

    A row with no ``url`` is not a contradiction but an answer — "searched
    here, not stocked". Eight of the reader's ten watchlist titles are in that
    state at the Onleihe, and this row is what stops them being searched for
    again every day.
    """

    __tablename__ = "book_source"

    book_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    source_item_id: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime)
    #: outcome, reason, and the title and author *as that Source rendered
    #: them* - the last two exist so a wrong automatic resolution stays visible
    #: (ADR 9). JSON rather than columns: nothing filters or sorts on them.
    details: Mapped[str] = mapped_column(String, default="{}")


class RatingRow(Base):
    """Was das Werkzeug von einem Buch hält (ADR 19).

    Bewusst **nicht** an der ``book``-Zeile. ADR 18 hält fest, dass ein Buch nur
    entsteht, wo die Leserin eine Beziehung hat — 243 Funde kamen im ersten
    echten Lauf herein, und eine Tabelle namens ``book``, die mehrheitlich aus
    ungeprüften Dubletten besteht, verdient den Namen nicht. Ratings an die
    Buch-Zeile zu hängen hätte genau das erzwungen: dreihundert Buch-Zeilen pro
    Lauf, damit das Tor irgendwo hinschreiben kann.

    Der Schlüssel ist deshalb der Fund selbst: die ISBN, wo es eine gibt,
    sonst ``(Quelle, Item-Id)``. Ein Buch, das später eine Beziehung bekommt,
    findet sein Urteil über die ISBN wieder.

    Was ein Mensch sagt, hängt dagegen am Buch — ``book:<id>``. Er vergibt seine
    Sterne auf der Buchseite, und sie sollen gelten, egal über welche Quelle das
    Buch das nächste Mal hereinkommt (Ticket 21).

    Maschinensterne und die der Leserin bleiben getrennt — und zwar dadurch,
    dass ``origin`` dabeisteht und Teil des Schlüssels ist: eine 4 von ihr ist
    eine Tatsache, eine 4 vom Modell ein Vorschlag. Beide dürfen nebeneinander
    stehen, und keines überschreibt das andere (ADR 17, ADR 19, Ticket 21).
    """

    __tablename__ = "rating"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: ``isbn:978…`` oder ``item:beam:1279702`` beim Tor, ``book:42`` bei einem
    #: Urteil über ein Buch.
    subject: Mapped[str] = mapped_column(String)
    #: Wer geurteilt hat. Solange es nur eine Herkunft gab, war das entbehrlich;
    #: mit den Urteilen aus dem Gespräch und denen der Leserin sind es drei.
    origin: Mapped[str] = mapped_column(String, default="model")
    #: Nachkommastellen sind erlaubt, weil fremde Stimmen sie mitbringen: die
    #: Onleihe nennt auf ihrer Trefferkarte 2.8, und zwischen 2 und 3 liegt bei
    #: einer Regel mit dem Angelpunkt "3 ist Durchschnitt" die Entscheidung.
    #: Die eigenen Urteile bleiben ganzzahlig — das erzwingt das Schema
    #: (``rating.parse_answer``), nicht die Spalte (Ticket 54).
    stars: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    #: Ein Satz für die Leserin, warum das Buch in Frage kommt — im Digest und
    #: auf der Vorschlagsseite. Getrennt von ``reason``: die Begründung ist ein
    #: Protokoll zum Nachprüfen und nennt auch, was fehlt.
    pitch: Mapped[str] = mapped_column(String, default="")
    #: Auf wie vielen Stimmen die Angabe ruht — nur bei fremden Bewertungen.
    #: 5,0 aus einer Stimme ist keine Auskunft, 2,8 aus 1641 schon
    #: (Ticket 54).
    votes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Die Fassung des Leseprofils, gegen die geurteilt wurde. Eine neue
    #: Fassung macht ein Maschinenurteil ungültig — das ist die eine Änderung,
    #: bei der ein erneuter Aufruf richtig ist. Eine Änderung am
    #: Bewertungsschema tut das ausdrücklich nicht (ADR 21).
    profile_version: Mapped[int] = mapped_column(Integer)
    rated_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("subject", "origin", name="uq_rating"),)


class BookRelationRow(Base):
    """Was die Leserin zu einem Buch sagt (ADR 18).

    Eine Tabelle für alle fünf Beziehungen, weil sie alle dasselbe sagen — nur
    die Art unterscheidet sich. Vorher lagen dieselben Bücher in vier Dateien:
    *Cold Eternity* stand in ``owned.yaml`` als Titel, in ``dismissed.yaml`` als
    beam-Produktnummer, und war einmal eine Zeile in ``watchlist.yaml``. Ein
    Buch als vorhanden zu markieren kostete zwei Bearbeitungen in zwei Formaten,
    und die Ablehnung galt nur für einen Shop.

    Beziehungen werden **deaktiviert, nicht gelöscht**. *Providence* heute von
    der Watchlist zu nehmen zerstörte die Tatsache, dass es je beobachtet wurde;
    ``active = false`` behält sie — "beobachtet, bis du es gekauft hast".
    """

    __tablename__ = "book_relation"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String, index=True)
    book_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    details: Mapped[str] = mapped_column(String, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("profile_slug", "book_id", "kind", name="uq_relation"),
    )


class InterestRow(Base):
    """Wo nach neuen Büchern gesehen werden soll (ADR 18).

    Referenzautor:in und Thema beantworten dieselbe Frage, also eine Tabelle.
    ``key`` ist Freitext, damit ein dritter Kanal — Verlag, Reihe, Schlagwort —
    einen Handler kostet und keine Migration; geprüft wird er beim Laden.
    """

    __tablename__ = "interest"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    details: Mapped[str] = mapped_column(String, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("profile_slug", "key", "value", name="uq_interest"),
    )


class InterestSeededRow(Base):
    """Dieses Interesse wurde bei dieser Quelle schon einmal angesehen.

    Löst ``seeded_scope`` ab und behebt einen Fehler, der beim Dokumentieren
    auffiel: der alte Schlüssel war ``(source, match_reason, category)``, und
    ``category`` blieb bei Autor:innen leer — **alle Autor:innen teilten sich
    also eine Aussaat**. Eine neue Referenzautor:in meldete daraufhin ihre
    ganze Backlist als Neuzugänge, während ein neues Thema still ansäte. Pro
    Interesse gehalten verhalten sich beide gleich.
    """

    __tablename__ = "interest_seeded"

    interest_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    seeded_at: Mapped[datetime] = mapped_column(DateTime)


class SourceRow(Base):
    """How a Source is faring — not what it is (ADR 18).

    Selectors, paths and base URLs stay with the parser they are versioned and
    tested with; a selector in a database would let someone break the parser
    without touching code. What lives here is what *running* produces: the
    probe result, which used to be printed and thrown away, and a switch to
    pause a Source without editing a file.

    Not keyed by profile: a Source is a shop or a library, and whether
    beam-shop's markup still parses is not a fact about a reader.

    Rows are never entered by hand; one appears when a Source first runs.
    """

    __tablename__ = "source"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_probe_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Zero after any success. Distinguishes a Source that just broke from one
    #: that has been broken for a week — the second needs a human, the first
    #: might be a redesign in progress.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class StateRow(Base):
    """Small bits of bookkeeping that belong to no other table."""

    __tablename__ = "state"

    profile_slug: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[datetime] = mapped_column(DateTime)


def _to_observation(row: ObservationRow) -> Observation:
    return Observation(
        source=row.source,
        source_item_id=row.source_item_id,
        title=row.title,
        match_reason=MatchReason(row.match_reason),
        blurb=row.blurb,
        subtitle=row.subtitle,
        isbn=row.isbn,
        series=row.series,
        author=row.author,
        watchlist_key=row.watchlist_key,
        book_id=row.book_id,
        price_cents=row.price_cents,
        original_price_cents=row.original_price_cents,
        availability=Availability(row.availability) if row.availability else None,
        reservation_count=row.reservation_count,
        available_from=row.available_from,
        category=row.category,
        url=row.url,
        cover_url=row.cover_url,
        rating=row.rating,
        rating_votes=row.rating_votes,
        observed_at=row.observed_at,
    )


def _tune_sqlite(connection, _record) -> None:
    """Zwei Prozesse teilen sich diese Datei: der Lauf und die Weboberflaeche.

    Gemessen, und die Messung sagt weniger, als sie zuerst schien: 600
    verschraenkte Schreibvorgaenge aus zwei Prozessen liefen **ohne einen
    einzigen Fehler** durch — vorher in 6,56 s, mit WAL in 1,86 s. Ein
    "database is locked" liess sich nur erzwingen, indem eine Transaktion
    kuenstlich offen gehalten wurde; so schreibt dieses Programm nirgends.

    Das ist also keine Reparatur, sondern Luft: WAL macht aus jedem Commit ein
    Anhaengen statt eines Umschreibens und laesst Leser waehrend eines
    Schreibvorgangs durch. ``busy_timeout`` sorgt dafuer, dass ein zweiter
    Schreiber wartet statt aufzugeben — 15 s sind grosszuegig fuer Vorgaenge,
    die Millisekunden dauern, und Warten ist hier immer die richtige Antwort.
    """
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=15000")
    finally:
        cursor.close()


def _better_spelling(kept: str | None, seen: str | None) -> str | None:
    """Die bessere Schreibweise **derselben** Person, sonst die bisherige.

    Der Shop liefert ``Barnes, S. A.``, die Watchlist sagt ``S.A. Barnes``, und
    wer zuerst da war, bestimmte bisher, wie das Buch für immer heißt — bei
    *Cold Eternity* und *Providence* war das der einmalige Auflöser aus
    ``dismissed.yaml``. Die Regel steht seit Ticket 16 in
    :mod:`ebook_watchlist.cleaning` und wurde hier nie angewandt (Ticket 23).

    Ausdrücklich nur *dieselbe* Person: stimmen die Namen nicht überein, bleibt
    stehen, was dasteht. Eine spätere Quelle ist nicht automatisch die bessere,
    und ein Namenswechsel wäre keine Schreibweise, sondern ein anderer Mensch.
    """
    if not seen or not seen.strip():
        return kept
    if not kept or not kept.strip():
        return seen.strip()
    if author_key(kept) != author_key(seen):
        return kept
    return preferred_spelling([kept, seen]) or kept


class Store:
    """Owns the SQLite file. Schema is created on first use."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{path}")
        event.listen(self._engine, "connect", _tune_sqlite)
        # Einmal je Datei, nicht je Verbindung: der Modus steht dauerhaft in
        # der Datenbank, ihn bei jedem Verbindungsaufbau zu setzen waere Arbeit
        # ohne Wirkung.
        with self._engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        migrate(self._engine, Base.metadata)

    def session(self) -> Session:
        return Session(self._engine)

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
            # Reihenfolge in ``profile.yaml``. Mit zwei Bibliotheken entschied
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
            paare = session.execute(
                select(BookSourceRow.source, BookSourceRow.source_item_id).where(
                    BookSourceRow.book_id == book_id,
                    BookSourceRow.source_item_id.is_not(None),
                )
            ).all()
            wege = [ObservationRow.book_id == book_id]
            wege += [
                and_(
                    ObservationRow.source == source,
                    ObservationRow.source_item_id == item_id,
                )
                for source, item_id in paare
            ]
            stmt = (
                select(ObservationRow)
                .where(ObservationRow.profile_slug == profile_slug, or_(*wege))
                .order_by(ObservationRow.id.desc())
                .limit(limit)
            )
            return [_to_observation(row) for row in session.scalars(stmt)]

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
            preise: dict[str, int] = {}
            for titel, preis in session.execute(stmt):
                if not titel or preis is None or preis <= 0:
                    continue
                # Der guenstigste gewinnt: derselbe Titel kann als mehrere
                # Ausgaben dastehen, und fuer den Vergleich zaehlt, was der
                # Einzelband mindestens kostet.
                if titel not in preise or preis < preise[titel]:
                    preise[titel] = preis
            return preise

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
            schon = select(DnbRecordRow.isbn)
            eigene = select(BookRow.isbn).where(BookRow.isbn.is_not(None))
            erst_die_buecher = case((ObservationRow.isbn.in_(eigene), 0), else_=1)
            stmt = (
                select(ObservationRow.isbn)
                .where(
                    ObservationRow.profile_slug == profile_slug,
                    ObservationRow.isbn.is_not(None),
                    ObservationRow.isbn.not_in(schon),
                )
                .group_by(ObservationRow.isbn)
                .order_by(erst_die_buecher, func.max(ObservationRow.id).desc())
                .limit(limit)
            )
            return [isbn for (isbn,) in session.execute(stmt) if isbn]

    def save_dnb(self, isbn: str, record, now: datetime) -> None:
        """Die Antwort festhalten — **auch wenn keine kam**.

        ``record is None`` heisst "gefragt, nichts gewusst". Ohne diese Zeile
        fragte jeder Lauf dieselben neun von dreissig erneut.
        """
        with self.session() as session:
            zeile = session.get(DnbRecordRow, isbn)
            if zeile is None:
                zeile = DnbRecordRow(isbn=isbn)
                session.add(zeile)
            zeile.checked_at = now
            zeile.found = record is not None
            if record is not None:
                zeile.title = record.title
                zeile.subtitle = record.subtitle
                zeile.author = record.author
                zeile.series = record.series
                zeile.series_index = record.series_index
                zeile.language = record.language
                for enthalten in record.contains:
                    if session.get(DnbContainsRow, (isbn, enthalten)) is None:
                        session.add(DnbContainsRow(isbn=isbn, contained=enthalten))
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
            preise: dict[str, int] = {}
            for isbn_wert, preis in session.execute(stmt):
                if not isbn_wert or preis is None or preis <= 0:
                    continue
                if isbn_wert not in preise or preis < preise[isbn_wert]:
                    preise[isbn_wert] = preis
            return preise

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

    def get_state(self, profile_slug: str, key: str) -> datetime | None:
        with self.session() as session:
            row = session.get(StateRow, (profile_slug, key))
            return row.value if row is not None else None

    def set_state(self, profile_slug: str, key: str, value: datetime) -> None:
        with self.session() as session:
            row = session.get(StateRow, (profile_slug, key))
            if row is None:
                row = StateRow(profile_slug=profile_slug, key=key)
                session.add(row)
            row.value = value
            session.commit()

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
            gefuellt = 0
            zeilen = session.execute(
                select(BookRow, DnbRecordRow)
                .join(DnbRecordRow, DnbRecordRow.isbn == BookRow.isbn)
                .where(
                    BookRow.series.is_(None),
                    DnbRecordRow.found.is_(True),
                    DnbRecordRow.series.is_not(None),
                )
            ).all()
            for buch, datensatz in zeilen:
                buch.series = datensatz.series
                buch.series_index = datensatz.series_index
                gefuellt += 1
            session.commit()
            return gefuellt

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
        gefunden: dict[int, list[BookSourceRow]] = {book_id: [] for book_id in wanted}
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
                gefunden[row.book_id].append(row)
            return gefunden

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
            beobachtet = select(BookRelationRow.book_id).where(
                BookRelationRow.profile_slug == profile_slug,
                BookRelationRow.kind == str(RelationKind.WATCHING),
                BookRelationRow.active.is_(True),
            )
            stmt = (
                select(BookSourceRow)
                .where(
                    BookSourceRow.book_id.in_(beobachtet),
                    BookSourceRow.details.like('%"unsure"%'),
                )
                .order_by(BookSourceRow.book_id)
            )
            rows = list(session.scalars(stmt))
            for row in rows:
                session.expunge(row)
            return rows

    def reject_candidates(
        self, book_id: int, source: str, urls: Iterable[str], *, now: datetime
    ) -> None:
        """Alle gezeigten Kandidaten ablehnen — „keiner davon" (Ticket 41).

        Festgehalten werden die **Adressen**, nicht bloss die Tatsache: dieselben
        Kandidaten werden nicht noch einmal vorgelegt, ein **neuer** schon.
        Einen einzelnen abzulehnen gibt es nicht mehr — waehlt man den
        richtigen, sind die anderen ohnehin erledigt.
        """
        with self.session() as session:
            row = session.get(BookSourceRow, (book_id, source))
            if row is None:
                return
            details = json.loads(row.details or '{}')
            abgelehnt = list(details.get('rejected') or [])
            for url in urls:
                if url and url not in abgelehnt:
                    abgelehnt.append(url)
            details['rejected'] = abgelehnt
            row.details = json.dumps(details, ensure_ascii=False)
            row.resolved_at = now
            session.commit()

    def restore_candidates(self, book_id: int, source: str, *, now: datetime) -> None:
        """Eine Ablehnung zuruecknehmen — ein Irrtum beim Wegklicken darf nicht
        dauerhaft sein (ADR 18)."""
        with self.session() as session:
            row = session.get(BookSourceRow, (book_id, source))
            if row is None:
                return
            details = json.loads(row.details or '{}')
            details['rejected'] = []
            row.details = json.dumps(details, ensure_ascii=False)
            row.resolved_at = now
            session.commit()

    def reject_candidate(
        self, book_id: int, source: str, url: str, *, now: datetime, undo: bool = False
    ) -> None:
        """Einen Kandidaten ablehnen — oder die Ablehnung zuruecknehmen.

        Festgehalten wird die Adresse, nicht bloss die Tatsache: derselbe
        Kandidat wird nicht noch einmal vorgelegt, ein **neuer** schon. Und
        umkehrbar, weil ein Irrtum beim Wegklicken sonst dauerhaft waere
        (ADR 18, Ticket 41).
        """
        with self.session() as session:
            row = session.get(BookSourceRow, (book_id, source))
            if row is None:
                return
            details = json.loads(row.details or "{}")
            abgelehnt = list(details.get("rejected") or [])
            if undo:
                abgelehnt = [eintrag for eintrag in abgelehnt if eintrag != url]
            elif url not in abgelehnt:
                abgelehnt.append(url)
            details["rejected"] = abgelehnt
            row.details = json.dumps(details, ensure_ascii=False)
            row.resolved_at = now
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

    # --- Bewertungen (Ticket 12) -------------------------------------------

    def rating(
        self, subject: str, profile_version: int, *, origin: str = "model"
    ) -> RatingRow | None:
        """Das gespeicherte Urteil einer Herkunft — wenn es zum Profil passt.

        Die Versionsprüfung gilt nur für Maschinenurteile; was die Leserin
        selbst gesagt hat, verfällt nicht, wenn sie ihr Profil schärft. Und sie
        gilt gegen das **Leseprofil**, nicht gegen das Bewertungsschema — das
        trägt gar keine Version (ADR 21).
        """
        with self.session() as session:
            row = session.scalars(
                select(RatingRow).where(
                    RatingRow.subject == subject, RatingRow.origin == origin
                )
            ).first()
            if row is None:
                return None
            # Nur profilgebundene Urteile veralten mit einer neuen Fassung.
            # Vorher stand hier "nicht menschlich" — und liess damit eine
            # fremde Leserstimme durchfallen, die mit dem Profil nie etwas zu
            # tun hatte (Ticket 54).
            if origin in PROFILE_BOUND and row.profile_version != profile_version:
                return None
            session.expunge(row)
            return row

    def ratings_for(self, subjects: Iterable[str]) -> dict[tuple[str, str], RatingRow]:
        """Alle Urteile zu diesen Schlüsseln, nach ``(Schlüssel, Herkunft)``."""
        wanted = set(subjects)
        if not wanted:
            return {}
        with self.session() as session:
            rows = list(
                session.scalars(select(RatingRow).where(RatingRow.subject.in_(wanted)))
            )
            for row in rows:
                session.expunge(row)
            return {(row.subject, row.origin): row for row in rows}

    def drop_rating(self, subject: str, origin: str) -> bool:
        """Ein Urteil zurücknehmen; ``True``, wenn eines dastand.

        Nur die Leserin nimmt zurück, und sie tut es, indem sie ihre eigenen
        Sterne noch einmal anklickt. Eine Null wäre dafür kein Ersatz: sie
        hieße "passt überhaupt nicht" und ist selbst ein Urteil.
        """
        with self.session() as session:
            row = session.scalars(
                select(RatingRow).where(
                    RatingRow.subject == subject, RatingRow.origin == origin
                )
            ).first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def put_rating(
        self,
        subject: str,
        *,
        stars: float,
        confidence: str,
        reason: str,
        profile_version: int,
        now: datetime,
        origin: str = "model",
        pitch: str = "",
        votes: int | None = None,
    ) -> None:
        """Ein Urteil festhalten.

        Der Schlüssel ist ``(subject, origin)``: das Urteil der Leserin und das
        des Modells stehen nebeneinander, und keines überschreibt das andere
        (ADR 17, Ticket 21).
        """
        if origin not in RATING_ORIGINS:
            raise ValueError(
                f"unbekannte Herkunft {origin!r} "
                f"(bekannt: {', '.join(sorted(RATING_ORIGINS))})"
            )
        with self.session() as session:
            row = session.scalars(
                select(RatingRow).where(
                    RatingRow.subject == subject, RatingRow.origin == origin
                )
            ).first()
            if row is None:
                row = RatingRow(subject=subject, origin=origin)
                session.add(row)
            row.stars = stars
            row.confidence = confidence
            row.votes = votes
            row.pitch = pitch
            row.reason = reason
            row.profile_version = profile_version
            row.rated_at = now
            session.commit()

    # --- Beziehungen und Interessen (Ticket 05) ----------------------------

    def put_relation(
        self,
        profile_slug: str,
        book_id: int,
        kind: str,
        *,
        active: bool = True,
        now: datetime,
        **details: object,
    ) -> None:
        """Was die Leserin zu einem Buch sagt. Mehrere Arten gelten gleichzeitig."""
        check_relation_kind(kind)
        check_details(kind, dict(details))
        with self.session() as session:
            row = session.scalars(
                select(BookRelationRow).where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.book_id == book_id,
                    BookRelationRow.kind == kind,
                )
            ).first()
            if row is None:
                row = BookRelationRow(
                    profile_slug=profile_slug,
                    book_id=book_id,
                    kind=kind,
                    created_at=now,
                )
                session.add(row)
            row.active = active
            if details:
                row.details = json.dumps(details, ensure_ascii=False)
            session.commit()

    def set_relation_details(
        self, profile_slug: str, book_id: int, kind: str, details: dict, *, now: datetime
    ) -> None:
        """Den Beutel *ersetzen*, auch wenn er leer wird.

        ``put_relation`` laesst vorhandene Angaben in Ruhe, wenn der Aufrufer
        keine mitgibt — sonst loeschte jedes Pausieren die Notizen. Wer etwas
        wegnehmen will, braucht deshalb diesen Weg: sonst liesse sich eine
        Einschraenkung setzen, aber nie wieder aufheben.
        """
        check_relation_kind(kind)
        check_details(kind, details)
        with self.session() as session:
            row = session.scalars(
                select(BookRelationRow).where(
                    BookRelationRow.profile_slug == profile_slug,
                    BookRelationRow.book_id == book_id,
                    BookRelationRow.kind == kind,
                )
            ).first()
            if row is None:
                row = BookRelationRow(
                    profile_slug=profile_slug, book_id=book_id, kind=kind, created_at=now
                )
                session.add(row)
                row.active = True
            row.details = json.dumps(details, ensure_ascii=False)
            session.commit()

    def relations(
        self, profile_slug: str, *, kind: str | None = None, active_only: bool = True
    ) -> list[BookRelationRow]:
        with self.session() as session:
            stmt = select(BookRelationRow).where(BookRelationRow.profile_slug == profile_slug)
            if kind is not None:
                stmt = stmt.where(BookRelationRow.kind == kind)
            if active_only:
                stmt = stmt.where(BookRelationRow.active.is_(True))
            rows = list(session.scalars(stmt.order_by(BookRelationRow.id)))
            for row in rows:
                session.expunge(row)
            return rows

    def relations_of(self, profile_slug: str, book_id: int) -> list[BookRelationRow]:
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(BookRelationRow).where(
                        BookRelationRow.profile_slug == profile_slug,
                        BookRelationRow.book_id == book_id,
                    )
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def deactivate_relation(
        self, profile_slug: str, book_id: int, kind: str, *, now: datetime
    ) -> None:
        """Beziehungen werden deaktiviert, nicht geloescht — die Tatsache, dass
        ein Buch einmal beobachtet wurde, ist selbst eine Auskunft (ADR 18).

        Die Uhr wird uebergeben, nicht gelesen: ein Store, der selbst nach der
        Zeit sieht, laesst sich nicht mit einer festen Uhr pruefen.
        """
        self.put_relation(profile_slug, book_id, kind, active=False, now=now)

    def put_interest(
        self,
        profile_slug: str,
        key: str,
        value: str,
        *,
        active: bool = True,
        now: datetime,
        **details: object,
    ) -> InterestRow:
        check_interest_key(key)
        check_details(key, dict(details))
        with self.session() as session:
            row = session.scalars(
                select(InterestRow).where(
                    InterestRow.profile_slug == profile_slug,
                    InterestRow.key == key,
                    InterestRow.value == value,
                )
            ).first()
            if row is None:
                row = InterestRow(
                    profile_slug=profile_slug, key=key, value=value, created_at=now
                )
                session.add(row)
            row.active = active
            if details:
                row.details = json.dumps(details, ensure_ascii=False)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    def interests(
        self, profile_slug: str, *, key: str | None = None, active_only: bool = True
    ) -> list[InterestRow]:
        with self.session() as session:
            stmt = select(InterestRow).where(InterestRow.profile_slug == profile_slug)
            if key is not None:
                stmt = stmt.where(InterestRow.key == key)
            if active_only:
                stmt = stmt.where(InterestRow.active.is_(True))
            rows = list(session.scalars(stmt.order_by(InterestRow.id)))
            for row in rows:
                session.expunge(row)
            return rows

    def is_interest_seeded(self, interest_id: int, source: str) -> bool:
        with self.session() as session:
            return session.get(InterestSeededRow, (interest_id, source)) is not None

    def mark_interest_seeded(self, interest_id: int, source: str, *, now: datetime) -> None:
        """Pro Interesse, nicht pro Anlass.

        Der alte Schluessel liess ``category`` bei Autor:innen leer, so dass
        sich *alle* Autor:innen eine Aussaat teilten: die erste saete still an,
        jede weitere meldete ihre ganze Backlist als Neuzugaenge.
        """
        with self.session() as session:
            if session.get(InterestSeededRow, (interest_id, source)) is None:
                session.add(
                    InterestSeededRow(interest_id=interest_id, source=source, seeded_at=now)
                )
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
        gefunden: dict[int, str] = {}
        for observation in observations:
            if observation.book_id and observation.blurb:
                vorher = gefunden.get(observation.book_id, "")
                if len(observation.blurb) > len(vorher):
                    gefunden[observation.book_id] = observation.blurb
        if not gefunden:
            return
        with self.session() as session:
            for book_id, blurb in gefunden.items():
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
                    subtitle=obs.subtitle,
                    isbn=obs.isbn,
                    series=obs.series,
                    observed_at=obs.observed_at or observed_at,
                )
                for obs in observations
            )
            session.commit()
