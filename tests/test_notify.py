"""Der Tagesbericht als Benachrichtigung aufs Telefon (#98)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from ebook_watchlist import credentials, notify, paths
from ebook_watchlist.config import Settings, load_settings
from ebook_watchlist.digest import (
    SECTION_AUTHORS,
    SECTION_GENRE,
    SECTION_LIBRARY,
    SECTION_PRICES,
    Digest,
    DigestEntry,
    DigestSection,
)
from ebook_watchlist.models import SourceFailure
from ebook_watchlist.run import main
from ebook_watchlist.store import Store

NOW = datetime(2026, 10, 25, 7, 0)


def digest(*sections: DigestSection) -> Digest:
    return Digest(profile_name="Test", generated_at=NOW, since=None, sections=sections)


def entries(*titles_and_details: tuple[str, str]) -> tuple[DigestEntry, ...]:
    return tuple(DigestEntry(title=t, detail=d) for t, d in titles_and_details)


@pytest.fixture
def sent(monkeypatch) -> list[tuple[str, str]]:
    """Was verschickt worden wäre — ohne je etwas zu verschicken."""
    out: list[tuple[str, str]] = []
    monkeypatch.setattr(notify, "deliver", lambda address, title, body: out.append((title, body)))
    monkeypatch.setenv(notify.ADDRESS_ENV, "ntfy://buchfink-test")
    return out


# --- die Nachricht --------------------------------------------------------------


def test_the_title_counts_what_is_to_be_had_and_what_is_new() -> None:
    message = notify.message(digest(
        DigestSection(SECTION_PRICES, entries(("Dark Matter", "12,99 € → 3,99 €"))),
        DigestSection(SECTION_LIBRARY, entries(("Kugelblitz", "jetzt verfügbar"))),
        DigestSection(SECTION_AUTHORS, entries(("A", "x"), ("B", "y"))),
        DigestSection(SECTION_GENRE, entries(("C", "z"))),
    ), public_url=None)

    assert message is not None
    assert message.title == "2 jetzt zu haben · 3 neue Vorschläge"


def test_at_most_three_lines_watchlist_first() -> None:
    message = notify.message(digest(
        DigestSection(SECTION_PRICES, entries(
            ("Eins", "9,99 € → 2,99 €"), ("Zwei", "5,99 € → 1,99 €"),
            ("Drei", "4,99 € → 0,99 €"), ("Vier", "3,99 € → 0,49 €"),
        )),
    ), public_url=None)

    assert message is not None
    lines = message.body.splitlines()
    assert lines == ["Eins — 2,99 €", "Zwei — 1,99 €", "Drei — 0,99 €"]


def test_a_library_hit_says_borrowable() -> None:
    message = notify.message(digest(
        DigestSection(SECTION_LIBRARY, entries(("Kugelblitz", "jetzt verfügbar"))),
    ), public_url=None)

    assert message is not None
    assert message.body.splitlines()[0] == "Kugelblitz — ausleihbar"


def test_the_link_needs_the_address_of_buchfink() -> None:
    hits = DigestSection(SECTION_LIBRARY, entries(("Kugelblitz", "jetzt verfügbar")))

    with_link = notify.message(digest(hits), public_url="http://192.168.178.20:8437")
    without = notify.message(digest(hits), public_url=None)

    assert with_link is not None and without is not None
    assert with_link.body.endswith("http://192.168.178.20:8437/")
    assert "http" not in without.body


def test_nothing_new_is_never_sent() -> None:
    assert notify.message(digest(), public_url=None) is None


def test_only_suggestions_still_make_a_message() -> None:
    message = notify.message(
        digest(DigestSection(SECTION_GENRE, entries(("C", "z")))), public_url=None
    )

    assert message is not None
    assert message.title == "1 neuer Vorschlag"


# --- die Adresse ist ein Geheimnis ----------------------------------------------


def test_the_address_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv(notify.ADDRESS_ENV, "ntfy://aus-der-umgebung")

    assert credentials.secret(notify.ADDRESS_ENV) == "ntfy://aus-der-umgebung"


def test_or_from_the_secrets_file(data_dir: Path, monkeypatch) -> None:
    monkeypatch.delenv(notify.ADDRESS_ENV, raising=False)
    (paths.data_dir() / "secrets.env").write_text(
        "# Kommentar\nANDERES=nicht-gelesen\nEBW_NOTIFY_URL=ntfy://aus-der-datei\n",
        encoding="utf-8",
    )

    assert credentials.secret(notify.ADDRESS_ENV) == "ntfy://aus-der-datei"
    assert "ANDERES" not in __import__("os").environ


def test_an_empty_value_is_no_address(data_dir: Path, monkeypatch) -> None:
    monkeypatch.delenv(notify.ADDRESS_ENV, raising=False)
    (paths.data_dir() / "secrets.env").write_text("EBW_NOTIFY_URL=\n", encoding="utf-8")

    assert credentials.secret(notify.ADDRESS_ENV) is None


def test_without_an_address_nothing_is_sent(data_dir: Path, monkeypatch) -> None:
    called: list = []
    monkeypatch.setattr(notify, "deliver", lambda *a: called.append(a))
    monkeypatch.delenv(notify.ADDRESS_ENV, raising=False)

    notify.after_run(
        digest(DigestSection(SECTION_GENRE, entries(("C", "z")))),
        load_settings(), Store(paths.db_path()), failures=[], ran=["beam"], now=NOW,
    )

    assert called == []


# --- Fehler erst beim zweiten Mal -------------------------------------------------


def test_a_source_failing_once_is_not_reported(data_dir: Path, sent) -> None:
    store = Store(paths.db_path())

    notify.after_run(digest(), load_settings(), store,
                     failures=[SourceFailure("beam", "kaputt")], ran=["beam"], now=NOW)

    assert sent == []


def test_a_source_failing_twice_in_a_row_is_reported(data_dir: Path, sent) -> None:
    store, settings = Store(paths.db_path()), load_settings()
    failure = [SourceFailure("beam", "SourceStructureError: kaputt")]

    notify.after_run(digest(), settings, store, failures=failure, ran=["beam"], now=NOW)
    notify.after_run(digest(), settings, store, failures=failure, ran=["beam"], now=NOW)

    assert len(sent) == 1
    title, body = sent[0]
    assert "beam" in title
    assert "kaputt" in body


def test_a_success_in_between_resets_the_count(data_dir: Path, sent) -> None:
    store, settings = Store(paths.db_path()), load_settings()
    failure = [SourceFailure("beam", "kaputt")]

    notify.after_run(digest(), settings, store, failures=failure, ran=["beam"], now=NOW)
    notify.after_run(digest(), settings, store, failures=[], ran=["beam"], now=NOW)
    notify.after_run(digest(), settings, store, failures=failure, ran=["beam"], now=NOW)

    assert sent == []


def test_a_broken_run_is_reported_at_once(sent) -> None:
    notify.run_broke(RuntimeError("Festplatte voll"))

    assert len(sent) == 1
    assert "abgebrochen" in sent[0][0]
    assert "Festplatte voll" in sent[0][1]


def test_a_failed_delivery_never_breaks_the_run(monkeypatch) -> None:
    def boom(address, title, body):
        raise OSError("kein Netz")

    monkeypatch.setattr(notify, "deliver", boom)
    monkeypatch.setenv(notify.ADDRESS_ENV, "ntfy://x")

    notify.send(notify.Message("t", "b"))  # wirft nicht


# --- im Lauf ----------------------------------------------------------------------


def test_the_run_sends_exactly_when_it_writes_a_digest(data_dir: Path, sent) -> None:
    """Dieselbe Bedingung wie der Tagesbericht: schweigt er, schweigt das Telefon."""
    main(["run"])
    main(["run", "--fruehestens-nach", "0"])

    folder = paths.digests_dir()
    written = list(folder.glob("digest-*.html")) if folder.is_dir() else []
    messages = [title for title, _ in sent if "Quelle" not in title]
    assert len(messages) == len(written)



def test_a_gate_that_failed_for_every_book_is_reported(sent) -> None:
    """Eine abgelaufene Anmeldung bemerkt sonst niemand (#95)."""
    from ebook_watchlist.digest import GateNote

    note = GateNote(unrated=12, reason="Claude Code meldet: OAuth session expired",
                    all_failed=True)
    blocked = replace(digest(), gate=note)

    notify.after_run(blocked, Settings(slug="t", name="T"),
                     _NoStore(), failures=[], ran=[], now=NOW)  # type: ignore[arg-type]

    assert any("Bewertungstor" in title and "OAuth" in body for title, body in sent)


def test_a_single_unrated_book_stays_quiet(sent) -> None:
    from ebook_watchlist.digest import GateNote

    note = GateNote(unrated=1, reason="Zeitüberschreitung", all_failed=False)

    notify.after_run(replace(digest(), gate=note),
                     Settings(slug="t", name="T"),
                     _NoStore(), failures=[], ran=[], now=NOW)  # type: ignore[arg-type]

    assert not any("Bewertungstor" in title for title, _ in sent)


def test_the_gate_line_names_the_reason() -> None:
    from ebook_watchlist.digest import GateNote

    note = GateNote(unrated=12, reason="Claude Code meldet: OAuth session expired")

    assert "OAuth session expired" in note.text


class _NoStore:
    def get_state(self, *a):
        return None

    def set_state(self, *a):
        pass

    def clear_state(self, *a):
        pass
