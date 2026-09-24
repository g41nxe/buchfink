"""Gekauft, oder nicht mehr interessant (Ticket 48).

`put_relation` fasst immer nur **eine** Art an. Wer auf der Buchseite „besitze
ich" klickte, bekam `owned` dazu — `watching` blieb aktiv, das Buch wurde
weiter abgerufen und weiter gemeldet. Genau der Fall, der bei *Auslöschung*
auffiel: ausgegraut und trotzdem als ausleihbar markiert.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app, watchlist

NOW = datetime(2026, 9, 6, 20, 0)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


def beobachtet(db: Store, titel: str = "Kugelblitz") -> int:
    settings = load_settings()
    buch = db.find_or_create_book(isbn=None, title=titel, author="Cixin Liu", now=NOW)
    db.put_relation(settings.slug, buch.id, str(RelationKind.WATCHING), now=NOW)
    return buch.id


def titel(db: Store) -> list[str]:
    return [e.title for e in watchlist.entries(db, load_settings())]


def arten(db: Store, buch_id: int) -> dict[str, bool]:
    return {
        row.kind: row.active for row in db.relations_of(load_settings().slug, buch_id)
    }


def test_buying_it_ends_the_watching(client: TestClient, db: Store) -> None:
    buch_id = beobachtet(db)

    client.post(f"/watchlist/{buch_id}/finish", data={"kind": "owned"})

    zustand = arten(db, buch_id)
    assert zustand["owned"] is True
    assert zustand["watching"] is False


def test_what_is_finished_leaves_the_list(client: TestClient, db: Store) -> None:
    """Die Watchlist zeigt, was beobachtet wird."""
    buch_id = beobachtet(db)
    assert "Kugelblitz" in titel(db)

    client.post(f"/watchlist/{buch_id}/finish", data={"kind": "owned"})

    assert "Kugelblitz" not in titel(db)


def test_no_longer_interested_works_the_same_way(client: TestClient, db: Store) -> None:
    buch_id = beobachtet(db)

    client.post(f"/watchlist/{buch_id}/finish", data={"kind": "dismissed"})

    assert arten(db, buch_id)["dismissed"] is True
    assert "Kugelblitz" not in titel(db)


def test_the_history_survives(client: TestClient, db: Store) -> None:
    """Stillgelegt, nicht gelöscht: dass ein Buch einmal beobachtet wurde, ist
    selbst eine Auskunft (ADR 18)."""
    buch_id = beobachtet(db)

    client.post(f"/watchlist/{buch_id}/finish", data={"kind": "owned"})

    assert arten(db, buch_id)["watching"] is False
    assert arten(db, buch_id)["owned"] is True


def test_a_kind_that_is_not_an_ending_changes_nothing(client: TestClient, db: Store) -> None:
    """Nur `owned` und `dismissed` schließen ab. „gefiel mir" beendet keine
    Beobachtung — sonst verschwände ein Buch, weil man es gelobt hat."""
    buch_id = beobachtet(db)

    client.post(f"/watchlist/{buch_id}/finish", data={"kind": "liked"})

    assert arten(db, buch_id)["watching"] is True
    assert "Kugelblitz" in titel(db)


def test_a_paused_entry_still_shows(client: TestClient, db: Store) -> None:
    """Nicht geprüft ist nicht dasselbe wie abgeschlossen."""
    buch_id = beobachtet(db)

    client.post(f"/watchlist/{buch_id}/active", data={"active": "0"})

    assert "Kugelblitz" in titel(db)


def test_the_row_menu_holds_the_endings_not_the_setting(
    client: TestClient, db: Store
) -> None:
    """„Prüfen bei" ist eine Einstellung und steht seit Ticket 48 auf der
    Buchseite; in der Zeile blieben die Abschlüsse."""
    beobachtet(db)

    body = client.get("/watchlist").text

    # Handlungswoerter, nicht Zustandsnamen: im Menue *tut* man etwas (Issue #5).
    assert "Hab ich" in body
    assert "Ausschließen" in body
    assert "Prüfen bei" not in body


def test_the_book_page_holds_the_setting(client: TestClient, db: Store) -> None:
    buch_id = beobachtet(db)

    body = client.get(f"/book/{buch_id}").text

    assert "Prüfen bei" in body
    assert f"/book/{buch_id}/restrict" in body


def test_a_book_nobody_watches_is_not_asked_where_to_check(
    client: TestClient, db: Store
) -> None:
    """Ohne Beobachtung gibt es nichts zu prüfen — die Frage wäre gegenstandslos."""
    buch = db.find_or_create_book(isbn=None, title="Nur gefunden", author="Wer", now=NOW)

    assert "Prüfen bei" not in client.get(f"/book/{buch.id}").text
