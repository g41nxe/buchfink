"""Picking the right book out of a list of search hits.

Two decisions live here, and they are separate on purpose:

*Ranking* orders candidates by a lexicographic key — deterministic, no
weightings to tune, ties broken in a documented order (research doc §3).

*Confidence* then decides whether the winner may be used without a human ever
looking at it. v1 resolves entries automatically, so this gate is the only thing
standing between a loose search hit and a wrong title being watched for months
(ADR 9). It answers with three states, never a bare boolean.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from rapidfuzz import fuzz

from .bundles import looks_like_bundle
from .normalize import (
    NormalizedAuthor,
    normalize_authors,
    normalize_title,
    title_tokens,
    volumes_conflict,
)

#: Below this, nothing is a match.
NO_MATCH_BELOW = 85
#: At or above this, a fuzzy title is as good as an exact one.
STRONG_TITLE = 95
#: An author this close counts as the same person.
STRONG_AUTHOR = 90
#: Two candidates within this many points are effectively tied.
TIE_MARGIN = 3
#: Hoechstens so viele Kandidaten kommen der Leserin zur Auswahl. Eine
#: Sicherung, keine Auswahlregel — welche gezeigt werden, entscheidet
#: :attr:`Resolution.indistinguishable` (Ticket 41).
MAX_CANDIDATES = 5
#: Stands in for "no year on either side" so the tie-break stays sortable.
UNKNOWN_YEAR_DELTA = 9999


class Confidence(StrEnum):
    AUTO_ACCEPT = "auto_accept"
    PROVISIONAL = "provisional"
    NO_MATCH = "no_match"


@dataclass(frozen=True, slots=True)
class Query:
    """What we are looking for — normally a Watchlist Entry."""

    title: str
    author: str | None = None
    year: int | None = None
    identifier: str | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One search hit. ``payload`` carries whatever the Source needs back."""

    title: str
    author: str | None = None
    year: int | None = None
    identifier: str | None = None
    #: Adresse des Titelbilds, wie die Kachel sie nennt. Kostet nichts: sie
    #: steht in jedem Suchtreffer, wurde bisher nur weggeworfen. Zwei Ausgaben
    #: nebeneinander zu vergleichen ist eine Frage ans Auge (Ticket 41).
    cover_url: str | None = None
    #: Die Sprache der Ausgabe, als Code der DNB (``ger``, ``eng``), wo die
    #: Quelle sie nennt. Der Matcher liest sie nicht — sie reist mit, damit
    #: eine angenommene fremdsprachige Ausgabe auf der Kachel als solche
    #: erkennbar bleibt (#77).
    language: str | None = None
    payload: Any = None


@dataclass(frozen=True, slots=True)
class Scored:
    candidate: Candidate
    id_match: bool
    title_exact: bool
    title_fuzzy: int
    author_exact: bool
    author_fuzzy: int
    year_delta: int
    source_rank: int
    #: Der gesuchte Titel steckt vollstaendig im Kandidaten — "Dark Matter" in
    #: "Dark Matter. Der Zeitenlaeufer". Ein eigenes Signal und nicht Teil von
    #: ``title_fuzzy``: es darf einen Kandidaten aus dem Nichts holen, aber nie
    #: allein eine Annahme tragen (Ticket 36).
    title_contained: bool = False
    #: Beide Seiten nennen einen Band, und einen verschiedenen — oder der
    #: Kandidat nennt einen spaeteren, wo die Anfrage keinen nennt.
    volume_conflict: bool = False
    #: Beide Seiten tragen eine Kennung, und eine verschiedene. Kein fehlendes
    #: Indiz, sondern ein **Widerspruch** — das Gegenstueck zu Primos negativem
    #: Gewicht (docs/research/title-matching-practices.md).
    id_conflict: bool = False
    #: Beide Seiten nennen eine Autor:in, und eine verschiedene. Von derselben
    #: Art wie ``id_conflict``: "Kim Mannix" statt "Blake Crouch" ist kein
    #: schwaches Indiz, sondern eine andere Person (ADR 23, Nachtrag).
    author_conflict: bool = False
    #: Gefragt wurde nach einer Autor:in, der Kandidat nennt **keine**. Kein
    #: Widerspruch — aber auch nichts, was sich bestaetigen liesse (Ticket 53).
    author_missing: bool = False
    #: Der Kandidat ist eine Sammelausgabe, die Anfrage nicht. Bisher waren
    #: "Der Kruzifix-Killer" und "Der Kruzifix-Killer / Der Vollstrecker"
    #: ununterscheidbar — beide exakter Titel, beide exakter Autor —, und wer
    #: gewann, entschied die Reihenfolge der Shop-Treffer (ADR 24).
    is_bundle: bool = False

    @property
    def sort_key(self) -> tuple[int, ...]:
        """Ascending = better. Fuzzy scores go in five-point buckets so that
        near-ties fall through to the next criterion instead of being decided by
        a point of noise."""
        return (
            0 if self.id_match else 1,
            # Eine widersprechende Kennung ist der staerkste Gegenbeleg, den
            # es gibt — staerker als ein abweichender Name, denn eine ISBN
            # meint genau eine Ausgabe. Sie hob bisher nur die
            # Sicherheitsstufe: bei zwei sonst gleichen Kandidaten gewann
            # deshalb der mit der *falschen* Kennung, wenn er zufaellig
            # zuerst kam (ADR 23, gefunden beim Review zu Ticket 54).
            1 if self.id_conflict else 0,
            # Vor dem Titel, und das ist der Kern von Ticket 45: "Dark Matter"
            # von Kim Mannix trifft den Titel exakt, "Dark Matter. Der
            # Zeitenlaeufer" von Crouch nur enthalten — gesucht war aber
            # Crouch. Stuende der Widerspruch hinter ``title_exact``, aenderte
            # sich fuer diesen Fall gar nichts.
            1 if self.author_conflict else 0,
            0 if self.title_exact else 1,
            # Ein nachweislich anderer Band steht hinten. Der Widerspruch hob
            # bisher nur die Sicherheitsstufe: bei 'Red Rising' kamen deshalb
            # 'Teil 1' und 'Teil 2' als gleichwertige Kandidaten mit vor,
            # obwohl wir *wissen*, dass sie es nicht sind (ADR 23).
            1 if self.volume_conflict else 0,
            # Der gesuchte Einzelband schlaegt die Sammelausgabe: sie steht
            # nicht auf der Watchlist, und sie ist ein eigenes Buch (ADR 24).
            1 if self.is_bundle else 0,
            0 if self.title_contained else 1,
            # **Nach** ``title_contained`` und vor der Aehnlichkeit: unter
            # sonst gleichwertigen Kandidaten steht der hinten, zu dem sich
            # nichts bestaetigen laesst. Weiter vorne haette es einen exakten
            # Titel ohne Autorfeld hinter einen bloss enthaltenen sortiert.
            1 if self.author_missing else 0,
            -(self.title_fuzzy // 5),
            0 if self.author_exact else 1,
            -(self.author_fuzzy // 5),
            self.year_delta,
            self.source_rank,
        )


@dataclass(frozen=True, slots=True)
class Resolution:
    confidence: Confidence
    best: Scored | None = None
    ranked: tuple[Scored, ...] = field(default_factory=tuple)
    reason: str = ""
    #: Wer ausser dem Sieger gleich gut war, wo das nicht die Titelwerte
    #: sagen: bei einer Zuordnung ueber den Originaltitel (#77) liegen die
    #: Kandidaten beim Titelvergleich weit auseinander — gleich sind sie erst
    #: in dem, was die DNB ueber sie weiss.
    alternatives: tuple[Scored, ...] = ()

    @property
    def accepted(self) -> Candidate | None:
        if self.best is None or self.confidence is not Confidence.AUTO_ACCEPT:
            return None
        return self.best.candidate

    @property
    def indistinguishable(self) -> tuple[Candidate, ...]:
        """Die Kandidaten, die der Matcher **nicht auseinanderhalten** konnte.

        Das ist die Antwort auf „warum fragst du mich?" — gezeigt wird genau
        das, was gleich gut aussah, nicht die ersten drei und nicht alles ueber
        einer erfundenen Punktzahl (Ticket 41).

        Der Deckel von fuenf ist eine Sicherung, keine Auswahlregel: sollte ein
        Matcher zwanzig Titel gleich bewerten, waere eine Liste von zwanzig
        keine Hilfe mehr. Gemessen an den vier offenen Bestaetigungen wird die
        Gruppe nicht groesser als zwei.
        """
        if self.best is None:
            return ()
        if self.alternatives:
            tied = [self.best, *(s for s in self.alternatives if s is not self.best)]
            return tuple(scored.candidate for scored in tied[:MAX_CANDIDATES])
        tied = [self.best] + [
            candidate for candidate in self.ranked[1:] if _is_tied(self.best, candidate)
        ]
        return tuple(scored.candidate for scored in tied[:MAX_CANDIDATES])


def _author_scores(
    query_authors: Sequence[NormalizedAuthor], candidate_authors: Sequence[NormalizedAuthor]
) -> tuple[bool, int]:
    if not query_authors or not candidate_authors:
        return False, 0

    exact = any(q.full == c.full for q in query_authors for c in candidate_authors)
    best = max(
        max(
            fuzz.token_set_ratio(q.full, c.full),
            fuzz.token_set_ratio(q.substantial, c.substantial),
        )
        for q in query_authors
        for c in candidate_authors
    )
    return exact, int(round(best))


def title_similarity(left: str, right: str) -> int:
    """How alike two normalized titles are, 0–100.

    ``token_set_ratio`` alone is not enough: it scores a perfect 100 whenever one
    token set is a subset of the other, so "Der Schwarm" would happily accept
    "Der Schwarm 2 - Die Rückkehr". Taking the lower of it and
    ``token_sort_ratio`` keeps its tolerance for reordering and leftover subtitle
    words while still making extra tokens cost something.
    """
    return int(
        round(min(fuzz.token_set_ratio(left, right), fuzz.token_sort_ratio(left, right)))
    )


def title_is_contained(query: str, candidate: str) -> bool:
    """Steckt der gesuchte Titel vollstaendig im Titel des Kandidaten?

    Der Fall, den ``title_similarity`` nicht sehen kann: der Shop haengt einen
    Untertitel an den Titel, statt ihn in ein eigenes Feld zu schreiben —
    "Dark Matter. Der Zeitenlaeufer". Das Minimum aus Mengen- und Sortiermass
    bestraft jedes zusaetzliche Wort gleich hart, und der Titel faellt mit 56
    von noetigen 85 durch.

    Deshalb ein **eigenes Signal** statt einer gesenkten Schwelle. Es sagt nur,
    dass es sich lohnt hinzusehen; entschieden wird an anderer Stelle. Genau
    diese Trennung — billiger Kandidatenschluessel, teure Entscheidung — ist,
    was Primo und die Record-Linkage-Literatur empfehlen
    (docs/research/title-matching-practices.md).

    Ein Wort allein reicht nicht: von fuenfzehn Watchlist-Titeln haben
    dreizehn hoechstens zwei Token, und "Morgen" steckt in sehr vielen Titeln.
    """
    wanted = title_tokens(query)
    if not wanted:
        return False
    found = title_tokens(candidate)
    if len(found) <= len(wanted):
        return False
    return set(wanted).issubset(found)


def score(query: Query, candidate: Candidate, source_rank: int = 0) -> Scored:
    query_title = normalize_title(query.title)
    candidate_title = normalize_title(candidate.title)

    query_authors = normalize_authors(query.author)
    candidate_authors = normalize_authors(candidate.author)
    author_exact, author_fuzzy = _author_scores(query_authors, candidate_authors)

    if query.year is not None and candidate.year is not None:
        year_delta = abs(query.year - candidate.year)
    else:
        year_delta = UNKNOWN_YEAR_DELTA

    return Scored(
        candidate=candidate,
        id_match=bool(query.identifier) and query.identifier == candidate.identifier,
        title_exact=bool(query_title) and query_title == candidate_title,
        title_fuzzy=title_similarity(query_title, candidate_title),
        author_exact=author_exact,
        author_fuzzy=author_fuzzy,
        year_delta=year_delta,
        source_rank=source_rank,
        title_contained=title_is_contained(query.title, candidate.title),
        volume_conflict=volumes_conflict(query.title, candidate.title),
        is_bundle=looks_like_bundle(candidate.title) and not looks_like_bundle(query.title),
        id_conflict=bool(query.identifier)
        and bool(candidate.identifier)
        and query.identifier != candidate.identifier,
        # Dieselbe strenge Regel, die schon entscheidet, ob ein Autorentreffer
        # einer ist — keine zweite Zahl daneben. Ein fehlendes Autorfeld auf
        # einer der beiden Seiten ist Nichtwissen und kein Widerspruch.
        author_conflict=authors_contradict(query.author, candidate.author),
        author_missing=bool(query.author) and not candidate.author,
    )


def author_matches(target: str, credited: str | None, threshold: int = STRONG_AUTHOR) -> bool:
    """Is ``target`` one of the people credited on this item?

    Deliberately stricter than the author score used while ranking a title
    (:func:`_author_scores`). There the author only corroborates a title that
    already matched, so being generous costs little; here the author *is* the
    entire decision, and every false positive becomes a book recommendation for
    a stranger.

    Two traps, both found against real shop data:

    ``token_set_ratio`` alone scores a perfect 100 whenever one name's tokens
    are a subset of the other's, which makes "Chris Carter" match "Chris James
    Carter" and plain "Max" match "Max Barry". Taking the lower of it and
    ``token_sort_ratio`` makes the extra given name count against the match.

    And the initials-stripped variant is not consulted at all: it reduces
    "S.A. Barnes" and "J.S. Barnes" to the same bare "barnes", which would make
    every author sharing a surname the same person.
    """
    if not credited:
        return False
    targets = normalize_authors(target)
    credits = normalize_authors(credited)
    if not targets or not credits:
        return False

    for wanted in targets:
        for person in credits:
            if wanted.full == person.full:
                return True
            score = min(
                fuzz.token_set_ratio(wanted.full, person.full),
                fuzz.token_sort_ratio(wanted.full, person.full),
            )
            if score >= threshold:
                return True
    return False


def authors_contradict(target: str | None, credited: str | None) -> bool:
    """Nennen beide Seiten eine Person — und **verschiedene**?

    Die Gegenrichtung zu :func:`author_matches`, und deshalb nicht einfach
    dessen Verneinung. Bestaetigen darf nur, wer sicher ist; **widersprechen**
    auch. Zwischen beidem liegt ein breites Feld: "F. Schätzing" ist Frank
    Schätzing, nur mit weniger Information — `author_matches` sagt dazu Nein,
    aber das ist kein Widerspruch, sondern Unwissen. Genau das hat der
    bestehende Test ``prefers_exact_title_over_a_better_author_score``
    aufgedeckt: mit der blossen Verneinung waere der exakte Titel hinter einen
    anderen Band gerutscht.

    Widersprochen wird deshalb erst, wenn die **tragenden** Namensteile
    disjunkt sind — die laenger als zwei Zeichen, also im Wesentlichen ohne
    Initialen. "Blake Crouch" gegen "Kim Mannix" hat nichts gemeinsam; "S.A.
    Barnes" gegen "J.S. Barnes" teilt den Nachnamen und bleibt damit
    unentschieden. Das ist bewusst vorsichtig: ein negatives Signal, das zu
    oft ausschlaegt, waere schlimmer als eines, das manchmal schweigt.
    """
    if not target or not credited:
        return False
    if author_matches(target, credited):
        return False
    def load_bearing(raw: str) -> set[str]:
        return {token for person in normalize_authors(raw) for token in person.substantial.split()}

    wanted, found = load_bearing(target), load_bearing(credited)
    if not wanted or not found:
        return False
    return wanted.isdisjoint(found)


def worth_confirming(scored: Scored, query: Query) -> bool:
    """Ob ein *enthaltener* Titel eine Frage an die Leserin wert ist (Ticket 53).

    `title_is_contained` holt einen Kandidaten aus dem Nichts, wo die
    Titelaehnlichkeit nicht reicht — "Dark Matter" in "Dark Matter. Der
    Zeitenlaeufer". Gebaut wurde die Regel fuer einen Fall, in dem die
    Autor:in **exakt** stimmte; geprueft hat sie das nie. Bei "Autoritaet" und
    "Akzeptanz" von VanderMeer legte sie deshalb je ein Sachbuch vor, das der
    Shop ohne jeden Verfasser fuehrt.

    Zwei Bedingungen, beide aus vorhandenen Bausteinen:

    * Die Personen duerfen sich nicht **widersprechen** (ADR 23, Nachtrag).
    * Wer nach einer Autor:in fragt, bekommt keine Frage zu einem Kandidaten,
      der **niemanden** nennt — dort ist nichts zu entscheiden.

    Ausdruecklich **nicht** verlangt wird eine Bestaetigung. `author_matches`
    ist fuers Bestaetigen bewusst streng, und zwischen "bestaetigt" und
    "widerspricht" liegt ein breites Feld: "Chris Carter" gegen "Chris James
    Carter" erreicht 80, "F. Schaetzing" gegen "Frank Schaetzing" 75 — alles
    dieselben Menschen. Gemessen an den gespeicherten Zuordnungen faellt
    ausserdem jede Eingabe, die nur einen Nachnamen traegt, in dieses Feld:
    "VanderMeer" gegen "VanderMeer, Jeff" ist weder das eine noch das andere.
    Eine Bestaetigung zu verlangen haette solche Eintraege dauerhaft von jeder
    Rueckfrage ausgeschlossen.

    Gemessen an fuenf Live-Suchen: 24 von 240 Kacheln tragen kein Autorfeld
    (10 %) — aber **null** in der Anfrage, fuer die die Regel gebaut wurde,
    und 21 von 96 in den beiden, die den Fehler ausgeloest haben.
    """
    return not (scored.author_conflict or scored.author_missing)


def _distinct(title: str) -> bool:
    """Ob ein Titel genug traegt, um ohne Autor:in angenommen zu werden (#20).

    Mindestens zwei Woerter, gezaehlt **nach** der Normalisierung: die wirft
    Artikel ab, und "Der Morgen" ist ein Wort — "Der" macht nichts
    unverwechselbar. Einwortige Titel wie *Profit* sind genau die, bei denen
    eine zufaellige Namensgleichheit plausibel ist; dort wird gefragt.
    """
    return len(normalize_title(title).split()) >= 2


def _is_tied(best: Scored, runner_up: Scored) -> bool:
    """Two hits we cannot honestly tell apart — the case Calibre punts to its GUI."""
    return (
        abs(best.title_fuzzy - runner_up.title_fuzzy) <= TIE_MARGIN
        and best.author_fuzzy // 5 == runner_up.author_fuzzy // 5
        and best.title_exact == runner_up.title_exact
        # Einzelband und Sammelausgabe sind nicht "gleich gut", sobald wir sie
        # auseinanderhalten koennen — genau das war vorher der Muenzwurf
        # (ADR 24).
        and best.is_bundle == runner_up.is_bundle
        # Dasselbe fuer die Bandnummer: was einen anderen Band nennt, ist
        # nicht 'gleich gut' wie etwas, das keinen nennt.
        and best.volume_conflict == runner_up.volume_conflict
        # Und fuer die Person: wer der falschen zugeschrieben ist, ist nicht
        # "gleich gut" wie jemand mit der richtigen. Ohne das bekam die
        # Leserin fuer 'Dark Matter' genau eine Karte vorgelegt — die falsche.
        and best.author_conflict == runner_up.author_conflict
    )


def _confidence(query: Query, ranked: Sequence[Scored]) -> tuple[Confidence, str]:
    best = ranked[0]

    if best.id_match:
        return Confidence.AUTO_ACCEPT, "Kennung stimmt überein"

    if best.title_fuzzy < NO_MATCH_BELOW:
        # Der gesuchte Titel steckt ganz im gefundenen: das ist zu wenig fuer
        # eine Annahme und zu viel zum Wegwerfen. Es kommt der Leserin zur
        # Bestaetigung vor — ein Klick, und die Zuordnung heisst danach
        # "von Hand bestaetigt" (Ticket 36, ADR 9).
        if best.title_contained and worth_confirming(best, query):
            return (
                Confidence.PROVISIONAL,
                "der gesuchte Titel steckt im gefundenen — bitte bestätigen",
            )
        if best.title_contained:
            # Enthalten schon, aber niemand kann die Frage beantworten
            # (Ticket 53). Welcher der beiden Gruende es ist, gehoert in die
            # Begruendung: "nennt niemanden" und "nennt jemand anderen" sind
            # fuer die Leserin zwei verschiedene Auskuenfte.
            return (
                Confidence.NO_MATCH,
                "der Titel steckt im gefundenen, aber dort steht eine andere Autor:in"
                if best.author_conflict
                else "der Titel steckt im gefundenen, aber dort steht keine Autor:in",
            )
        return (
            Confidence.NO_MATCH,
            f"bester Titelwert {best.title_fuzzy} liegt unter {NO_MATCH_BELOW}",
        )

    # Ein anderer Band ist ein anderes Buch — aber nicht *kein* Buch. Bisher
    # wurde "Der Schwarm - Band 2" als "Der Schwarm" automatisch angenommen,
    # weil der Untertitel-Schnitt die Bandangabe entfernte, bevor sie jemand
    # sah. Jetzt kommt der Fall zur Bestaetigung statt durchzurutschen — und
    # nicht in den Papierkorb: wegwerfen hiesse, der Leserin einen Kandidaten
    # zu verschweigen, den nur sie beurteilen kann (ADR 9).
    #
    # Steht **nach** der Titelschwelle: sonst wuerde ein voellig fremdes Buch
    # mit einer 2 im Titel zum Kandidaten.
    if best.volume_conflict:
        return Confidence.PROVISIONAL, "der Treffer nennt einen anderen Band der Reihe"

    # Dieselbe Überlegung eine Stufe härter: eine abweichende ISBN ist kein
    # fehlendes Indiz, sondern ein Widerspruch. Bisher wog sie gar nichts — nur
    # eine *übereinstimmende* Kennung zählte, eine widersprechende nicht.
    if best.id_conflict:
        return Confidence.PROVISIONAL, "die Kennungen widersprechen sich"

    runner_up = ranked[1] if len(ranked) > 1 else None
    tied = runner_up is not None and _is_tied(best, runner_up)

    if query.author:
        confident = (best.title_exact and best.author_fuzzy >= STRONG_AUTHOR) or (
            best.title_fuzzy >= STRONG_TITLE and best.author_exact
        )
        if confident and tied:
            return Confidence.PROVISIONAL, "zwei Kandidaten sind gleich gut"
        if confident:
            return Confidence.AUTO_ACCEPT, "Titel und Autor stimmen beide"
        # Nennt der Treffer *niemanden*, ist das kein Widerspruch, sondern
        # eine Luecke (ADR 23). Bis #20 zaehlte sie wie eine andere Person: die
        # *Wayward Pines-Trilogie* musste bestaetigt werden, weil das Paket im
        # Shop keine Autorin traegt — und waere ohne Autorin am Eintrag
        # angenommen worden. Jetzt gilt dieselbe Regel wie dort.
        if best.author_missing and best.title_exact and not tied and _distinct(query.title):
            return (
                Confidence.AUTO_ACCEPT,
                "exakter Titel, dort ohne Autor:in, kein konkurrierender Treffer",
            )
        return (
            Confidence.PROVISIONAL,
            f"Titel {best.title_fuzzy}, Autor {best.author_fuzzy} — nicht eindeutig",
        )

    # No author to corroborate with: an exact, unrivalled title is the only
    # thing we will accept unattended — and only one of at least two words
    # (#20). A one-word title is where a stranger of the same name is
    # plausible.
    if best.title_exact and not tied and _distinct(query.title):
        return (
            Confidence.AUTO_ACCEPT,
            "exakter Titel, kein konkurrierender Treffer, kein Autor angegeben",
        )
    return Confidence.PROVISIONAL, "kein Autor am Eintrag, mit dem sich der Titel bestätigen ließe"


def match(query: Query, candidates: Sequence[Candidate]) -> Resolution:
    """Rank ``candidates`` against ``query`` and say how much to trust the winner."""
    if not candidates:
        return Resolution(confidence=Confidence.NO_MATCH, reason="keine Kandidaten")

    ranked = tuple(
        sorted(
            (score(query, candidate, rank) for rank, candidate in enumerate(candidates)),
            key=lambda scored: scored.sort_key,
        )
    )
    confidence, reason = _confidence(query, ranked)
    return Resolution(
        confidence=confidence,
        best=ranked[0] if confidence is not Confidence.NO_MATCH else None,
        ranked=ranked,
        reason=reason,
    )


#: ISBN rein, die Namen der DNB raus: Originaltitel und Titel (ein einzelner
#: Name oder ``None`` geht auch). Was nicht im Ergebnis steht, ist unbekannt
#: geblieben (etwa ueber dem Budget).
OriginalTitleLookup = Callable[[Sequence[str]], Mapping[str, Any]]

#: Wo ein Titel der DNB in Teile zerfaellt: „Scythe – Die Hueter des Todes".
_TITLE_PARTS = re.compile(r"\s+[–—-]\s+|:\s+")


def _names(value: Any) -> tuple[str, ...]:
    """Die Namen eines Buchs laut DNB, und jeder Teil eines zusammengesetzten
    Titels für sich: die Übersetzung stellt den Originaltitel oft voran."""
    if not value:
        return ()
    names = (value,) if isinstance(value, str) else tuple(value)
    parts = [part for name in names for part in (name, *_TITLE_PARTS.split(name))]
    return tuple(dict.fromkeys(p.strip() for p in parts if p and p.strip()))


def needs_original_title(resolution: Resolution) -> bool:
    """Ob der Titelvergleich so wenig gefunden hat, dass der Originaltitel
    gefragt werden darf (#77).

    Nur, was sonst **unaufgeloest** bliebe: kein Treffer, oder einer, dessen
    Titelwert unter der Schwelle liegt. Ein Titel ueber der Schwelle ist schon
    eine Antwort oder eine Frage an die Leserin — ihn der DNB vorzulegen hiesse,
    fuer jeden gewoehnlichen Fund eine Anfrage zu stellen.
    """
    if resolution.accepted is not None:
        return False
    best = resolution.best
    return best is None or best.title_fuzzy < NO_MATCH_BELOW


def by_original_title(
    query: Query, resolution: Resolution, original_titles: OriginalTitleLookup
) -> Resolution:
    """Eine uebersetzte Ausgabe ueber den Originaltitel finden (#77).

    *Scythe* von Neal Shusterman steht bei OverDrive und im Shop als *Die
    Hueter des Todes*. Der Titelvergleich sieht darin nichts (Wert 29), und
    die Autor:in allein darf nichts entscheiden — sie bestaetigt nur einen
    Titel, der schon passt (ADR 8). Die DNB aber kennt zur ISBN der deutschen
    Ausgabe den Titel des Originals, und **der** wird gegen den eingegebenen
    gehalten, mit denselben Schwellen wie jeder Titel.

    Gefragt wird sparsam, weil jede Frage eine Anfrage an die DNB sein kann:

    * nur fuer eine Zuordnung, die sonst offen bliebe (:func:`needs_original_title`),
    * nur fuer Kandidaten, deren Autor:in **bestaetigt** stimmt
      (:func:`author_matches`, die strenge Regel) und die eine ISBN tragen,
    * und nie ohne Autor:in am Eintrag — dann trueg der Originaltitel die
      Zuordnung allein, und "Dark Matter" ist der Originaltitel zweier Buecher.

    Angenommen wird nur **ein** Buch. Treffen zwei verschiedene ISBNs, kommt
    die Frage zur Leserin; dieselbe ISBN auf zwei Karten ist ein Buch.

    Reihen: der Originaltitel muss den eingegebenen Titel treffen, nicht bloss
    die Reihe. "Arc of a Scythe" gegen "Scythe" ergibt 57 und faellt durch;
    eine Karte, die einen spaeteren Band nennt, wird gar nicht erst gefragt —
    ein Treffer auf Band 2 darf Band 1 nicht ersetzen.
    """
    if not query.author or not needs_original_title(resolution):
        return resolution
    wanted_title = normalize_title(query.title)
    if not wanted_title:
        return resolution

    worth_asking = [
        scored
        for scored in resolution.ranked
        if scored.candidate.identifier
        and not scored.volume_conflict
        and author_matches(query.author, scored.candidate.author)
    ]
    if not worth_asking:
        return resolution

    known = original_titles(list(dict.fromkeys(s.candidate.identifier for s in worth_asking)))

    hits: list[tuple[Scored, str, int]] = []
    for scored in worth_asking:
        best_name, best_similarity = None, 0
        for name in _names(known.get(scored.candidate.identifier or "")):
            if volumes_conflict(query.title, name):
                continue
            found_title = normalize_title(name)
            similarity = 100 if found_title == wanted_title else title_similarity(
                wanted_title, found_title
            )
            if similarity > best_similarity:
                best_name, best_similarity = name, similarity
        if best_name is not None and best_similarity >= NO_MATCH_BELOW:
            hits.append((scored, best_name, best_similarity))
    if not hits:
        return resolution

    # Eine Karte je Buch: dieselbe ISBN in zwei Formaten ist kein Zweifel.
    books: dict[str, tuple[Scored, str, int]] = {}
    for hit in hits:
        books.setdefault(hit[0].candidate.identifier or "", hit)
    best, original, similarity = next(iter(books.values()))
    others = tuple(scored for scored, _, _ in books.values())

    if len(books) > 1:
        return replace(
            resolution,
            confidence=Confidence.PROVISIONAL,
            best=best,
            alternatives=others,
            reason=f"der Originaltitel „{original}“ trifft {len(books)} Bücher — bitte bestätigen",
        )
    if similarity < STRONG_TITLE or best.id_conflict:
        return replace(
            resolution,
            confidence=Confidence.PROVISIONAL,
            best=best,
            alternatives=others,
            reason=f"Originaltitel „{original}“ laut DNB, nicht eindeutig — bitte bestätigen",
        )
    return replace(
        resolution,
        confidence=Confidence.AUTO_ACCEPT,
        best=best,
        alternatives=others,
        reason=f"über den Originaltitel „{original}“ zugeordnet (DNB)",
    )
