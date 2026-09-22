"""Self-checks, error aggregation and the weekly cadence."""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ebook_watchlist.config import ConfigError, Settings, load_settings
from ebook_watchlist.run import (
    EXIT_OK,
    EXIT_SOURCE_FAILURE,
    EXTENDED_SWEEP_KEY,
    _should_sweep_extended,
    main,
)
from ebook_watchlist.store import Store

TWO_SOURCES = """
slug: test
name: Testprofil
sources:
  gut:
    kind: fake
    name: Gut
    fixture: fake-source.yaml
  kaputt:
    kind: fake
    name: Kaputt
    fixture: broken.yaml
"""
# Zwei Quellen derselben Bauart brauchen eigene Namen, sonst hiessen beide
# "Shop" — und die Konfiguration wird beim Lesen zurueckgewiesen (#14).


@pytest.fixture
def two_sources(data_dir: Path) -> Path:
    (data_dir / "profile.yaml").write_text(textwrap.dedent(TWO_SOURCES).lstrip(), encoding="utf-8")
    (data_dir / "broken.yaml").write_text("not: a list\n", encoding="utf-8")
    return data_dir


# --- the doctor command ---------------------------------------------------


def test_doctor_reports_every_source_as_ok(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["doctor"]) == EXIT_OK
    assert "fake" in capsys.readouterr().out


def test_doctor_exits_non_zero_and_names_the_broken_source(
    two_sources: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["doctor"]) == EXIT_SOURCE_FAILURE

    captured = capsys.readouterr()
    assert "FEHLER" in captured.out
    assert "kaputt" in captured.out
    assert "gut" in captured.out
    assert "must be a list of items" in captured.err


def test_doctor_writes_no_digest_and_records_no_run(two_sources: Path) -> None:
    main(["doctor"])
    assert not (two_sources / "digests").exists()

    # Die Datenbank entsteht jetzt doch - aber nur fuer den Befund je Quelle
    # (Ticket 03). Ein Lauf ist das nicht.
    store = Store(two_sources / "snapshots.db")
    assert store.recent_runs("test") == []
    assert {row.name for row in store.sources()}


def test_doctor_records_what_it_found(two_sources: Path) -> None:
    """Der Befund wurde bisher gedruckt und weggeworfen."""
    main(["doctor"])
    store = Store(two_sources / "snapshots.db")
    by_name = {row.name: row for row in store.sources()}

    broken = by_name["kaputt"]
    assert broken.last_probe_ok is False
    assert broken.consecutive_failures == 1
    assert broken.last_error and "Selbsttest" in broken.last_error
    assert broken.last_probe_at is not None

    healthy = by_name["gut"]
    assert healthy.last_probe_ok is True
    assert healthy.last_error is None
    assert healthy.consecutive_failures == 0


def test_a_source_broken_for_days_is_distinguishable_from_one_that_just_broke(
    two_sources: Path,
) -> None:
    for _ in range(3):
        main(["doctor"])
    store = Store(two_sources / "snapshots.db")
    by_name = {row.name: row for row in store.sources()}

    assert by_name["kaputt"].consecutive_failures == 3
    assert by_name["gut"].consecutive_failures == 0


def test_one_success_clears_the_streak(two_sources: Path) -> None:
    store = Store(two_sources / "snapshots.db")
    now = datetime.now()
    store.record_probe("kaputt", ok=False, error="kaputt", now=now)
    store.record_probe("kaputt", ok=False, error="kaputt", now=now)
    assert store.source("kaputt").consecutive_failures == 2

    store.record_probe("kaputt", ok=True, error=None, now=now)
    row = store.source("kaputt")
    assert row.consecutive_failures == 0
    assert row.last_error is None


def test_a_paused_source_is_skipped_and_said_so(
    two_sources: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stillschweigend uebergehen saehe aus wie ein ruhiger Tag beim Shop."""
    store = Store(two_sources / "snapshots.db")
    store.set_enabled("kaputt", False, now=datetime.now())

    assert main(["doctor"]) == EXIT_OK  # die kaputte Quelle wird nicht geprueft
    out = capsys.readouterr().out
    assert "pausiert" in out
    assert store.source("kaputt").last_probe_ok is None


# --- probes guarding a Run ------------------------------------------------


def test_a_source_that_fails_its_probe_sits_the_run_out(
    two_sources: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Half-reading a redesigned site would poison every future diff."""
    assert main([]) == EXIT_SOURCE_FAILURE

    out = capsys.readouterr().out
    assert "Selbsttest fehlgeschlagen" in out
    assert "kaputt" in out


def test_the_healthy_sources_still_run(two_sources: Path) -> None:
    main([])

    from ebook_watchlist import paths
    from ebook_watchlist.store import ObservationRow

    with Store(paths.db_path()).session() as session:
        sources = {row.source for row in session.query(ObservationRow).all()}
    assert sources == {"gut"}


def test_probes_can_be_skipped(two_sources: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--skip-probes"])
    out = capsys.readouterr().out
    assert "Selbsttest" not in out
    # The Source still fails, just later and with its own message.
    assert "kaputt" in out


# --- core / extended reference authors ------------------------------------


def test_a_plain_list_of_authors_is_all_core(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nreference_authors: [A, B]\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.reference_authors == ["A", "B"]
    assert settings.extended_authors == []


def test_authors_can_be_split_into_core_and_extended(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nreference_authors:\n  core: [A]\n  extended: [B]\n"
        "extended_sweep_weekday: 0\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.reference_authors == ["A"]
    assert settings.extended_authors == ["B"]
    assert settings.extended_sweep_weekday == 0


def test_an_unknown_author_group_is_rejected(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nreference_authors:\n  kern: [A]\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown key"):
        load_settings()


def test_an_impossible_weekday_is_rejected(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nextended_sweep_weekday: 9\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="0 \\(Monday\\) to 6"):
        load_settings()


def test_only_the_core_list_is_swept_by_default() -> None:
    settings = Settings(slug="t", name="T", reference_authors=["A"], extended_authors=["B"])
    assert settings.authors_to_sweep(include_extended=False) == ["A"]
    assert settings.authors_to_sweep(include_extended=True) == ["A", "B"]


def test_an_author_in_both_lists_is_swept_once() -> None:
    settings = Settings(slug="t", name="T", reference_authors=["A"], extended_authors=["A", "B"])
    assert settings.authors_to_sweep(include_extended=True) == ["A", "B"]


# --- when the weekly sweep happens ----------------------------------------


SUNDAY = datetime(2026, 9, 6, 6, 0)
MONDAY = datetime(2026, 9, 7, 6, 0)


def profile_with_extended(weekday: int = 6) -> Settings:
    return Settings(
        slug="t",
        name="T",
        reference_authors=["A"],
        extended_authors=["B"],
        extended_sweep_weekday=weekday,
    )


def test_nothing_to_sweep_means_no_sweep(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    plain = Settings(slug="t", name="T", reference_authors=["A"])
    assert not _should_sweep_extended(plain, store, SUNDAY)


def test_the_first_run_sweeps(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    assert _should_sweep_extended(profile_with_extended(), store, MONDAY)


def test_it_sweeps_on_the_configured_day(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    store.set_state("t", EXTENDED_SWEEP_KEY, SUNDAY - timedelta(days=2))

    assert _should_sweep_extended(profile_with_extended(weekday=6), store, SUNDAY)
    assert not _should_sweep_extended(profile_with_extended(weekday=6), store, MONDAY)


def test_it_sweeps_only_once_on_that_day(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    store.set_state("t", EXTENDED_SWEEP_KEY, SUNDAY)
    assert not _should_sweep_extended(profile_with_extended(), store, SUNDAY + timedelta(hours=6))


def test_a_missed_week_is_caught_up_on_the_next_run_whatever_day(tmp_path: Path) -> None:
    """A cron that did not fire must not cost a whole week (ADR 4)."""
    store = Store(tmp_path / "s.db")
    store.set_state("t", EXTENDED_SWEEP_KEY, SUNDAY - timedelta(days=9))
    assert _should_sweep_extended(profile_with_extended(weekday=6), store, MONDAY)
