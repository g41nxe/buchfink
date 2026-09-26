"""Schema migrations: an existing snapshots.db must survive a schema change."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from ebook_watchlist.migrations import SCHEMA_VERSION, SchemaTooNew, add_column, migrate
from ebook_watchlist.store import Base, Store


def user_version(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


def columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


# --- versioning -----------------------------------------------------------


def test_a_fresh_database_is_stamped_at_the_current_version(tmp_path: Path) -> None:
    """create_all already built the finished schema — nothing to upgrade."""
    path = tmp_path / "s.db"
    Store(path)


    assert user_version(path) == SCHEMA_VERSION


def test_a_fresh_database_never_runs_a_migration(tmp_path: Path) -> None:
    ran: list[str] = []
    engine = create_engine(f"sqlite:///{tmp_path / 's.db'}")

    migrate(engine, Base.metadata, migrations=[lambda _c: ran.append("boom")])

    assert ran == []


def test_an_existing_database_runs_the_pending_migrations(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    Store(path)  # v1 schema on disk
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 0")

    ran: list[int] = []
    engine = create_engine(f"sqlite:///{path}")
    migrate(engine, Base.metadata, migrations=[lambda _c: ran.append(0), lambda _c: ran.append(1)])

    assert ran == [0, 1]
    assert user_version(path) == 2


def test_only_the_migrations_after_the_current_version_run(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")

    ran: list[int] = []
    engine = create_engine(f"sqlite:///{path}")
    migrate(engine, Base.metadata, migrations=[lambda _c: ran.append(0), lambda _c: ran.append(1)])

    assert ran == [1]


def test_a_database_from_the_future_refuses_to_open(tmp_path: Path) -> None:
    """Better a clear error than silently writing rows a newer schema owns."""
    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")

    engine = create_engine(f"sqlite:///{path}")
    with pytest.raises(SchemaTooNew, match="newer version"):
        migrate(engine, Base.metadata)


# --- the column helper ----------------------------------------------------


def test_add_column_adds_it_and_keeps_the_data(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    Store(path)
    engine = create_engine(f"sqlite:///{path}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO state (profile_slug, key, value) VALUES ('t', 'k', '2026-01-01')"
        )
        add_column(connection, "state", "note", "TEXT")

    assert "note" in columns(path, "state")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT key FROM state").fetchone() == ("k",)


def test_add_column_is_safe_to_run_twice(tmp_path: Path) -> None:
    """A half-applied migration must be re-runnable."""
    path = tmp_path / "s.db"
    Store(path)
    engine = create_engine(f"sqlite:///{path}")

    with engine.begin() as connection:
        add_column(connection, "state", "note", "TEXT")
        add_column(connection, "state", "note", "TEXT")

    assert "note" in columns(path, "state")


# --- the real migration: backfilling seeded scopes ------------------------


def test_an_old_database_upgrades_all_the_way(tmp_path: Path) -> None:
    """Die Kette laeuft bis zum Ende durch, auch von Version 0 aus.

    ``seeded_scope`` ist unterwegs erst befuellt und dann fallengelassen worden
    (Ticket 05): eine Migration beschreibt die Welt, in der sie geschrieben
    wurde, und muss das weiter tun, auch wenn eine spaetere sie ueberholt.
    """
    path = tmp_path / "s.db"
    Store(path)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO observation (run_id, profile_slug, source, source_item_id, "
            "match_reason, title, category, observed_at) "
            "VALUES (1, 'default', 'beam', '1', 'genre_category', 'Titel', 'krimi', "
            "'2026-09-04')"
        )
        connection.execute("PRAGMA user_version = 0")

    Store(path)  # darf nicht scheitern
    tables = inspect(create_engine(f"sqlite:///{path}")).get_table_names()
    assert "seeded_scope" not in tables
    assert "interest_seeded" in tables


def test_the_observations_survive_the_upgrade(tmp_path: Path) -> None:
    """Die Aussaat war ein Cache; die Historie ist es nicht."""
    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO observation (run_id, profile_slug, source, source_item_id, "
            "match_reason, title, observed_at) "
            "VALUES (1, 'default', 'beam', '1', 'watchlist', 'Titel', '2026-09-04')"
        )
        connection.execute("PRAGMA user_version = 0")

    Store(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM observation").fetchone()[0] == 1


def test_the_rating_table_is_rebuilt_from_the_old_shape(tmp_path: Path) -> None:
    """Die einzige Migration, die Daten umkopiert — und die einzige, die kein
    Test berührte: die Aufwärtstests starten von einer Datenbank *heutiger*
    Form, in der ``origin`` schon steht, und lösen damit nur den Frühausstieg
    aus. Die umkopierte Zeile ist ein Modellurteil, und das räumt seit #52 die
    letzte Migration der Kette wieder weg."""
    path = tmp_path / "s.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE rating (
                id INTEGER NOT NULL PRIMARY KEY,
                subject VARCHAR NOT NULL UNIQUE,
                stars INTEGER NOT NULL,
                confidence VARCHAR NOT NULL,
                reason VARCHAR NOT NULL,
                rubric_version INTEGER NOT NULL,
                rated_at DATETIME NOT NULL
            );
            INSERT INTO rating
            VALUES (7, 'isbn:9783104911854', 4, 'teils', 'Achse D', 1, '2026-09-01');
            PRAGMA user_version = 0;
            """
        )

    Store(path)

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT id, subject, origin, stars, reason FROM rating"
        ).fetchall()
        # Und die Spalte trägt danach den neuen Namen (Ticket 25).
        assert "profile_version" in {
            row[1] for row in connection.execute("PRAGMA table_info(rating)")
        }
        # Die Zeile wanderte mit und galt als Modellurteil, die einzige Herkunft,
        # die es bis dahin gab — und das Modellurteil fällt am Ende der Kette
        # weg (#52). Dass die Tabelle sauber neu gebaut wurde, sagen die Spalten.
        assert rows == []
        assert "rating_old" not in {
            name for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def test_after_the_rebuild_two_origins_stand_side_by_side(tmp_path: Path) -> None:
    """Der Grund für den Neubau: der alte eindeutige Schlüssel lag auf
    ``subject`` allein, und genau der musste fallen (ADR 17)."""
    path = tmp_path / "s.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE rating (
                id INTEGER NOT NULL PRIMARY KEY,
                subject VARCHAR NOT NULL UNIQUE,
                stars INTEGER NOT NULL,
                confidence VARCHAR NOT NULL,
                reason VARCHAR NOT NULL,
                rubric_version INTEGER NOT NULL,
                rated_at DATETIME NOT NULL
            );
            PRAGMA user_version = 0;
            """
        )

    store = Store(path)
    now = datetime(2026, 9, 4, 20, 0)
    store.put_rating("book:5", stars=5, confidence="belegt", reason="", profile_version=1,
                     now=now, origin="reader")
    store.put_rating("book:5", stars=3.4, confidence="belegt", reason="", profile_version=0,
                     now=now, origin="onleihe_readers", votes=12)

    assert store.rating("book:5", origin="reader").stars == 5
    assert store.rating("book:5", origin="onleihe_readers").stars == 3.4


def test_a_doubled_blurb_is_cut_down_to_one(tmp_path: Path) -> None:
    """Der Parser nahm Anriss und vollen Text; von selbst geht das nie weg,
    weil nur nachgeladen wird, was auf „…" endet — und ein doppelter Text
    endet auf dem vollen (Ticket 40)."""
    path = tmp_path / "s.db"
    doubled = "Der Anfang ... alles anzeigen expand_more Der Anfang und der Rest."
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE observation (
                id INTEGER NOT NULL PRIMARY KEY,
                blurb VARCHAR
            );
            PRAGMA user_version = 14;
            """
        )
        connection.execute("INSERT INTO observation VALUES (1, ?)", (doubled,))
        connection.execute("INSERT INTO observation VALUES (2, 'Ein kurzer Text.')")

    migrate(create_engine(f"sqlite:///{path}"), Base.metadata)

    with sqlite3.connect(path) as connection:
        texts = dict(connection.execute("SELECT id, blurb FROM observation"))
    assert texts[1] == "Der Anfang und der Rest."
    # Wer nie doppelt war, bleibt unberuehrt.
    assert texts[2] == "Ein kurzer Text."


# --- voebb heisst onleihe ----------------------------------------------------


def test_the_rename_keeps_every_row_that_carried_the_old_name(tmp_path: Path) -> None:
    """Der VOEBB betreibt zwei Plattformen; "onleihe" meinte eine von beiden,
    ohne zu sagen welche. Der Name steht aber in fuenf Spalten, und ueber zwei
    davon ist geschluesselt — ohne diesen Schritt verloere jedes beobachtete
    Buch seine Geschichte."""
    from ebook_watchlist.migrations import _voebb_is_called_onleihe

    path = tmp_path / "s.db"
    Store(path)  # baut das fertige Schema
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO observation (profile_slug, run_id, source, source_item_id, title,"
            " match_reason, observed_at) VALUES ('t', 1, 'voebb', '42', 'Ein Buch',"
            " 'watchlist', '2026-09-11 12:00:00')"
        )
        connection.execute(
            "INSERT INTO book_source (book_id, source, source_item_id, resolved_at, details)"
            " VALUES (1, 'voebb', '42', '2026-09-11 12:00:00', '{}')"
        )
        connection.execute(
            "INSERT INTO source (name, enabled, consecutive_failures, updated_at)"
            " VALUES ('voebb', 1, 0, '2026-09-11 12:00:00')"
        )
        connection.execute(
            "INSERT INTO rating (subject, origin, stars, confidence, reason, profile_version,"
            " rated_at, pitch) VALUES ('item:voebb:42', 'voebb_readers', 4, 'belegt', 'gut', 1,"
            " '2026-09-11 12:00:00', '')"
        )

    with create_engine(f"sqlite:///{path}").begin() as connection:
        _voebb_is_called_onleihe(connection)

    with sqlite3.connect(path) as connection:
        fetch = connection.execute
        assert fetch("SELECT source FROM observation").fetchone()[0] == "onleihe"
        assert fetch("SELECT source FROM book_source").fetchone()[0] == "onleihe"
        assert fetch("SELECT name FROM source").fetchone()[0] == "onleihe"
        # Schritt 22 machte daraus zunaechst ein generisches
        # ``library_readers``; Schritt 23 nimmt das zurueck (siehe dort).
        assert fetch("SELECT origin FROM rating").fetchone()[0] == "library_readers"
        # Ein Urteil ueber einen Fund ohne ISBN haengt am Quellnamen.
        assert fetch("SELECT subject FROM rating").fetchone()[0] == "item:onleihe:42"


def test_the_rename_leaves_other_sources_alone(tmp_path: Path) -> None:
    from ebook_watchlist.migrations import _voebb_is_called_onleihe

    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO source (name, enabled, consecutive_failures, updated_at)"
            " VALUES ('beam', 1, 0, '2026-09-11 12:00:00')"
        )
        connection.execute(
            "INSERT INTO rating (subject, origin, stars, confidence, reason, profile_version,"
            " rated_at, pitch) VALUES ('item:beam:7', 'model', 4, 'belegt', 'gut', 1,"
            " '2026-09-11 12:00:00', '')"
        )

    with create_engine(f"sqlite:///{path}").begin() as connection:
        _voebb_is_called_onleihe(connection)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM source").fetchone()[0] == "beam"
        assert connection.execute("SELECT subject FROM rating").fetchone()[0] == "item:beam:7"


def test_running_the_rename_twice_changes_nothing(tmp_path: Path) -> None:
    """Eine Migration laeuft im Normalfall einmal — aber sie darf beim zweiten
    Mal nicht etwas kaputt machen, und niemand hat das bisher nachgesehen."""
    from ebook_watchlist.migrations import _voebb_is_called_onleihe

    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO source (name, enabled, consecutive_failures, updated_at)"
            " VALUES ('voebb', 1, 0, '2026-09-11 12:00:00')"
        )

    engine = create_engine(f"sqlite:///{path}")
    for _ in range(2):
        with engine.begin() as connection:
            _voebb_is_called_onleihe(connection)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM source").fetchall() == [("onleihe",)]


def test_a_seeded_interest_moves_too(tmp_path: Path) -> None:
    """Die sechste Spalte mit einem Quellnamen. Im echten Bestand leer, in
    einer anderen Installation nicht — und sie steht im Primaerschluessel."""
    from ebook_watchlist.migrations import _voebb_is_called_onleihe

    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO interest_seeded (interest_id, source, seeded_at)"
            " VALUES (1, 'voebb', '2026-09-11 12:00:00')"
        )

    with create_engine(f"sqlite:///{path}").begin() as connection:
        _voebb_is_called_onleihe(connection)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT source FROM interest_seeded").fetchone()[0] == "onleihe"


def test_a_name_collision_does_not_take_the_database_down(tmp_path: Path) -> None:
    """Wer vorher ``onleihe: {kind: voebb}`` konfiguriert hat, traegt beide
    Namen — und der Quellname steht bei ``book_source`` im Primaerschluessel.
    Ohne ``OR IGNORE`` rollte die ganze Migration zurueck, die Version bliebe
    alt, und die Anwendung startete nicht mehr."""
    from ebook_watchlist.migrations import _voebb_is_called_onleihe

    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        for name in ("voebb", "onleihe"):
            connection.execute(
                "INSERT INTO book_source (book_id, source, source_item_id, resolved_at, details)"
                f" VALUES (1, '{name}', '42', '2026-09-11 12:00:00', '{{}}')"
            )

    with create_engine(f"sqlite:///{path}").begin() as connection:
        _voebb_is_called_onleihe(connection)

    with sqlite3.connect(path) as connection:
        # Die neue Zeile steht; die alte bleibt liegen und findet niemand mehr.
        assert ("onleihe",) in connection.execute("SELECT source FROM book_source").fetchall()


def test_the_readers_are_named_after_their_library_again(tmp_path: Path) -> None:
    """Generisch waere falsch: ein Urteil haengt an der ISBN, sobald es eine
    gibt, und dann faellt der Quellname aus dem Schluessel. Zwei Bibliotheken
    schrieben fuer dieselbe ISBN in dieselbe Zeile."""
    from ebook_watchlist.migrations import _library_readers_are_named_per_library

    path = tmp_path / "s.db"
    Store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO rating (subject, origin, stars, confidence, reason, profile_version,"
            " rated_at, pitch) VALUES ('isbn:9783641130008', 'library_readers', 4, 'belegt',"
            " '1641 Stimmen', 1, '2026-09-11 12:00:00', '')"
        )

    with create_engine(f"sqlite:///{path}").begin() as connection:
        _library_readers_are_named_per_library(connection)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT origin FROM rating").fetchone()[0] == "onleihe_readers"


def test_the_old_machine_judgements_are_deleted_and_hers_stay(tmp_path: Path) -> None:
    """Die Urteile des alten Sterne-Modells fallen weg (#52): das Tor
    (``model``) und die Sterne aus ``owned.yaml`` (``conversation``). Die
    eigenen Sterne der Leserin und die fremden Stimmen bleiben."""
    path = tmp_path / "s.db"
    Store(path)  # legt das aktuelle Schema an
    # Der Stand unmittelbar vor dieser Migration, unabhängig davon, wie viele danach kamen.
    from ebook_watchlist.migrations import MIGRATIONS, _the_old_machine_judgements_are_gone

    version = MIGRATIONS.index(_the_old_machine_judgements_are_gone) + 1
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            INSERT INTO rating
              (subject, origin, stars, confidence, reason, pitch, profile_version, rated_at)
            VALUES
              ('isbn:1', 'model', 4, 'teils', '', '', 4, '2026-09-01'),
              ('book:2', 'conversation', 5, 'teils', '', '', 1, '2026-09-01'),
              ('book:3', 'reader', 3, 'belegt', '', '', 4, '2026-09-01'),
              ('isbn:4', 'onleihe_readers', 2.8, 'belegt', '', '', 0, '2026-09-01');
            PRAGMA user_version = {version - 1};
            """
        )

    Store(path)

    with sqlite3.connect(path) as connection:
        origins = sorted(o for (o,) in connection.execute("SELECT origin FROM rating"))
    assert origins == ["onleihe_readers", "reader"]
