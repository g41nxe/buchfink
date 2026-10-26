"""Die Bausteinseite ``/_design`` (#113): jeder Baustein in seinen Zuständen."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import needs_vocabulary
from ebook_watchlist.web import create_app


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_the_design_page_shows_every_building_block(client: TestClient) -> None:
    body = client.get("/_design").text

    for section in ("Farben", "Cover", "Buchzeile", "Zeichen", "Pillen", "Sterne",
                    "Statuszeile", "Lauf", "Rückgängig", "Abschnitt und Karte"):
        assert re.search(rf">\s*{section}\s*<", body), section


def test_it_renders_the_real_building_blocks_not_copies(client: TestClient) -> None:
    """Ein Baustein, der hier nachgebaut wäre, liefe seinem Original davon."""
    body = client.get("/_design").text

    assert 'aria-label="neu beurteilen"' in body  # _judge_button.html
    assert 'aria-label="jetzt beurteilen"' in body
    assert "wird beurteilt" in body
    assert 'title="Schnäppchen"' in body  # _cover.html
    assert "zuletzt geprüft" in body  # _status_bar.html
    assert "letzter Lauf fehlgeschlagen" in body
    assert 'id="run-panel"' in body  # _run_panel.html


def test_the_states_that_would_poll_or_act_stay_still(client: TestClient) -> None:
    """Der laufende Hammer und die laufende Lauf-Leiste fragen von selbst nach,
    „Jetzt prüfen“ stieße einen echten Lauf an. Auf der Musterseite darf nichts
    davon geschehen."""
    body = client.get("/_design").text

    assert body.count("hx-disable") >= 1
    assert "inert" in body


def test_a_very_long_title_is_part_of_the_specimens(client: TestClient) -> None:
    body = client.get("/_design").text

    assert "Er – Er ist hier. Er beobachtet dich." in body


def test_the_design_page_is_not_in_the_menu(client: TestClient) -> None:
    assert 'href="/_design"' not in client.get("/").text


def test_the_rows_come_from_the_collection_where_it_has_them(client: TestClient) -> None:
    """Echte Bücher zeigen ehrlicher, wie ein Baustein wirkt, als erfundene —
    die Watchlist des Testbestands nennt „Die sieben Schwestern“."""
    body = client.get("/_design").text

    assert "Die sieben Schwestern" in body
    assert "Watchlist · " in body


def test_an_empty_collection_falls_back_to_examples(unseeded_data_dir: Path) -> None:
    """Im CI und in einem frischen Klon gibt es keine Bücher — die Seite zeigt
    dann erfundene Beispiele statt leerer Abschnitte."""
    body = TestClient(create_app(), raise_server_exceptions=False).get("/_design").text

    assert "Der schuldige Ehemann" in body
    assert "Watchlist · " not in body


def test_the_design_page_switches_between_today_and_a2(client: TestClient) -> None:
    """A2′ (ADR 39) entsteht zuerst hier, umschaltbar gegen den heutigen Stand."""
    body = client.get("/_design").text

    assert 'data-look-choice=""' in body and 'data-look-choice="a2"' in body


def test_the_serif_is_served_by_buchfink_itself(client: TestClient) -> None:
    """Keine fremden Server, auch nicht für eine Schrift (ADR 39)."""
    response = client.get("/static/fraunces.woff2")

    assert response.status_code == 200
    assert response.content[:4] == b"wOF2"
    assert "fonts.googleapis" not in client.get("/_design").text


def test_the_sort_select_and_the_verdict_have_their_place(client: TestClient) -> None:
    """Spinne, Abgleich und Sortierauswahl (#112): die Sortierauswahl steht
    immer da; das Urteil nur, wenn es ein Buch mit Steckbrief gibt."""
    body = client.get("/_design").text

    assert re.search(r">\s*Sortierauswahl\s*<", body)
    assert re.search(r">\s*Urteil, Abgleich und Spinne\s*<", body)
    assert 'name="sort"' in body


@needs_vocabulary
def test_the_verdict_comes_from_a_real_book(client: TestClient, data_dir: Path) -> None:
    from datetime import datetime

    from conftest import STAR_TERMS, give_profile
    from ebook_watchlist import paths
    from ebook_watchlist.judging.portrait import Portrait, Trait, fingerprint, load_vocabulary
    from ebook_watchlist.judging.ratings import book_subject
    from ebook_watchlist.store import Store

    store = Store(paths.db_path())
    give_profile(store)
    book = store.books()[0]
    store.put_portrait(book_subject(book.id), Portrait(
        known=True, fingerprint=fingerprint(load_vocabulary()), pitch="Ein echter Satz.",
        traits=tuple(Trait(t, f"Satz zu {t}", "wissen") for t in STAR_TERMS[4]),
    ), now=datetime(2026, 10, 26, 9, 0))

    body = client.get("/_design").text

    assert "data-fit" in body and "Ein echter Satz." in body
