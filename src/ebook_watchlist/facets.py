"""Das Urteil kommt aus dem Code (#46, ADR 33).

Ein Leseprofil besteht aus **gemochten Merkmalen** (bis zu drei davon
verstärkt), **gemochten Erzählmustern**, **Facetten** und **Gegengewichten**.
Wie gut ein Buch dazu passt, rechnet dieser Code aus dem Steckbrief des Buchs;
kein Modell wird gefragt.

Das Leseprofil ist das, was die Leserin angetippt hat. Geurteilt wird mit der
Geschmacksform (``taste_form``), die aus ihren bewerteten Büchern gelernt wird
und das Profil als Startwert nimmt (#79). Eine Facette ist eine Kombination
gemochter Merkmale, die mehrere geliebte Bücher gemeinsam tragen; das Werkzeug
bildet sie selbst (``derive_facets``), und ein Buch, das sie ganz trägt, bekommt
einen Aufschlag. Erzählmuster stecken nie in einer Facette (#63).

Ein Gegengewicht darf ein Genre enthalten, eine Facette nicht: im Gegengewicht
grenzt es nur ein, was bestraft wird, in einer Facette grenzte es ein, was
gefunden wird (Nachtrag zu ADR 33).

    uv run python -m ebook_watchlist.facets profil.yaml

liest ein Profil aus einer Datei ein. Der gewöhnliche Weg ist die
Erstaufnahme (#50).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from .portrait import Portrait, Vocabulary, load_vocabulary

#: Wie viele Familien eine Facette mindestens braucht. Eine einzelne ist zu
#: breit: im Versuch ließ "große Ideen" allein einen enttäuschenden
#: Wissenschaftsthriller herein (#44). Einzelne Merkmale zählen stattdessen
#: schwach für sich (#64).
MIN_FAMILIES = 2
#: Wie viele Merkmale und Erzählmuster die Leserin höchstens verstärkt.
MOST_BOOSTED = 3


class ProfileError(Exception):
    """Ein Profil widerspricht dem Vokabular oder den Regeln."""


#: Die Gewichte, mit denen der Code urteilt — und nichts sonst (ADR 33). Sie
#: nennen keinen Geschmack und gelten für jede Leserin gleich.
SCHEME_PATH = Path(__file__).resolve().parents[2] / "docs" / "bewertungsschema.yaml"


@dataclass(frozen=True, slots=True)
class Facet:
    """Eine Kombination gemochter Merkmale, die mehrere geliebte Bücher tragen."""

    #: Die ids der Merkmalsfamilien.
    families: tuple[str, ...]
    #: Aus welchen geliebten Büchern sie stammt — für die Stärke.
    books: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Counterweight:
    """Was ein Buch die Leserin gekostet hat. Zählt nur, wenn alles zutrifft."""

    families: tuple[str, ...]
    #: Nur bei Büchern dieses Genres, etwa "High Fantasy".
    genre: str | None = None
    books: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Liked:
    """Ein gemochtes Merkmal oder Erzählmuster — eine Familie, angetippt."""

    family: str
    #: Von der Leserin verstärkt (höchstens ``MOST_BOOSTED``).
    boosted: bool = False


@dataclass(frozen=True, slots=True)
class ReadingProfile:
    facets: tuple[Facet, ...]
    counterweights: tuple[Counterweight, ...]
    #: Die gemochten Merkmale und Erzählmuster, jedes für sich.
    liked: tuple[Liked, ...] = ()
    #: Die Fassung, wie sie der Speicher vergeben hat; 0 für eines, das nicht
    #: aus dem Speicher kommt.
    version: int = 0


@dataclass(frozen=True, slots=True)
class Weights:
    """Die Werte der Formüberdeckung (``taste_form``), aus dem Bewertungsschema."""

    #: Wie stark ein Merkmal im Buch wiegt: prägend, deutlich, am Rand, und
    #: ohne Angabe (ein Steckbrief aus der Zeit davor).
    defining: float
    clear: float
    marginal: float
    unweighted: float
    #: Wie stark ein enttäuschendes Buch gegenüber einem durchschnittlichen
    #: gemochten wiegt (Rocchio, γ/β).
    rejection_ratio: float
    #: Ablehnung über die enttäuschenden Bücher gemittelt (Rocchio) statt je
    #: Merkmal das stärkste Buch (MultiNeg).
    rejection_mean: bool
    #: Wie stark eine Familie wiegt, die die Leserin selbst zu einem Buch nennt.
    reader_reason: float
    #: Wie viele Bücher das Getippte als Startwert wiegt.
    prior_books: float
    prior_liked: float
    prior_boosted: float
    prior_against: float
    #: Wie stark ein einzelnes Merkmal zu seiner Familie hin geglättet wird.
    term_to_family: float
    #: Welches Quantil der Vorlieben als voll gemocht gilt.
    full_quantile: float
    #: Glättung des Anteils und der Wert, zu dem ein dünner Steckbrief strebt.
    smoothing: float
    baseline: float
    pattern_smoothing: float
    pattern_for: float
    pattern_against: float
    facet_bonus: float
    genre_counterweight: float
    #: (Sterne, ab welcher Übereinstimmung), absteigend.
    stars_from: tuple[tuple[int, float], ...]
    #: Ab wie vielen Sternen das Bewertungstor einen Fund durchlässt (ADR 19).
    gate_stars: int

    def trait_weight(self, weight: str | None) -> float:
        return {"defining": self.defining, "clear": self.clear,
                "marginal": self.marginal}.get(weight or "", self.unweighted)

    def stars(self, share: float) -> int:
        return next((s for s, threshold in self.stars_from if share >= threshold - 1e-9), 1)


@dataclass(frozen=True, slots=True)
class Reason:
    """Eine Zeile der Begründung.

    Knapp wie eine Marke, kein Satz: die Facette oder das Merkmal steht mit
    seinem Namen da, und was es ist, sagt die Art der Zeile — das Bild macht
    daraus ein Zeichen. Woher etwas stammt, steht nicht hier: "wie
    Leichenblässe" unter einem Buch von Nesbø las sich wie ein Vergleich der
    beiden Bücher, und den zieht niemand.
    """

    #: ``ganz`` (eine Facette), ``merkmal``, ``muster`` (ein Erzählmuster),
    #: ``dagegen``, ``keine`` oder ``beleg``.
    kind: str
    text: str
    #: Bei ``merkmal`` und ``muster``: von der Leserin verstärkt.
    boosted: bool = False

    @property
    def detail(self) -> bool:
        """Ein Beleg zur Zeile davor — der Satz aus dem Steckbrief."""
        return self.kind == "beleg"

    @property
    def line(self) -> str:
        """Die Zeile als Text, ohne Bild."""
        prefix = {"muster": "Erzählmuster: ", "dagegen": "dagegen: "}.get(self.kind, "")
        return prefix + self.text + (" (verstärkt)" if self.boosted else "")


def load_weights(path: Path | None = None) -> Weights:
    """Die Werte aus dem Bewertungsschema."""
    data = yaml.safe_load((path or SCHEME_PATH).read_text(encoding="utf-8"))
    section = data["urteil_formueberdeckung"]
    in_book = section["gewicht_im_buch"]
    tiers = sorted(
        ((int(s), float(threshold)) for s, threshold in section["sterne_ab"].items()),
        reverse=True,
    )
    return Weights(
        defining=float(in_book["praegend"]),
        clear=float(in_book["deutlich"]),
        marginal=float(in_book["rand"]),
        unweighted=float(in_book["ohne_angabe"]),
        rejection_ratio=float(section["ablehnung_verhaeltnis"]),
        rejection_mean=bool(section["ablehnung_gemittelt"]),
        reader_reason=float(section["grund_der_leserin"]),
        prior_books=float(section["getipptes_wiegt_buecher"]),
        prior_liked=float(section["getippt"]),
        prior_boosted=float(section["verstaerkt"]),
        prior_against=float(section["gegengewicht"]),
        term_to_family=float(section["merkmal_zur_familie"]),
        full_quantile=float(section["voll_ab_quantil"]),
        smoothing=float(section["glaettung"]),
        baseline=float(section["grundwert"]),
        pattern_smoothing=float(section["glaettung_muster"]),
        pattern_for=float(section["muster_dafuer"]),
        pattern_against=float(section["muster_dagegen"]),
        facet_bonus=float(section["facette_ganz"]),
        genre_counterweight=float(section["gegengewicht_mit_genre"]),
        stars_from=tuple(tiers),
        gate_stars=int(section["tor_ab_sternen"]),
    )


def families_of(portrait: Portrait, vocabulary: Vocabulary) -> set[str]:
    """Die Familien, die ein Buch trägt."""
    return {
        vocabulary.family_of(trait.term).id
        for trait in portrait.traits
        if trait.term in vocabulary.terms
    }


def genre_matches(counterweight: Counterweight, portrait: Portrait) -> bool:
    """Ob das Buch zum Genre des Gegengewichts gehört — als ganzes Wort.

    "High Fantasy" steckt in "High Fantasy / Heroische Fantasy"; "Roman"
    steckt nicht in "Kriminalroman", sonst träfe ein Gegengewicht "nur bei
    Roman" jeden Krimi.
    """
    if counterweight.genre is None:
        return True
    pattern = re.compile(rf"(?<!\w){re.escape(counterweight.genre.casefold())}(?!\w)")
    parts = (portrait.genre, portrait.subgenre)
    return any(pattern.search((part or "").casefold()) for part in parts)


#: Der Umfang eines Gegengewichts: überall, nur bei diesem einen Buch (zählt
#: gegen nichts), oder nur zusammen mit seinem Genre (Nachtrag zu ADR 33).
GENERAL, HERE, WITH_GENRE = "general", "here", "genre"
SCOPES = (GENERAL, HERE, WITH_GENRE)


class ScopeError(ValueError):
    """Ein Umfang, der sich für dieses Buch nicht einlösen lässt."""


def scoped_counterweight(
    family: str, scope: str, genre: str | None, book: str
) -> Counterweight | None:
    """Das Gegengewicht, das eine Antwort meint — oder keines bei *nur hier*.

    Eine Stelle für Erstaufnahme und Nachschärfen. „Nur bei diesem Genre"
    ohne Genre ist ein Fehler und wird kein Gegengewicht, das überall gilt.
    """
    if scope not in SCOPES:
        raise ScopeError(f"unbekannter Umfang {scope!r}")
    if scope == HERE:
        return None
    if scope == WITH_GENRE:
        if not genre:
            raise ScopeError("Dieses Buch hat kein Genre, auf das sich das beschränken ließe.")
        return Counterweight((family,), genre, (book,))
    return Counterweight((family,), None, (book,))


def merge_counterweights(
    old: Sequence[Counterweight], new: Sequence[Counterweight]
) -> tuple[tuple[Counterweight, ...], bool]:
    """Neue Gegengewichte dazu; ein gleiches (Familien und Genre) nimmt nur
    das Buch auf. Zurück kommt, ob sich etwas geändert hat."""
    merged = list(old)
    changed = False
    for c in new:
        for i, existing in enumerate(merged):
            if (existing.families, existing.genre) == (c.families, c.genre):
                missing = tuple(b for b in c.books if b not in existing.books)
                if missing:
                    merged[i] = Counterweight(existing.families, existing.genre,
                                               (*existing.books, *missing))
                    changed = True
                break
        else:
            merged.append(c)
            changed = True
    return tuple(merged), changed


def family_name(family_id: str, vocabulary: Vocabulary) -> str:
    """Der Name einer Familie — oder ihre id, wenn das Vokabular sie nicht mehr
    kennt. Die Familien sind ein Arbeitsstand; ein gespeichertes Profil darf
    die Buchseite nicht umwerfen, nur weil eine umbenannt wurde."""
    try:
        return vocabulary.family(family_id).name
    except KeyError:
        return family_id


def family_names(families: Sequence[str], vocabulary: Vocabulary) -> str:
    return " · ".join(family_name(f, vocabulary) for f in families)


def family_description(family_id: str, vocabulary: Vocabulary) -> str:
    """Was die Familie als Ganzes heißt — nicht die Beschreibung eines
    einzelnen Merkmals, das zufällig zu ihr gehört. Leer, wenn das Vokabular
    die Familie nicht mehr kennt."""
    try:
        return vocabulary.family(family_id).description
    except KeyError:
        return ""


def is_pattern(family_id: str, vocabulary: Vocabulary) -> bool:
    """Ob eine Familie ein Erzählmuster ist — und nein, wenn es sie nicht mehr gibt."""
    try:
        return vocabulary.is_pattern(family_id)
    except KeyError:
        return False


#: Wie stark etwas belegt ist, als Skala statt als Zahl (#44): ein Buch ist
#: schwach, ab vier sehr stark. Die Anzahl wird gemerkt, gezeigt wird das
#: Wort. Die Zuordnung ist vorläufig; #62 bringt die Ausprägung im Buch dazu.
STRENGTHS = ("schwach", "mittel", "stark", "sehr stark")


def strength_level(books: int, defining: bool = False) -> int:
    """Die Stufe von 1 (schwach) bis 4 (sehr stark): die Zahl der geliebten
    Bücher, die eine Familie oder Facette tragen — und eine Stufe mehr, wenn sie
    in einem dieser Bücher prägt (#62). Ein einziges Buch, in dem sie das Buch
    ausmacht, soll nicht als „schwach" dastehen."""
    return max(1, min(books + int(defining), len(STRENGTHS)))


def strength(books: int, defining: bool = False) -> str:
    return STRENGTHS[strength_level(books, defining) - 1]


def derive_facets(
    chosen: Sequence[str], carriers: Mapping[str, Collection[str]]
) -> list[Facet]:
    """Facetten aus den gemochten Merkmalen — das Werkzeug bildet sie selbst.

    Eine Facette sind Merkmale, die **mehrere geliebte Bücher gemeinsam
    tragen** — nicht nur genau gleiche Buchmengen: "lebendiger Schauplatz"
    (drei Bücher) und "große Ideen" (zwei davon) gehören zusammen, weil die
    zwei beide tragen. Kandidaten sind die Buchmenge jeder Familie und jede
    Schnittmenge zweier, solange es mindestens zwei Bücher sind; ein Kandidat,
    der in einem anderen ganz aufgeht, fällt weg. Bücher werden nie paarweise
    verglichen, und es gibt keine Schwelle für "ähnlich" (#44).

    Facetten aus einem einzigen Buch gibt es nicht: einzelne Merkmale zählen
    für sich (#64), also braucht kein Buch eine eigene Facette, und eine
    Kombination aus einem Buch sagte mehr über dieses Buch als über einen
    Geschmack (24.09.2026). Erzählmuster gehören nie hinein (#63) — der
    Aufrufer reicht nur Merkmale.

    ``carriers`` nennt je Familie die geliebten Bücher, die sie tragen.
    """
    families = [f for f in dict.fromkeys(chosen) if carriers.get(f)]
    carrier_sets = {f: frozenset(carriers[f]) for f in families}

    candidates = {carrier_sets[f] for f in families if len(carrier_sets[f]) >= 2}
    candidates |= {
        carrier_sets[a] & carrier_sets[b]
        for i, a in enumerate(families)
        for b in families[i + 1:]
        if len(carrier_sets[a] & carrier_sets[b]) >= 2
    }
    shared_families = {b: tuple(f for f in families if b <= carrier_sets[f]) for b in candidates}
    valid = [(b, f) for b, f in shared_families.items() if len(f) >= MIN_FAMILIES]
    valid = [
        (b, f)
        for b, f in valid
        if not any((b2, f2) != (b, f) and set(f) <= set(f2) and b <= b2 for b2, f2 in valid)
    ]
    # Fest geordnet: die breitesten zuerst, dann in der Reihenfolge, in der
    # ihre Familien angetippt wurden — Mengen haben keine Reihenfolge.
    order = {f: i for i, f in enumerate(families)}
    valid.sort(key=lambda bf: (-len(bf[0]), min(order[f] for f in bf[1])))
    return [Facet(fs, tuple(sorted(b))) for b, fs in valid]


def load_profile_file(path: Path, vocabulary: Vocabulary) -> ReadingProfile:
    """Ein Profil aus einer Datei, gegen das Vokabular geprüft."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"{path.name} ist nicht lesbar: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileError(f"{path.name} enthält keine Facetten und Gegengewichte")

    def check_known(ids: Sequence[str]) -> None:
        for family_id in ids:
            try:
                vocabulary.family(family_id)
            except KeyError:
                raise ProfileError(f"keine solche Merkmalsfamilie: {family_id}") from None

    def read_family_ids(entry: object) -> tuple[str, ...]:
        if not isinstance(entry, dict):
            raise ProfileError(f"kein Eintrag mit familien: {entry!r}")
        # Doppelt Genanntes zählt einmal: "hart, hart" ist keine zweite Familie.
        ids = tuple(dict.fromkeys(str(f) for f in entry.get("familien") or []))
        check_known(ids)
        return ids

    facets = []
    for entry in data.get("facetten") or []:
        ids = read_family_ids(entry)
        if len(ids) < MIN_FAMILIES:
            raise ProfileError(
                f"eine Facette braucht mindestens zwei Familien: {', '.join(ids) or '(leer)'}"
            )
        facets.append(Facet(ids, tuple(str(b) for b in entry.get("buecher") or [])))

    liked_ids = list(dict.fromkeys(str(f) for f in data.get("gemocht") or []))
    boosted_ids = list(dict.fromkeys(str(f) for f in data.get("verstaerkt") or []))
    check_known(liked_ids)
    if len(boosted_ids) > MOST_BOOSTED:
        raise ProfileError(f"höchstens {MOST_BOOSTED} verstärkt, nicht {len(boosted_ids)}")
    if unknown := [f for f in boosted_ids if f not in liked_ids]:
        raise ProfileError(f"verstärkt, aber nicht gemocht: {', '.join(unknown)}")

    counterweights = []
    for entry in data.get("gegengewichte") or []:
        ids = read_family_ids(entry)
        # Ein leeres Gegengewicht träfe jedes Buch.
        if not ids:
            raise ProfileError("ein Gegengewicht braucht mindestens eine Familie")
        counterweights.append(Counterweight(
            ids,
            genre=str(entry["genre"]) if entry.get("genre") else None,
            books=tuple(str(b) for b in entry.get("buecher") or []),
        ))
    return ReadingProfile(
        facets=tuple(facets),
        counterweights=tuple(counterweights),
        liked=tuple(Liked(f, f in boosted_ids) for f in liked_ids),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Ein Profil aus einer Datei als neue Fassung speichern."""
    from . import paths
    from .config import load_settings
    from .store import Store

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("Aufruf: python -m ebook_watchlist.facets <profil.yaml>", file=sys.stderr)
        return 2
    file_path = Path(arguments[0])
    try:
        profile = load_profile_file(file_path, load_vocabulary())
    except ProfileError as exc:
        print(f"Profil nicht übernommen: {exc}", file=sys.stderr)
        return 1
    settings = load_settings()
    version = Store(paths.db_path()).put_reading_profile(
        settings.slug, profile, cause=f"aus der Datei {file_path.name}", now=datetime.now()
    )
    print(f"Profil gespeichert als Fassung {version}: {len(profile.liked)} gemocht, "
          f"{len(profile.facets)} Facetten, {len(profile.counterweights)} Gegengewichte.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
