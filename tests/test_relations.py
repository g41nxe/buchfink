"""Ein Name je Beziehung, überall derselbe.

Vier Module hatten sich je eine eigene Liste geschrieben, und die waren
auseinandergelaufen: `owned` hieß "besitze ich" auf der Buchseite, "besessen"
im Profil, "Habe ich" im Stapel und "im Besitz" im Watchlist-Menü. Vier Namen
für dieselbe Sache entstehen nicht aus Absicht, sondern daraus, dass es vier
Stellen gab.
"""

from __future__ import annotations


def test_every_button_reads_the_same_word() -> None:
    """Vier Module hatten sich je eine eigene Liste geschrieben, und die waren
    auseinandergelaufen — `owned` hiess an vier Stellen vier verschiedene
    Dinge. Jetzt lesen alle aus derselben.

    Zwei Listen mit klarer Zustaendigkeit (ADR 29 mit Nachtrag): auf jedem
    Knopf steht das Handlungswort — Stapel, Startseite, Watchlist-Menue, Fund-
    und Buchseite —, der Zustandsname beschreibt ein Buch in Prosa, im Profil
    und im Tagesbericht. Keine Ansicht mischt."""
    from ebook_watchlist.relations import ACTION_LABELS, RELATION_LABELS, RelationKind
    from ebook_watchlist.web import book, profile_page, triage, watchlist

    for schluessel, wort in (*book.KINDS, *triage.ACTIONS, *watchlist.CLOSINGS):
        assert wort == ACTION_LABELS[RelationKind(schluessel)]
    for schluessel, name in profile_page._RELATION_LABELS:
        assert name == RELATION_LABELS[RelationKind(schluessel)]


def test_every_kind_has_a_name() -> None:
    from ebook_watchlist.relations import RELATION_LABELS, RelationKind

    assert set(RELATION_LABELS) == set(RelationKind)


def test_every_kind_has_a_word_for_the_button() -> None:
    """Die Buchseite bietet alle fuenf an — ohne Wort bliebe ein Knopf leer."""
    from ebook_watchlist.relations import ACTION_LABELS, RelationKind

    assert set(ACTION_LABELS) == set(RelationKind)


def test_a_state_name_that_is_no_action_word_never_reaches_a_button() -> None:
    """Sonst rutscht "im Besitz" irgendwann wieder auf einen Knopf — an einer
    Stelle, und die Drift beginnt von vorn.

    Zwei Woerter duerfen sich treffen: "Mag ich" ist Regalschild und Antwort
    zugleich. Verboten ist nicht die Gleichheit, sondern der Rollentausch."""
    from ebook_watchlist.relations import ACTION_LABELS, RELATION_LABELS
    from ebook_watchlist.web import book, triage, watchlist

    nur_zustand = set(RELATION_LABELS.values()) - set(ACTION_LABELS.values())
    auf_knoepfen = {wort for _, wort in (*book.KINDS, *triage.ACTIONS, *watchlist.CLOSINGS)}
    assert not nur_zustand & auf_knoepfen


def test_no_two_names_differ_only_by_a_negation() -> None:
    """„Mag ich" und „Mag ich nicht" sahen beim Ueberfliegen gleich aus."""
    from ebook_watchlist.relations import ACTION_LABELS, RELATION_LABELS

    for liste in (RELATION_LABELS, ACTION_LABELS):
        namen = list(liste.values())
        for name in namen:
            assert f"{name} nicht" not in namen
