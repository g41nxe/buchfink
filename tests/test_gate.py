"""Das Bewertungstor mit gerechneten Urteilen (ADR 19, ADR 33, #48).

Kein Test hier ruft ein Modell: der Steckbrief kommt aus einem Stub.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from conftest import needs_vocabulary
from ebook_watchlist import gate
from ebook_watchlist.facets import Counterweight, Facet, Liked, ReadingProfile, load_weights
from ebook_watchlist.models import Delta, DeltaKind, MatchReason, Observation
from ebook_watchlist.portrait import (
    Portrait,
    PortrayalUnavailable,
    Trait,
    fingerprint,
    load_vocabulary,
)
from ebook_watchlist.ratings import BY_READER, book_subject

pytestmark = needs_vocabulary

NOW = datetime(2026, 9, 24, 22, 0)
PROFILE = ReadingProfile(
    facets=(Facet(("brooding", "harsh"), ("Leichenblässe", "Sharp Objects")),),
    counterweights=(Counterweight(("leisurely",), None, ("Herr der Ringe",)),),
    liked=(Liked("brooding"), Liked("harsh")),
)
#: Trägt die Facette ganz: vier Sterne oder mehr.
GOOD = ("brooding", "gritty")
#: Trägt nichts Gemochtes: ein Stern.
POOR = ("leisurely", "lyrical")


@pytest.fixture(scope="module")
def vocabulary():
    return load_vocabulary()


@pytest.fixture(scope="module")
def weights():
    return load_weights()


def discovery(**overrides) -> Observation:
    defaults = dict(
        source="beam",
        source_item_id="1",
        title="Ein Fund",
        match_reason=MatchReason.GENRE_CATEGORY,
        price_cents=399,
    )
    return Observation(**{**defaults, **overrides})


def first_seen(observation: Observation) -> Delta:
    return Delta(DeltaKind.FIRST_SEEN, observation, None)


class Portrayer:
    """Legt zu jedem Fund einen Steckbrief an — und merkt sich, wen er fragte."""

    def __init__(self, vocabulary, terms=GOOD, *, error: Exception | None = None, known=True,
                 skip=()):
        self.vocabulary, self.terms, self.error, self.known = vocabulary, terms, error, known
        self.skip = set(skip)
        self.calls: list[Observation] = []

    def __call__(self, observations) -> dict[tuple[str, str], Portrait]:
        self.calls.extend(observations)
        if self.error is not None:
            raise self.error
        traits = tuple(Trait(t, f"Satz zu {t}", "wissen") for t in self.terms)
        return {
            o.key: Portrait(
                known=self.known,
                fingerprint=fingerprint(self.vocabulary),
                pitch="Ein Buch.",
                traits=traits if self.known else (),
            )
            for o in observations
            if o.key not in self.skip
        }


def run(store, vocabulary, weights, deltas, portrayer, *, profile=PROFILE, budget=10, **kw):
    return gate.apply(
        deltas, store=store, profile=profile, vocabulary=vocabulary, weights=weights,
        portrayer=portrayer, threshold=weights.gate_stars, budget=budget, now=NOW, **kw,
    )


# --- wer durchkommt ---------------------------------------------------------------


def test_a_good_fit_passes(store, vocabulary, weights) -> None:
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    kept, report = run(store, vocabulary, weights, deltas, Portrayer(vocabulary, GOOD))

    assert kept == deltas
    assert report.held_back == 0


def test_a_poor_fit_never_reaches_the_pile(store, vocabulary, weights) -> None:
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    kept, report = run(store, vocabulary, weights, deltas, Portrayer(vocabulary, POOR))

    assert kept == []
    assert report.held_back == 1


def test_the_verdict_of_a_passing_find_is_reported(store, vocabulary, weights) -> None:
    found = discovery(isbn="9783104911854")

    _, report = run(store, vocabulary, weights, [first_seen(found)], Portrayer(vocabulary, GOOD))

    verdict = report.judgements[found.key]
    assert verdict.stars >= 4 and verdict.percent >= 60 and verdict.pitch == "Ein Buch."


def test_a_book_is_described_once_not_every_run(store, vocabulary, weights) -> None:
    """Ein Lauf, der es wiedersieht, darf keinen Aufruf mehr kosten."""
    portrayer = Portrayer(vocabulary)
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    run(store, vocabulary, weights, deltas, portrayer)
    _, second = run(store, vocabulary, weights, deltas, portrayer)

    assert len(portrayer.calls) == 1
    assert second.reused == 1 and second.rated == 0


def test_a_new_profile_version_costs_no_call(store, vocabulary, weights) -> None:
    """Der Steckbrief hängt am Buch, nicht am Profil: eine neue Fassung rechnet
    nur neu."""
    portrayer = Portrayer(vocabulary)
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    run(store, vocabulary, weights, deltas, portrayer)
    run(store, vocabulary, weights, deltas, portrayer, profile=replace(PROFILE, version=2))

    assert len(portrayer.calls) == 1


def test_a_new_profile_can_let_a_held_back_book_through(store, vocabulary, weights) -> None:
    deltas = [first_seen(discovery(isbn="9783104911854"))]
    portrayer = Portrayer(vocabulary, POOR)
    kept, _ = run(store, vocabulary, weights, deltas, portrayer)
    assert kept == []

    friendlier = replace(
        PROFILE,
        facets=PROFILE.facets + (Facet(("leisurely", "lyrical"), ("Ein Buch", "Noch eins")),),
        counterweights=(),
    )
    kept, _ = run(store, vocabulary, weights, deltas, portrayer, profile=friendlier)

    assert len(portrayer.calls) == 1  # nur die Rechnung ändert sich, nie der Aufruf
    assert kept == deltas


def test_the_portrait_follows_the_isbn_across_sources(store, vocabulary, weights) -> None:
    """Dasselbe Buch bei zwei Shops kostet einen Steckbrief, nicht zwei."""
    portrayer = Portrayer(vocabulary)
    at_beam = first_seen(discovery(source="beam", source_item_id="1", isbn="9783104911854"))
    at_onleihe = first_seen(
        discovery(source="onleihe", source_item_id="9", isbn="9783104911854",
                  match_reason=MatchReason.PROFILE_AUTHOR)
    )

    for deltas in ([at_beam], [at_onleihe]):
        run(store, vocabulary, weights, deltas, portrayer)

    assert len(portrayer.calls) == 1


def test_the_whole_blurb_is_fetched_before_the_model_is_asked(store, vocabulary, weights) -> None:
    """Die Kachel einer Trefferliste trägt im Median 197 Zeichen und ist zu 85 %
    abgeschnitten; ein Steckbrief daraus bliebe für immer dünn."""
    teaser = discovery(blurb="Manche Menschen haben Geheimnisse. Heinz…")
    whole = replace(teaser, blurb="Manche Menschen haben Geheimnisse. Heinz Brandt hat Regeln.")
    portrayer = Portrayer(vocabulary)
    fetched: list[tuple[str, str]] = []

    def full_text(observations):
        fetched.extend(o.key for o in observations)
        return [whole]

    run(store, vocabulary, weights, [first_seen(teaser)], portrayer, evidence=full_text)

    assert fetched == [teaser.key]
    assert portrayer.calls[0].blurb == whole.blurb


# --- ohne Urteil wird gezeigt -----------------------------------------------------


def test_the_gate_never_fails_closed(store, vocabulary, weights) -> None:
    """Ohne Steckbrief wird gezeigt. Ein Tor, das im Zweifel schließt,
    verschluckt Neuzugänge stillschweigend — das eine verbotene Verhalten."""
    deltas = [first_seen(discovery(isbn="9783104911854"))]
    broken = Portrayer(vocabulary, error=PortrayalUnavailable("kein Netz"))

    kept, report = run(store, vocabulary, weights, deltas, broken)

    assert kept == deltas
    assert report.unrated == 1


def test_a_rater_that_never_gets_through_is_said_out_loud(store, vocabulary, weights) -> None:
    """Ein Tor, das für jedes Buch scheitert, sieht sonst aus wie ein Tag ohne
    Rückhalt statt wie ein Defekt — und ein Cron-Job wirft stderr weg."""
    from ebook_watchlist.digest import GateNote

    broken = Portrayer(vocabulary, error=PortrayalUnavailable("claude nicht gefunden"))
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(3)]

    kept, report = run(store, vocabulary, weights, deltas, broken)

    assert len(kept) == 3 and report.unrated == 3
    note = GateNote(threshold=3, unrated=report.unrated)
    assert note.is_worth_saying and "konnten nicht bewertet werden" in note.text


def test_a_book_the_model_does_not_know_is_shown(store, vocabulary, weights) -> None:
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    kept, report = run(store, vocabulary, weights, deltas, Portrayer(vocabulary, known=False))

    assert kept == deltas
    assert (report.unrated, report.held_back) == (1, 0)


def test_without_a_rater_the_stored_portraits_still_judge(store, vocabulary, weights) -> None:
    """Kein Schlüssel heißt nicht: kein Tor. Was schon einen Steckbrief hat, wird
    gerechnet; der Rest wird gezeigt und als unbewertet gezählt."""
    known_poor = first_seen(discovery(source_item_id="1", isbn="9783104911854"))
    unknown = first_seen(discovery(source_item_id="2"))
    run(store, vocabulary, weights, [known_poor], Portrayer(vocabulary, POOR))

    kept, report = run(store, vocabulary, weights, [known_poor, unknown], None)

    assert kept == [unknown]
    assert (report.held_back, report.unrated) == (1, 1)


def test_without_a_profile_nothing_is_judged_and_it_is_said(store, vocabulary, weights) -> None:
    portrayer = Portrayer(vocabulary, POOR)
    deltas = [first_seen(discovery())]

    kept, report = run(store, vocabulary, weights, deltas, portrayer, profile=None)

    assert kept == deltas and portrayer.calls == []
    assert report.no_profile and report.held_back == 0


def test_a_run_without_finds_says_nothing_about_the_missing_profile(
    store, vocabulary, weights
) -> None:
    _, report = run(store, vocabulary, weights, [], Portrayer(vocabulary), profile=None)

    assert not report.no_profile


def test_a_watchlist_title_is_never_judged(store, vocabulary, weights) -> None:
    """Die Leserin hat es selbst gewählt — es gegen ihr eigenes Profil
    abzulehnen wäre anmaßend."""
    portrayer = Portrayer(vocabulary, POOR)
    deltas = [first_seen(discovery(match_reason=MatchReason.WATCHLIST))]

    kept, _ = run(store, vocabulary, weights, deltas, portrayer)

    assert kept == deltas and portrayer.calls == []


# --- das Budget -------------------------------------------------------------------


def test_a_run_stops_asking_once_the_budget_is_spent(store, vocabulary, weights) -> None:
    """Der erste Lauf mit einem Schlüssel trifft einen Rückstand von
    dreihundert Entdeckungen. Er darf ihn nicht am Stück abfeuern (ADR 7)."""
    portrayer = Portrayer(vocabulary)
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(5)]

    _, report = run(store, vocabulary, weights, deltas, portrayer, budget=2)

    assert len(portrayer.calls) == 2
    assert report.over_budget == 3


def test_what_the_budget_skips_is_shown_not_dropped(store, vocabulary, weights) -> None:
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(3)]

    kept, report = run(store, vocabulary, weights, deltas, Portrayer(vocabulary, POOR), budget=1)

    assert len(kept) == 2 and report.held_back == 1
    assert report.over_budget == 2


def test_the_rest_is_described_on_the_next_run(store, vocabulary, weights) -> None:
    portrayer = Portrayer(vocabulary)
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(4)]

    run(store, vocabulary, weights, deltas, portrayer, budget=2)
    _, second = run(store, vocabulary, weights, deltas, portrayer, budget=2)

    assert len(portrayer.calls) == 4
    assert second.reused == 2 and second.over_budget == 0


def test_a_stored_portrait_does_not_cost_budget(store, vocabulary, weights) -> None:
    portrayer = Portrayer(vocabulary)
    known = first_seen(discovery(source_item_id="alt"))
    run(store, vocabulary, weights, [known], portrayer, budget=5)

    _, report = run(
        store, vocabulary, weights, [known, first_seen(discovery(source_item_id="neu"))],
        portrayer, budget=1,
    )

    assert (report.reused, report.rated, report.over_budget) == (1, 1, 0)


def test_a_dead_network_costs_the_budget_too(store, vocabulary, weights) -> None:
    """Sonst wären dreihundert vergebliche Anfragen am Stück möglich — genau der
    Ausbruch, den das Budget verhindern soll."""
    broken = Portrayer(vocabulary, error=PortrayalUnavailable("kein Netz"))
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(5)]

    kept, report = run(store, vocabulary, weights, deltas, broken, budget=2)

    assert len(broken.calls) == 2
    assert (report.unrated, report.over_budget) == (2, 3)
    assert kept == deltas


# --- wessen Sterne ----------------------------------------------------------------


def test_her_stars_outrank_the_calculation_and_cost_no_call(store, vocabulary, weights) -> None:
    """Eine 4 von ihr ist eine Tatsache, eine 4 aus der Rechnung ein Vorschlag
    (ADR 17)."""
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=5, confidence="belegt", reason="",
                     profile_version=1, now=NOW, origin=BY_READER)
    portrayer = Portrayer(vocabulary, POOR)

    kept, report = run(
        store, vocabulary, weights, [first_seen(discovery(book_id=book.id))], portrayer
    )

    assert portrayer.calls == [] and len(kept) == 1
    assert report.judgements[kept[0].current.key].by_reader


def test_her_low_stars_hold_back_even_a_good_fit(store, vocabulary, weights) -> None:
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=1, confidence="belegt", reason="",
                     profile_version=1, now=NOW, origin=BY_READER)

    kept, report = run(
        store, vocabulary, weights, [first_seen(discovery(book_id=book.id))],
        Portrayer(vocabulary, GOOD),
    )

    assert kept == [] and report.held_back == 1


def test_her_stars_survive_a_new_profile_version(store, vocabulary, weights) -> None:
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=5, confidence="belegt", reason="",
                     profile_version=1, now=NOW, origin=BY_READER)
    portrayer = Portrayer(vocabulary, POOR)

    run(store, vocabulary, weights, [first_seen(discovery(book_id=book.id))], portrayer,
        profile=replace(PROFILE, version=7))

    assert portrayer.calls == []


# --- Preissturz -------------------------------------------------------------------


def test_a_rejected_book_does_not_come_back_through_a_price_drop(
    store, vocabulary, weights
) -> None:
    """Streng an der Vordertür, offen an der Hintertür: ein Buch, das
    zurückgehalten wurde, meldete sich beim nächsten Nachlass doch."""
    portrayer = Portrayer(vocabulary, POOR)
    found = discovery(isbn="9783104911854", price_cents=399)
    kept, _ = run(store, vocabulary, weights, [first_seen(found)], portrayer)
    assert kept == []

    cheaper = discovery(isbn="9783104911854", price_cents=299)
    kept, report = run(
        store, vocabulary, weights, [Delta(DeltaKind.PRICE_DROP, cheaper, found)], portrayer
    )

    assert kept == [] and report.held_back == 1
    assert len(portrayer.calls) == 1  # der Sturz hat keinen zweiten Steckbrief gekostet


def test_a_price_drop_of_a_passing_book_still_carries_its_verdict(
    store, vocabulary, weights
) -> None:
    portrayer = Portrayer(vocabulary, GOOD)
    found = discovery(isbn="9783104911854", price_cents=399)
    run(store, vocabulary, weights, [first_seen(found)], portrayer)

    cheaper = discovery(isbn="9783104911854", price_cents=299)
    kept, report = run(
        store, vocabulary, weights, [Delta(DeltaKind.PRICE_DROP, cheaper, found)], portrayer
    )

    assert len(kept) == 1 and report.judgements[cheaper.key].stars >= 4


def test_a_price_drop_without_a_portrait_is_shown_and_costs_nothing(
    store, vocabulary, weights
) -> None:
    portrayer = Portrayer(vocabulary, POOR)
    drop = Delta(DeltaKind.PRICE_DROP, discovery(price_cents=299), discovery(price_cents=999))

    kept, _ = run(store, vocabulary, weights, [drop], portrayer)

    assert kept == [drop] and portrayer.calls == []


def test_a_watchlist_price_drop_is_never_measured_against_a_verdict(
    store, vocabulary, weights
) -> None:
    portrayer = Portrayer(vocabulary, POOR)
    found = discovery(isbn="9783104911854", price_cents=399)
    run(store, vocabulary, weights, [first_seen(found)], portrayer)
    on_list = replace(found, match_reason=MatchReason.WATCHLIST, price_cents=299)
    drop = Delta(DeltaKind.PRICE_DROP, on_list, found)

    kept, _ = run(store, vocabulary, weights, [drop], portrayer)

    assert kept == [drop]


# --- was der Review gefunden hat (#48) ---------------------------------------------


def test_the_same_book_at_two_shops_costs_one_call_within_a_run(
    store, vocabulary, weights
) -> None:
    """Dasselbe Buch bei zwei Shops steht unter derselben ISBN — auch innerhalb
    eines Laufs kostet es nur einen Steckbrief und einen Platz im Budget."""
    portrayer = Portrayer(vocabulary)
    at_beam = first_seen(discovery(source="beam", source_item_id="1", isbn="9783104911854"))
    at_onleihe = first_seen(
        discovery(source="onleihe", source_item_id="9", isbn="9783104911854",
                  match_reason=MatchReason.PROFILE_AUTHOR)
    )

    kept, report = run(store, vocabulary, weights, [at_beam, at_onleihe], portrayer, budget=1)

    assert len(portrayer.calls) == 1 and report.rated == 1
    assert kept == [at_beam, at_onleihe]
    assert report.over_budget == 0


def test_an_unreadable_vocabulary_is_counted_as_unrated_not_swallowed() -> None:
    """Ein Lauf, der gar nicht urteilen konnte, darf nicht wie ein ruhiger Tag
    aussehen (ADR 7): die Funde bleiben, und der Bericht zählt sie."""
    deltas = [
        first_seen(discovery(source_item_id="1")),
        first_seen(discovery(source_item_id="2", match_reason=MatchReason.WATCHLIST)),
    ]

    report = gate.unrated_report(deltas)

    assert report.unrated == 1


def test_a_book_the_answer_leaves_out_is_shown_and_counted(store, vocabulary, weights) -> None:
    """Ein Bündel kostet nie mehr als seine ausgelassenen Bücher (#66): das eine
    bleibt unbeschrieben und wird gezeigt, die übrigen sind beurteilt."""
    left_out = first_seen(discovery(source_item_id="2"))
    deltas = [first_seen(discovery(source_item_id="1")), left_out,
              first_seen(discovery(source_item_id="3"))]
    portrayer = Portrayer(vocabulary, POOR, skip=[left_out.current.key])

    kept, report = run(store, vocabulary, weights, deltas, portrayer)

    assert kept == [left_out]
    assert (report.held_back, report.unrated, report.rated) == (2, 1, 2)
    assert len(portrayer.calls) == 3  # ein Bündel, alle drei gefragt
