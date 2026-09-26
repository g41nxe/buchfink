"""Ein Lauf für einen Eintrag (Ticket 51).

Wer gerade bestätigt, berichtigt oder aufgenommen hat, wartet nicht bis zum
nächsten großen Lauf. Am 6.9.2026 traf das dreimal hintereinander — *Dark
Matter* stand nach dem Bestätigen ohne Preis da, weil der Lauf 43 Minuten
vorher gelaufen war.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.single import Report
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app, recheck

NOW = datetime(2026, 9, 6, 22, 0)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


def entry(db: Store, title: str = "Kugelblitz") -> int:
    book = db.find_or_create_book(isbn=None, title=title, author="Cixin Liu", now=NOW)
    db.put_relation(load_settings().slug, book.id, str(RelationKind.WATCHING), now=NOW)
    return book.id


# --- die Zustandsablage ----------------------------------------------------


def test_a_check_that_is_running_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    released = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: released.wait(5) or Report())
    rechecker = recheck.Rechecker()
    try:
        state = rechecker.start(7, now=NOW)
        assert state.busy
        assert rechecker.state(7).busy
    finally:
        released.set()


def test_a_finished_check_carries_its_report(monkeypatch: pytest.MonkeyPatch) -> None:
    done = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: Report(trouble="nichts da"))
    rechecker = recheck.Rechecker()

    rechecker.start(7, now=NOW)
    for _ in range(100):
        if not rechecker.state(7).busy:
            done.set()
            break
        threading.Event().wait(0.02)

    assert done.is_set()
    assert rechecker.state(7).trouble == "nichts da"


def test_a_second_start_does_not_duplicate_a_running_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: released.wait(5) or Report())
    rechecker = recheck.Rechecker()

    first = rechecker.start(7, now=NOW)
    again = rechecker.start(7, now=NOW)

    assert first.started_at == again.started_at
    released.set()


def test_waiting_and_searching_are_told_apart() -> None:
    """Ein enger Lauf ist nach gemessenen 2,1 s durch. Dauert es länger, hält
    ein großer Lauf die Sperre — und das ist etwas anderes als „sucht"."""
    running = recheck.Check(key=7, started_at=NOW)

    assert running.label(now=NOW + timedelta(seconds=1)) == "sucht …"
    assert running.label(now=NOW + timedelta(minutes=2)) == "wartet …"


def test_a_check_that_blew_up_does_not_stay_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein Faden, der eine Ausnahme wirft, darf die Zeile nicht ewig auf
    „sucht …" stehen lassen."""

    def broken(book_id: int) -> Report:
        raise RuntimeError("Zonk")

    monkeypatch.setattr(recheck, "check_one", broken)
    rechecker = recheck.Rechecker()

    rechecker.start(7, now=NOW)
    for _ in range(100):
        if not rechecker.state(7).busy:
            break
        threading.Event().wait(0.02)

    assert not rechecker.state(7).busy
    assert "Zonk" in rechecker.state(7).trouble


# --- die Zeile -------------------------------------------------------------


def test_the_row_asks_again_while_something_runs(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    released = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: released.wait(5) or Report())
    book_id = entry(db)

    try:
        body = client.post(f"/watchlist/{book_id}/recheck").text
    finally:
        released.set()

    assert f'hx-get="/watchlist/{book_id}/recheck"' in body
    assert "every 2s" in body


def test_the_row_stops_asking_when_it_is_over(client: TestClient, db: Store) -> None:
    """Der Trigger steht nur dran, solange etwas läuft — sonst hört die Seite
    von selbst auf zu fragen (ADR 3, wie `_run_panel.html`)."""
    book_id = entry(db)

    body = client.get(f"/watchlist/{book_id}/recheck").text

    assert "every 2s" not in body


def test_an_unknown_entry_is_not_found(client: TestClient, db: Store) -> None:
    assert client.get("/watchlist/9999/recheck").status_code == 404


# --- was der Review gefunden hat -------------------------------------------


def test_a_narrow_run_always_closes_its_row(data_dir: Path, db: Store) -> None:
    """Eine Lauf-Zeile ohne Ende sieht für `runs.py` aus wie ein laufender
    Lauf — und ihre Prozessnummer ist die des Webservers, der lebt. Das Panel
    hätte danach für immer „Lauf läuft …" gemeldet."""
    from ebook_watchlist import single

    book_id = entry(db)
    settings = load_settings()
    real_sources = single.build_sources

    class Stumbles:
        name = "beam"

        def watch(self, watchlist: object, context: object) -> list:
            raise RuntimeError("der Shop ist weg")

    monkeypatch_target = single
    monkeypatch_target.build_sources = lambda settings, client: [Stumbles()]  # type: ignore[assignment]
    try:
        report = single.check_one(book_id)
    finally:
        monkeypatch_target.build_sources = real_sources

    unfinished = [row for row in db.recent_runs(settings.slug, limit=50) if row.finished_at is None]
    assert not unfinished
    assert "beam" in report.trouble


def test_a_narrow_run_is_not_the_last_run(data_dir: Path, db: Store) -> None:
    """Ein „Lauf" im Journal heißt: jemand hat alles angesehen. Ein einzelner
    Eintrag würde das Panel nach jedem Klick auf „Lauf abgeschlossen,
    1 Änderung(en)" setzen."""
    from ebook_watchlist.store import ENTRY_TRIGGER

    settings = load_settings()
    big_run = db.start_run(settings.slug, "cli", NOW)
    db.finish_run(big_run, status="ok", delta_count=42, finished_at=NOW)
    db.start_run(settings.slug, ENTRY_TRIGGER, NOW)

    assert db.latest_run(settings.slug).id == big_run


def test_the_digest_dates_itself_from_the_last_real_run(data_dir: Path, db: Store) -> None:
    """Sonst datierte „Änderungen seit letztem Check" auf einen einzelnen
    Eintrag, den die Leserin selbst angesehen hat."""
    from ebook_watchlist.store import ENTRY_TRIGGER

    settings = load_settings()
    big_run = db.start_run(settings.slug, "cli", NOW)
    db.finish_run(big_run, status="ok", delta_count=42, finished_at=NOW)
    narrow = db.start_run(settings.slug, ENTRY_TRIGGER, NOW)
    db.finish_run(narrow, status="ok", delta_count=1, finished_at=NOW)
    next_run = db.start_run(settings.slug, "cli", NOW)

    assert db.last_finished_run(settings.slug, next_run).id == big_run


# --- das Titelbild ----------------------------------------------------------


def test_a_narrow_run_fetches_the_cover(data_dir: Path, db: Store) -> None:
    """Ein Buch, das über den engen Lauf hereinkommt, stand sonst bis zum
    nächsten Rundgang ohne Bild da — die Adresse lag in der Beobachtung, nur
    geholt hat sie niemand. Am 12.9.2026 traf das "Splittt" und "Connnect"."""
    from ebook_watchlist import single
    from ebook_watchlist.covers import MIN_BYTES, file_name
    from ebook_watchlist.models import MatchReason, Observation

    image = b"\xff\xd8\xff" + b"x" * MIN_BYTES
    address = "https://www.beam-shop.de/media/image/aa/bb/cc/9783757989606_600x600.jpg"
    book_id = entry(db, "Splittt")

    class Finds:
        name = "beam"

        def watch(self, watchlist: object, context: object) -> list:
            return [
                Observation(
                    source="beam",
                    source_item_id="927640",
                    title="Splittt",
                    match_reason=MatchReason.WATCHLIST,
                    book_id=book_id,
                    cover_url=address,
                )
            ]

    class FetchesTheImage:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def get_bytes(self, url: str) -> bytes:
            assert url == address
            return image

    real_sources, real_client = single.build_sources, single.HttpClient
    single.build_sources = lambda settings, client: [Finds()]  # type: ignore[assignment]
    single.HttpClient = FetchesTheImage  # type: ignore[assignment]
    try:
        single.check_one(book_id)
    finally:
        single.build_sources = real_sources  # type: ignore[assignment]
        single.HttpClient = real_client  # type: ignore[assignment]

    assert (paths.covers_dir() / file_name(address)).is_file()
    assert db.book(book_id).cover_file == file_name(address)


def test_the_same_keeper_carries_other_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Das Urteil laeuft ueber denselben Verwalter wie der enge Lauf (#15):
    welche Arbeit getan wird, kommt herein, und der Schluessel muss keine
    Buchnummer sein."""
    done: list[object] = []

    def work(key: object) -> Report:
        done.append(key)
        return Report(trouble="geurteilt")

    rechecker = recheck.Rechecker(work=work)
    rechecker.start(("item", "beam", "7"), now=NOW)
    for _ in range(100):
        if not rechecker.state(("item", "beam", "7")).busy:
            break
        threading.Event().wait(0.02)

    assert done == [("item", "beam", "7")]
    assert rechecker.state(("item", "beam", "7")).trouble == "geurteilt"
