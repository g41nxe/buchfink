"""Der Vorteil einer Sammelausgabe (ADR 24).

Kein Test hier braucht die Datenbank: die Preise kommen als Funktion herein.
"""

from __future__ import annotations

import pytest

from ebook_watchlist.bundle_deal import advantage_for
from ebook_watchlist.config import Settings
from ebook_watchlist.models import MatchReason, Observation

PROFIL = Settings(slug="test", name="Test", contact="test@example.invalid")

#: Die echten Preise aus dem Bestand, in Cent.
PREISE = {
    "Der Kruzifix-Killer": 1099,
    "Der Vollstrecker": 1099,
    "Kakerlaken": 1099,
    "Rotkehlchen": 1099,
}


def preis(titel: str) -> int | None:
    return PREISE.get(titel)


def fund(
    title: str,
    price_cents: int | None = 1299,
    reason: MatchReason = MatchReason.PROFILE_AUTHOR,
) -> Observation:
    return Observation(
        source="beam",
        source_item_id="1",
        title=title,
        author="Chris Carter",
        match_reason=reason,
        price_cents=price_cents,
    )


def test_two_volumes_for_less_than_two_singles_is_an_advantage() -> None:
    """Der echte Fall: 12,99 € gegen 21,98 €."""
    vorteil = advantage_for(fund("Der Kruzifix-Killer / Der Vollstrecker"), PROFIL, preis)

    assert vorteil is not None
    assert vorteil.volumes == ("Der Kruzifix-Killer", "Der Vollstrecker")
    assert vorteil.singles_cents == 2198
    assert vorteil.saved_pct == 41
    assert "41 % gespart" in vorteil.summary


def test_nothing_is_estimated_when_a_single_price_is_missing() -> None:
    """Ein fehlender Einzelpreis macht die Summe zu einer Schätzung — und ein
    erfundener Vergleich wäre schlimmer als keine Meldung."""
    assert advantage_for(fund("Der Kruzifix-Killer / Unbekannt"), PROFIL, preis) is None


def test_a_bundle_without_volume_titles_yields_nothing() -> None:
    """"3in1 Bundle" nennt keinen Bandtitel. Die Zahl aus dem Namen zu
    hochzurechnen ginge — aber gemessen liest ein Zähler am Titel mindestens
    drei von neunzehn falsch."""
    assert advantage_for(fund("David Hunter: 3in1 Bundle"), PROFIL, preis) is None


def test_a_shelf_find_is_never_a_bundle_advantage() -> None:
    """14 der 19 Sammelausgaben im Bestand sind Massenware vom Themenregal."""
    beobachtung = fund(
        "Der Kruzifix-Killer / Der Vollstrecker", reason=MatchReason.GENRE_CATEGORY
    )
    assert advantage_for(beobachtung, PROFIL, preis) is None


def test_a_watchlist_bundle_counts() -> None:
    beobachtung = fund("Der Kruzifix-Killer / Der Vollstrecker", reason=MatchReason.WATCHLIST)
    assert advantage_for(beobachtung, PROFIL, preis) is not None


@pytest.mark.parametrize("preis_cents", [2198, 2200, 1700])
def test_too_small_a_saving_is_no_advantage(preis_cents: int) -> None:
    """Die Schwelle ist ``min_discount_pct`` aus dem Profil — 25 %. 17,00 €
    gegen 21,98 € sind 23 % und reichen nicht."""
    beobachtung = fund("Der Kruzifix-Killer / Der Vollstrecker", price_cents=preis_cents)
    assert advantage_for(beobachtung, PROFIL, preis) is None


def test_an_ordinary_title_is_no_bundle() -> None:
    assert advantage_for(fund("Der Kruzifix-Killer"), PROFIL, preis) is None


# --- der Weg durch die Meldelogik (ADR 24) ---------------------------------


def test_a_bundle_advantage_is_reported_although_it_is_no_bargain() -> None:
    """12,99 € ist weder unter der Schnäppchengrenze noch ein Preissturz. Genau
    dafür gibt es den dritten Weg: der absolute Preis ist beim Bündel die
    falsche Frage, denn zwei Bände sind teurer als einer."""
    from ebook_watchlist.diff import worth_announcing

    beobachtung = fund("Der Kruzifix-Killer / Der Vollstrecker")
    assert worth_announcing(beobachtung, PROFIL) is False

    vorteil = advantage_for(beobachtung, PROFIL, preis)
    assert worth_announcing(beobachtung, PROFIL, bundle_advantage=vorteil) is True


# --- der Weg bis in den Tagesbericht (Review nach 1.0) ----------------------


def test_a_bundle_advantage_produces_a_first_sighting() -> None:
    """Der Befund aus dem Review: `worth_announcing` kannte den Bündelvorteil,
    aber `compare` reichte ihn nicht durch. Ein neu auftauchendes Bündel blieb
    deshalb still, obwohl der Stapel es zeigte — die Entscheidung aus ADR 24
    war nur zur Hälfte umgesetzt."""
    from ebook_watchlist.diff import compute_deltas
    from ebook_watchlist.models import DeltaKind

    beobachtung = fund("Der Kruzifix-Killer / Der Vollstrecker")

    ohne = compute_deltas([beobachtung], {}, PROFIL)
    assert ohne == []

    mit = compute_deltas(
        [beobachtung], {}, PROFIL, lambda o: advantage_for(o, PROFIL, preis)
    )
    assert [delta.kind for delta in mit] == [DeltaKind.FIRST_SEEN]


def test_the_digest_says_why_the_bundle_is_there() -> None:
    """Ohne den Satz stünde ein Titel zu 12,99 € ohne erkennbaren Grund im
    Tagesbericht — weder Schnäppchen noch Preissturz."""
    from datetime import datetime

    from ebook_watchlist.digest import build_digest
    from ebook_watchlist.models import Delta, DeltaKind

    beobachtung = fund("Der Kruzifix-Killer / Der Vollstrecker")
    digest = build_digest(
        profile_name="Test",
        generated_at=datetime(2026, 9, 6, 10, 0),
        since=None,
        deltas=[Delta(DeltaKind.FIRST_SEEN, beobachtung, None)],
        failures=[],
        settings=PROFIL,
        advantage_of=lambda o: advantage_for(o, PROFIL, preis),
    )

    texte = [
        eintrag.detail or ""
        for abschnitt in digest.sections
        for eintrag in abschnitt.entries
    ]
    assert any("41 % gespart" in text for text in texte)
