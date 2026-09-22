"""Genre discovery: what turned up on a shelf the reader follows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from conftest import beam_fixture
from ebook_watchlist.config import ConfigError, Settings, load_dismissals
from ebook_watchlist.diff import compute_deltas, suppress_unseeded_interests
from ebook_watchlist.digest import SECTION_GENRE, build_digest
from ebook_watchlist.dismissals import Dismissed
from ebook_watchlist.junk import is_junk
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.sources.base import RunContext
from ebook_watchlist.sources.beam.source import BeamSource
from ebook_watchlist.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "beam"
NOW = datetime(2026, 9, 4, 6, 0)
SPACE_OPERA = "belletristik/science-fiction/space-opera"
PROFILE = Settings(slug="t", name="T")


def fixture(name: str) -> str:
    return beam_fixture(name)


class RecordingClient:
    def __init__(self, html: str) -> None:
        self.html = html
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None) -> str:
        self.requests.append((url, params))
        return self.html


def source() -> BeamSource:
    return BeamSource(client=RecordingClient(fixture("category-new-arrivals.html")))  # type: ignore[arg-type]


def context(tmp_path: Path, **kwargs) -> RunContext:
    return RunContext(profile_slug="t", store=Store(tmp_path / "s.db"), now=NOW, **kwargs)


def discovery(source_name: str, item_id: str, isbn: str | None = None) -> Observation:
    return Observation(
        source=source_name,
        source_item_id=item_id,
        title="Egal",
        match_reason=MatchReason.GENRE_CATEGORY,
        isbn=isbn,
    )


# --- fetching a shelf -----------------------------------------------------


def test_a_category_is_read_newest_first() -> None:
    beam = source()
    beam.by_category(SPACE_OPERA)

    url, params = beam.client.requests[0]  # type: ignore[attr-defined]
    assert url.endswith("/belletristik/science-fiction/space-opera/")
    assert params["o"] == "1"  # sort by release date


def test_the_shelf_is_recorded_on_every_observation() -> None:
    observations = source().by_category(SPACE_OPERA)

    assert observations
    assert all(o.match_reason is MatchReason.GENRE_CATEGORY for o in observations)
    assert all(o.category == SPACE_OPERA for o in observations)
    assert all(o.original_price_cents is None for o in observations)


def test_a_leading_or_trailing_slash_does_not_change_the_request() -> None:
    beam = source()
    beam.by_category("/" + SPACE_OPERA + "/")
    url, _ = beam.client.requests[0]  # type: ignore[attr-defined]
    assert url.endswith("/belletristik/science-fiction/space-opera/")


# --- what counts as new ---------------------------------------------------


def _bargains(observations):
    """The shelf as if everything on it were cheap.

    A discovery only reaches the reader as a deal (ADR 19), so a test about
    *newness* has to hold the price constant or it measures the price rule
    instead.
    """
    return [replace(o, price_cents=399) for o in observations if not is_junk(o)]


def test_a_new_arrival_is_reported_once_and_then_stays_quiet() -> None:
    observations = _bargains(source().by_category(SPACE_OPERA))

    first_run = compute_deltas(observations, {}, PROFILE)
    assert len(first_run) == len(observations)

    already_known = {o.key: o for o in observations}
    assert compute_deltas(observations, already_known, PROFILE) == []


def test_a_full_price_arrival_is_recorded_but_not_announced() -> None:
    """It is not lost — the Observation is stored, so the day the price drops
    the mid-band tier picks it up."""
    full_price = [
        o for o in source().by_category(SPACE_OPERA) if (o.price_cents or 0) >= 500
    ]
    assert full_price
    assert compute_deltas(full_price, {}, PROFILE) == []


def test_a_shelf_being_followed_for_the_first_time_is_seeded_quietly() -> None:
    """Everything on a fresh shelf is technically new; none of it is news."""
    observations = _bargains(source().by_category(SPACE_OPERA))
    deltas = compute_deltas(observations, {}, PROFILE)
    origin = {observation.key: 7 for observation in observations}

    assert suppress_unseeded_interests(deltas, origin, seeded=set()) == []
    assert suppress_unseeded_interests(deltas, origin, seeded={7}) == deltas


def test_seeding_only_silences_first_sightings_not_real_changes() -> None:
    dropped = Observation(
        source="beam",
        source_item_id="1",
        title="Ein Titel",
        match_reason=MatchReason.GENRE_CATEGORY,
        category=SPACE_OPERA,
        price_cents=499,
    )
    before = replace(dropped, price_cents=1299)
    deltas = compute_deltas([dropped], {dropped.key: before})

    assert suppress_unseeded_interests(deltas, {dropped.key: 7}, seeded=set()) == deltas


def test_each_interest_is_seeded_on_its_own() -> None:
    """Der behobene Fehler: vorher teilten sich alle Autor:innen eine Aussaat,
    weil der Schlüssel bei ihnen leer blieb (Ticket 05)."""
    observations = _bargains(source().by_category(SPACE_OPERA))
    deltas = compute_deltas(observations, {}, PROFILE)
    assert deltas
    origin = {observation.key: 7 for observation in observations}

    # Ein *anderes* Interesse ist angesät — dieses hier nicht.
    assert suppress_unseeded_interests(deltas, origin, seeded={8}) == []


def test_suggestions_land_in_their_own_section_never_among_real_hits() -> None:
    observations = source().by_category(SPACE_OPERA)
    digest = build_digest(
        profile_name="T",
        generated_at=NOW,
        since=None,
        deltas=compute_deltas(_bargains(observations), {}, PROFILE),
        failures=[],
        settings=PROFILE,
    )

    assert [section.title for section in digest.sections] == [SECTION_GENRE]
    detail = digest.sections[0].entries[0].detail
    # Der Anlass steht da, in Worten - nicht der rohe Regalpfad (Ticket 14).
    assert detail and detail.startswith("neu im Thema Space Opera")
    assert SPACE_OPERA not in detail


# --- dismissals -----------------------------------------------------------


def test_a_dismissed_suggestion_never_comes_back(tmp_path: Path) -> None:
    beam = source()
    all_ids = {o.source_item_id for o in beam.by_category(SPACE_OPERA)}
    unwanted = sorted(all_ids)[0]

    settings = Settings(slug="t", name="T", genre_categories=[SPACE_OPERA])
    ctx = context(tmp_path, dismissed=Dismissed(items=frozenset({("beam", unwanted)})))
    observations = beam.collect(settings, [], ctx)

    assert unwanted not in {o.source_item_id for o in observations}
    assert len(observations) == len(all_ids) - 1


def test_a_product_number_only_speaks_for_its_own_shop(tmp_path: Path) -> None:
    """Die Nummer ist die Sprache eines Shops. Sie auf eine andere Quelle zu
    übertragen hiesse, zwei fremde Nummernkreise gleichzusetzen."""
    ctx = context(tmp_path, dismissed=Dismissed(items=frozenset({("onleihe", "123")})))
    assert ctx.is_dismissed(discovery("onleihe", "123"))
    assert not ctx.is_dismissed(discovery("beam", "123"))


def test_the_isbn_carries_a_dismissal_to_every_source(tmp_path: Path) -> None:
    """Der eigentliche Anlass von Ticket 17: "das besitze ich schon" gilt dem
    Buch, nicht dem Regal eines Shops (ADR 18)."""
    ctx = context(tmp_path, dismissed=Dismissed(isbns=frozenset({"9783641117009"})))

    assert ctx.is_dismissed(discovery("onleihe", "irgendwas", isbn="9783641117009"))
    assert not ctx.is_dismissed(discovery("onleihe", "irgendwas", isbn="9783641130008"))
    # Ohne ISBN bleibt nur die Nummer, und die kennt diese Ablehnung nicht.
    assert not ctx.is_dismissed(discovery("onleihe", "irgendwas"))


def test_an_absent_dismissal_file_simply_means_nothing_is_dismissed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EBW_DATA_DIR", str(tmp_path))
    assert load_dismissals() == {}


def test_dismissals_are_read_per_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EBW_DATA_DIR", str(tmp_path))
    (tmp_path / "dismissed.yaml").write_text("beam:\n  - 1278797\n", encoding="utf-8")
    assert load_dismissals() == {"beam": frozenset({"1278797"})}


def test_a_malformed_dismissal_file_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EBW_DATA_DIR", str(tmp_path))
    (tmp_path / "dismissed.yaml").write_text("beam: 1278797\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a list"):
        load_dismissals()
