"""Die Warteschlange und der Hintergrunddienst (ADR 40, #99)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ebook_watchlist import cli, jobs, paths
from ebook_watchlist.store import ENTRY_TRIGGER, Store
from ebook_watchlist.web import runs

NOW = datetime(2026, 10, 25, 12, 0)


@pytest.fixture
def store(data_dir: Path) -> Store:
    return Store(paths.db_path())


# --- abgebrochene Läufe ohne Prozessnummer ----------------------------------


def test_a_run_holding_the_lock_marks_the_orphans(store: Store) -> None:
    """Wer die Sperre hat, weiß: kein anderer Lauf lebt. Was noch „läuft“, ist tot."""
    orphan = store.start_run("default", "ui", NOW - timedelta(hours=1))
    finished = store.start_run("default", "cron", NOW - timedelta(hours=2))
    store.finish_run(finished, status="ok", delta_count=0, finished_at=NOW - timedelta(hours=2))

    assert store.abandon_unfinished("default") == 1

    rows = {row.id: row for row in store.recent_runs("default")}
    assert rows[orphan].status == "abandoned"
    assert rows[orphan].finished_at is None
    assert rows[finished].status == "ok"


def test_an_abandoned_run_reads_as_abandoned(store: Store) -> None:
    orphan = store.start_run("default", "ui", NOW)
    store.abandon_unfinished("default")

    state = runs.RunLauncher().state(store, "default")

    assert state.kind == "abandoned"
    assert runs.journal_status(store.recent_runs("default"))[orphan] == "abgebrochen"


def test_an_unfinished_young_run_still_reads_as_running(store: Store) -> None:
    """Ohne Prozessnummer: jung und nicht aufgegeben heißt „läuft“."""
    store.start_run("default", "cron", datetime.now() - timedelta(minutes=3))

    assert runs.RunLauncher().state(store, "default").kind == "running"


# --- fällig ------------------------------------------------------------------


def test_without_any_run_a_run_is_due(store: Store) -> None:
    assert jobs.run_is_due(store, "default", hours=24, now=NOW)


def test_a_fresh_finished_run_is_not_due(store: Store) -> None:
    run_id = store.start_run("default", "cron", NOW - timedelta(hours=5))
    store.finish_run(run_id, status="ok", delta_count=0, finished_at=NOW - timedelta(hours=5))

    assert not jobs.run_is_due(store, "default", hours=24, now=NOW)


def test_an_old_finished_run_makes_the_next_due(store: Store) -> None:
    run_id = store.start_run("default", "cron", NOW - timedelta(hours=25))
    store.finish_run(run_id, status="failed", delta_count=0, finished_at=NOW - timedelta(hours=25))

    assert jobs.run_is_due(store, "default", hours=24, now=NOW)


def test_an_abandoned_run_does_not_count(store: Store) -> None:
    """Der Rechner ging mitten im Lauf aus: er ist beim nächsten Prüfen wieder fällig."""
    run_id = store.start_run("default", "cron", NOW - timedelta(hours=1))
    store.abandon_unfinished("default")

    assert run_id
    assert jobs.run_is_due(store, "default", hours=24, now=NOW)


def test_a_narrow_run_does_not_count(store: Store) -> None:
    run_id = store.start_run("default", ENTRY_TRIGGER, NOW - timedelta(hours=1))
    store.finish_run(run_id, status="ok", delta_count=0, finished_at=NOW - timedelta(hours=1))

    assert jobs.run_is_due(store, "default", hours=24, now=NOW)


def test_a_run_in_progress_is_not_due_again(store: Store) -> None:
    store.start_run("default", "cron", NOW - timedelta(minutes=10))

    assert not jobs.run_is_due(store, "default", hours=24, now=NOW)


# --- der Dienst ---------------------------------------------------------------


def test_without_a_service_the_button_says_so(store: Store, monkeypatch) -> None:
    """Ein Knopf, der still in eine Schlange legt, die niemand abarbeitet, wäre kaputt."""
    monkeypatch.setattr(jobs, "service_alive", lambda: False)

    state = runs.RunLauncher().start(store, "default")

    assert state.kind == "no-service"
    assert "ebw serve" in (state.detail or "")
    assert not state.busy


def test_without_a_service_a_small_job_says_so(data_dir: Path, monkeypatch) -> None:
    from ebook_watchlist.web import recheck

    monkeypatch.setattr(jobs, "service_alive", lambda: False)

    check = recheck.Rechecker("recheck").start(7)

    assert not check.busy
    assert "ebw serve" in check.trouble
    assert jobs.job_state("recheck", 7) is None


def test_the_heartbeat_keeps_the_service_alive(data_dir: Path, monkeypatch) -> None:
    monkeypatch.delenv("EBW_JOBS_INLINE", raising=False)
    jobs.heartbeat(now=datetime.now())

    assert jobs.service_alive()


def test_an_old_heartbeat_is_no_service(data_dir: Path, monkeypatch) -> None:
    monkeypatch.delenv("EBW_JOBS_INLINE", raising=False)
    jobs.heartbeat(now=datetime.now() - timedelta(minutes=10))

    assert not jobs.service_alive()


def test_the_queue_lives_in_its_own_file(data_dir: Path, monkeypatch) -> None:
    monkeypatch.delenv("EBW_JOBS_INLINE", raising=False)
    jobs.heartbeat(now=datetime.now())

    assert (paths.data_dir() / "jobs.db").is_file()


# --- der Befehl ---------------------------------------------------------------


@pytest.mark.parametrize("word", ["web", "worker", "serve"])
def test_ebw_knows_the_service_commands(word: str, monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setitem(cli.COMMANDS, word, lambda argv: called.append(word) or 0)

    assert cli.main([word]) == 0
    assert called == [word]


def test_everything_else_is_the_run(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "run_main", lambda argv: seen.append(list(argv)) or 0)

    assert cli.main(["run", "--watchlist"]) == 0
    assert seen == [["run", "--watchlist"]]


def test_tests_never_queue_into_the_real_data_dir(monkeypatch) -> None:
    """Ohne eigenes Datenverzeichnis läge die Schlange sonst in `data/jobs.db` —
    und ein laufender Dienst holte sich die Aufträge der Tests ab."""
    monkeypatch.delenv("EBW_DATA_DIR", raising=False)

    where = Path(jobs._queue_path())

    assert where.parent != paths.data_dir()
    assert where.name == "jobs.db"
