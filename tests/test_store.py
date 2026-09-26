from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 4, 6, 0)


def observation(source: str, item_id: str, price: int) -> Observation:
    return Observation(
        source=source,
        source_item_id=item_id,
        title=f"{source}/{item_id}",
        match_reason=MatchReason.WATCHLIST,
        price_cents=price,
    )


def test_latest_observations_returns_the_newest_row_per_item(tmp_path: Path) -> None:
    store = Store(tmp_path / "snapshots.db")
    for run, price in enumerate([1299, 1199, 999], start=1):
        run_id = store.start_run("p", "cli", NOW)
        store.append(run_id, "p", [observation("beam", "1", price)], NOW)
        store.finish_run(run_id, status="ok", delta_count=0, finished_at=NOW)
        assert run == run_id

    latest = store.latest_observations("p", [("beam", "1")])
    assert latest[("beam", "1")].price_cents == 999


def test_latest_observations_does_not_cross_sources_or_profiles(tmp_path: Path) -> None:
    """Two Sources can legitimately use the same item id; profiles never share rows."""
    store = Store(tmp_path / "snapshots.db")
    run_id = store.start_run("p", "cli", NOW)
    store.append(
        run_id,
        "p",
        [observation("beam", "1", 100), observation("onleihe", "1", 200)],
        NOW,
    )
    other = store.start_run("other", "cli", NOW)
    store.append(other, "other", [observation("beam", "1", 999)], NOW)

    latest = store.latest_observations("p", [("beam", "1")])
    assert set(latest) == {("beam", "1")}
    assert latest[("beam", "1")].price_cents == 100


def test_unknown_items_are_simply_absent(tmp_path: Path) -> None:
    store = Store(tmp_path / "snapshots.db")
    assert store.latest_observations("p", [("beam", "nope")]) == {}


def test_the_whole_history_of_a_find_newest_first(tmp_path: Path) -> None:
    """Ein Fund hat keine Buch-Zeile (ADR 18) — seine Geschichte haengt am
    Paar aus Quelle und Nummer, nicht an einer ``book_id``."""
    store = Store(tmp_path / "snapshots.db")
    for price in (1299, 1199, 999):
        run_id = store.start_run("p", "cli", NOW)
        store.append(run_id, "p", [observation("beam", "1", price)], NOW)

    seen = store.observations_for_item("p", "beam", "1")

    assert [row.price_cents for row in seen] == [999, 1199, 1299]


def test_the_history_of_a_find_does_not_cross_sources_or_profiles(tmp_path: Path) -> None:
    store = Store(tmp_path / "snapshots.db")
    run_id = store.start_run("p", "cli", NOW)
    store.append(
        run_id, "p", [observation("beam", "1", 100), observation("onleihe", "1", 200)], NOW
    )
    other = store.start_run("other", "cli", NOW)
    store.append(other, "other", [observation("beam", "1", 999)], NOW)

    seen = store.observations_for_item("p", "beam", "1")

    assert [row.price_cents for row in seen] == [100]


def test_a_book_made_from_a_find_keeps_the_finds_history(tmp_path: Path) -> None:
    """Die Beobachtungen einer Entdeckung tragen keine ``book_id`` — es gab ja
    noch kein Buch (ADR 18). Wird eines daraus, hing seine ganze Vorgeschichte
    in der Luft: die Buchseite sagte "Noch nichts gesehen" und die Kachel der
    Quelle zeigte keinen Preis, obwohl elf Beobachtungen dazu dastanden.

    Nachgeschlagen statt nachgetragen: der Snapshot wird nie umgeschrieben
    (ADR 5), und die Verknuepfung zur Quelle sagt ohnehin, welche Nummer
    dieses Buch dort traegt."""
    store = Store(tmp_path / "snapshots.db")
    for price in (1299, 999):
        run_id = store.start_run("p", "cli", NOW)
        store.append(run_id, "p", [observation("beam", "1", price)], NOW)
    book = store.find_or_create_book(isbn=None, title="beam/1", author=None, now=NOW)
    store.put_book_source(
        book.id, "beam", outcome="confirmed", source_item_id="1", resolved_at=NOW
    )

    seen = store.observations_for_book("p", book.id)

    assert [row.price_cents for row in seen] == [999, 1299]


def test_a_find_nobody_ever_saw_has_no_history(tmp_path: Path) -> None:
    store = Store(tmp_path / "snapshots.db")
    assert store.observations_for_item("p", "beam", "nope") == []


def test_every_discovery_comes_back_not_the_newest_five_hundred(tmp_path: Path) -> None:
    """Die Abfrage hatte eine stille Grenze von 500. Der echte Bestand stand
    bei 397, und jeder Lauf legt zu — daran waere der Stapel nicht langsam
    geworden, sondern unvollstaendig: die aeltesten Funde waeren aus der
    Liste, aus der Zaehlung "N offen" und aus dem Bilderholen gefallen, ohne
    dass irgendwo etwas davon steht."""
    store = Store(tmp_path / "snapshots.db")
    run_id = store.start_run("p", "cli", NOW)
    store.append(
        run_id,
        "p",
        [
            Observation(
                source="beam",
                source_item_id=str(number),
                title=f"Fund {number}",
                match_reason=MatchReason.GENRE_CATEGORY,
                price_cents=399,
            )
            for number in range(600)
        ],
        NOW,
    )

    assert len(store.latest_discoveries("p")) == 600


def test_last_finished_run_ignores_the_current_one(tmp_path: Path) -> None:
    store = Store(tmp_path / "snapshots.db")
    first = store.start_run("p", "cli", NOW)
    store.finish_run(first, status="ok", delta_count=0, finished_at=NOW)
    current = store.start_run("p", "cli", NOW)

    previous = store.last_finished_run("p", current)
    assert previous is not None
    assert previous.id == first
    assert store.last_finished_run("p", first) is None


# --- seeded discovery scopes ----------------------------------------------




# --- Schreibweisen auf der Buch-Zeile (Ticket 23) ---------------------------


def test_the_book_keeps_the_better_spelling_of_the_same_author(store: Store) -> None:
    """Der Shop liefert "Barnes, S. A.", die Watchlist sagt "S.A. Barnes".
    Wer zuerst da war, bestimmte bisher, wie das Buch für immer heißt — bei
    *Cold Eternity* war das der einmalige Auflöser aus dismissed.yaml."""
    store.find_or_create_book(
        isbn="9783641329433", title="Cold Eternity", author="Barnes, S. A.", now=NOW
    )

    again = store.find_or_create_book(
        isbn="9783641329433", title="Cold Eternity", author="S.A. Barnes", now=NOW
    )

    assert again.author == "S.A. Barnes"
    assert len(store.books()) == 1


def test_a_worse_spelling_does_not_win_by_arriving_later(store: Store) -> None:
    """Eine spätere Quelle ist nicht automatisch die bessere."""
    store.find_or_create_book(isbn=None, title="Schneemann", author="Jo Nesbø", now=NOW)

    again = store.find_or_create_book(isbn=None, title="Schneemann", author="Jo Nesbo", now=NOW)

    assert again.author == "Jo Nesbø"


def test_a_different_person_never_replaces_the_author(store: Store) -> None:
    """Ein Namenswechsel wäre keine Schreibweise, sondern ein anderer Mensch."""
    store.find_or_create_book(isbn="9783104911854", title="Krieg der Klone",
                              author="John Scalzi", now=NOW)

    again = store.find_or_create_book(isbn="9783104911854", title="Krieg der Klone",
                                      author="Max Barry", now=NOW)

    assert again.author == "John Scalzi"


def test_a_missing_author_is_filled_in_when_one_turns_up(store: Store) -> None:
    store.find_or_create_book(isbn=None, title="Providence", now=NOW)

    again = store.find_or_create_book(isbn=None, title="Providence", author="Max Barry", now=NOW)

    assert again.author == "Max Barry"


# --- zwei Prozesse, eine Datei (Review) -------------------------------------


def test_the_snapshot_is_written_ahead(tmp_path: Path) -> None:
    """Lauf und Weboberflaeche teilen sich diese Datei. WAL laesst Leser
    waehrend eines Schreibvorgangs durch und macht aus jedem Commit ein
    Anhaengen — gemessen 1,86 s statt 6,56 s fuer 600 verschraenkte Schreib-
    vorgaenge aus zwei Verbindungen."""
    store = Store(tmp_path / "s.db")
    with store.session() as session:
        mode = session.connection().exec_driver_sql("PRAGMA journal_mode").scalar()
    assert mode == "wal"


def test_a_second_writer_waits_rather_than_giving_up(tmp_path: Path) -> None:
    """Der Standardwert von SQLite sind 5 s; danach steht "database is locked"
    auf der Seite. Warten ist hier immer richtig — die Schreibvorgaenge dieses
    Programms dauern Millisekunden."""
    store = Store(tmp_path / "s.db")
    with store.session() as session:
        timeout = session.connection().exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert timeout >= 15000


def test_an_observation_keeps_its_page_count(store) -> None:
    """Der Umfang aus der Detailseite, für das Erkennen von Kurzgeschichten (#73)."""
    from datetime import datetime

    from ebook_watchlist.models import MatchReason, Observation

    now = datetime(2026, 9, 26, 12, 0)
    run_id = store.start_run("test", "cli", now)
    store.append(run_id, "test", [Observation(
        source="beam", source_item_id="7", title="Kurz", pages=48,
        match_reason=MatchReason.GENRE_CATEGORY, observed_at=now)], now)

    (found,) = store.latest_discoveries("test")
    assert found.pages == 48


def test_a_portrait_remembers_whether_a_sample_went_along(store) -> None:
    from datetime import datetime

    from ebook_watchlist.portrait import Portrait

    store.put_portrait("item:beam:697", Portrait(known=False, fingerprint="x", with_text=True,
                                                 with_sample=True),
                       now=datetime(2026, 9, 26, 12, 0))

    assert store.portrait("item:beam:697", "x").with_sample is True



def test_a_known_page_count_is_carried_to_the_next_sighting(store) -> None:
    """Die Trefferliste nennt keinen Umfang; der von der Detailseite gilt weiter (#73)."""
    from datetime import datetime

    from ebook_watchlist.models import MatchReason, Observation

    now = datetime(2026, 9, 26, 12, 0)
    fund = Observation(source="beam", source_item_id="7", title="Kurz", pages=48,
                       match_reason=MatchReason.GENRE_CATEGORY, observed_at=now)
    store.append(store.start_run("test", "cli", now), "test", [fund], now)

    (weiter,) = store.with_known_pages([Observation(
        source="beam", source_item_id="7", title="Kurz",
        match_reason=MatchReason.GENRE_CATEGORY)])

    assert weiter.pages == 48


def test_a_later_volume_does_not_lend_its_series_name(store) -> None:
    """„Scythe – Der Zorn der Gerechten" ist Band 2: sein Titel trägt die Reihe,
    nicht das gesuchte Buch (#77)."""
    from datetime import datetime

    from ebook_watchlist.dnb import Record

    store.save_dnb("9783733650162", Record(title="Scythe – Der Zorn der Gerechten",
                                           series="Scythe", series_index="2"),
                   datetime(2026, 9, 26, 12, 0))

    assert store.dnb_original_titles(["9783733650162"]) == {"9783733650162": ()}
