"""Der "Jetzt prüfen"-Knopf (Ticket 10).

Der Lauf läuft hier wirklich als eigener Prozess — die Tests starten ihn und
warten auf sein Ergebnis, statt das Starten wegzumocken. Genau das ist die
Eigenschaft, um die es geht: die Weboberfläche stößt an und schaut zu, mehr
nicht (ADR 3).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock

from ebook_watchlist import paths
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app
from ebook_watchlist.web.runs import RunLauncher

#: Ein Lauf gegen die Fixtures ist in Sekunden durch; das Hochfahren eines
#: Python-Prozesses ist der langsamste Teil daran.
PATIENCE = timedelta(seconds=90)

#: Eine Prozessnummer, unter der nichts läuft. Prozessnummern beginnen bei 1,
#: und diese liegt jenseits jedes üblichen Maximums.
DEAD_PID = 0x7FFFFFFF


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def store(data_dir: Path) -> Store:
    return Store(data_dir / "snapshots.db")


def wait_until(condition, what: str) -> None:
    """Auf den Kindprozess warten, ohne den Test an einer festen Zeit aufzuhängen."""
    deadline = datetime.now() + PATIENCE
    while datetime.now() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError(f"nach {PATIENCE.seconds}s immer noch nicht: {what}")


def runs_of(store: Store) -> list:
    return store.recent_runs("test", limit=50)


# --- der gute Fall ---------------------------------------------------------


def test_the_dashboard_offers_to_start_a_run(client: TestClient) -> None:
    body = client.get("/uebersicht").text

    assert "Jetzt prüfen" in body
    assert 'hx-post="/run"' in body


def test_pressing_the_button_really_runs_a_check(client: TestClient, store: Store) -> None:
    """Der ganze Schnitt: Klick, eigener Prozess, Ergebnis im Laufjournal."""
    assert runs_of(store) == []

    started = client.post("/run")
    assert started.status_code == 200

    wait_until(lambda: bool(runs_of(store)), "ein Lauf ist im Journal aufgetaucht")
    wait_until(
        lambda: runs_of(store)[0].finished_at is not None,
        "der Lauf ist fertig geworden",
    )

    run = runs_of(store)[0]
    assert run.trigger == "ui"
    assert run.status == "ok"
    # Der Lauf hat wirklich gearbeitet, nicht nur eine Zeile geschrieben.
    assert paths.db_path().exists()


def test_the_run_happens_in_a_process_of_its_own(client: TestClient, store: Store) -> None:
    """Ein Lauf im Webprozess wäre genau das, was ADR 3 ausschließt."""
    import os

    client.post("/run")
    wait_until(lambda: bool(runs_of(store)), "ein Lauf ist im Journal aufgetaucht")

    run = runs_of(store)[0]
    assert run.pid is not None
    assert run.pid != os.getpid()


def test_the_page_stops_asking_once_the_run_is_over(
    client: TestClient, store: Store
) -> None:
    """Solange gepollt wird, steht der Trigger im Fragment — danach nicht mehr.

    Damit hört die Seite von selbst auf zu fragen; es gibt keinen Timer im
    Browser, der weiterläuft, nachdem der Lauf fertig ist.
    """
    client.post("/run")
    wait_until(
        lambda: "every 2s" not in client.get("/run/status").text,
        "die Seite hat aufgehört zu pollen",
    )

    done = client.get("/run/status")
    assert "abgeschlossen" in done.text
    assert "Jetzt prüfen" in done.text  # der Knopf ist wieder da


def test_the_rest_of_the_page_is_brought_up_to_date_when_the_run_ends(
    client: TestClient, store: Store
) -> None:
    """Der Lauf hat gerade Quellen geprüft, ein Digest geschrieben und eine
    Zeile ins Journal gelegt — die stehen sonst veraltet daneben."""
    client.post("/run")
    wait_until(
        lambda: client.get("/run/status").headers.get("HX-Refresh") == "true",
        "die Seite wurde zum Neuladen aufgefordert",
    )

    # Und danach steht der frische Lauf wirklich auf der Seite.
    assert "ui" in client.get("/uebersicht").text


# --- es läuft schon einer --------------------------------------------------


def test_a_run_in_progress_is_reported_rather_than_duplicated(
    client: TestClient, store: Store
) -> None:
    """Ein laufender cron-Lauf: der Knopf darf keinen zweiten anstoßen — und
    die Seite muss das sagen, nicht stillschweigend nichts tun."""
    import os

    store.start_run("test", "cron", datetime.now(), pid=os.getpid())
    before = len(runs_of(store))

    held = FileLock(str(paths.lock_path()), timeout=0)
    held.acquire()
    try:
        response = client.post("/run")
    finally:
        held.release()

    assert response.status_code == 200
    assert "läuft" in response.text.lower()
    assert "Jetzt prüfen" not in response.text  # kein zweiter Klick angeboten
    assert len(runs_of(store)) == before  # und kein zweiter Lauf


def test_a_second_run_that_slips_past_the_button_bounces_off_the_lock(
    client: TestClient, store: Store
) -> None:
    """Die Dateisperre ist die eigentliche Absicherung, nicht der graue Knopf.

    Hier hält jemand die Sperre, ohne dass ein Laufeintrag existiert — der
    Kindprozess muss von selbst abprallen, und die Seite muss das melden.
    """
    held = FileLock(str(paths.lock_path()), timeout=0)
    held.acquire()
    try:
        client.post("/run")
        wait_until(
            lambda: "bereits ein Lauf" in client.get("/run/status").text,
            "die Seite meldet den schon laufenden Lauf",
        )
        assert runs_of(store) == []  # der zweite Lauf hat nichts angefangen
    finally:
        held.release()


# --- wenn etwas schiefgeht -------------------------------------------------


def test_a_killed_run_is_reported_instead_of_running_forever(
    client: TestClient, store: Store
) -> None:
    """Ein abgeschossener Lauf schreibt sein Ende nie. Eine Seite, die dann für
    immer "läuft …" zeigt, ist schlechter als eine Fehlermeldung."""
    store.start_run("test", "ui", datetime.now(), pid=DEAD_PID)

    panel = client.get("/run/status").text

    assert "abgebrochen" in panel
    assert "läuft …" not in panel
    assert "every 2s" not in panel  # nicht ewig weiterfragen
    assert "Jetzt prüfen" in panel  # sondern einen neuen anbieten


def test_a_killed_run_is_not_still_listed_as_running_in_the_journal(
    client: TestClient, store: Store
) -> None:
    store.start_run("test", "cron", datetime.now(), pid=DEAD_PID)

    assert "abgebrochen" in client.get("/uebersicht").text


def test_a_run_that_hung_for_hours_is_given_up_on(
    client: TestClient, store: Store
) -> None:
    """Prozessnummern werden wiederverwendet: ein tagealter Eintrag darf nicht
    dadurch als lebendig gelten, dass zufällig etwas anderes diese Nummer hat."""
    import os

    long_ago = datetime.now() - timedelta(days=2)
    store.start_run("test", "cron", long_ago, pid=os.getpid())

    assert "abgebrochen" in client.get("/run/status").text


def test_a_failing_run_says_so_rather_than_looking_finished(
    client: TestClient, store: Store, data_dir: Path
) -> None:
    (data_dir / "fake-source.yaml").write_text("not: a list\n", encoding="utf-8")

    client.post("/run")
    wait_until(
        lambda: runs_of(store) and runs_of(store)[0].finished_at is not None,
        "der Lauf ist fertig geworden",
    )

    panel = client.get("/run/status").text
    assert "Fehler" in panel
    assert "must be a list of items" in panel


def test_a_run_that_never_got_off_the_ground_shows_why(
    store: Store, data_dir: Path
) -> None:
    """Ein kaputtes Profil bricht den Lauf ab, bevor er einen Eintrag schreibt.

    Das Journal kann davon nichts wissen — also muss die Ausgabe des
    Kindprozesses erhalten bleiben, sonst sähe der Klick aus, als wäre nichts
    passiert.
    """
    (data_dir / "profile.yaml").unlink()
    launcher = RunLauncher()

    launcher.start(store, "test")
    wait_until(
        lambda: launcher.state(store, "test").kind == "failed",
        "der gescheiterte Start ist gemeldet",
    )

    state = launcher.state(store, "test")
    assert runs_of(store) == []
    assert state.detail is not None
    assert "config error" in state.detail


def test_the_run_opens_no_console_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein abgekoppelter Konsolenprozess bekommt unter Windows sein *eigenes*
    Fenster — und das poppte bei jedem Lauf und jedem Urteil auf dem Schreibtisch
    auf. ``CREATE_NO_WINDOW`` statt ``DETACHED_PROCESS``: losgelöst bleibt er
    durch die eigene Prozessgruppe."""
    import subprocess

    from ebook_watchlist.web import runs

    monkeypatch.setattr(runs.sys, "platform", "win32")
    gesehen: dict = {}

    class Popen:
        def __init__(self, *args, **kwargs) -> None:
            gesehen.update(kwargs)

    monkeypatch.setattr(runs.subprocess, "Popen", Popen)
    RunLauncher()._spawn()

    flags = gesehen["creationflags"]
    assert flags & subprocess.CREATE_NO_WINDOW
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert not flags & subprocess.DETACHED_PROCESS
