"""Die Bausteinseite ``/_design`` (#113): jeder Baustein in seinen Zuständen."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
