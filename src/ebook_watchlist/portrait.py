"""Der Steckbrief eines Buchs: was ein Modell einmal über ein Buch sagt (#45).

Das Modell sieht jedes Buch genau einmal, unabhängig von jeder Leserin, und gibt
ihm Merkmale aus dem festen Vokabular in ``docs/merkmale.yaml``: zu jedem einen
Satz, der nur unter diesem Buch stehen kann, und worauf er beruht. Dazu, welches
Buch es ist, Genre und Pitch. Geurteilt wird hier nicht; das tut später der
Code (ADR 33, Punkt 4).

Reproduzierbar heißt: dasselbe Buch trägt immer denselben Steckbrief. Er trägt
deshalb einen Fingerabdruck aus Anweisung und Merkmalen, und nur wenn sich eines
davon ändert, wird neu gefragt. Die Familien gehören nicht dazu: sie sind ein
Arbeitsstand und werden erst beim Lesen angewandt.

Die Anweisung ist die aus dem Versuch vom 23.09.2026 (#44), dort an *Der Name
der Rose* und an einem erfundenen Titel geprüft; dazu kommen das Erkennen des
Buchs und der Pitch, die ADR 33 in denselben Aufruf legt.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from .rating import RatingUnavailable, _json_object

VOCABULARY_PATH = Path(__file__).resolve().parents[2] / "docs" / "merkmale.yaml"

#: Worauf ein Merkmal beruhen darf. "wissen" ist erlaubt: bei der Erstaufnahme
#: gibt es keine Vorgeschichte und damit oft keinen Klappentext (#44).
EVIDENCE = ("klappentext", "leseprobe", "wissen")
FEWEST, MOST = 4, 8
MIN_DIMENSIONS, MOST_PER_DIMENSION = 3, 3
#: Dieselbe Grenze wie im Bewertungsschema (#29).
PITCH_MAX = 200
#: Eine Antwort mit acht Merkmalen und ihren Sätzen braucht rund 700 Tokens.
MAX_TOKENS = 1500


class VocabularyError(Exception):
    """``docs/merkmale.yaml`` widerspricht sich oder ist nicht lesbar."""


@dataclass(frozen=True, slots=True)
class Term:
    """Ein Merkmal: ein Wort des festen Vokabulars."""

    id: str
    name: str
    description: str
    #: Der Name der Dimension, wie die Leserin sie liest ("Stimmung").
    dimension: str


@dataclass(frozen=True, slots=True)
class Family:
    """Merkmale, die eine Leserin nicht unterscheidet."""

    id: str
    name: str
    members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Vocabulary:
    terms: dict[str, Term]
    families: tuple[Family, ...]
    #: Name und Frage je Dimension, in der Reihenfolge der Datei.
    dimensions: tuple[tuple[str, str], ...]

    def family_of(self, term_id: str) -> Family:
        """Die Familie eines Merkmals; eines, das in keiner steht, ist seine eigene."""
        for family in self.families:
            if term_id in family.members:
                return family
        term = self.terms[term_id]
        return Family(term.id, term.name, (term.id,))

    def family(self, family_id: str) -> Family:
        """Eine Familie nach ihrer id; ein Merkmal ohne Familie ist seine eigene.

        Wirft ``KeyError``, wenn es sie nicht gibt.
        """
        for family in self.families:
            if family.id == family_id:
                return family
        if family_id in self.terms and self.family_of(family_id).id == family_id:
            return self.family_of(family_id)
        raise KeyError(family_id)

    def prompt_text(self) -> str:
        """Das Vokabular, wie das Modell es liest — ohne Familien."""
        zeilen = []
        for name, frage in self.dimensions:
            zeilen.append(f"{name} ({frage}):")
            zeilen.extend(
                f"  {term.id}: {term.name} — {term.description}"
                for term in self.terms.values()
                if term.dimension == name
            )
        return "\n".join(zeilen)


@dataclass(frozen=True, slots=True)
class Trait:
    """Ein vergebenes Merkmal: welches, wo es im Buch steckt, worauf es beruht."""

    term: str
    sentence: str
    evidence: str


@dataclass(frozen=True, slots=True)
class Portrait:
    """Der Steckbrief. Ohne ``known`` ist alles andere leer."""

    known: bool
    fingerprint: str
    title: str | None = None
    author: str | None = None
    #: Bei einer Übersetzung: *Cry Baby* ist *Sharp Objects*.
    original_title: str | None = None
    genre: str | None = None
    subgenre: str | None = None
    pitch: str | None = None
    traits: tuple[Trait, ...] = ()
    #: Welche Regeln die Antwort verletzt. Ein Verstoß verwirft nichts; er
    #: steht daneben, damit man ihn sieht.
    violations: tuple[str, ...] = ()


def load_vocabulary(path: Path | None = None) -> Vocabulary:
    """Das Vokabular, geprüft: jede id einmal, jede Familie mit echten Merkmalen."""
    datei = path or VOCABULARY_PATH
    try:
        daten = yaml.safe_load(datei.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise VocabularyError(f"{datei.name} ist nicht lesbar: {exc}") from exc

    terms: dict[str, Term] = {}
    dimensions: list[tuple[str, str]] = []
    for dimension in daten.get("dimensionen") or []:
        name = str(dimension["name"])
        dimensions.append((name, str(dimension.get("frage", ""))))
        for eintrag in dimension.get("merkmale") or []:
            term_id = str(eintrag["id"])
            if term_id in terms:
                raise VocabularyError(f"das Merkmal {term_id} steht zweimal im Vokabular")
            terms[term_id] = Term(
                term_id, str(eintrag["name"]), str(eintrag.get("beschreibung", "")).strip(), name
            )

    families: list[Family] = []
    vergeben: dict[str, str] = {}
    for eintrag in daten.get("familien") or []:
        name = str(eintrag["name"])
        members = tuple(str(term_id) for term_id in eintrag.get("merkmale") or [])
        for term_id in members:
            if term_id not in terms:
                raise VocabularyError(f"die Familie {name} nennt {term_id}, das es nicht gibt")
            if term_id in vergeben:
                raise VocabularyError(
                    f"{term_id} steht in zwei Familien: {vergeben[term_id]} und {name}"
                )
            vergeben[term_id] = name
        families.append(Family(str(eintrag["id"]), name, members))

    return Vocabulary(terms, tuple(families), tuple(dimensions))


TEMPLATE = """\
Du legst den Steckbrief eines Buchs an. Er beschreibt, wie sich das Lesen
dieses Buches anfühlt, und gilt für jede Leserin gleich.

Zuerst: Welches Buch ist gemeint? Nenne Titel und Autor so, wie das Buch
wirklich heißt, und bei einer Übersetzung den Originaltitel. Ein Tippfehler im
Namen oder ein deutscher Titel darf dich nicht irreführen. Kennst du das Buch
nicht sicher und liegt kein Text bei, setze "bekannt" auf false und lass alles
andere weg. Verwechsle es nicht mit einem ähnlich klingenden Buch.

Dann die Merkmale. Du wählst sie ausschließlich aus dem Vokabular unten und
gibst ihre id an; neue erfindest du nicht. Eine Leserin wird später sehen,
welche Merkmale du vergeben hast, und auswählen, welche davon sie an diesem Buch
gehalten oder verloren haben. Vergib also die Merkmale, die dieses Buch am
deutlichsten prägen.

Regeln:
- Vier bis acht Merkmale.
- Aus mindestens drei verschiedenen Dimensionen, höchstens drei aus derselben.
- Was auf fast jedes Buch seines Genres zutrifft, nimmst du nur, wenn es hier
  deutlich stärker ausgeprägt ist als üblich. Ein Thriller ist nicht schon
  deshalb spannungsgeladen, weil er ein Thriller ist.
- Zu jedem Merkmal schreibst du einen Satz, der zeigt, wo es in DIESEM Buch
  steckt: eine Figur, eine Situation, eine Eigenart. Die Probe: Könnte derselbe
  Satz unter einem anderen Buch stehen, ist er falsch. Verrate kein Ende.
- Zu jedem Merkmal nennst du, worauf es beruht: "klappentext", "leseprobe"
  oder "wissen" (was du selbst über das Buch weißt).
- Nichts erfinden.

Nenne außerdem Genre und Untergenre auf Deutsch, so wie eine Buchhandlung das
Buch einordnen würde.

Und schreib den Pitch: ein bis zwei Sätze, höchstens 200 Zeichen. Zuerst, was
das Buch ist; dann, was es ausmacht. Wähle ein Bild, an dem dieses Buch hängt,
statt es zusammenzufassen. Beschreiben, nicht loben. Nichts verraten.

--- VOKABULAR ---
{vokabular}
--- ENDE VOKABULAR ---

--- BUCH ---
{buch}
--- ENDE BUCH ---

Antworte ausschließlich mit JSON in genau dieser Form:
{{"bekannt": true, "titel": "...", "autor": "...", "originaltitel": "... oder null",
  "genre": "...", "untergenre": "...", "pitch": "...",
  "merkmale": [{{"id": "...", "satz": "...", "beleg": "..."}}]}}
"""


def fingerprint(vocabulary: Vocabulary) -> str:
    """Woran man sieht, ob ein gespeicherter Steckbrief noch gilt."""
    stoff = TEMPLATE + vocabulary.prompt_text()
    return hashlib.sha256(stoff.encode("utf-8")).hexdigest()[:16]


def prompt(title: str, author: str | None, blurb: str | None, vocabulary: Vocabulary) -> str:
    buch = [f"Titel: {title}", f"Autor: {author or '(nicht angegeben)'}"]
    if blurb:
        buch.append(f"Klappentext: {blurb}")
    return TEMPLATE.format(vokabular=vocabulary.prompt_text(), buch="\n".join(buch))


def _text(value) -> str | None:
    """Ein Feld der Antwort als Text; leer, ``null`` und "null" sind nichts."""
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text.lower() == "null" else text


def parse_answer(text: str, vocabulary: Vocabulary) -> Portrait:
    """Die Antwort des Modells als Steckbrief, mit den Regeln daneben geprüft.

    Ein Merkmal außerhalb des Vokabulars wird nicht übernommen, sondern
    genannt: ein erfundenes Wort könnte keine zwei Bücher je gemeinsam haben.
    Alle anderen Verstöße verwerfen nichts.
    """
    daten = _json_object(text)
    if not isinstance(daten, dict):
        raise RatingUnavailable("Antwort ist kein JSON-Objekt")
    abdruck = fingerprint(vocabulary)
    roh = daten.get("merkmale") or []

    # Nur ein echtes Ja: "false" als Text ist kein Ja.
    if daten.get("bekannt") is not True:
        verstoesse = ("unbekannt, aber Merkmale vergeben",) if roh else ()
        return Portrait(known=False, fingerprint=abdruck, violations=verstoesse)

    traits: list[Trait] = []
    verstoesse: list[str] = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            verstoesse.append("ein Merkmal ohne Form")
            continue
        term_id = str(eintrag.get("id") or "").strip()
        if term_id not in vocabulary.terms:
            verstoesse.append(f"nicht im Vokabular: {term_id or '(leer)'}")
            continue
        if any(trait.term == term_id for trait in traits):
            verstoesse.append(f"doppelt vergeben: {term_id}")
            continue
        beleg = str(eintrag.get("beleg") or "").strip()
        if beleg not in EVIDENCE:
            verstoesse.append(f"ungültiger Beleg bei {term_id}: {beleg or '(keiner)'}")
        traits.append(Trait(term_id, str(eintrag.get("satz") or "").strip(), beleg))

    if not FEWEST <= len(traits) <= MOST:
        verstoesse.append(f"{len(traits)} Merkmale statt vier bis acht")
    dimensionen = Counter(vocabulary.terms[trait.term].dimension for trait in traits)
    if traits and len(dimensionen) < MIN_DIMENSIONS:
        verstoesse.append(f"nur {len(dimensionen)} Dimensionen statt mindestens drei")
    for dimension, anzahl in dimensionen.items():
        if anzahl > MOST_PER_DIMENSION:
            verstoesse.append(f"{anzahl} Merkmale aus {dimension}, höchstens drei")

    pitch = _text(daten.get("pitch"))
    if pitch is None:
        verstoesse.append("kein Pitch")
    elif len(pitch) > PITCH_MAX:
        verstoesse.append(f"Pitch hat {len(pitch)} Zeichen, höchstens {PITCH_MAX}")

    return Portrait(
        known=True,
        fingerprint=abdruck,
        title=_text(daten.get("titel")),
        author=_text(daten.get("autor")),
        original_title=_text(daten.get("originaltitel")),
        genre=_text(daten.get("genre")),
        subgenre=_text(daten.get("untergenre")),
        pitch=pitch,
        traits=tuple(traits),
        violations=tuple(verstoesse),
    )


def portray(
    title: str,
    author: str | None,
    blurb: str | None,
    ask: Callable[[str, int], str],
    vocabulary: Vocabulary,
) -> Portrait:
    """Einmal fragen, die Antwort lesen. Speichern tut der Aufrufer."""
    return parse_answer(ask(prompt(title, author, blurb, vocabulary), MAX_TOKENS), vocabulary)
