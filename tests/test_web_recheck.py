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


def eintrag(db: Store, titel: str = "Kugelblitz") -> int:
    buch = db.find_or_create_book(isbn=None, title=titel, author="Cixin Liu", now=NOW)
    db.put_relation(load_settings().slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    return buch.id


# --- die Zustandsablage ----------------------------------------------------


def test_a_check_that_is_running_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    losgelassen = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: losgelassen.wait(5) or Report())
    rechecker = recheck.Rechecker()
    try:
        zustand = rechecker.start(7, now=NOW)
        assert zustand.busy
        assert rechecker.state(7).busy
    finally:
        losgelassen.set()


def test_a_finished_check_carries_its_report(monkeypatch: pytest.MonkeyPatch) -> None:
    fertig = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: Report(trouble="nichts da"))
    rechecker = recheck.Rechecker()

    rechecker.start(7, now=NOW)
    for _ in range(100):
        if not rechecker.state(7).busy:
            fertig.set()
            break
        threading.Event().wait(0.02)

    assert fertig.is_set()
    assert rechecker.state(7).trouble == "nichts da"


def test_a_second_start_does_not_duplicate_a_running_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    losgelassen = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: losgelassen.wait(5) or Report())
    rechecker = recheck.Rechecker()

    erst = rechecker.start(7, now=NOW)
    nochmal = rechecker.start(7, now=NOW)

    assert erst.started_at == nochmal.started_at
    losgelassen.set()


def test_waiting_and_searching_are_told_apart() -> None:
    """Ein enger Lauf ist nach gemessenen 2,1 s durch. Dauert es länger, hält
    ein großer Lauf die Sperre — und das ist etwas anderes als „sucht"."""
    laeuft = recheck.Check(key=7, started_at=NOW)

    assert laeuft.label(now=NOW + timedelta(seconds=1)) == "sucht …"
    assert laeuft.label(now=NOW + timedelta(minutes=2)) == "wartet …"


def test_a_check_that_blew_up_does_not_stay_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein Faden, der eine Ausnahme wirft, darf die Zeile nicht ewig auf
    „sucht …" stehen lassen."""

    def kaputt(book_id: int) -> Report:
        raise RuntimeError("Zonk")

    monkeypatch.setattr(recheck, "check_one", kaputt)
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
    losgelassen = threading.Event()
    monkeypatch.setattr(recheck, "check_one", lambda book_id: losgelassen.wait(5) or Report())
    buch_id = eintrag(db)

    try:
        body = client.post(f"/watchlist/{buch_id}/nachsehen").text
    finally:
        losgelassen.set()

    assert f'hx-get="/watchlist/{buch_id}/nachsehen"' in body
    assert "every 2s" in body


def test_the_row_stops_asking_when_it_is_over(client: TestClient, db: Store) -> None:
    """Der Trigger steht nur dran, solange etwas läuft — sonst hört die Seite
    von selbst auf zu fragen (ADR 3, wie `_run_panel.html`)."""
    buch_id = eintrag(db)

    body = client.get(f"/watchlist/{buch_id}/nachsehen").text

    assert "every 2s" not in body


def test_an_unknown_entry_is_not_found(client: TestClient, db: Store) -> None:
    assert client.get("/watchlist/9999/nachsehen").status_code == 404


# --- was der Review gefunden hat -------------------------------------------


def test_a_narrow_run_always_closes_its_row(data_dir: Path, db: Store) -> None:
    """Eine Lauf-Zeile ohne Ende sieht für `runs.py` aus wie ein laufender
    Lauf — und ihre Prozessnummer ist die des Webservers, der lebt. Das Panel
    hätte danach für immer „Lauf läuft …" gemeldet."""
    from ebook_watchlist import single

    buch_id = eintrag(db)
    settings = load_settings()
    echte_quellen = single.build_sources

    class Stolpert:
        name = "beam"

        def watch(self, watchlist: object, context: object) -> list:
            raise RuntimeError("der Shop ist weg")

    monkeypatch_ziel = single
    monkeypatch_ziel.build_sources = lambda settings, client: [Stolpert()]  # type: ignore[assignment]
    try:
        bericht = single.check_one(buch_id)
    finally:
        monkeypatch_ziel.build_sources = echte_quellen

    offen = [row for row in db.recent_runs(settings.slug, limit=50) if row.finished_at is None]
    assert not offen
    assert "beam" in bericht.trouble


def test_a_narrow_run_is_not_the_last_run(data_dir: Path, db: Store) -> None:
    """Ein „Lauf" im Journal heißt: jemand hat alles angesehen. Ein einzelner
    Eintrag würde das Panel nach jedem Klick auf „Lauf abgeschlossen,
    1 Änderung(en)" setzen."""
    from ebook_watchlist.store import ENTRY_TRIGGER

    settings = load_settings()
    gross = db.start_run(settings.slug, "cli", NOW)
    db.finish_run(gross, status="ok", delta_count=42, finished_at=NOW)
    db.start_run(settings.slug, ENTRY_TRIGGER, NOW)

    assert db.latest_run(settings.slug).id == gross


def test_the_digest_dates_itself_from_the_last_real_run(data_dir: Path, db: Store) -> None:
    """Sonst datierte „Änderungen seit letztem Check" auf einen einzelnen
    Eintrag, den die Leserin selbst angesehen hat."""
    from ebook_watchlist.store import ENTRY_TRIGGER

    settings = load_settings()
    gross = db.start_run(settings.slug, "cli", NOW)
    db.finish_run(gross, status="ok", delta_count=42, finished_at=NOW)
    eng = db.start_run(settings.slug, ENTRY_TRIGGER, NOW)
    db.finish_run(eng, status="ok", delta_count=1, finished_at=NOW)
    naechster = db.start_run(settings.slug, "cli", NOW)

    assert db.last_finished_run(settings.slug, naechster).id == gross


# --- das Titelbild ----------------------------------------------------------


def test_a_narrow_run_fetches_the_cover(data_dir: Path, db: Store) -> None:
    """Ein Buch, das über den engen Lauf hereinkommt, stand sonst bis zum
    nächsten Rundgang ohne Bild da — die Adresse lag in der Beobachtung, nur
    geholt hat sie niemand. Am 12.9.2026 traf das "Splittt" und "Connnect"."""
    from ebook_watchlist import single
    from ebook_watchlist.covers import MIN_BYTES, file_name
    from ebook_watchlist.models import MatchReason, Observation

    bild = b"\xff\xd8\xff" + b"x" * MIN_BYTES
    adresse = "https://www.beam-shop.de/media/image/aa/bb/cc/9783757989606_600x600.jpg"
    buch_id = eintrag(db, "Splittt")

    class Findet:
        name = "beam"

        def watch(self, watchlist: object, context: object) -> list:
            return [
                Observation(
                    source="beam",
                    source_item_id="927640",
                    title="Splittt",
                    match_reason=MatchReason.WATCHLIST,
                    book_id=buch_id,
                    cover_url=adresse,
                )
            ]

    class HoltDasBild:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def get_bytes(self, url: str) -> bytes:
            assert url == adresse
            return bild

    echte_quellen, echter_client = single.build_sources, single.HttpClient
    single.build_sources = lambda settings, client: [Findet()]  # type: ignore[assignment]
    single.HttpClient = HoltDasBild  # type: ignore[assignment]
    try:
        single.check_one(buch_id)
    finally:
        single.build_sources = echte_quellen  # type: ignore[assignment]
        single.HttpClient = echter_client  # type: ignore[assignment]

    assert (paths.covers_dir() / file_name(adresse)).is_file()
    assert db.book(buch_id).cover_file == file_name(adresse)


def test_the_same_keeper_carries_other_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Das Urteil laeuft ueber denselben Verwalter wie der enge Lauf (#15):
    welche Arbeit getan wird, kommt herein, und der Schluessel muss keine
    Buchnummer sein."""
    getan: list[object] = []

    def arbeit(key: object) -> Report:
        getan.append(key)
        return Report(trouble="geurteilt")

    urteiler = recheck.Rechecker(work=arbeit)
    urteiler.start(("item", "beam", "7"), now=NOW)
    for _ in range(100):
        if not urteiler.state(("item", "beam", "7")).busy:
            break
        threading.Event().wait(0.02)

    assert getan == [("item", "beam", "7")]
    assert urteiler.state(("item", "beam", "7")).trouble == "geurteilt"
