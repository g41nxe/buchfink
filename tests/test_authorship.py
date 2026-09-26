"""KI-erzeugte Bücher sind keine Kandidaten (#31).

Gemessen am Bestand vom 23.09.2026: ein einziger Autor, 32 Titel, 5 % aller
Titel mit Autorenangabe — und 26 davon hatten je einen Modellaufruf gekostet,
im Schnitt für 1,8 Sterne.
"""

from __future__ import annotations

from datetime import datetime

from ebook_watchlist.authorship import ai_authors, declares_ai, is_ai_authored
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.store import Store

NOW = datetime(2026, 9, 23, 12, 0)

#: Der Wortlaut aus dem Bestand, gekürzt.
SELF_DISCLOSURE = (
    "Achtung: Der Autor verwendet zum Erstellen seiner Texte meistens "
    "künstliche Intelligenz (und muss das angeben, was er hiermit macht)! "
    "Matze K. ist ein phantasiereicher deutscher KI-Autor."
)
#: Ebenfalls aus dem Bestand: ein Roman *über* eine künstliche Intelligenz.
#: Ein gröberes Muster traf zwei Bände des Pandora-Zyklus.
ABOUT_AN_AI = (
    "Sechs geklonten Wissenschaftlern ist es gelungen, an Bord eines "
    "Raumschiffs eine künstliche Intelligenz zu erschaffen."
)


def discovery(**overrides) -> Observation:
    defaults = dict(
        source="beam",
        source_item_id="1",
        title="Ein Fund",
        author="Matze K",
        match_reason=MatchReason.GENRE_CATEGORY,
        price_cents=199,
    )
    return Observation(**{**defaults, **overrides})


# --- das Muster -------------------------------------------------------------


def test_a_self_declaration_is_recognised() -> None:
    assert declares_ai(SELF_DISCLOSURE)


def test_a_novel_about_an_ai_is_not_a_novel_by_one() -> None:
    """Der teuerste denkbare Fehlgriff: Frank Herbert fällt aus dem Stapel,
    weil sein Raumschiff eine künstliche Intelligenz an Bord hat."""
    assert not declares_ai(ABOUT_AN_AI)


def test_nothing_said_is_not_a_declaration() -> None:
    assert not declares_ai(None)
    assert not declares_ai("Ein Krimi in Aberdeen.")


# --- die Ableitung ----------------------------------------------------------


def _sight(store: Store, **overrides) -> None:
    run_id = store.start_run("test", "cli", NOW)
    store.append(run_id, "test", [discovery(**overrides)], NOW)


def test_one_detail_page_teaches_about_the_whole_work(store: Store) -> None:
    """Die Angabe steht nur auf der Detailseite, und die wird allein für
    Bücher geholt, die gleich beurteilt werden.

    Von 232 Kacheltexten trug keiner sie, von 25 Detailseiten alle. Ohne den
    Schluss auf die Autorenschaft spart der Filter genau dort nichts, wo er
    greifen soll — zehn der zweiunddreißig Titel haben bis heute nur den
    kurzen Text.
    """
    _sight(store, source_item_id="1", title="Mit Detailseite", blurb=SELF_DISCLOSURE)

    authors = ai_authors(store)

    assert authors == frozenset({"Matze K"})
    # Der Titel, dessen Detailseite nie geholt wurde, faellt trotzdem weg.
    assert is_ai_authored(discovery(source_item_id="2", blurb="Ein kurzer Teaser."), authors)


def test_an_author_who_says_nothing_stays(store: Store) -> None:
    _sight(store, author="Jo Nesbø", blurb="Harry Hole ermittelt in Oslo.")

    assert ai_authors(store) == frozenset()


# --- wer trotzdem bleibt ----------------------------------------------------


def test_a_watchlist_title_is_never_filtered() -> None:
    """Was die Leserin selbst auf die Liste setzt, bleibt dort — dieselbe
    Ausnahme wie bei der Sprache (#10)."""
    own = discovery(match_reason=MatchReason.WATCHLIST, blurb=SELF_DISCLOSURE)

    assert not is_ai_authored(own, frozenset({"Matze K"}))


def test_without_an_author_nothing_is_assumed() -> None:
    """Zu raten, wo niemand etwas gesagt hat, wäre hier der teure Fehler: ein
    zu Unrecht gefiltertes Buch erscheint nie, und niemand erfährt davon."""
    assert not is_ai_authored(discovery(author=None), frozenset({"Matze K"}))


def test_a_declaration_on_the_find_itself_is_enough() -> None:
    """Auch ohne dass die Autorenschaft schon bekannt wäre."""
    assert is_ai_authored(discovery(author="Wer Neues", blurb=SELF_DISCLOSURE), frozenset())
