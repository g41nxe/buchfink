"""Die Tabellen des Snapshots und was mehrere Fachgebiete an ihnen brauchen (#103).

Hier stehen die Zeilen (`RunRow`, `BookRow` …), ihre Konstanten und die
Hilfsfunktionen, die beim Ablegen von Reihen, Werken und BISAC-Codes von mehr
als einem Fachgebiet gebraucht werden. Die Methoden des `Store` liegen nach
Fachgebiet in den Nachbarmodulen.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from ..catalog.series import series_key
from ..catalog.work import work_key
from ..cleaning import author_key, preferred_spelling
from ..judging.portrait import Portrait, Trait
from ..models import Availability, MatchReason, Observation

#: Wie oft eine neue Fassung bei einer Kollision der Nummer erneut versucht wird.
_VERSION_ATTEMPTS = 20


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
    #: Die Seitenzahl, von der Detailseite (#73).
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


#: Die Fassung, in der ``dnb.parse`` einen Datensatz liest. Hochzaehlen, wenn
#: es ein Feld mehr liest: dann werden die schon gefundenen einmal neu gefragt.
#: 2 = Originaltitel und Schlagwoerter (#17), 3 = Verlag (#28),
#: 4 = Seitenzahl (#82), 5 = BISAC-Codes (#88).
DNB_READING = 5


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
    original_title: Mapped[str | None] = mapped_column(String, nullable=True)
    #: JSON-Liste der Schlagwoerter aus ``653``.
    keywords: Mapped[str | None] = mapped_column(String, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Die Seitenzahl aus ``300 $a``, wo die DNB sie nennt (#82).
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Mit welcher Fassung des Auslesens die Antwort gelesen wurde. Liest der
    #: Parser mehr als frueher, wird ein altes Ja einmal neu gefragt (#17).
    reading: Mapped[int] = mapped_column(Integer, default=DNB_READING)


class DnbContainsRow(Base):
    """Die ISBNs der Baende einer Sammelausgabe, aus MARC ``770 $i Enthaelt``.

    Die Entsprechung zu ONIX "01 includes". Der enthaltene Band muss bei uns
    kein Buch sein — die ISBN bleibt richtig, auch wenn er nie eines wird.
    """

    __tablename__ = "dnb_contains"

    isbn: Mapped[str] = mapped_column(String, primary_key=True)
    contained: Mapped[str] = mapped_column(String, primary_key=True)


class SeriesRow(Base):
    """Eine Reihe, gleich unter welchem Namen eine Quelle sie führt (ADR 35).

    ``key`` ist der Schlüssel des ersten Namens (`series.series_key`), ``name``
    der, unter dem sie zuerst kam. Die Adressen sind die eigenen Nummern der
    Reihe bei den Quellen, unter denen sie sich fegen lässt (#85).
    """

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    author_key: Mapped[str] = mapped_column(String, default="")
    overdrive_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    onleihe_ref: Mapped[str | None] = mapped_column(String, nullable=True)


class SeriesNameRow(Base):
    """Ein Schlüssel einer Autor:in, und zu welcher Reihe er gehört.

    Zwei Schlüssel zeigen auf dieselbe Reihe, wenn zwei Quellen sie für dieselbe
    ISBN nennen. Die Autor:in steht im Schlüssel, damit „Die Chroniken" zweier
    Leute zwei Reihen bleiben.
    """

    __tablename__ = "series_name"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    author_key: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[int] = mapped_column(Integer, index=True)


class SeriesEntryRow(Base):
    """Zu welcher Reihe eine ISBN gehört und als welcher Band — je Herkunft.

    Je ISBN und nicht am Buch: die Reihe wird schon für Funde gebraucht, und
    ein Buch entsteht erst durch eine Entscheidung der Leserin (ADR 18, 35). Die
    Herkunft bleibt, damit die Rangfolge beim Lesen entschieden wird.
    """

    __tablename__ = "series_entry"

    isbn: Mapped[str] = mapped_column(String, primary_key=True)
    origin: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[int] = mapped_column(Integer, index=True)
    #: Text wie ``series_index``: „3", „6.1", „Sonderband".
    volume: Mapped[str | None] = mapped_column(String, nullable=True)


class SeriesWatchRow(Base):
    """Dass die Leserin eine Reihe beobachtet (#85).

    Wie eine Buchbeziehung abgeschaltet statt gelöscht: „beobachtet bis …"
    bleibt eine Auskunft (ADR 18).
    """

    __tablename__ = "series_watch"

    profile_slug: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    since: Mapped[datetime] = mapped_column(DateTime)


class BisacEntryRow(Base):
    """Die BISAC-Codes einer ISBN, je Herkunft (ADR 37, #88).

    Vom Verlag vergeben und von der DNB oder OverDrive weitergereicht — nicht
    vom Modell. Alle bleiben gespeichert; welche für das Genre zählen, sagt die
    Liste (`genres.py`).
    """

    __tablename__ = "bisac_entry"

    isbn: Mapped[str] = mapped_column(String, primary_key=True)
    origin: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, primary_key=True)
    #: Die Reihenfolge, in der die Herkunft sie nannte.
    rank: Mapped[int] = mapped_column(Integer, default=0)


#: Wessen BISAC-Codes zuerst stehen: die DNB spricht über genau diese ISBN.
BISAC_ORIGINS = ("dnb", "overdrive")


class SourceCategoryRow(Base):
    """Eine Quellkategorie, wie die Detailseiten sie nennen (#92).

    Die Onleihe hat kein Verzeichnis ihrer Kategorien; bekannt wird eine
    Nummer nur, wo eine Detailseite sie nennt. Gesammelt, damit die
    Genre-Tabelle der Quelle sich füllen lässt — kein Buch bekommt daraus ein
    Genre.
    """

    __tablename__ = "source_category"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    number: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    #: Wie oft eine geholte Detailseite sie nannte — Abholungen, nicht
    #: verschiedene Titel: ein neu beurteiltes Buch zählt noch einmal. Ein
    #: grober Anhalt, keine Statistik (Review 04.10.2026).
    count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    #: Ein Titel, der sie trug — hilft beim Zuordnen eines unklaren Namens.
    example: Mapped[str | None] = mapped_column(String, nullable=True)


class WorkEntryRow(Base):
    """Zu welchem Werk eine ISBN gehört — je Herkunft (ADR 36, #80).

    ``dnb``: Autor:in und Originaltitel aus der DNB, bei einer Übersetzung.
    ``title``: Autor:in und eigener Titel, wie eine Quelle ihn nennt. Die DNB
    geht vor; über die ISBN treffen sich so Übersetzung und Original.
    """

    __tablename__ = "work_entry"

    isbn: Mapped[str] = mapped_column(String, primary_key=True)
    origin: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, index=True)


@dataclass(frozen=True, slots=True)
class SeriesEntry:
    """Eine Zuordnung ISBN -> Reihe, wie sie eine Herkunft nennt."""

    isbn: str
    origin: str
    series_id: int
    volume: str | None


#: Wer bei Band und Reihe einer ISBN vorgeht: die DNB spricht über genau diese
#: ISBN, OverDrive vielleicht über das Werk (ADR 35). Der Titel zuletzt
#: (ADR 38), und eine Sammelausgabe erbt von ihren Bänden.
SERIES_ORIGINS = ("dnb", "overdrive", "onleihe", "title", "bundle")


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
    """Was ein Mensch von einem Buch hält: die Sterne der Leserin und der
    Durchschnitt fremder Leser:innen (ADR 17, ADR 33).

    Das Urteil der Anwendung selbst steht hier nicht: es wird aus Steckbrief und
    Profil gerechnet und nie gespeichert (#52).

    Was jemand sagt, hängt am Buch — ``book:<id>``, oder bei fremden Stimmen an
    der ISBN. Die Leserin vergibt ihre Sterne auf der Buchseite, und sie sollen
    gelten, egal über welche Quelle das Buch das nächste Mal hereinkommt
    (Ticket 21). ``origin`` ist Teil des Schlüssels: eine 4 von ihr ist eine
    Tatsache, ein fremder Durchschnitt sagt etwas über das Buch. Beide dürfen
    nebeneinander stehen, und keines überschreibt das andere (Ticket 54).
    """

    __tablename__ = "rating"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: ``isbn:978…`` oder ``item:beam:1279702`` beim Tor, ``book:42`` bei einem
    #: Urteil über ein Buch.
    subject: Mapped[str] = mapped_column(String)
    #: Wer geurteilt hat. Solange es nur eine Herkunft gab, war das entbehrlich;
    #: mit den Urteilen aus dem Gespräch und denen der Leserin sind es drei.
    origin: Mapped[str] = mapped_column(String, default="reader")
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
    #: Seit #52 ungenutzt: die Urteile des alten Sterne-Modells gibt es nicht
    #: mehr (ADR 33). Die Spalten ``via``, ``axes``, ``deducted``, ``model_stars``
    #: und ``pitch`` bleiben, weil die Datei sie schon trägt (ADR 16).
    via: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Welche Achsen das Urteil trifft und verfehlt, als JSON
    #: ``{"trifft": [...], "fehlt": [...]}`` (#12). JSON wie
    #: ``book_source.details``, weil nichts danach filtert oder sortiert.
    axes: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Was der Code nach dem Urteil abgezogen hat, als JSON-Liste, und die
    #: Sterne des Modells davor (#28). ``stars`` sind die geltenden: nach ihnen
    #: entscheiden Tor, Stapel und Tagesbericht, ohne den Abzug zu kennen.
    deducted: Mapped[str | None] = mapped_column(String, nullable=True)
    model_stars: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Die Fassung des Leseprofils, als die Leserin ihre Sterne gab (0: keine
    #: bekannt, und bei fremden Stimmen). Verfallen tut das Urteil damit nicht.
    profile_version: Mapped[int] = mapped_column(Integer)
    rated_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("subject", "origin", name="uq_rating"),)


class PortraitRow(Base):
    """Der Steckbrief eines Buchs: was das Modell einmal darüber sagt (#45, ADR 33).

    Geschlüsselt wie ein Urteil des Tors, an der ISBN, wo es eine gibt, sonst am
    Buch oder am Fund — damit findet der Lauf später denselben Steckbrief
    wieder, den die Buchseite angelegt hat.

    Append-only (ADR 5): ein neuer Steckbrief ersetzt keinen alten, er kommt
    dazu, und gelesen wird der jüngste mit passendem Fingerabdruck. Die
    Merkmale stehen als JSON da: nichts filtert oder sortiert danach, gelesen
    werden sie immer als Ganzes.
    """

    __tablename__ = "portrait"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String, index=True)
    fingerprint: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    known: Mapped[bool] = mapped_column(Boolean)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    original_title: Mapped[str | None] = mapped_column(String, nullable=True)
    genre: Mapped[str | None] = mapped_column(String, nullable=True)
    subgenre: Mapped[str | None] = mapped_column(String, nullable=True)
    pitch: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Ob beim Fragen ein Text beilag; ``NULL`` bei Zeilen aus der Zeit davor.
    with_text: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Ob die Leseprobe beilag (#76).
    with_sample: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Das Genre als Code der Liste und sein Name (ADR 37); der Freitext in
    #: ``genre``/``subgenre`` bleibt daneben.
    genre_code: Mapped[str | None] = mapped_column(String, nullable=True)
    genre_name: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Kurzgeschichte, Novelle, Roman (ADR 43); ``NULL`` heißt unbekannt.
    form: Mapped[str | None] = mapped_column(String, nullable=True)
    #: JSON-Liste aus ``{"term", "sentence", "evidence", "weight"}``.
    traits: Mapped[str] = mapped_column(String, default="[]")
    #: JSON-Liste der verletzten Regeln.
    violations: Mapped[str] = mapped_column(String, default="[]")


class ReadingProfileRow(Base):
    """Eine Fassung des Leseprofils: Facetten und Gegengewichte (#46, ADR 33).

    Append-only (ADR 5): jede Änderung ist eine neue Fassung mit ihrem Anlass,
    gelesen wird die jüngste. Facetten und Gegengewichte stehen als JSON da;
    gelesen werden sie immer als Ganzes.
    """

    __tablename__ = "reading_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    #: Warum es diese Fassung gibt, etwa "aus der Datei profil.yaml".
    cause: Mapped[str] = mapped_column(String)
    #: JSON: ``{"facets": [...], "counterweights": [...]}``.
    body: Mapped[str] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("profile_slug", "version", name="uq_reading_profile_version"),
    )


class IntakeEntryRow(Base):
    """Ein Buch, das die Leserin in der Erstaufnahme genannt hat (#47).

    Sofort gespeichert, noch bevor das Modell geantwortet hat: ein Abbruch
    verliert nichts, und wer die Seite wieder öffnet, findet seine Bücher.
    Wo ein Eintrag steht — gefragt, vorgeschlagen, unbekannt —, sagt sein
    Steckbrief, nicht eine Spalte hier; die Zeile hält nur fest, was die
    Leserin getan hat.
    """

    __tablename__ = "intake_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String, index=True)
    #: ``liked`` oder ``disliked`` — dieselben Wörter wie die Beziehungen.
    side: Mapped[str] = mapped_column(String)
    typed_title: Mapped[str] = mapped_column(String)
    typed_author: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    #: ``open``, ``confirmed`` oder ``removed``.
    status: Mapped[str] = mapped_column(String, default="open")
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class IntakeChoiceRow(Base):
    """Was die Leserin in der Erstaufnahme angetippt hat (#50).

    Auf Bildschirm 3 eine Familie, die sie an ihren Büchern hält (``loved``),
    auf Bildschirm 4 eine, die sie an einem enttäuschenden Buch verloren hat
    (``lost``, mit dem Buch und dem Umfang). Sofort gespeichert wie die
    Einträge: ein Abbruch verliert nichts.
    """

    __tablename__ = "intake_choice"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    family_id: Mapped[str] = mapped_column(String)
    #: Nur bei ``lost``: an welchem enttäuschenden Buch.
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Nur bei ``lost``: ``general``, ``here`` oder ``genre``.
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


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
    #: Unter welcher Adresse (Regal, Thema) angesät wurde; ``None`` bei
    #: Autor:innen und bei Zeilen von vor ADR 37.
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    seeded_at: Mapped[datetime] = mapped_column(DateTime)


class SourceRow(Base):
    """How a Source is faring — not what it is (ADR 18).

    Selectors, paths and base URLs stay with the parser they are versioned and
    tested with; a selector in a database would let someone break the parser
    without touching code. What lives here is what *running* produces: the
    probe result, which used to be printed and thrown away, and a switch to
    pause a Source without editing a file.

    Not keyed by settings: a Source is a shop or a library, and whether
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


class SettingRow(Base):
    """Eine Einstellung, die die Leserin in der Oberfläche geändert hat (#104).

    Liegt über ``settings.yaml``: die Datei ist nur noch der Startwert. Der
    Wert steht als JSON da, damit Zahlen Zahlen bleiben und eine Adresse eine
    Zeichenkette. Geprüft wird er beim Laden mit denselben Regeln wie die Datei
    (`config.load_settings`).
    """

    __tablename__ = "setting"

    profile_slug: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


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
        pages=row.pages,
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


#: Welcher Steckbrief eines Buchs gilt: einer mit Text vor jedem ohne, dann
#: ein bekannter vor einem „unbekannt", dann der mit den wenigsten
#: Regelverstößen (ADR 43), dann der jüngste. Eine Zeile aus der Zeit vor der
#: Spalte (``NULL``) zählt wie „ohne Text" — ob einer dabei war, weiß niemand
#: mehr.
_BEST_PORTRAIT_FIRST = (
    PortraitRow.with_text.is_(True).desc(),
    PortraitRow.known.desc(),
    func.json_array_length(PortraitRow.violations).asc(),
    PortraitRow.created_at.desc(),
    PortraitRow.id.desc(),
)


def _portrait_of(row: PortraitRow) -> Portrait:
    """Eine gespeicherte Zeile als Steckbrief."""
    return Portrait(
        known=row.known,
        fingerprint=row.fingerprint,
        title=row.title,
        author=row.author,
        original_title=row.original_title,
        genre=row.genre,
        subgenre=row.subgenre,
        pitch=row.pitch,
        traits=tuple(
            Trait(t["term"], t["sentence"], t["evidence"], t.get("weight"))
            for t in json.loads(row.traits)
        ),
        violations=tuple(json.loads(row.violations)),
        with_text=row.with_text,
        with_sample=row.with_sample,
        genre_code=row.genre_code,
        form=row.form,
    )


def _file_series(
    session: Session,
    isbn: str,
    name: str,
    author: str | None,
    volume: str | None,
    origin: str,
    ref: str | None = None,
) -> None:
    """Eine Angabe zur Reihe festhalten — und Namen zusammenführen (ADR 35).

    Ein Name gilt je Autor:in. Nennt eine andere Herkunft für dieselbe ISBN
    schon eine Reihe, ist es diese: „Ein Hunter-und-Garcia-Thriller" (DNB) und
    „Robert Hunter" (OverDrive) werden eine Reihe, ohne dass eine Regel sie
    gleich machen müsste.
    """
    key = series_key(name)
    writer = author_key(author) if author else ""
    session.flush()
    named = session.get(SeriesNameRow, (key, writer)) or _unknown_author_name(
        session, key, writer
    )
    elsewhere = session.scalars(
        select(SeriesEntryRow.series_id).where(
            SeriesEntryRow.isbn == isbn, SeriesEntryRow.origin != origin
        )
    ).first()
    if named is None:
        series_id = elsewhere
        if series_id is None:
            row = SeriesRow(key=key, name=name, author_key=writer)
            session.add(row)
            session.flush()
            series_id = row.id
        session.add(SeriesNameRow(key=key, author_key=writer, series_id=series_id))
    else:
        series_id = named.series_id
        if elsewhere is not None and elsewhere != series_id:
            series_id = _merge_series(session, keep=min(series_id, elsewhere),
                                      drop=max(series_id, elsewhere))
        if named.author_key != writer and session.get(SeriesNameRow, (key, writer)) is None:
            # Über eine unbekannte Autor:in gefunden: der Name gilt jetzt auch
            # unter dieser, damit ihn ein Fund dieser Autor:in wiederfindet.
            session.add(SeriesNameRow(key=key, author_key=writer, series_id=series_id))
    entry = session.get(SeriesEntryRow, (isbn, origin))
    if entry is None:
        session.add(SeriesEntryRow(isbn=isbn, origin=origin, series_id=series_id, volume=volume))
    else:
        entry.series_id = series_id
        entry.volume = volume or entry.volume
    if ref and origin in ("overdrive", "onleihe"):
        setattr(session.get(SeriesRow, series_id), f"{origin}_ref", ref)


def _unknown_author_name(session: Session, key: str, writer: str) -> SeriesNameRow | None:
    """Eine unbekannte Autor:in trennt nichts (Review, 04.10.2026).

    Eine DNB-Antwort ohne Autor:in legt „Ein Wayward-Pines-Thriller" unter
    (Schlüssel, leer) ab; OverDrive nennt dieselbe Reihe mit „Blake Crouch".
    Ohne Autor:in gilt die einzige Reihe dieses Schlüssels; mit Autor:in eine,
    die bisher keine kannte — sie gehört danach dieser. Zwei *bekannte*
    verschiedene bleiben zwei Reihen.
    """
    if writer:
        anonymous = session.get(SeriesNameRow, (key, ""))
        if anonymous is None:
            return None
        claimed = session.scalars(
            select(SeriesNameRow.author_key).where(
                SeriesNameRow.series_id == anonymous.series_id, SeriesNameRow.author_key != ""
            )
        ).first()
        if claimed is not None:
            return None
        session.get(SeriesRow, anonymous.series_id).author_key = writer
        return anonymous
    rows = session.scalars(select(SeriesNameRow).where(SeriesNameRow.key == key)).all()
    series = {row.series_id for row in rows}
    return rows[0] if len(series) == 1 else None


def _merge_series(session: Session, *, keep: int, drop: int) -> int:
    """Zwei Reihen sind eine: Namen, Bände und Adressen gehen auf ``keep``."""
    session.execute(update(SeriesNameRow).where(SeriesNameRow.series_id == drop)
                    .values(series_id=keep))
    session.execute(update(SeriesEntryRow).where(SeriesEntryRow.series_id == drop)
                    .values(series_id=keep))
    kept, dropped = session.get(SeriesRow, keep), session.get(SeriesRow, drop)
    kept.overdrive_ref = kept.overdrive_ref or dropped.overdrive_ref
    kept.onleihe_ref = kept.onleihe_ref or dropped.onleihe_ref
    # Beobachtet sie die Reihe, die verschwindet, beobachtet sie danach die
    # zusammengeführte — samt der Bände, die über sie kamen (Review, 04.10.2026).
    for watch in session.scalars(
        select(SeriesWatchRow).where(SeriesWatchRow.series_id == drop)
    ).all():
        other = session.get(SeriesWatchRow, (watch.profile_slug, keep))
        if other is None:
            session.add(SeriesWatchRow(profile_slug=watch.profile_slug, series_id=keep,
                                       active=watch.active, since=watch.since))
        else:
            other.active = other.active or watch.active
        session.delete(watch)
    for relation in session.scalars(
        select(BookRelationRow).where(BookRelationRow.details.contains('"series"'))
    ).all():
        details = json.loads(relation.details)
        if details.get("series") == drop:
            relation.details = json.dumps({**details, "series": keep}, ensure_ascii=False)
    session.delete(dropped)
    return keep


def _file_work(
    session: Session, isbn: str, author: str | None, title: str | None, origin: str
) -> None:
    """Das Werk einer ISBN festhalten, je Herkunft (ADR 36)."""
    key = work_key(author, title)
    if key is None:
        return
    entry = session.get(WorkEntryRow, (isbn, origin))
    if entry is None:
        session.add(WorkEntryRow(isbn=isbn, origin=origin, key=key))
    else:
        entry.key = key


def _work_keys(session: Session, isbns: Iterable[str]) -> dict[str, str]:
    """ISBN -> Werk; die DNB geht dem eigenen Titel vor."""
    wanted = {isbn for isbn in isbns if isbn}
    if not wanted:
        return {}
    session.flush()
    keys: dict[str, str] = {}
    for isbn, origin, key in session.execute(
        select(WorkEntryRow.isbn, WorkEntryRow.origin, WorkEntryRow.key)
        .where(WorkEntryRow.isbn.in_(wanted))
    ):
        if origin == "dnb" or isbn not in keys:
            keys[isbn] = key
    return keys


def _work_siblings(session: Session, isbns: Iterable[str]) -> dict[str, set[str]]:
    """ISBN -> alle ISBNs desselben Werks, sie selbst eingeschlossen."""
    wanted = {isbn for isbn in isbns if isbn}
    keys = _work_keys(session, wanted)
    candidates = set(session.scalars(
        select(WorkEntryRow.isbn).where(WorkEntryRow.key.in_(set(keys.values())))
    ))
    # Ein Kandidat zählt nur mit dem Werk, das für *ihn* gilt: eine
    # Übersetzung, deren eigener Titel zufällig passt, gehört trotzdem zu ihrem
    # Original.
    theirs = _work_keys(session, candidates)
    # Einmal nach Werk gruppiert: je ISBN alle Kandidaten durchzugehen, kostete
    # bei einem vollen Stapel eine halbe Sekunde je Seitenaufruf (29.10.2026).
    by_work: dict[str, set[str]] = {}
    for other in candidates:
        if (key := theirs.get(other)) is not None:
            by_work.setdefault(key, set()).add(other)
    return {
        isbn: by_work.get(keys[isbn], set()) | {isbn} if isbn in keys else {isbn}
        for isbn in wanted
    }


def _work_subjects(session: Session, subjects: Iterable[str]) -> dict[str, set[str]]:
    """Schlüssel eines Steckbriefs -> die Schlüssel aller Ausgaben seines Werks.

    Nur ``isbn:`` hat ein Werk; eine Produktnummer oder Buchnummer bleibt für
    sich.
    """
    wanted = set(subjects)
    isbns = {s.removeprefix("isbn:") for s in wanted if s.startswith("isbn:")}
    siblings = _work_siblings(session, isbns)
    return {
        s: {f"isbn:{o}" for o in siblings[s.removeprefix("isbn:")]}
        if s.startswith("isbn:") else {s}
        for s in wanted
    }


def _work_book_subjects(session: Session, subjects: Iterable[str]) -> dict[str, set[str]]:
    """``book:<id>`` -> die Buchschlüssel aller Ausgaben seines Werks."""
    wanted = set(subjects)
    id_of = {s: int(s.removeprefix("book:")) for s in wanted
             if s.startswith("book:") and s.removeprefix("book:").isdigit()}
    ids = set(id_of.values())
    isbn_of = dict(session.execute(
        select(BookRow.id, BookRow.isbn).where(BookRow.id.in_(ids), BookRow.isbn.is_not(None))
    ).all())
    siblings = _work_siblings(session, isbn_of.values())
    others = {o for group in siblings.values() for o in group}
    book_of = {isbn: book_id for book_id, isbn in session.execute(
        select(BookRow.id, BookRow.isbn).where(BookRow.isbn.in_(others))
    )}
    out: dict[str, set[str]] = {}
    for s in wanted:
        isbn = isbn_of.get(id_of[s]) if s in id_of else None
        group = {f"book:{book_of[o]}" for o in siblings.get(isbn, ()) if o in book_of}
        out[s] = group | {s}
    return out


def _file_bisac(session: Session, isbn: str, origin: str, codes: Iterable[str]) -> None:
    """Die Codes einer Herkunft ersetzen — eine neue Antwort gilt ganz (#88)."""
    session.execute(
        delete(BisacEntryRow).where(BisacEntryRow.isbn == isbn, BisacEntryRow.origin == origin)
    )
    for rank, code in enumerate(dict.fromkeys(codes)):
        session.add(BisacEntryRow(isbn=isbn, origin=origin, code=code, rank=rank))
