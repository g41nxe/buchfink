from __future__ import annotations

from pathlib import Path

import pytest

from ebook_watchlist.config import ConfigError, load_profile, load_watchlist


def test_loads_profile_with_defaults(data_dir: Path) -> None:
    profile = load_profile()
    assert profile.slug == "test"
    assert profile.strong_deal_max_cents == 500
    assert profile.deal_max_cents == 1000
    assert profile.min_discount_pct == 25
    assert profile.sources == {"fake": {"fixture": "fake-source.yaml"}}


def test_loads_watchlist(data_dir: Path) -> None:
    entries = load_watchlist()
    assert [entry.title for entry in entries] == ["Die sieben Schwestern"]
    assert entries[0].check_library is True
    assert entries[0].check_shop is True


def test_missing_profile_fails_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EBW_DATA_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="profile.yaml not found"):
        load_profile()


def test_empty_watchlist_file_fails_loudly(data_dir: Path) -> None:
    (data_dir / "watchlist.yaml").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="is empty"):
        load_watchlist()


def test_broken_yaml_fails_loudly(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text("slug: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_profile()


def test_missing_required_field_fails_loudly(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text("name: Ohne Slug\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="'slug'"):
        load_profile()


def test_inverted_deal_thresholds_rejected(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nstrong_deal_max_cents: 2000\ndeal_max_cents: 1000\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="must be below"):
        load_profile()


def test_duplicate_watchlist_entry_rejected(data_dir: Path) -> None:
    (data_dir / "watchlist.yaml").write_text(
        "- title: A\n  author: B\n- title: a\n  author: b\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_watchlist()


def test_shipped_examples_load(monkeypatch: pytest.MonkeyPatch) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples"
    monkeypatch.setenv("EBW_DATA_DIR", str(examples))
    assert load_profile().slug == "default"
    assert len(load_watchlist()) == 2


def test_a_zero_discount_threshold_is_allowed(data_dir: Path) -> None:
    """"Any drop inside the band counts" is a real setting, not a mistake."""
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nmin_discount_pct: 0\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    assert load_profile().min_discount_pct == 0


def test_a_discount_threshold_of_a_hundred_percent_is_rejected(data_dir: Path) -> None:
    """Nothing can ever be 100% below its old price."""
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nmin_discount_pct: 100\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="0 to 99"):
        load_profile()


def test_the_price_ceilings_still_have_to_be_positive(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nstrong_deal_max_cents: 0\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="positive integer"):
        load_profile()


def test_the_rating_budget_is_configurable(data_dir: Path) -> None:
    """Wie viele Urteile ein Lauf einholt, entscheidet die Konfiguration —
    im Zweifel weniger (ADR 19, Ticket 20)."""
    assert load_profile().rating_budget == 40
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nrating_budget: 5\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    assert load_profile().rating_budget == 5


def test_a_budget_of_zero_is_rejected(data_dir: Path) -> None:
    """Kein Budget heißt "kein Tor" — dafür lässt man den Schlüssel weg,
    statt eine Null zu konfigurieren, die wie eine Panne aussieht."""
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nrating_budget: 0\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="positive integer"):
        load_profile()


def test_liked_books_are_kept_even_though_nothing_reads_them_yet(data_dir: Path) -> None:
    """Dormant like no_gos: the seed for judging whether a discovered title fits
    the reader, and the list only gets sharper the longer it is kept."""
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nliked_books:\n  - Cry Baby - Gillian Flynn\n"
        "sources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    assert load_profile().liked_books == ["Cry Baby - Gillian Flynn"]


def test_no_liked_books_is_simply_an_empty_list(data_dir: Path) -> None:
    assert load_profile().liked_books == []


def test_the_cadence_comes_from_the_profile(data_dir: Path) -> None:
    """Wie oft gelaufen wird, ist eine Einstellung und keine Konstante: das
    Journal weiss, wann zuletzt gelaufen wurde, die Kadenz sagt, ab wann
    wieder."""
    assert load_profile().run_every_hours == 20
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nrun_every_hours: 6\nsources: {fake: {fixture: f.yaml}}\n",
        encoding="utf-8",
    )
    assert load_profile().run_every_hours == 6


# --- Sprachen (#10) ----------------------------------------------------------


def test_german_is_the_default_language(data_dir: Path) -> None:
    assert load_profile().languages == ("ger",)


def test_the_languages_can_be_set(data_dir: Path) -> None:
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nlanguages: [ger, eng]\n", encoding="utf-8"
    )
    assert load_profile().languages == ("ger", "eng")


def test_a_language_is_a_dnb_code(data_dir: Path) -> None:
    """Die DNB liefert ISO 639-2 — ``ger``, nicht ``de`` und nicht "Deutsch".
    Ein falscher Code filterte sonst still jeden Fund heraus."""
    (data_dir / "profile.yaml").write_text(
        "slug: t\nname: T\nlanguages: [de]\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="languages"):
        load_profile()
