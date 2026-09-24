"""Das Urteil kommt aus dem Code (#46, ADR 33).

Ein Leseprofil besteht aus **Facetten** und **Gegengewichten**, beide Bündel aus
Merkmalsfamilien. Wie gut ein Buch dazu passt, rechnet dieser Code aus dem
Steckbrief des Buchs; kein Modell wird gefragt.

Jede Facette ist ein eigener Grund, das Buch zu mögen: ganz getroffen wiegt sie
0,8, teilweise 0,1, und die Gründe werden als Noisy-OR verbunden — mehrere
verstärken sich, ohne je Gewissheit zu erreichen, und halbe Gründe sammeln sich
nicht zu einem ganzen. Das stärkste Gegengewicht zieht ein Fünftel ab. Die
Werte stehen im Bewertungsschema (``urteil_aus_merkmalen``).

Ein Gegengewicht darf ein Genre enthalten, eine Facette nicht: im Gegengewicht
grenzt es nur ein, was bestraft wird, in einer Facette grenzte es ein, was
gefunden wird (Nachtrag zu ADR 33).

    uv run python -m ebook_watchlist.facets profil.yaml

liest ein Profil aus einer Datei ein. Der gewöhnliche Weg ist die
Erstaufnahme (#50); aus deren Antworten leitet ``derive_facets`` die Facetten
ab, und ``uncovered`` nennt die geliebten Bücher, die in keiner stecken.
"""

from __future__ import annotations

import math
import re
import sys
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from .portrait import Portrait, Vocabulary, load_vocabulary
from .rating import SCHEME_PATH

#: Wie viele Familien eine Facette mindestens braucht. Eine einzelne ist zu
#: breit: im Versuch ließ "große Ideen" allein einen enttäuschenden
#: Wissenschaftsthriller herein (#44).
MIN_FAMILIES = 2


class ProfileError(Exception):
    """Ein Profil widerspricht dem Vokabular oder den Regeln."""


@dataclass(frozen=True, slots=True)
class Facet:
    """Eine benannte Art, wie ein Buch zur Leserin passt."""

    #: Die ids der Merkmalsfamilien.
    families: tuple[str, ...]
    #: Aus welchen geliebten Büchern sie stammt — für die Stärke und die Profilseite.
    books: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Counterweight:
    """Was ein Buch die Leserin gekostet hat. Zählt nur, wenn alles zutrifft."""

    families: tuple[str, ...]
    #: Nur bei Büchern dieses Genres, etwa "High Fantasy".
    genre: str | None = None
    books: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadingProfile:
    facets: tuple[Facet, ...]
    counterweights: tuple[Counterweight, ...]
    #: Die Fassung, wie sie der Speicher vergeben hat; 0 für eines, das nicht
    #: aus dem Speicher kommt.
    version: int = 0


@dataclass(frozen=True, slots=True)
class Weights:
    full: float
    partial: float
    counterweight: float
    #: (Sterne, ab welcher Übereinstimmung), absteigend.
    stars_from: tuple[tuple[int, float], ...]


@dataclass(frozen=True, slots=True)
class FacetHit:
    facet: Facet
    #: Welche ihrer Familien das Buch trägt.
    hit: tuple[str, ...]

    @property
    def full(self) -> bool:
        return len(self.hit) == len(self.facet.families)


@dataclass(frozen=True, slots=True)
class Reason:
    """Eine Zeile der Begründung.

    Knapp wie eine Marke, kein Satz: die Facette steht mit ihrem Namen da,
    und ob sie ganz oder zum Teil trifft, sagt die Art der Zeile — das Bild
    macht daraus ein Zeichen. Woher eine Facette stammt, steht nicht hier:
    "wie Leichenblässe" unter einem Buch von Nesbø las sich wie ein Vergleich
    der beiden Bücher, und den zieht niemand.
    """

    #: ``ganz``, ``teils``, ``dagegen``, ``keine`` oder ``beleg``.
    kind: str
    text: str

    @property
    def detail(self) -> bool:
        """Ein Beleg zur Zeile davor — der Satz aus dem Steckbrief."""
        return self.kind == "beleg"

    @property
    def line(self) -> str:
        """Die Zeile als Text, ohne Bild."""
        vorn = {"teils": "zum Teil: ", "dagegen": "dagegen: "}.get(self.kind, "")
        return vorn + self.text


@dataclass(frozen=True, slots=True)
class Fit:
    """Die Übereinstimmung eines Buchs mit einem Profil."""

    #: Zwischen 0 und 1; ordnet die Liste.
    share: float
    #: 0 bis 5; fasst zusammen.
    stars: int
    #: Die berührten Facetten, die ganzen zuerst.
    hits: tuple[FacetHit, ...]
    #: Das Gegengewicht, das abgezogen wurde, oder keines.
    against: Counterweight | None
    #: Die Begründung, Zeile für Zeile.
    reasons: tuple[Reason, ...]


def load_weights(path: Path | None = None) -> Weights:
    """Die Gewichte aus dem Bewertungsschema."""
    daten = yaml.safe_load((path or SCHEME_PATH).read_text(encoding="utf-8"))
    teil = daten["urteil_aus_merkmalen"]
    stufen = sorted(((int(s), float(ab)) for s, ab in teil["sterne_ab"].items()), reverse=True)
    return Weights(
        full=float(teil["facette_ganz"]),
        partial=float(teil["facette_teilweise"]),
        counterweight=float(teil["gegengewicht"]),
        stars_from=tuple(stufen),
    )


def families_of(portrait: Portrait, vocabulary: Vocabulary) -> set[str]:
    """Die Familien, die ein Buch trägt."""
    return {
        vocabulary.family_of(trait.term).id
        for trait in portrait.traits
        if trait.term in vocabulary.terms
    }


def _genre_matches(counterweight: Counterweight, portrait: Portrait) -> bool:
    """Ob das Buch zum Genre des Gegengewichts gehört — als ganzes Wort.

    "High Fantasy" steckt in "High Fantasy / Heroische Fantasy"; "Roman"
    steckt nicht in "Kriminalroman", sonst träfe ein Gegengewicht "nur bei
    Roman" jeden Krimi.
    """
    if counterweight.genre is None:
        return True
    gesucht = re.compile(rf"(?<!\w){re.escape(counterweight.genre.casefold())}(?!\w)")
    teile = (portrait.genre, portrait.subgenre)
    return any(gesucht.search((teil or "").casefold()) for teil in teile)


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
    alle = list(old)
    geaendert = False
    for c in new:
        for i, da in enumerate(alle):
            if (da.families, da.genre) == (c.families, c.genre):
                fehlend = tuple(b for b in c.books if b not in da.books)
                if fehlend:
                    alle[i] = Counterweight(da.families, da.genre, (*da.books, *fehlend))
                    geaendert = True
                break
        else:
            alle.append(c)
            geaendert = True
    return tuple(alle), geaendert


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


def fit(
    portrait: Portrait, profile: ReadingProfile, vocabulary: Vocabulary, weights: Weights
) -> Fit | None:
    """Wie gut das Buch passt — oder ``None``, wenn nicht geurteilt wird.

    Nicht geurteilt wird ohne Facetten (ADR 33, Punkt 8) und über ein Buch, das
    das Modell nicht kennt: ohne Merkmale hieße jedes Urteil "passt nicht", und
    das wäre eine Behauptung, keine Auskunft.
    """
    if not profile.facets or not portrait.known:
        return None
    familien = families_of(portrait, vocabulary)

    treffer = []
    for facet in profile.facets:
        getroffen = tuple(f for f in facet.families if f in familien)
        if getroffen:
            treffer.append(FacetHit(facet, getroffen))
    treffer.sort(key=lambda t: (not t.full, -len(t.hit)))

    anteil = 1 - math.prod(
        1 - (weights.full if t.full else weights.partial) for t in treffer
    )
    dagegen = next(
        (
            c
            for c in profile.counterweights
            if all(f in familien for f in c.families) and _genre_matches(c, portrait)
        ),
        None,
    )
    if dagegen is not None:
        anteil *= 1 - weights.counterweight

    if anteil == 0:
        sterne = 0 if dagegen is not None else 1
    else:
        sterne = next((s for s, ab in weights.stars_from if anteil >= ab), 1)

    return Fit(
        share=anteil,
        stars=sterne,
        hits=tuple(treffer),
        against=dagegen,
        reasons=_reasons(treffer, dagegen, portrait, vocabulary),
    )


def _reasons(
    treffer: list[FacetHit],
    dagegen: Counterweight | None,
    portrait: Portrait,
    vocabulary: Vocabulary,
) -> tuple[Reason, ...]:
    """Die Begründung aus Daten: welche Facette, und der Satz dazu.

    Facette und Gegengewicht sind gleich gebaut — eine Marke, darunter die
    Sätze aus dem Steckbrief. Nur der Satz: die Familie steht schon in der
    Marke, und zweimal derselbe Name ist keine zweite Auskunft.
    """

    def belege(family_ids: Sequence[str]) -> list[Reason]:
        saetze = []
        for family_id in family_ids:
            satz = next(
                (
                    trait.sentence
                    for trait in portrait.traits
                    if trait.term in vocabulary.terms
                    and vocabulary.family_of(trait.term).id == family_id
                ),
                "",
            )
            if satz:
                saetze.append(Reason("beleg", satz))
        return saetze

    zeilen: list[Reason] = []
    for t in treffer:
        # Beim Teiltreffer nur, was das Buch trägt: "große Welt · verschachtelt"
        # las sich bei Leopard, als hätte Harry Hole eine große Welt.
        if t.full:
            zeilen.append(Reason("ganz", family_names(t.facet.families, vocabulary)))
        else:
            zeilen.append(Reason("teils", family_names(t.hit, vocabulary)))
        zeilen.extend(belege(t.hit))
    if not treffer:
        zeilen.append(Reason("keine", "keine Facette getroffen"))
    if dagegen is not None:
        im_genre = f" (bei {dagegen.genre})" if dagegen.genre else ""
        zeilen.append(Reason("dagegen", family_names(dagegen.families, vocabulary) + im_genre))
        zeilen.extend(belege(dagegen.families))
    return tuple(zeilen)


#: Wie stark eine Facette belegt ist, als Skala statt als Zahl (#44): ein Buch
#: ist schwach, ab vier sehr stark. Die Anzahl wird gemerkt, gezeigt wird das
#: Wort. Die Zuordnung ist vorläufig.
STRENGTHS = ("schwach", "mittel", "stark", "sehr stark")


def strength(books: int) -> str:
    return STRENGTHS[max(1, min(books, len(STRENGTHS))) - 1]


def derive_facets(
    chosen: Sequence[str], carriers: Mapping[str, Collection[str]]
) -> list[Facet]:
    """Facetten aus den Familien, die die Leserin bestätigt hat (#50).

    Eine Facette sind Familien, die **dieselben Bücher gemeinsam tragen** —
    nicht nur genau gleiche Buchmengen: "lebendiger Schauplatz" (drei Bücher)
    und "große Ideen" (zwei davon) gehören zusammen, weil die zwei beide
    tragen. Kandidaten sind die Buchmenge jeder Familie und jede Schnittmenge
    zweier, die mindestens zwei Bücher hat; ein Kandidat, der in einem anderen
    ganz aufgeht, fällt weg. Bücher werden nie paarweise verglichen, und es
    gibt keine Schwelle für "ähnlich" (#44).

    Was in keiner Facette steckt, kommt als Facette aus einer einzigen Familie
    zurück: zu breit, um zu zählen, aber sichtbar (``MIN_FAMILIES``).

    ``carriers`` nennt je Familie die geliebten Bücher, die sie tragen.
    """
    familien = [f for f in dict.fromkeys(chosen) if carriers.get(f)]
    traeger = {f: frozenset(carriers[f]) for f in familien}

    kandidaten: dict[frozenset, tuple[str, ...]] = {}

    def dazu(buecher: frozenset) -> None:
        if buecher and buecher not in kandidaten:
            kandidaten[buecher] = tuple(f for f in familien if buecher <= traeger[f])

    for f in familien:
        dazu(traeger[f])
    for i, a in enumerate(familien):
        for b in familien[i + 1:]:
            gemeinsam = traeger[a] & traeger[b]
            if len(gemeinsam) >= 2:
                dazu(gemeinsam)

    echte = [(b, f) for b, f in kandidaten.items() if len(f) >= MIN_FAMILIES]
    echte = [
        (b, f)
        for b, f in echte
        if not any(
            (b2, f2) != (b, f) and set(f) <= set(f2) and b <= b2 for b2, f2 in echte
        )
    ]
    echte.sort(key=lambda bf: -len(bf[0]))
    drin = {f for _, fs in echte for f in fs}
    einzeln = [(traeger[f], (f,)) for f in familien if f not in drin]
    return [Facet(fs, tuple(sorted(b))) for b, fs in (*echte, *einzeln)]


def uncovered(facets: Sequence[Facet], loved: Collection[str]) -> list[str]:
    """Die geliebten Bücher, die in keiner Facette stecken, die zählt.

    Die Abdeckungsregel (ADR 33, Punkt 6): jedes geliebte Buch muss am Ende in
    einer Facette stecken. Im Versuch landete *Otherland* in keiner, und was
    es eigentlich trägt, wurde nie gefragt (#44).
    """
    gedeckt = {b for f in facets if len(f.families) >= MIN_FAMILIES for b in f.books}
    return [b for b in loved if b not in gedeckt]


def load_profile_file(path: Path, vocabulary: Vocabulary) -> ReadingProfile:
    """Ein Profil aus einer Datei, gegen das Vokabular geprüft."""
    try:
        daten = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"{path.name} ist nicht lesbar: {exc}") from exc

    if not isinstance(daten, dict):
        raise ProfileError(f"{path.name} enthält keine Facetten und Gegengewichte")

    def familien(eintrag: object) -> tuple[str, ...]:
        if not isinstance(eintrag, dict):
            raise ProfileError(f"kein Eintrag mit familien: {eintrag!r}")
        # Doppelt Genanntes zählt einmal: "hart, hart" ist keine zweite Familie.
        ids = tuple(dict.fromkeys(str(f) for f in eintrag.get("familien") or []))
        for family_id in ids:
            try:
                vocabulary.family(family_id)
            except KeyError:
                raise ProfileError(f"keine solche Merkmalsfamilie: {family_id}") from None
        return ids

    facetten = []
    for eintrag in daten.get("facetten") or []:
        ids = familien(eintrag)
        if len(ids) < MIN_FAMILIES:
            raise ProfileError(
                f"eine Facette braucht mindestens zwei Familien: {', '.join(ids) or '(leer)'}"
            )
        facetten.append(Facet(ids, tuple(str(b) for b in eintrag.get("buecher") or [])))

    gegen = []
    for eintrag in daten.get("gegengewichte") or []:
        ids = familien(eintrag)
        # Ein leeres Gegengewicht träfe jedes Buch.
        if not ids:
            raise ProfileError("ein Gegengewicht braucht mindestens eine Familie")
        gegen.append(Counterweight(
            ids,
            genre=str(eintrag["genre"]) if eintrag.get("genre") else None,
            books=tuple(str(b) for b in eintrag.get("buecher") or []),
        ))
    return ReadingProfile(facets=tuple(facetten), counterweights=tuple(gegen))


def main(argv: Sequence[str] | None = None) -> int:
    """Ein Profil aus einer Datei als neue Fassung speichern."""
    from . import paths
    from .config import load_settings
    from .store import Store

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Aufruf: python -m ebook_watchlist.facets <profil.yaml>", file=sys.stderr)
        return 2
    datei = Path(args[0])
    try:
        profil = load_profile_file(datei, load_vocabulary())
    except ProfileError as exc:
        print(f"Profil nicht übernommen: {exc}", file=sys.stderr)
        return 1
    settings = load_settings()
    fassung = Store(paths.db_path()).put_reading_profile(
        settings.slug, profil, cause=f"aus der Datei {datei.name}", now=datetime.now()
    )
    print(f"Profil gespeichert als Fassung {fassung}: {len(profil.facets)} Facetten, "
          f"{len(profil.counterweights)} Gegengewichte.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
