from __future__ import annotations

from datetime import datetime

from ebook_watchlist.digest import (
    SECTION_ERRORS,
    SECTION_GENRE,
    SECTION_LIBRARY,
    SECTION_PRICES,
    GateNote,
    build_digest,
)
from ebook_watchlist.facets import Reason
from ebook_watchlist.judging import Verdict
from ebook_watchlist.models import (
    Availability,
    Delta,
    DeltaKind,
    MatchReason,
    Observation,
    SourceFailure,
)
from ebook_watchlist.render import render_html, render_text

NOW = datetime(2026, 9, 4, 6, 0)
THEN = datetime(2026, 9, 3, 6, 0)


def build(**kwargs):
    defaults = dict(
        profile_name="Testprofil",
        generated_at=NOW,
        since=THEN,
        deltas=[],
        failures=[],
    )
    return build_digest(**{**defaults, **kwargs})


def observation(**overrides) -> Observation:
    defaults = dict(
        source="fake",
        source_item_id="1",
        title="Ein Titel",
        author="Eine Autorin",
        match_reason=MatchReason.WATCHLIST,
    )
    return Observation(**{**defaults, **overrides})


def test_nothing_to_report_is_empty() -> None:
    assert build().is_empty


def test_empty_sections_are_omitted_and_order_is_fixed() -> None:
    digest = build(
        deltas=[
            Delta(
                DeltaKind.PRICE_DROP,
                observation(
                    source_item_id="2",
                    price_cents=499,
                    match_reason=MatchReason.GENRE_CATEGORY,
                ),
                observation(
                    source_item_id="2",
                    price_cents=999,
                    match_reason=MatchReason.GENRE_CATEGORY,
                ),
            ),
            Delta(
                DeltaKind.BECAME_AVAILABLE,
                observation(availability=Availability.AVAILABLE),
                observation(availability=Availability.UNAVAILABLE),
            ),
        ]
    )
    assert [section.title for section in digest.sections] == [SECTION_LIBRARY, SECTION_GENRE]


def test_error_section_is_always_last_and_renders_on_its_own() -> None:
    digest = build(failures=[SourceFailure("onleihe", "structure changed")])
    assert [section.title for section in digest.sections] == [SECTION_ERRORS]
    assert not digest.is_empty
    assert "structure changed" in render_text(digest)


def test_price_delta_shows_both_prices() -> None:
    digest = build(
        deltas=[
            Delta(
                DeltaKind.PRICE_DROP,
                observation(price_cents=499),
                observation(price_cents=1299),
            )
        ]
    )
    section = digest.sections[0]
    assert section.title == SECTION_PRICES
    assert section.entries[0].detail == "12,99 € → 4,99 €"


def test_headline_names_the_previous_check() -> None:
    assert build().headline == "Änderungen seit letztem Check 03.09.2026 06:00"
    assert build(since=None).headline == "Erster Check"


def test_renderers_cover_every_entry() -> None:
    digest = build(
        deltas=[
            Delta(
                DeltaKind.BECAME_AVAILABLE,
                observation(availability=Availability.AVAILABLE, url="https://example.invalid/x"),
                observation(availability=Availability.UNAVAILABLE, reservation_count=3),
            )
        ]
    )
    text = render_text(digest)
    assert "Ein Titel" in text
    assert "jetzt verfügbar (zuvor 3 Vormerkungen)" in text
    assert "https://example.invalid/x" in text

    html = render_html(digest)
    assert html.startswith("<!doctype html>")
    assert 'href="https://example.invalid/x"' in html
    assert "Ein Titel" in html


def test_html_escapes_scraped_text() -> None:
    digest = build(
        deltas=[
            Delta(
                DeltaKind.PRICE_DROP,
                observation(title="<script>alert(1)</script>", price_cents=499),
                observation(title="<script>alert(1)</script>", price_cents=999),
            )
        ]
    )
    html = render_html(digest)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --- das Bewertungstor im Digest (Ticket 20) --------------------------------


def discovered() -> Delta:
    return Delta(
        DeltaKind.FIRST_SEEN,
        observation(source_item_id="7", match_reason=MatchReason.GENRE_CATEGORY),
        None,
    )


def test_the_digest_names_what_the_gate_held_back() -> None:
    """Auf stderr wirft ein Cron-Job es weg; ein zu scharfer Schwellwert sähe
    dann aus wie ein ruhiger Tag."""
    digest = build(deltas=[discovered()], gate=GateNote(held_back=12, threshold=3))

    assert "12 Vorschläge unter 3 Sternen zurückgehalten" in render_text(digest)
    assert "12 Vorschläge" in render_html(digest)


def test_a_digest_that_only_has_something_held_back_is_not_empty() -> None:
    """Genau dann muss die Leserin merken, dass das Tor arbeitet."""
    assert not build(gate=GateNote(held_back=3, threshold=3)).is_empty
    assert build(gate=GateNote(threshold=3)).is_empty


def test_the_digest_says_what_the_budget_left_unjudged() -> None:
    text = render_text(build(gate=GateNote(threshold=3, over_budget=8)))
    assert "8 heute nicht bewertet" in text
    assert "ungeprüft gezeigt" in text


def test_a_suggestion_carries_its_verdict() -> None:
    """Sterne, Prozent und Begründung waren gespeichert und für niemanden
    nachprüfbar (ADR 19, Ticket 14); seit #48 rechnet sie der Code."""
    delta = discovered()
    verdict = Verdict(
        stars=4,
        percent=63,
        reasons=(
            Reason("ganz", "gezeichnete Figur · hart"),
            Reason("beleg", "Sie trägt ein Geheimnis."),
            Reason("dagegen", "gemächlich"),
        ),
        pitch="Ein Ermittler mit Vergangenheit.",
    )
    digest = build(deltas=[delta], judgements={delta.current.key: verdict})

    text = render_text(digest)
    assert "Übereinstimmung ★★★★☆ 63 %" in text
    assert "gezeichnete Figur · hart" in text and "dagegen: gemächlich" in text
    assert "Sie trägt ein Geheimnis." not in text  # die Marken, nicht die Sätze
    assert "Ein Ermittler mit Vergangenheit." in text
    assert "gezeichnete Figur" in render_html(digest)


def test_her_own_stars_are_shown_as_hers() -> None:
    delta = discovered()
    digest = build(deltas=[delta], judgements={delta.current.key: Verdict(5, by_reader=True)})

    assert "Deine Sterne ★★★★★" in render_text(digest)


def test_the_digest_says_when_there_is_no_profile_yet() -> None:
    """Ohne Profil wird nichts geurteilt (ADR 33, Punkt 8) — und das soll dastehen,
    sonst sieht ein Stapel ohne Urteile aus wie ein Defekt."""
    digest = build(gate=GateNote(threshold=3, no_profile=True))

    assert not digest.is_empty
    assert "noch kein Leseprofil" in render_text(digest)
    assert "Erstaufnahme" in render_html(digest)


def test_a_gate_note_about_nothing_stays_silent() -> None:
    assert build(gate=GateNote(threshold=3)).is_empty
