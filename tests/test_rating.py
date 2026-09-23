"""Das Bewertungstor (ADR 19, Ticket 12).

Kein Test hier ruft ein Modell. Der Bewerter ist ein Protokoll mit einer
Methode — genau damit ein Stub genügt.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from ebook_watchlist import gate
from ebook_watchlist.models import Delta, DeltaKind, MatchReason, Observation
from ebook_watchlist.rating import (
    BATCH_SIZE,
    ClaudeCodeRater,
    ModelRater,
    Rating,
    RatingUnavailable,
    Scheme,
    build_rater,
    leseprofil_version,
    load_rating_scheme,
    parse_answer,
    parse_many,
    pitch_prompt,
    pitch_trouble,
    prompt_for,
    prompt_for_many,
    rate_in_batches,
    with_better_pitch,
)
from ebook_watchlist.ratings import BY_CONVERSATION, BY_MODEL, BY_READER, book_subject
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 4, 22, 0)
#: Wie das Profil im Prompt ankommt: gerendert, ohne Versionsfeld.
LESEPROFIL = "EINLEITUNG: Hier stünde das Leseprofil."
#: Der Dateiinhalt, aus dem die Version gelesen wird.
LESEPROFIL_YAML = "version: 1\neinleitung: Hier stünde das Leseprofil.\n"
SCHEMA = Scheme(
    text="Hier stünde das Bewertungsschema.",
    prompt_text="Hier stünde das Bewertungsschema.",
    min_stars=0,
    max_stars=5,
    confidences=("belegt", "teils", "vermutet"),
    withhold_from="teils",
)


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


class StubRater:
    def __init__(self, rating: Rating | Exception) -> None:
        self.rating = rating
        self.calls: list[Observation] = []

    def rate(self, observation: Observation) -> Rating:
        self.calls.append(observation)
        if isinstance(self.rating, Exception):
            raise self.rating
        return self.rating


def rating(stars: int) -> Rating:
    return Rating(stars=stars, reason="Achse D: isoliertes Setting", confidence="teils",
                  profile_version=1)


# --- der Maßstab ------------------------------------------------------------


def test_the_leseprofil_states_its_version() -> None:
    assert leseprofil_version(LESEPROFIL_YAML) == 1


def test_a_leseprofil_without_a_version_is_refused() -> None:
    """Ohne Version stünden irgendwann Sterne aus drei Fassungen nebeneinander."""
    with pytest.raises(RatingUnavailable, match="Profilversion"):
        leseprofil_version("einleitung: Eine Datei ganz ohne Versionsfeld.\n")


# --- der Prompt -------------------------------------------------------------


def test_the_prompt_carries_only_public_facts() -> None:
    """Kein Watchlist-Inhalt, kein Besitz, keine Identität der Leserin (ADR 19)."""
    text = prompt_for(
        discovery(author="Max Barry", blurb="Ein Schiff, allein."), LESEPROFIL, SCHEMA
    )

    assert "Max Barry" in text
    assert "Ein Schiff, allein." in text
    assert LESEPROFIL in text
    assert "Bewertungsschema" in text


def test_a_truncated_blurb_says_so() -> None:
    """Ein Modell, das nicht weiß, wie dünn seine Grundlage ist, urteilt zu sicher."""
    text = prompt_for(discovery(blurb="Sydney wollte nur Geld verdienen..."), LESEPROFIL, SCHEMA)
    assert "abgeschnitten" in text


def test_a_whole_blurb_is_not_flagged() -> None:
    text = prompt_for(discovery(blurb="Ein vollständiger Satz."), LESEPROFIL, SCHEMA)
    assert "abgeschnitten" not in text


def test_the_evidence_reaches_the_prompt() -> None:
    """Schlagwörter, Originaltitel und der Anfang des Buchs (#17). Die Probe
    steht als solche ausgewiesen da: das Modell soll wissen, dass es den Text
    selbst liest und nicht noch einen Werbetext."""
    text = prompt_for(
        discovery(
            keywords=("Space Opera", "Dune"),
            original_title="Old Man's War",
            sample="An meinem fünfundsiebzigsten Geburtstag tat ich zwei Dinge.",
        ),
        LESEPROFIL,
        SCHEMA,
    )

    assert "Space Opera, Dune" in text
    assert "Old Man's War" in text
    assert "Leseprobe" in text
    assert "An meinem fünfundsiebzigsten Geburtstag" in text


def test_without_a_sample_the_prompt_says_so() -> None:
    """Sonst liest das Modell das Fehlen nicht mit und belegt aus dem Klappentext."""
    assert "keine Leseprobe" in prompt_for(discovery(), LESEPROFIL, SCHEMA)


# --- die Antwort ------------------------------------------------------------


def test_a_clean_answer_is_read() -> None:
    answer = '{"stars": 4, "confidence": "teils", "reason": "Achse A: Reihe", "trifft": ["Tempo"]}'
    result = parse_answer(answer, version=1, scheme=SCHEMA)

    assert (result.stars, result.confidence) == (4, "teils")
    assert result.profile_version == 1


def test_json_wrapped_in_chatter_is_still_read() -> None:
    answer = 'Gern:\n{"stars": 2, "confidence": "vermutet", "reason": "x"}\n'
    assert parse_answer(answer, 1, SCHEMA).stars == 2


@pytest.mark.parametrize(
    "answer",
    [
        "gar kein JSON",
        '{"stars": 7, "confidence": "teils", "reason": "x"}',
        '{"stars": 3, "confidence": "sicher", "reason": "x"}',
        '{"stars": 3, "confidence": "teils"}',
        '{"confidence": "teils", "reason": "x"}',
    ],
)
def test_an_unusable_answer_is_refused_rather_than_guessed(answer: str) -> None:
    with pytest.raises(RatingUnavailable):
        parse_answer(answer, version=1, scheme=SCHEMA)


# --- das Tor ----------------------------------------------------------------


def test_a_good_fit_passes(store: Store) -> None:
    deltas = [first_seen(discovery(isbn="9783104911854"))]
    kept, report = gate.apply(
        deltas, store=store, rater=StubRater(rating(4)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )
    assert kept == deltas
    assert report.held_back == 0


def test_the_gate_notes_that_it_judged_in_a_run(store: Store) -> None:
    """Drei Wege fuehren zu einem Modellurteil, und hinterher wusste niemand,
    welcher es war — damit war "entscheidet das Tor im Lauf ueberhaupt?"
    nicht zu beantworten (#10)."""
    from ebook_watchlist.ratings import BY_MODEL, VIA_RUN

    gate.apply([first_seen(discovery(isbn="9783104911854"))], store=store,
               rater=StubRater(rating(4)), profile_version=1, threshold=3, budget=10, now=NOW)

    zeile = store.ratings_for(["isbn:9783104911854"])[("isbn:9783104911854", BY_MODEL)]
    assert zeile.via == VIA_RUN


def test_a_poor_fit_never_reaches_the_pile(store: Store) -> None:
    deltas = [first_seen(discovery(isbn="9783104911854"))]
    kept, report = gate.apply(
        deltas, store=store, rater=StubRater(rating(1)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )
    assert kept == []
    assert report.held_back == 1


def test_a_book_is_judged_once_not_every_run(store: Store) -> None:
    """Ein Lauf, der es wiedersieht, darf keinen Aufruf mehr kosten."""
    rater = StubRater(rating(4))
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    gate.apply(deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW)
    _, second = gate.apply(
        deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW
    )

    assert len(rater.calls) == 1
    assert second.reused == 1


def test_the_gate_judges_the_whole_blurb_not_the_teaser(store: Store) -> None:
    """Die Kachel einer Trefferliste traegt im Median 197 Zeichen und ist zu
    85 % abgeschnitten; die Detailseite traegt das Zehnfache. Das Tor urteilte
    bisher auf dem Anriss, waehrend der Rueckstands-Schritt den ganzen Text
    nachlaedt — zwei Wege, dieselbe Frage, verschieden gut beantwortet."""
    angeriss = discovery(blurb="Manche Menschen haben Geheimnisse. Heinz…")
    ganz = replace(angeriss, blurb="Manche Menschen haben Geheimnisse. Heinz Brandt hat Regeln.")
    rater = StubRater(rating(4))
    geholt: list[str] = []

    def voller_text(observations):
        geholt.extend(o.key for o in observations)
        return [ganz]

    gate.apply(
        [first_seen(angeriss)], store=store, rater=rater, profile_version=1,
        threshold=3, budget=10, now=NOW, evidence=voller_text,
    )

    assert geholt == [angeriss.key]
    assert rater.calls[0].blurb == ganz.blurb


def test_a_new_leseprofil_invalidates_the_judgement(store: Store) -> None:
    """Die eine Änderung, bei der ein erneuter Aufruf richtig ist."""
    rater = StubRater(rating(4))
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    gate.apply(deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW)
    gate.apply(deltas, store=store, rater=rater, profile_version=2, threshold=3, budget=10, now=NOW)

    assert len(rater.calls) == 2


def test_the_gate_never_fails_closed(store: Store) -> None:
    """Ohne Urteil wird gezeigt. Ein Tor, das im Zweifel schließt, verschluckt
    Neuzugänge stillschweigend — das eine Verhalten, das verboten ist."""
    deltas = [first_seen(discovery(isbn="9783104911854"))]
    kept, report = gate.apply(
        deltas,
        store=store,
        rater=StubRater(RatingUnavailable("kein Netz")),
        profile_version=1,
        threshold=3,
        budget=10,
        now=NOW,
    )
    assert kept == deltas
    assert report.unrated == 1


def test_without_a_rater_nothing_is_held_back(store: Store) -> None:
    deltas = [first_seen(discovery())]
    kept, report = gate.apply(
        deltas, store=store, rater=None, profile_version=1, threshold=3, budget=10, now=NOW
    )
    assert kept == deltas
    assert report.held_back == 0


def test_a_watchlist_title_is_never_judged(store: Store) -> None:
    """Die Leserin hat es selbst gewählt — es gegen ihr eigenes Profil
    abzulehnen wäre anmaßend."""
    rater = StubRater(rating(0))
    deltas = [first_seen(discovery(match_reason=MatchReason.WATCHLIST))]

    kept, _ = gate.apply(
        deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW
    )

    assert kept == deltas
    assert rater.calls == []


def test_a_price_drop_is_not_judged_again(store: Store) -> None:
    """Es betrifft ein Buch, das schon einmal durchgelassen wurde."""
    rater = StubRater(rating(0))
    drop = Delta(DeltaKind.PRICE_DROP, discovery(price_cents=299), discovery(price_cents=999))

    kept, _ = gate.apply(
        [drop], store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW
    )

    assert kept == [drop]
    assert rater.calls == []


def test_the_judgement_follows_the_isbn_across_sources(store: Store) -> None:
    """Dasselbe Buch bei zwei Shops kostet ein Urteil, nicht zwei."""
    rater = StubRater(rating(4))
    at_beam = first_seen(discovery(source="beam", source_item_id="1", isbn="9783104911854"))
    at_voebb = first_seen(
        discovery(source="onleihe", source_item_id="9", isbn="9783104911854",
                  match_reason=MatchReason.PROFILE_AUTHOR)
    )

    for deltas in ([at_beam], [at_voebb]):
        gate.apply(
            deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW
        )

    assert len(rater.calls) == 1


def test_without_an_isbn_the_find_itself_is_the_subject(store: Store) -> None:
    """Bündel und Einzelfolgen haben keine — ein Urteil je Quelle ist ehrlicher
    als eines, das über den Titel geraten wäre."""
    assert gate.subject_of(discovery(isbn=None)) == "item:beam:1"
    assert gate.subject_of(discovery(isbn="9783104911854")) == "isbn:9783104911854"


# --- das Budget (Ticket 20) -------------------------------------------------


def test_a_run_stops_asking_once_the_budget_is_spent(store: Store) -> None:
    """Der erste Lauf mit einem Schlüssel trifft einen Rückstand von
    dreihundert Entdeckungen. Er darf ihn nicht am Stück abfeuern (ADR 7)."""
    rater = StubRater(rating(4))
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(5)]

    _, report = gate.apply(
        deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=2, now=NOW
    )

    assert len(rater.calls) == 2
    assert report.over_budget == 3


def test_what_the_budget_skips_is_shown_not_dropped(store: Store) -> None:
    """Übersprungen heißt unbewertet. Sonst verschluckte ausgerechnet das
    Sparen die Neuzugänge."""
    rater = StubRater(rating(4))
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(3)]

    kept, report = gate.apply(
        deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=1, now=NOW
    )

    assert kept == deltas
    assert report.held_back == 0


def test_the_rest_is_judged_on_the_next_run(store: Store) -> None:
    """Der Rückstand wird über Läufe abgearbeitet, nicht verloren."""
    rater = StubRater(rating(4))
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(4)]
    kwargs = dict(store=store, rater=rater, profile_version=1, threshold=3, budget=2, now=NOW)

    gate.apply(deltas, **kwargs)
    _, second = gate.apply(deltas, **kwargs)

    assert len(rater.calls) == 4
    assert second.reused == 2
    assert second.over_budget == 0


def test_a_stored_judgement_does_not_cost_budget(store: Store) -> None:
    """Ein gespeichertes Urteil kostet keinen Aufruf — also auch kein Budget."""
    rater = StubRater(rating(4))
    known = first_seen(discovery(source_item_id="alt"))
    gate.apply(
        [known], store=store, rater=rater, profile_version=1, threshold=3, budget=5, now=NOW
    )

    _, report = gate.apply(
        [known, first_seen(discovery(source_item_id="neu"))],
        store=store, rater=rater, profile_version=1, threshold=3, budget=1, now=NOW,
    )

    assert (report.reused, report.rated, report.over_budget) == (1, 1, 0)


# --- was der Lauf weitergibt ------------------------------------------------


def test_without_a_rater_only_discoveries_count_as_unrated() -> None:
    """Ein Watchlist-Titel wird nie beurteilt. Ihn als unbewertet zu zählen
    ergab im Lauf eine andere Zahl als im Tor — eine der beiden war falsch."""
    report = gate.unrated_report(
        [
            first_seen(discovery(source_item_id="1")),
            first_seen(discovery(source_item_id="2", match_reason=MatchReason.WATCHLIST)),
        ]
    )
    assert report.unrated == 1


def test_the_judgement_of_a_passing_find_is_reported(store: Store) -> None:
    """Gespeichert und nie gezeigt konnte niemand das Urteil nachprüfen."""
    found = discovery(isbn="9783104911854")
    _, report = gate.apply(
        [first_seen(found)],
        store=store, rater=StubRater(rating(4)), profile_version=1,
        threshold=3, budget=5, now=NOW,
    )
    assert report.judgements[found.key].stars == 4


def test_a_dead_network_costs_the_budget_too(store: Store) -> None:
    """Sonst wären dreihundert vergebliche Anfragen am Stück möglich — genau
    der Ausbruch, den das Budget verhindern soll."""
    rater = StubRater(RatingUnavailable("kein Netz"))
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(5)]

    kept, report = gate.apply(
        deltas, store=store, rater=rater, profile_version=1, threshold=3, budget=2, now=NOW
    )

    assert len(rater.calls) == 2
    assert (report.unrated, report.over_budget) == (2, 3)
    assert kept == deltas


# --- wessen Sterne (Ticket 21) ----------------------------------------------


def test_the_readers_stars_outrank_the_model_and_cost_no_call(store: Store) -> None:
    """Eine 4 von ihr ist eine Tatsache, eine 4 vom Modell ein Vorschlag
    (ADR 17). Das Tor fragt sie zuerst und ruft dann gar kein Modell mehr."""
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=5, confidence="belegt", reason="",
                     profile_version=1, now=NOW, origin=BY_READER)
    rater = StubRater(rating(1))

    kept, report = gate.apply(
        [first_seen(discovery(book_id=book.id))],
        store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW,
    )

    assert rater.calls == []
    assert (len(kept), report.reused) == (1, 1)


def test_her_stars_survive_a_sharpened_leseprofil(store: Store) -> None:
    """Eine neue Maßstabsversion entwertet ein Modellurteil. Was ein Mensch
    gesagt hat, verfällt nicht, wenn er seinen Maßstab schärft."""
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=5, confidence="belegt", reason="",
                     profile_version=1, now=NOW, origin=BY_READER)
    rater = StubRater(rating(1))

    gate.apply(
        [first_seen(discovery(book_id=book.id))],
        store=store, rater=rater, profile_version=2, threshold=3, budget=10, now=NOW,
    )

    assert rater.calls == []


def test_the_model_never_overwrites_what_she_said(store: Store) -> None:
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=5, confidence="belegt", reason="",
                     profile_version=1, now=NOW, origin=BY_READER)

    store.put_rating(book_subject(book.id), stars=1, confidence="teils", reason="Modell",
                     profile_version=1, now=NOW, origin=BY_MODEL)

    hers = store.rating(book_subject(book.id), 1, origin=BY_READER)
    its = store.rating(book_subject(book.id), 1, origin=BY_MODEL)
    assert (hers.stars, its.stars) == (5, 1)


def test_a_judgement_from_the_conversation_also_spares_the_call(store: Store) -> None:
    """Die dreizehn aus owned.yaml sind gegen denselben Maßstab entstanden —
    sie noch einmal einzuholen wäre Verschwendung."""
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=4, confidence="teils", reason="Reihe.",
                     profile_version=1, now=NOW, origin=BY_CONVERSATION)
    rater = StubRater(rating(1))

    gate.apply(
        [first_seen(discovery(book_id=book.id))],
        store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW,
    )

    assert rater.calls == []


def test_an_unknown_origin_is_refused(store: Store) -> None:
    with pytest.raises(ValueError, match="unbekannte Herkunft"):
        store.put_rating("book:1", stars=4, confidence="teils", reason="", profile_version=1,
                         now=NOW, origin="freund")


def test_taking_her_stars_back_leaves_nothing_rather_than_a_zero(store: Store) -> None:
    """Nicht bewertet und "passt überhaupt nicht" sind zwei Auskünfte."""
    store.put_rating("book:1", stars=4, confidence="belegt", reason="", profile_version=1,
                     now=NOW, origin=BY_READER)

    assert store.drop_rating("book:1", BY_READER) is True
    assert store.rating("book:1", 1, origin=BY_READER) is None
    assert store.drop_rating("book:1", BY_READER) is False


def test_a_rejected_book_does_not_come_back_through_a_price_drop(store: Store) -> None:
    """Streng an der Vordertür, offen an der Hintertür: ein Buch, das mit einem
    Stern zurückgehalten wurde, meldete sich beim nächsten Nachlass doch."""
    rater = StubRater(rating(1))
    found = discovery(isbn="9783104911854", price_cents=399)
    kept, _ = gate.apply(
        [first_seen(found)], store=store, rater=rater, profile_version=1,
        threshold=3, budget=10, now=NOW,
    )
    assert kept == []

    cheaper = discovery(isbn="9783104911854", price_cents=299)
    kept, report = gate.apply(
        [Delta(DeltaKind.PRICE_DROP, cheaper, found)],
        store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW,
    )

    assert kept == []
    assert report.held_back == 1
    assert len(rater.calls) == 1  # der Sturz hat kein zweites Urteil gekostet


def test_a_price_drop_of_a_passing_book_still_carries_its_reason(store: Store) -> None:
    rater = StubRater(rating(4))
    found = discovery(isbn="9783104911854", price_cents=399)
    gate.apply(
        [first_seen(found)], store=store, rater=rater, profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    cheaper = discovery(isbn="9783104911854", price_cents=299)
    kept, report = gate.apply(
        [Delta(DeltaKind.PRICE_DROP, cheaper, found)],
        store=store, rater=rater, profile_version=1, threshold=3, budget=10, now=NOW,
    )

    assert len(kept) == 1
    assert report.judgements[cheaper.key].stars == 4
    assert len(rater.calls) == 1


def test_a_price_drop_without_a_judgement_is_shown(store: Store) -> None:
    """Ein Fund von vor dem Tor hat keins. Ihn dafür zu verschlucken hieße,
    das Schweigen zur Voreinstellung zu machen."""
    found = discovery(isbn="9783104911854", price_cents=999)
    kept, report = gate.apply(
        [Delta(DeltaKind.PRICE_DROP, discovery(isbn="9783104911854", price_cents=899), found)],
        store=store, rater=StubRater(rating(1)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    assert len(kept) == 1
    assert report.held_back == 0


def test_a_watchlist_price_drop_is_never_measured_against_a_judgement(store: Store) -> None:
    store.put_rating("isbn:9783104911854", stars=1, confidence="teils", reason="",
                     profile_version=1, now=NOW, origin=BY_MODEL)
    watched = discovery(isbn="9783104911854", price_cents=999,
                        match_reason=MatchReason.WATCHLIST)

    kept, report = gate.apply(
        [Delta(DeltaKind.PRICE_DROP, watched, watched)],
        store=store, rater=StubRater(rating(1)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    assert len(kept) == 1
    assert report.held_back == 0


# --- der Weg ohne Schlüssel: claude -p (Ticket 12) --------------------------


ANSWER = ('{"stars": 4, "reason": "Achse D: isoliertes Setting", "confidence": "teils", '
          '"trifft": ["Tempo"]}')


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    from subprocess import CompletedProcess

    return CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_the_cli_answer_is_read_out_of_its_json_envelope(monkeypatch) -> None:
    """``--output-format json`` verpackt das Ergebnis in ``result``."""
    import json as _json

    monkeypatch.setattr(
        "ebook_watchlist.rating.subprocess.run",
        lambda *a, **k: _completed(stdout=_json.dumps({"result": ANSWER, "is_error": False})),
    )
    rater = ClaudeCodeRater(leseprofil=LESEPROFIL, version=1)

    assert rater.rate(discovery()).stars == 4


def test_a_bare_answer_is_read_too(monkeypatch) -> None:
    """Auf das Hüllenformat zu bestehen hiesse, an einer fremden Version zu
    hängen. Fehlt sie, geht der Text unverändert in dieselbe Auswertung."""
    monkeypatch.setattr(
        "ebook_watchlist.rating.subprocess.run", lambda *a, **k: _completed(stdout=ANSWER)
    )
    assert ClaudeCodeRater(leseprofil=LESEPROFIL, version=1).rate(discovery()).stars == 4


def test_a_missing_executable_is_no_reason_to_fail_a_run(monkeypatch) -> None:
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr("ebook_watchlist.rating.subprocess.run", boom)
    with pytest.raises(RatingUnavailable, match="nicht gefunden"):
        ClaudeCodeRater(leseprofil=LESEPROFIL, version=1).rate(discovery())


def test_a_timeout_is_reported_as_unavailable(monkeypatch) -> None:
    from subprocess import TimeoutExpired

    def slow(*a, **k):
        raise TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr("ebook_watchlist.rating.subprocess.run", slow)
    with pytest.raises(RatingUnavailable, match="antwortete nicht"):
        ClaudeCodeRater(leseprofil=LESEPROFIL, version=1, timeout=1).rate(discovery())


def test_a_nonzero_exit_names_what_the_cli_said(monkeypatch) -> None:
    monkeypatch.setattr(
        "ebook_watchlist.rating.subprocess.run",
        lambda *a, **k: _completed(returncode=1, stderr="not logged in"),
    )
    with pytest.raises(RatingUnavailable, match="not logged in"):
        ClaudeCodeRater(leseprofil=LESEPROFIL, version=1).rate(discovery())


def test_the_prompt_reaches_the_cli_over_stdin(monkeypatch) -> None:
    """Nicht als Argument: Windows begrenzt eine Kommandozeile auf 32767
    Zeichen, und ein Buendel aus Profil, Verfahren und drei ganzen
    Klappentexten liegt darueber. Python meldet das als FileNotFoundError —
    also ununterscheidbar von "claude ist nicht installiert"."""
    seen: list[tuple[list[str], str | None]] = []

    def capture(command, **kwargs):
        seen.append((command, kwargs.get("input")))
        return _completed(stdout=ANSWER)

    monkeypatch.setattr("ebook_watchlist.rating.subprocess.run", capture)
    ClaudeCodeRater(executable="claude", leseprofil=LESEPROFIL, version=1).rate(
        discovery(title="Blindflug", author="Peter Watts")
    )

    command, prompt = seen[0]
    assert command == ["claude", "-p", "--output-format", "json"]
    assert prompt is not None and "Blindflug" in prompt
    assert not any("Blindflug" in teil for teil in command)


# --- welcher Bewerter gewählt wird ------------------------------------------


def test_a_key_in_the_environment_wins(monkeypatch, tmp_path) -> None:
    """Wer ihn setzt, hat sich für ihn entschieden."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("ebook_watchlist.rating.shutil.which", lambda name: "/usr/bin/claude")

    assert isinstance(build_rater(), ModelRater)


def test_without_a_key_the_local_installation_is_used(monkeypatch) -> None:
    """API-Zugang ist in keinem Claude-Abo enthalten; die angemeldete
    Installation ist der Weg ohne zusätzliches Guthaben."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ebook_watchlist.rating.shutil.which", lambda name: "/usr/bin/claude")

    rater = build_rater()
    assert isinstance(rater, ClaudeCodeRater)
    assert rater.executable == "/usr/bin/claude"


@pytest.mark.parametrize("schluessel", ["sk-test", None])
def test_the_rater_in_use_checks_the_axis_names(monkeypatch, schluessel) -> None:
    """Die Namensprobe aus #12 lief nie: ``build_rater`` reicht das Profil
    herein, und dann luden die Bewerter die Achsen nicht mit. Nur Tests, die
    das Profil selbst laden, sahen sie arbeiten."""
    if schluessel:
        monkeypatch.setenv("ANTHROPIC_API_KEY", schluessel)
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ebook_watchlist.rating.shutil.which", lambda name: "/usr/bin/claude")

    rater = build_rater()

    assert rater.axes and "Tempo" in rater.axes
    assert "Einstieg" not in rater.axes


def test_with_neither_there_is_simply_no_gate(monkeypatch) -> None:
    """Kein Fehler, sondern der Zustand ohne Tor: alles bleibt unbewertet und
    wird gezeigt."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ebook_watchlist.rating.shutil.which", lambda name: None)

    assert build_rater() is None


def test_a_rater_that_never_gets_through_is_said_out_loud(store: Store) -> None:
    """Ein Tor, das für jedes Buch scheitert, sieht sonst aus wie ein Tag ohne
    Rückhalt statt wie ein Defekt — und ein Cron-Job wirft stderr weg."""
    from ebook_watchlist.digest import GateNote

    broken = StubRater(RatingUnavailable("claude nicht gefunden"))
    deltas = [first_seen(discovery(source_item_id=str(n))) for n in range(3)]

    kept, report = gate.apply(
        deltas, store=store, rater=broken,
        profile_version=1, threshold=3, budget=10, now=NOW,
    )

    assert len(kept) == 3  # nichts verschluckt
    assert report.unrated == 3

    note = GateNote(held_back=0, threshold=3, unrated=report.unrated)
    assert note.is_worth_saying
    assert "konnten nicht bewertet werden" in note.text


# --- gebündelte Anfragen (Ticket 12) ---------------------------------------


def _books(count: int) -> list[Observation]:
    return [discovery(source_item_id=str(n), title=f"Buch {n}") for n in range(1, count + 1)]


def _entry(stars: int) -> dict:
    # Ab drei Sternen braucht ein Urteil einen Treffer (#12).
    return {"stars": stars, "confidence": "teils", "reason": f"Achse D, {stars} Sterne",
            "trifft": ["Tempo"] if stars >= 3 else []}


def test_the_leseprofil_goes_out_once_not_once_per_book() -> None:
    """Der eigentliche Gewinn: Verfahren und Profil sind der weitaus größte Teil
    des Prompts, das Buch selbst sind ein paar Zeilen."""
    prompt = prompt_for_many(_books(5), LESEPROFIL, SCHEMA)

    assert prompt.count(LESEPROFIL) == 1
    assert prompt.count(SCHEMA.text) == 1
    for number in range(1, 6):
        assert f"--- BUCH {number} ---" in prompt


def test_every_book_is_numbered_so_the_answer_can_be_matched() -> None:
    """Ohne Kennung liesse sich eine Antwort, die ein Buch auslässt oder
    umsortiert, nicht mehr sicher zuordnen."""
    books = _books(3)
    answer = json.dumps({"1": _entry(5), "2": _entry(1), "3": _entry(4)})

    ratings = parse_many(answer, books, version=1, scheme=SCHEMA)

    assert [ratings[b.key].stars for b in books] == [5, 1, 4]


def test_a_book_the_answer_skips_is_simply_missing() -> None:
    books = _books(3)
    answer = json.dumps({"1": _entry(4), "3": _entry(2)})

    ratings = parse_many(answer, books, version=1, scheme=SCHEMA)

    assert books[1].key not in ratings
    assert set(ratings) == {books[0].key, books[2].key}


def test_one_crooked_entry_costs_one_book_not_the_batch() -> None:
    """Sonst machte eine einzige krumme Zeile zwanzig Bücher unbewertet — der
    Schaden wäre zwanzigmal so groß wie beim Einzelaufruf."""
    books = _books(3)
    answer = json.dumps({"1": _entry(4), "2": {"stars": 99}, "3": _entry(3)})

    ratings = parse_many(answer, books, version=1, scheme=SCHEMA)

    assert set(ratings) == {books[0].key, books[2].key}


def test_an_answer_without_json_fails_the_batch_but_raises_cleanly() -> None:
    with pytest.raises(RatingUnavailable, match="kein JSON"):
        parse_many("Ich kann das nicht beurteilen.", _books(2), version=1, scheme=SCHEMA)


def test_batches_are_capped_at_twenty() -> None:
    class Counting:
        def __init__(self) -> None:
            self.sizes: list[int] = []

        def rate_many(self, observations):
            self.sizes.append(len(observations))
            return {o.key: rating(4) for o in observations}

    rater = Counting()
    ratings = rate_in_batches(rater, _books(45), size=BATCH_SIZE)

    assert rater.sizes == [20, 20, 5]
    assert len(ratings) == 45


def test_a_failed_batch_costs_that_batch_and_no_more() -> None:
    """Was nicht zurückkommt, fehlt — und fehlende Urteile heissen unbewertet
    und gezeigt, nie verworfen."""
    class HalfBroken:
        def __init__(self) -> None:
            self.seen = 0

        def rate_many(self, observations):
            self.seen += 1
            if self.seen == 1:
                raise RatingUnavailable("claude endete mit 1")
            return {o.key: rating(4) for o in observations}

    books = _books(25)
    ratings = rate_in_batches(HalfBroken(), books, size=BATCH_SIZE)

    assert len(ratings) == 5  # nur das zweite Bündel
    assert all(b.key not in ratings for b in books[:20])


def test_a_rater_that_only_knows_single_books_is_still_used() -> None:
    """Der HTTP-Weg, bei dem ein Aufruf fast nichts kostet, bleibt unverändert."""
    single = StubRater(rating(4))
    books = _books(3)

    ratings = rate_in_batches(single, books, size=BATCH_SIZE)

    assert len(single.calls) == 3
    assert len(ratings) == 3


def test_the_cli_asks_once_for_the_whole_batch(monkeypatch) -> None:
    prompts: list[str] = []

    def capture(command, **kwargs):
        prompts.append(command[2])
        return _completed(stdout=json.dumps({"1": _entry(4), "2": _entry(5)}))

    monkeypatch.setattr("ebook_watchlist.rating.subprocess.run", capture)
    books = _books(2)

    ratings = ClaudeCodeRater(leseprofil=LESEPROFIL, version=1).rate_many(books)

    assert len(prompts) == 1
    assert {ratings[b.key].stars for b in books} == {4, 5}


def test_an_empty_batch_asks_nobody(monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("hätte nicht fragen dürfen")

    monkeypatch.setattr("ebook_watchlist.rating.subprocess.run", boom)
    assert ClaudeCodeRater(leseprofil=LESEPROFIL, version=1).rate_many([]) == {}


# --- was ein vermutetes Urteil darf (Ticket 24) -----------------------------


def unsure(stars: int) -> Rating:
    return Rating(stars=stars, reason="Ruht auf Ableitung.", confidence="vermutet",
                  profile_version=1)


def test_a_merely_suspected_judgement_never_withholds_a_book(store: Store) -> None:
    """Ein zu Unrecht gezeigtes Buch kostet eine Zeile. Ein zu Unrecht
    verschwiegenes ist unsichtbar — die Leserin erfährt nie, dass es das Buch
    gab (bewertungsschema.md, 3)."""
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    kept, report = gate.apply(
        deltas, store=store, rater=StubRater(unsure(1)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    assert kept == deltas
    assert report.held_back == 0
    assert report.shown_unsure == 1


def test_a_well_founded_judgement_still_withholds(store: Store) -> None:
    """Die Regel weicht das Tor nicht auf — sie betrifft nur das Raten."""
    deltas = [first_seen(discovery(isbn="9783104911854"))]

    kept, report = gate.apply(
        deltas, store=store, rater=StubRater(rating(1)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    assert kept == []
    assert (report.held_back, report.shown_unsure) == (1, 0)


def test_a_suspected_judgement_does_not_withhold_on_a_price_drop_either(
    store: Store,
) -> None:
    """Sonst wäre die Regel an der Vordertür scharf und an der Hintertür nicht."""
    store.put_rating("isbn:9783104911854", stars=1, confidence="vermutet",
                     reason="Ableitung.", profile_version=1, now=NOW, origin=BY_MODEL)
    found = discovery(isbn="9783104911854", price_cents=399)

    kept, report = gate.apply(
        [Delta(DeltaKind.PRICE_DROP, discovery(isbn="9783104911854", price_cents=299), found)],
        store=store, rater=StubRater(rating(4)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    assert len(kept) == 1
    assert report.held_back == 0


def test_a_passing_judgement_is_never_counted_as_unsure(store: Store) -> None:
    kept, report = gate.apply(
        [first_seen(discovery(isbn="9783104911854"))],
        store=store, rater=StubRater(unsure(5)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    assert len(kept) == 1
    assert report.shown_unsure == 0


def test_the_scheme_is_not_versioned() -> None:
    """Eine Änderung am Verfahren entwertet keine Bewertung (ADR 21). Trüge es
    eine Version, läge die Versuchung nahe, sie an ein Urteil zu hängen."""
    from ebook_watchlist.rating import load_rating_scheme

    geladen = yaml.safe_load(load_rating_scheme().text)

    assert "version" not in geladen


def test_the_code_agrees_with_the_scheme_about_withholding() -> None:
    """Die Regel steht im Dokument und noch einmal in ``Rating.withholds``.
    Dieser Test ist das, was die beiden zusammenhält — sonst wäre es wieder
    eine Regel im Dokument, die im Code nicht gilt."""
    from ebook_watchlist.rating import load_rating_scheme

    scheme = load_rating_scheme()

    for confidence in scheme.confidences:
        urteil = Rating(stars=1, reason="x", confidence=confidence, profile_version=1)
        assert urteil.withholds(threshold=3) is (confidence in scheme.may_withhold)


def test_the_code_agrees_with_the_scheme_about_the_star_range() -> None:
    scheme = load_rating_scheme()
    zu_hoch = f'{{"stars": {scheme.max_stars + 1}, "confidence": "teils", "reason": "x"}}'

    with pytest.raises(RatingUnavailable):
        parse_answer(zu_hoch, 1, scheme)


def test_the_scheme_names_no_axis() -> None:
    """Das Verfahren muss für jedes Profil taugen. Nennt es eine inhaltliche
    Achse, ist es keins mehr."""
    from ebook_watchlist.rating import load_rating_scheme

    text = load_rating_scheme().text.lower()

    for verboten in ("achse a", "achse b", "achse c", "achse d", "achse e", "kernachse"):
        assert verboten not in text, f"{verboten!r} steht im Bewertungsschema"


# --- woran eine Bewertung hängt (Ticket 25) ---------------------------------


def test_a_changed_scheme_ages_no_judgement(store: Store, tmp_path) -> None:
    """Das Verfahren trägt keine Version. Es kann sich ändern, ohne dass ein
    einziges Urteil über ein Buch dadurch falsch würde (ADR 21)."""
    from ebook_watchlist.rating import load_rating_scheme

    vorlage = load_rating_scheme().text
    erst = tmp_path / "a.yaml"
    erst.write_text(vorlage, encoding="utf-8")
    dann = tmp_path / "b.yaml"
    dann.write_text(vorlage + "\nnachtrag: ganz anders\n", encoding="utf-8")

    rater = StubRater(rating(4))
    deltas = [first_seen(discovery(isbn="9783104911854"))]
    gate.apply(deltas, store=store, rater=rater, profile_version=1,
               threshold=3, budget=10, now=NOW)

    assert load_rating_scheme(erst).text != load_rating_scheme(dann).text

    _, second = gate.apply(deltas, store=store, rater=rater, profile_version=1,
                           threshold=3, budget=10, now=NOW)

    assert len(rater.calls) == 1
    assert second.reused == 1


def test_a_changed_profile_ages_the_machines_judgement_but_not_hers(
    store: Store,
) -> None:
    book = store.find_or_create_book(isbn=None, title="Ein Fund", now=NOW)
    store.put_rating(book_subject(book.id), stars=5, confidence="belegt", reason="",
                     profile_version=1, now=NOW, origin=BY_READER)
    store.put_rating("isbn:9783104911854", stars=4, confidence="teils", reason="",
                     profile_version=1, now=NOW, origin=BY_MODEL)

    assert store.rating("isbn:9783104911854", 2, origin=BY_MODEL) is None
    assert store.rating(book_subject(book.id), 2, origin=BY_READER).stars == 5


def test_without_a_scheme_there_is_no_gate_rather_than_a_crash(monkeypatch) -> None:
    """Ein fehlendes Verfahren ist derselbe Fall wie ein fehlender Schlüssel:
    kein Tor, alles wird gezeigt. Ein Lauf darf daran nicht sterben."""
    import ebook_watchlist.rating as rating_module

    monkeypatch.setattr(rating_module, "SCHEME_PATH", Path("gibt-es-nicht.md"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    assert build_rater() is None


def test_a_price_drop_of_an_unsure_low_rating_carries_its_reason(store: Store) -> None:
    """Erstsichtung und Preissturz entscheiden mit derselben Funktion. Vorher
    zählte nur der eine Weg mit und nur der eine trug die Begründung."""
    store.put_rating("isbn:9783104911854", stars=1, confidence="vermutet",
                     reason="Ruht auf Ableitung.", profile_version=1, now=NOW,
                     origin=BY_MODEL)
    teuer = discovery(isbn="9783104911854", price_cents=999)
    billig = discovery(isbn="9783104911854", price_cents=299)

    kept, report = gate.apply(
        [Delta(DeltaKind.PRICE_DROP, billig, teuer)],
        store=store, rater=StubRater(rating(4)), profile_version=1,
        threshold=3, budget=10, now=NOW,
    )

    assert len(kept) == 1
    assert report.shown_unsure == 1
    assert report.judgements[billig.key].reason == "Ruht auf Ableitung."


def test_the_prompt_carries_the_scheme_as_text_not_as_an_object() -> None:
    """Gemessen statt vermutet: der Prompt enthielt eine Weile
    ``Scheme(text='…', min_stars=0, …)`` — das Python-Repr des Datenobjekts."""
    text = prompt_for(discovery(), LESEPROFIL, SCHEMA)

    assert SCHEMA.text in text
    assert "Scheme(" not in text
    assert "min_stars" not in text


def test_the_prompt_asks_for_a_pitch() -> None:
    """Der Pitch nützt nichts, wenn das Modell nicht danach gefragt wird."""
    for text in (prompt_for(discovery(), LESEPROFIL, SCHEMA),
                 prompt_for_many([discovery()], LESEPROFIL, SCHEMA)):
        assert '"pitch"' in text


def test_the_answer_shape_comes_from_the_scheme() -> None:
    """Spanne und Werte standen ausgeschrieben im Prompt. Ein vierter
    confidence-Wert im Dokument hätte sie nicht erreicht."""
    eigen = Scheme(text="x", prompt_text="x", min_stars=1, max_stars=9,
                   confidences=("sicher", "unsicher"), withhold_from="sicher")

    text = prompt_for(discovery(), LESEPROFIL, eigen)

    assert "<1-9>" in text
    assert "sicher|unsicher" in text


def test_a_pitch_is_read_from_the_answer() -> None:
    answer = ('{"stars": 4, "confidence": "teils", "reason": "x", "trifft": ["Tempo"], '
              '"pitch": "Ein Profiler am Abgrund, und die Jagd beginnt auf Seite eins."}')

    result = parse_answer(answer, 1, SCHEMA)

    assert result.pitch.startswith("Ein Profiler")


def test_a_missing_pitch_does_not_cost_the_judgement() -> None:
    """Sterne und Begründung tragen für sich. Ein Buch deswegen unbewertet zu
    lassen wäre teurer als eine leere Zeile im Digest."""
    result = parse_answer(
        '{"stars": 4, "confidence": "teils", "reason": "x", "trifft": ["Tempo"]}', 1, SCHEMA
    )

    assert (result.stars, result.pitch) == (4, "")


# --- was der Bewerter zu sehen bekommt (Review) -----------------------------


def test_the_prompt_leaves_out_what_only_humans_need() -> None:
    """Die Gegenprobe betrifft die Pflege des Profils, nicht das Urteil über
    ein Buch. Sie mitzuschicken kostet Aufmerksamkeit für etwas, das der
    Bewerter gar nicht tun soll."""
    scheme = load_rating_scheme()

    assert "GEGENPROBE" not in scheme.prompt_text
    assert "gegenprobe" in scheme.text  # für Menschen steht sie weiterhin da
    assert len(scheme.prompt_text) < len(scheme.text)


def test_the_rendered_scheme_is_instructions_not_yaml() -> None:
    """Einrückungstiefe und Listenstriche kosten Aufmerksamkeit, die dem Buch
    fehlt."""
    text = load_rating_scheme().prompt_text

    assert "fuer_den_bewerter" not in text
    assert "was_bewertet_wird" not in text
    assert "WAS BEWERTET WIRD" in text
    assert "STERNE" in text


def test_the_scheme_shows_the_rater_what_a_good_pitch_looks_like() -> None:
    """Für die Begründung gab es ein Beispiel und für den Pitch nur Verbote —
    das war die Stelle mit dem klarsten Ertrag."""
    text = load_rating_scheme().prompt_text

    assert "GUT" in text
    assert "SCHLECHT" in text
    assert "Klappentext" in text


def test_the_answer_rule_is_not_repeated_beside_the_scheme() -> None:
    """Zwei Fassungen derselben Regel in einem Prompt sind schlechter als eine.
    Die frühere Kurzfassung wiederholte, was das Verfahren genauer sagt."""
    text = prompt_for(discovery(), LESEPROFIL, load_rating_scheme())

    assert text.count("confidence 'vermutet'") == 0


def test_an_error_envelope_is_not_mistaken_for_an_answer() -> None:
    """Gemessen an einer abgelaufenen Anmeldung: die Hülle trug exit 0, aber
    is_error true, und in ``result`` stand "Failed to authenticate: OAuth
    session expired". Ohne diese Prüfung wanderte das als Urteil weiter."""
    from ebook_watchlist.rating import _cli_text

    huelle = json.dumps({
        "is_error": True,
        "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
        "type": "result",
    })

    with pytest.raises(RatingUnavailable, match="OAuth session expired"):
        _cli_text(huelle)


def test_a_failing_call_names_what_the_envelope_says(monkeypatch) -> None:
    """Gemessen an einem Container ohne Anmeldung: Rueckgabewert 1, stderr
    leer, und der einzige Hinweis — "Not logged in · Please run /login" —
    stand in der Huelle auf stdout. Uebrig blieb "claude endete mit 1"."""
    monkeypatch.setattr(
        "ebook_watchlist.rating.subprocess.run",
        lambda *a, **k: _completed(
            stdout=json.dumps({"is_error": True, "result": "Not logged in · Please run /login"}),
            returncode=1,
        ),
    )

    with pytest.raises(RatingUnavailable, match="Not logged in"):
        ClaudeCodeRater(leseprofil=LESEPROFIL, version=1).rate(discovery())


def test_a_failure_without_an_envelope_still_names_the_return_code(monkeypatch) -> None:
    monkeypatch.setattr(
        "ebook_watchlist.rating.subprocess.run",
        lambda *a, **k: _completed(stdout="", stderr="Killed", returncode=137),
    )

    with pytest.raises(RatingUnavailable, match="endete mit 137: Killed"):
        ClaudeCodeRater(leseprofil=LESEPROFIL, version=1).rate(discovery())


def test_a_good_envelope_still_yields_its_result() -> None:
    from ebook_watchlist.rating import _cli_text

    huelle = json.dumps({"is_error": False, "result": '{"stars": 4}'})

    assert _cli_text(huelle) == '{"stars": 4}'


def test_foreign_voices_stand_beside_the_tool_not_instead_of_it(store: Store) -> None:
    """Keine eigene Tabelle: `rating` ist schon nach (subject, origin)
    geschlüsselt, und genau darauf kommt eine weitere Quelle dazu (ADR 19,
    Ticket 54)."""
    from datetime import datetime

    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.ratings import BY_MODEL, BY_ONLEIHE_READERS, subject_of
    from ebook_watchlist.run import _record_foreign_ratings

    fund = Observation(
        source="onleihe", source_item_id="1", title="Die sieben Schwestern",
        author="Riley, Lucinda", match_reason=MatchReason.WATCHLIST,
        isbn="9783641117009", rating=4, rating_votes=1641,
    )
    store.put_rating(subject_of(fund), stars=2, confidence="teils", reason="Modell",
                     profile_version=2, now=datetime(2026, 9, 6), origin=BY_MODEL)

    _record_foreign_ratings(store, [fund])

    # Ausdruecklich mit der *aktuellen* Profilversion: eine fremde Stimme
    # veraltet nicht mit einer neuen Fassung, und die Abfrage darf sie
    # deshalb nicht wegfiltern (Befund aus dem Review zu Ticket 54).
    fremd = store.rating(subject_of(fund), 2, origin=BY_ONLEIHE_READERS)
    assert fremd.stars == 4
    assert fremd.votes == 1641
    assert fremd.confidence == "belegt"
    # Das eigene Urteil bleibt unberührt daneben stehen.
    assert store.rating(subject_of(fund), 2, origin=BY_MODEL).stars == 2


def test_a_single_voice_is_not_evidence(store: Store) -> None:
    """Fünf von sieben Bewertungen unseres Korpus ruhen bei Google Books auf
    einer einzigen Stimme. Der Wert wird festgehalten, gilt aber nicht als
    belegt — und ohne Anzahl wird gar nichts geschrieben."""
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.ratings import BY_ONLEIHE_READERS, subject_of
    from ebook_watchlist.run import _record_foreign_ratings

    knapp = Observation(source="onleihe", source_item_id="2", title="Kaum Stimmen",
                        author="Wer", match_reason=MatchReason.WATCHLIST,
                        isbn="9780000000002", rating=5, rating_votes=3)
    ohne = Observation(source="onleihe", source_item_id="3", title="Gar keine",
                       author="Wer", match_reason=MatchReason.WATCHLIST,
                       isbn="9780000000003", rating=5, rating_votes=None)

    _record_foreign_ratings(store, [knapp, ohne])

    # "belegt" heisst "aus geprueter Quelle" — nicht "statistisch belastbar".
    # Wie duenn die Stimmenlage ist, sagt die Zahl daneben, keine erfundene
    # Grenze (Befund aus dem Review zu Ticket 54).
    knapp_row = store.rating(subject_of(knapp), 2, origin=BY_ONLEIHE_READERS)
    assert knapp_row.confidence == "belegt"
    assert knapp_row.votes == 3
    assert store.rating(subject_of(ohne), 2, origin=BY_ONLEIHE_READERS) is None


def test_a_foreign_voice_survives_a_new_profile_version(store: Store) -> None:
    """Der Befund aus dem Review: die Versionsprüfung im Store stand auf
    „nicht menschlich" und liess damit eine fremde Leserstimme durchfallen,
    die mit dem Leseprofil nie etwas zu tun hatte. Auf der Buchseite war es
    schon richtig — im Store nicht."""
    from datetime import datetime

    from ebook_watchlist.ratings import BY_MODEL, BY_ONLEIHE_READERS

    store.put_rating("isbn:9780000000009", stars=4, confidence="belegt",
                     reason="1641 Stimmen", profile_version=0,
                     now=datetime(2026, 9, 6), origin=BY_ONLEIHE_READERS, votes=1641)
    store.put_rating("isbn:9780000000009", stars=2, confidence="teils", reason="Modell",
                     profile_version=1, now=datetime(2026, 9, 6), origin=BY_MODEL)

    # Das Modellurteil gegen Profil 1 veraltet mit Profil 2 — die fremde nicht.
    assert store.rating("isbn:9780000000009", 2, origin=BY_MODEL) is None
    assert store.rating("isbn:9780000000009", 2, origin=BY_ONLEIHE_READERS).stars == 4


def test_an_apostrophe_escaped_the_wrong_way_does_not_cost_the_judgement() -> None:
    """Gemessen an einem echten Urteil ueber "Das Knochenband": das Modell
    schuetzte die Apostrophe um einen zitierten Achsennamen mit einem
    Backslash. In JSON ist das kein Escape — fuenf tadellose Felder fielen
    deshalb als "Antwort ist kein gueltiges JSON" aus."""
    antwort = (
        '{"stars": 2, "confidence": "vermutet", "reason": "ob die Figur die von '
        # Rohzeichenkette: ``"\'"`` ist in Python nur ein Apostroph, und der
        # Test pruefte dann gar nichts — genau so ist er beim ersten Versuch
        # durchgerutscht und ueberlebte die Mutation.
        + r"der Achse \'Die Figur traegt alles\' geforderte Bruchstelle traegt"
        + '"}'
    )
    assert r"\'" in antwort

    urteil = parse_answer(antwort, 1, load_rating_scheme())

    assert urteil.stars == 2
    assert "'Die Figur traegt alles'" in urteil.reason


def test_genuinely_broken_json_still_fails(monkeypatch) -> None:
    """Die Nachsicht gilt einer Lesart, nicht dem Raten: was auch danach kein
    JSON ist, bleibt unbewertet (ADR 7)."""
    with pytest.raises(RatingUnavailable, match="kein gültiges JSON"):
        parse_answer('{"stars": 2, "confidence" "vermutet"}', 1, load_rating_scheme())


# --- die Achsen als Daten (#12) ---------------------------------------------

ACHSEN = frozenset({"Die Figur trägt alles", "Tempo", "Katz und Maus"})


def antwort(stars: int, trifft: list[str], fehlt: list[str]) -> str:
    import json

    return json.dumps({"stars": stars, "confidence": "teils", "reason": "Beide Seiten handeln.",
                       "pitch": "Ein Duell.", "trifft": trifft, "fehlt": fehlt})


def test_text_after_the_answer_does_not_cost_the_judgement() -> None:
    """Gemessen am 2026-09-19 auf der Fundseite: das Modell schrieb nach dem
    Objekt noch etwas, und das ganze Urteil fiel mit "Extra data" aus. Das
    erste vollständige Objekt ist die Antwort; was danach kommt, ist keine
    zweite Lesart, sondern Beiwerk."""
    text = antwort(1, [], ["Tempo"]) + '\n\nHinweis: {"das hier" gehört nicht dazu}'

    assert parse_answer(text, 1, SCHEMA, axes=ACHSEN).stars == 1


def test_the_axes_come_as_data_beside_the_text() -> None:
    """Die Begruendung stand voller Achsennamen — "trifft Katz und Maus
    woertlich". Jetzt sagt der Text es in normalen Worten, und die Achsen
    kommen daneben als Daten: die Marke traegt den Namen, der Satz den Beleg."""
    gelesen = parse_answer(antwort(4, ["Katz und Maus", "tempo"], ["Die Figur trägt alles"]),
                           1, SCHEMA, axes=ACHSEN)

    # Gross- und Kleinschreibung zaehlt nicht, gespeichert wird die Schreibung
    # des Profils.
    assert gelesen.hits == ("Katz und Maus", "Tempo")
    assert gelesen.misses == ("Die Figur trägt alles",)


@pytest.mark.parametrize(
    ("stars", "trifft", "fehlt", "grund"),
    [
        (4, ["Erfundene Achse"], [], "unbekannt"),
        (5, ["Tempo"], ["Katz und Maus"], "fünf Sterne"),
        (3, [], ["Tempo"], "trifft"),
    ],
)
def test_a_judgement_that_contradicts_itself_is_refused(
    stars: int, trifft: list[str], fehlt: list[str], grund: str
) -> None:
    """Streng gelesen (#12): ein Achsenname, den es im Profil nicht gibt; fuenf
    Sterne und trotzdem etwas unter "fehlt"; drei oder mehr Sterne und nichts
    unter "trifft". Jede der drei verwirft das ganze Urteil — das Buch bleibt
    unbeurteilt und wird trotzdem gezeigt. Milde lesen hiesse, ein erfundener
    Bezug verschwaende still, und niemand pruefte mehr etwas."""
    with pytest.raises(RatingUnavailable, match=grund):
        parse_answer(antwort(stars, trifft, fehlt), 1, SCHEMA, axes=ACHSEN)


def test_belegt_needs_the_sample() -> None:
    """Auf Klappentext und Schlagwörtern allein ist "belegt" zu viel (#17): sie
    versprechen, was das Buch vielleicht nicht hält. Ohne Leseprobe wird
    herabgestuft, nicht verworfen — die Sterne tragen trotzdem."""
    import json

    belegt = json.dumps({"stars": 4, "confidence": "belegt", "reason": "Zieht.",
                         "pitch": "Ein Duell.", "trifft": ["Tempo"], "fehlt": []})

    assert parse_answer(belegt, 1, SCHEMA, had_sample=False).confidence == "teils"
    assert parse_answer(belegt, 1, SCHEMA, had_sample=True).confidence == "belegt"


@pytest.mark.parametrize(
    "verlag",
    ["neobooks", "epubli", "tredition GmbH", "via tolino media", "Independently published",
     "BoD – Books on Demand"],
)
def test_self_publishing_costs_a_star(verlag: str) -> None:
    """Ein Buch ohne Verlag im Rücken muss aus eigener Kraft vier Sterne holen,
    um über die Schwelle von drei zu kommen (#28). Abgezogen wird im Code und
    nach dem Urteil — das Modell soll das Buch beurteilen, nicht den Verlag."""
    gelesen = parse_answer(antwort(4, ["Tempo"], []), 1, SCHEMA, axes=ACHSEN, publisher=verlag)

    assert gelesen.stars == 3
    assert gelesen.model_stars == 4
    assert gelesen.deductions == ("Selbstverlag",)


@pytest.mark.parametrize("verlag", ["Luzifer-Verlag", "Goldmann Verlag", "PerryPayneBooks", None])
def test_a_real_publisher_or_none_costs_nothing(verlag: str | None) -> None:
    """Kleinverlage haben ein Lektorat; ein Autorenlabel ist nicht zu erkennen,
    und eine fehlende Angabe ist kein Beleg."""
    gelesen = parse_answer(antwort(4, ["Tempo"], []), 1, SCHEMA, axes=ACHSEN, publisher=verlag)

    assert gelesen.stars == 4
    assert gelesen.model_stars is None
    assert gelesen.deductions == ()


def test_no_star_goes_below_zero() -> None:
    gelesen = parse_answer(antwort(0, [], ["Tempo"]), 1, SCHEMA, axes=ACHSEN,
                           publisher="neobooks")

    # Wo nichts mehr abgeht, wird auch kein Abzug verbucht — "0 vom Modell,
    # −1 Selbstverlag" hiesse, es sei etwas abgezogen worden.
    assert gelesen.stars == 0
    assert gelesen.deductions == ()
    assert gelesen.model_stars is None


def test_the_deduction_is_stored_beside_the_judgement(store: Store) -> None:
    store.put_rating("isbn:9783754123456", stars=3, confidence="teils", reason="Zieht.",
                     profile_version=1, now=NOW, origin=BY_MODEL,
                     model_stars=4, deductions=("Selbstverlag",))

    zeile = store.ratings_for(["isbn:9783754123456"])[("isbn:9783754123456", BY_MODEL)]

    assert (zeile.stars, zeile.model_stars, zeile.deductions) == (3, 4, ("Selbstverlag",))


def test_a_low_judgement_may_hit_nothing() -> None:
    """Unter drei Sternen darf "trifft" leer sein — das ist die Aussage."""
    gelesen = parse_answer(antwort(1, [], ["Die Figur trägt alles"]), 1, SCHEMA, axes=ACHSEN)

    assert gelesen.hits == ()


def test_the_axes_are_read_from_the_reading_profile() -> None:
    from ebook_watchlist.rating import leseprofil_axes

    achsen = leseprofil_axes()

    assert "Die Figur trägt alles" in achsen
    assert "Katz und Maus" in achsen


def test_the_axes_are_stored_with_the_judgement(store: Store) -> None:
    store.put_rating("isbn:9783104911854", stars=4, confidence="teils", reason="Passt.",
                     profile_version=1, now=NOW, origin=BY_MODEL,
                     hits=("Katz und Maus",), misses=("Tempo",))

    zeile = store.ratings_for(["isbn:9783104911854"])[("isbn:9783104911854", BY_MODEL)]

    assert (zeile.hits, zeile.misses) == (("Katz und Maus",), ("Tempo",))


# --- Der Pitch und seine eine Nachfrage (#29) -------------------------------


def test_a_pitch_that_talks_about_the_profile_is_trouble() -> None:
    """Die Schablone, die achtzehn von 132 Pitches woertlich benutzten."""
    trouble = pitch_trouble(
        "Melancholischer Horror an einer Bruecke — atmosphaerisch, wo das Profil "
        "eine beschaedigte Stimme verlangt.",
        SCHEMA,
    )

    assert trouble is not None
    assert "Profil" in trouble


def test_an_axis_name_is_not_trouble() -> None:
    """"Enge" und "Tempo" sind Achsennamen *und* gewoehnliche Woerter.

    Der beste Pitch im Bestand enthaelt beide. Eine Probe, die gute Saetze
    verwirft, waere schlechter als keine — deshalb prueft sie das nicht.
    """
    gut = (
        "Ein Trupp Soldaten steigt in die Tunnel unter einem Geisterdorf — "
        "Enge, Dreck und ein Gegner, der zurueckschlaegt."
    )

    assert pitch_trouble(gut, SCHEMA) is None


def test_a_pitch_naming_its_own_stars_is_trouble() -> None:
    assert pitch_trouble("Trifft das Genre — drei von fuenf Sternen.", SCHEMA)


def test_a_pitch_over_the_limit_is_trouble() -> None:
    assert pitch_trouble("x" * (SCHEMA.pitch_max + 1), SCHEMA)


def test_an_empty_pitch_is_not_trouble() -> None:
    """Ein fehlender Pitch kostet nichts — daran aendert die Probe nichts."""
    assert pitch_trouble("", SCHEMA) is None


def test_a_bad_pitch_is_asked_once_and_replaced() -> None:
    gefragt = []

    def ask(prompt: str, max_tokens: int = 300) -> str:
        gefragt.append(prompt)
        return '"Eine Glocke laeutet von selbst — bis dahin: Tuchmacher."'

    schlecht = Rating(
        stars=1, reason="…", confidence="teils", profile_version=1,
        pitch="Dark Fantasy — freundlich, wo das Profil Haerte verlangt.",
    )

    besser = with_better_pitch(schlecht, discovery(), ask, SCHEMA)

    assert len(gefragt) == 1
    assert besser.pitch == "Eine Glocke laeutet von selbst — bis dahin: Tuchmacher."
    # Das Urteil bleibt unberuehrt: geprueft wurde ein Satz, nicht die Sterne.
    assert (besser.stars, besser.reason, besser.confidence) == (1, "…", "teils")


def test_a_good_pitch_costs_no_second_call() -> None:
    def ask(prompt: str, max_tokens: int = 300) -> str:
        raise AssertionError("haette nicht fragen duerfen")

    gut = Rating(
        stars=4, reason="…", confidence="belegt", profile_version=1,
        pitch="Ein Anruf zwingt ihn dorthin zurueck, wo es passierte.",
    )

    assert with_better_pitch(gut, discovery(), ask, SCHEMA) is gut


def test_the_second_pitch_stands_even_if_it_still_breaks_the_rule() -> None:
    """Lieber ein schwacher Satz als eine leere Zeile.

    Das Verfahren sagt selbst "es gibt immer einen Pitch", und in der Liste
    steht sonst gar nichts ueber das Buch.
    """
    def ask(prompt: str, max_tokens: int = 300) -> str:
        return "Wieder etwas, wo das Profil etwas anderes verlangt."

    schlecht = Rating(
        stars=1, reason="…", confidence="teils", profile_version=1,
        pitch="Erster Versuch, wo das Profil Haerte verlangt.",
    )

    assert "Profil" in with_better_pitch(schlecht, discovery(), ask, SCHEMA).pitch


def test_a_failed_second_call_leaves_the_first_pitch_standing() -> None:
    """Nie zumachen (ADR 7): eine misslungene Nachfrage kostet nichts."""
    def ask(prompt: str, max_tokens: int = 300) -> str:
        raise RatingUnavailable("Modell nicht erreichbar")

    schlecht = Rating(
        stars=1, reason="…", confidence="teils", profile_version=1,
        pitch="Erster Versuch, wo das Profil Haerte verlangt.",
    )

    assert with_better_pitch(schlecht, discovery(), ask, SCHEMA).pitch.startswith(
        "Erster Versuch"
    )


def test_the_retry_carries_neither_profile_nor_star_table() -> None:
    """Der teure Teil eines Prompts ist der, den man weglaesst."""
    prompt = pitch_prompt(discovery(), SCHEMA, "Alter Satz", "er redet vom Profil")

    assert "LESEPROFIL" not in prompt
    assert SCHEMA.text not in prompt
    assert "Ein Fund" in prompt
    assert "Alter Satz" in prompt


def test_the_rater_only_sees_the_sections_meant_for_it() -> None:
    """`prompt_text` gab es samt Funktion und Tests — benutzt wurde es nicht.

    Beide Prompts schickten die ganze Datei, also auch die Gegenprobe, die von
    der Pflege des Profils handelt und nicht vom Urteil ueber ein Buch. 22 %
    des Verfahrens im Prompt waren Anweisungen fuer etwas anderes (#29).
    """
    schema = load_rating_scheme()

    prompt = prompt_for(discovery(), LESEPROFIL, schema)

    assert schema.prompt_text in prompt
    assert "GEGENPROBE" not in prompt


def test_profiler_is_not_the_profile() -> None:
    """"Profiler-Jagd" ist kein Verstoß — das Leseprofil sagt selbst
    "Profiler gegen Täter". Zwei der 31 gemessenen Treffer waren genau das,
    und eine Probe, die gute Sätze verwirft, wäre schlechter als keine."""
    assert pitch_trouble("Profiler-Jagd an der Ostsee — aber Band vier.", SCHEMA) is None


def test_a_scheme_without_the_pitch_length_still_loads(tmp_path) -> None:
    """Das Tor scheitert nie zu (ADR 7).

    Der Lader verlangte die Zahl kurzzeitig, und damit war ein älteres Schema
    nicht mehr zu laden — aufgefallen beim Gegenversuch zu #29, der genau das
    tun wollte.
    """
    ohne = tmp_path / "schema.yaml"
    ohne.write_text(
        load_rating_scheme().text.replace("  hoechstens_zeichen: 200\n", ""),
        encoding="utf-8",
    )

    assert load_rating_scheme(ohne).pitch_max == 200
