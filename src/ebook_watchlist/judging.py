"""Das Urteil über einen Fund, gerechnet statt gespeichert (ADR 33, #48, #79).

Eine Stelle für Tor, Stapel, Tagesbericht und Buchseite: aus dem Steckbrief
eines Buchs und der Geschmacksform der Leserin werden Prozent, Sterne und
Begründung. Die Form wird aus dem Leseprofil und ihren bewerteten Büchern
gelernt (``taste_form``). Nichts davon wird gespeichert — eine neue
Profilfassung oder ein neu bewertetes Buch wirkt damit sofort und ohne
Modellaufruf auf alles.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import yaml

from . import reader_reasons
from .facets import ReadingProfile, Reason, Weights, load_weights
from .portrait import Portrait, Vocabulary, VocabularyError, fingerprint, load_vocabulary
from .ratings import book_subject
from .relations import RelationKind
from .store import Store
from .taste_form import RatedBook, TasteForm, book_terms, learn, overlap


@dataclass(frozen=True, slots=True)
class Verdict:
    """Was das Tor über einen Fund weiß."""

    stars: int
    #: ``None``, wenn die Leserin die Sterne selbst gegeben hat.
    percent: int | None = None
    reasons: tuple[Reason, ...] = ()
    pitch: str | None = None
    #: Die Sterne stammen von der Leserin, nicht aus der Rechnung.
    by_reader: bool = False
    #: So nah an der Schwelle, dass ein anderer Steckbrief das Buch auf die
    #: andere Seite legen könnte (#81).
    borderline: bool = False

    def withholds(self, threshold: int) -> bool:
        return self.stars < threshold

    @property
    def marks(self) -> tuple[str, ...]:
        """Die Begründung in Marken: die getroffene Facette, das Gemochte, was dagegen spricht."""
        return tuple(
            f"dagegen: {r.text}" if r.kind == "dagegen" else r.text
            for r in self.reasons
            if r.kind in ("ganz", "merkmal", "muster", "dagegen")
        )

    @property
    def why(self) -> str:
        """Prozent und Marken in einer Zeile, wo eine Begründung in ein Feld passen muss."""
        if self.by_reader:
            return "deine Sterne"
        head = f"{self.percent} %"
        return f"{head} — {', '.join(self.marks)}" if self.marks else head

    @property
    def text(self) -> str:
        """Gerechnete Sterne bleiben als solche erkennbar (ADR 17): eine 4 aus der
        Rechnung ist ein Vorschlag, eine 4 der Leserin eine Tatsache."""
        stars = "★" * self.stars + "☆" * (5 - self.stars)
        if self.by_reader:
            return f"Deine Sterne {stars}"
        return f"Übereinstimmung {stars} {self.why}"


def judge(
    portrait: Portrait | None,
    profile: ReadingProfile | None,
    vocabulary: Vocabulary,
    weights: Weights,
    form: TasteForm | None = None,
) -> Verdict | None:
    """Das gerechnete Urteil — oder ``None``, wenn nicht geurteilt wird.

    Nicht geurteilt wird ohne Steckbrief, über ein Buch, das das Modell nicht
    kennt, und ohne Profil (ADR 33, Punkt 8). Ein Fund ohne Urteil wird nie
    zurückgehalten (ADR 7). Ohne ``form`` wird sie aus dem Profil allein
    gelernt, ohne Bücher.
    """
    if portrait is None or profile is None:
        return None
    if form is None:
        form = learn(profile, (), vocabulary, weights)
    result = overlap(portrait, profile, form, vocabulary, weights)
    if result is None:
        return None
    return Verdict(
        stars=result.stars,
        percent=round(result.share * 100),
        reasons=result.reasons,
        pitch=portrait.pitch,
        borderline=weights.is_borderline(result.share),
    )


def readers_verdict(stars: int) -> Verdict:
    """Die eigenen Sterne der Leserin: eine Tatsache, sie gehen der Rechnung vor."""
    return Verdict(stars=stars, by_reader=True)


@dataclass(frozen=True, slots=True)
class Judge:
    """Profil, Vokabular und Gewichte, einmal geladen — für eine ganze Liste.

    Der Stapel, die Watchlist und die Startseite urteilen über Dutzende Funde
    auf einmal; das Profil und das Vokabular je Zeile neu zu laden wäre
    Verschwendung.
    """

    profile: ReadingProfile
    vocabulary: Vocabulary
    weights: Weights
    #: Der Fingerabdruck des Vokabulars: nur Steckbriefe mit diesem gelten.
    stamp: str
    #: Wessen Profil das ist.
    slug: str = ""
    #: Die Geschmacksform, aus Profil und bewerteten Büchern gelernt.
    form: TasteForm | None = None

    @property
    def threshold(self) -> int:
        """Ab wie vielen Sternen das Tor durchlässt."""
        return self.weights.gate_stars

    def verdict(self, portrait: Portrait | None) -> Verdict | None:
        return judge(portrait, self.profile, self.vocabulary, self.weights, self.form)

    def verdict_among(
        self, portraits: Mapping[str, Portrait], subjects: Sequence[str]
    ) -> Verdict | None:
        """Das Urteil nach dem ersten Schlüssel, zu dem es einen Steckbrief gibt.

        Ein Buch kann unter der ISBN, unter einer Produktnummer oder unter seiner
        Buchnummer beschrieben sein; welcher gilt, sagt die Reihenfolge.
        """
        for subject in subjects:
            if subject in portraits:
                return self.verdict(portraits[subject])
        return None

    def portraits(self, store: Store, subjects) -> dict[str, Portrait]:
        return store.portraits_for(subjects, self.stamp)


def load_judge(store: Store, slug: str) -> Judge | None:
    """Der Urteilende dieser Leserin — oder ``None``, wenn nicht geurteilt wird.

    Nicht geurteilt wird ohne Profil in der Datenbank (ADR 33, Punkt 8) und
    ohne lesbares Vokabular oder Schema: die Seiten zeigen dann, was sie ohne
    Urteil zeigen, statt zu scheitern.
    """
    profile = store.reading_profile(slug)
    if profile is None:
        return None
    try:
        vocabulary = load_vocabulary()
        weights = load_weights()
    except (VocabularyError, OSError, KeyError, ValueError, yaml.YAMLError):
        return None
    stamp = fingerprint(vocabulary)
    rated = rated_books(store, slug, vocabulary, weights, stamp)
    form = learn(profile, rated, vocabulary, weights)
    return Judge(profile, vocabulary, weights, stamp, slug, form)


def rated_books(
    store: Store, slug: str, vocabulary: Vocabulary, weights: Weights, stamp: str
) -> tuple[RatedBook, ...]:
    """Die Bücher, die die Leserin gelesen und bewertet hat, mit ihren Merkmalen.

    Ein Buch ohne Steckbrief zum geltenden Vokabular oder eines, das das Modell
    nicht kennt, lehrt die Form nichts und fehlt. Der Steckbrief hängt an der
    ISBN, wo es eine gibt, sonst an der Buchnummer — in derselben Reihenfolge,
    in der die Buchseite ihn anlegt (``web.book.portrait_subject``).
    """
    marked = [
        (sign, relation.book_id, reader_reasons.parse(relation.details)[1])
        for sign, kind in ((1, RelationKind.LIKED), (-1, RelationKind.DISLIKED))
        for relation in store.relations(slug, kind=str(kind))
    ]
    books = store.books_by_id([book_id for _, book_id, _ in marked])
    subjects = {
        book_id: ([f"isbn:{b.isbn}"] if b.isbn else []) + [book_subject(book_id)]
        for book_id, b in books.items()
    }
    portraits = store.portraits_for([s for ss in subjects.values() for s in ss], stamp)
    rated = []
    for sign, book_id, reasons in marked:
        book = books.get(book_id)
        if book is None:
            continue
        portrait = next(
            (portraits[s] for s in subjects[book_id] if s in portraits and portraits[s].known),
            None,
        )
        if portrait is None:
            continue
        rated.append(
            RatedBook(
                book.title,
                sign,
                book_terms(portrait, vocabulary, weights),
                portrait.genre,
                added=tuple(reasons.get("add", ())),
                dropped=reader_reasons.not_counted(reasons),
            )
        )
    return tuple(rated)
