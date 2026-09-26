"""Der Steckbrief eines Buchs: was ein Modell einmal über ein Buch sagt (#45).

Das Modell sieht jedes Buch genau einmal, unabhängig von jeder Leserin, und gibt
ihm Merkmale aus dem festen Vokabular in ``vocabulary/merkmale.yaml``: zu jedem einen
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

Im selben Aufruf vergibt das Modell auch Erzählmuster aus
``vocabulary/erzaehlmuster.yaml`` (#49). Sie sind Wörter desselben Vokabulars, in
einer eigenen Dimension: so können Facetten und Gegengewichte sie enthalten,
ohne dass der Code sie anders behandeln müsste. Gezählt werden sie getrennt —
vier bis acht Merkmale und dazu ein bis drei Muster.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

#: Wo das Vokabular liegt. Nicht in Git: es beruht auf NoveList, und ob es
#: veröffentlicht werden darf, ist ungeklärt (#59). Ein anderes Verzeichnis
#: lässt sich mit ``EBW_VOCABULARY_DIR`` angeben.
VOCABULARY_DIR = Path(
    os.environ.get("EBW_VOCABULARY_DIR") or Path(__file__).resolve().parents[2] / "vocabulary"
)
VOCABULARY_PATH = VOCABULARY_DIR / "merkmale.yaml"
PATTERNS_PATH = VOCABULARY_DIR / "erzaehlmuster.yaml"
#: Die Dimension, in der die Erzählmuster stehen.
PATTERN_DIMENSION = "Erzählmuster"

#: Worauf ein Merkmal beruhen darf. "wissen" ist erlaubt: bei der Erstaufnahme
#: gibt es keine Vorgeschichte und damit oft keinen Klappentext (#44).
#: Seit #68 wird keine Leseprobe mehr mitgeschickt; wer sich auf sie beruft, hat
#: sie erfunden (#69), also gilt sie nicht mehr als Beleg.
EVIDENCE = ("klappentext", "wissen")
#: Wie stark ein Merkmal dieses Buch prägt (#62): ohne es wäre es ein anderes
#: Buch — es gehört klar dazu — es kommt vor, trägt aber nicht. Auf Deutsch
#: fragt das Modell, in diesen drei Wörtern antwortet es; gerechnet wird mit den
#: englischen Namen.
DEFINING, CLEAR, MARGINAL = "defining", "clear", "marginal"
#: „prägend“ mit Umlaut steht dabei, weil das Modell es so schreibt (sechs von 24
#: Antworten am 25.09.2026), obwohl die Anweisung „praegend“ nennt.
WEIGHT_WORDS = {"praegend": DEFINING, "prägend": DEFINING, "deutlich": CLEAR, "rand": MARGINAL}
FEWEST, MOST = 4, 8
MIN_DIMENSIONS, MOST_PER_DIMENSION = 3, 3
FEWEST_PATTERNS, MOST_PATTERNS = 1, 3
#: Wie lang der Kurztext höchstens sein darf.
PITCH_MAX = 200
#: Eine Antwort mit acht Merkmalen, drei Mustern und ihren Sätzen braucht rund
#: 1000 Tokens.
MAX_TOKENS = 2000


class PortrayalUnavailable(Exception):
    """Kein Steckbrief: kein Schlüssel, kein Netz, eine Absage, eine unlesbare
    Antwort. Das Buch bleibt unbeschrieben und wird trotzdem gezeigt (ADR 7)."""


class VocabularyError(Exception):
    """``merkmale.yaml`` oder ``erzaehlmuster.yaml`` widerspricht sich, fehlt
    oder ist nicht lesbar."""


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
    #: Was die Familie als Ganzes heißt — nicht nur eines ihrer Merkmale.
    description: str = ""


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
        return Family(term.id, term.name, (term.id,), term.description)

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

    def is_pattern(self, term_id: str) -> bool:
        """Ob ein Wort — oder eine Familie — ein Erzählmuster ist.

        Eine Familie ist nie gemischt: Merkmale und Muster stehen in eigenen
        Familien, also entscheidet ihr erstes Mitglied.
        """
        if term_id not in self.terms:
            term_id = self.family(term_id).members[0]
        return self.terms[term_id].dimension == PATTERN_DIMENSION

    def prompt_text(self) -> str:
        """Das Vokabular, wie das Modell es liest.

        Die Merkmale ohne Familien — die sind ein Arbeitsstand. Die Erzählmuster
        dagegen unter ihrer Grundhandlung: die ist selbst vergebbar, und das
        Modell soll sehen, wann das genauere Muster passt.
        """
        rows = []
        for name, question in self.dimensions:
            rows.append(f"{name} ({question}):")
            if name == PATTERN_DIMENSION:
                for family in self.families:
                    if not family.members or not self.is_pattern(family.members[0]):
                        continue
                    for index, term_id in enumerate(family.members):
                        term = self.terms[term_id]
                        indent = "  " if index == 0 else "    "
                        rows.append(f"{indent}{term.id}: {term.name} — {term.description}")
                continue
            rows.extend(
                f"  {term.id}: {term.name} — {term.description}"
                for term in self.terms.values()
                if term.dimension == name
            )
        return "\n".join(rows)


@dataclass(frozen=True, slots=True)
class Trait:
    """Ein vergebenes Merkmal: welches, wo es im Buch steckt, worauf es beruht."""

    term: str
    sentence: str
    evidence: str
    #: Wie stark es das Buch prägt (``DEFINING``, ``CLEAR``, ``MARGINAL``) — nur
    #: bei einem Merkmal; ein Erzählmuster trägt keines, und wo das Modell keines
    #: nannte, steht ``None`` (#62).
    weight: str | None = None


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
    #: Ob beim Fragen ein Text (Klappentext, Schlagwörter) beilag. ``None`` bei
    #: einer Zeile aus der Zeit davor. Ein „unbekannt“ ohne Text sagt etwas über
    #: den fehlenden Text, nicht über das Buch (siehe ``worth_asking_again``).
    with_text: bool | None = None
    #: Ob beim Fragen der Anfang der Leseprobe beilag (#76): die zweite Stufe,
    #: wenn ein Buch trotz Klappentext unbekannt blieb. Einmal, nie wieder.
    with_sample: bool | None = None


def worth_asking_again(portrait: Portrait, *, text_now: bool, sample_now: bool = False) -> bool:
    """Ob ein gespeicherter Steckbrief noch einmal gefragt werden darf.

    Nur ein **unbekanntes** Buch, das ohne Text beschrieben wurde, und nur, wenn
    jetzt einer da ist: ein Watchlist-Titel wird beim Anlegen mit Titel und
    Autor:in allein gefragt, der Klappentext kommt erst mit dem ersten Lauf
    (fünf Bücher am 25.09.2026). Ein „unbekannt“ mit Text bleibt stehen — ein
    zweiter Versuch mit demselben Text brächte dasselbe und kostete einen
    Aufruf. Eine Zeile aus der Zeit vor diesem Vermerk (``None``) gilt als ohne
    Text beschrieben.

    Mit Text unbekannt geblieben, darf es genau einmal noch mit der Leseprobe
    gefragt werden, sobald eine da ist (#76).
    """
    if portrait.known:
        return False
    if portrait.with_text is not True:
        return text_now
    return portrait.with_sample is not True and sample_now


def load_vocabulary(path: Path | None = None, patterns: Path | None = None) -> Vocabulary:
    """Das Vokabular, geprüft: jede id einmal, jede Familie mit echten Merkmalen.

    Merkmale und Erzählmuster zusammen; fehlt die Datei der Erzählmuster, gibt
    es eben keine.
    """
    file = path or VOCABULARY_PATH
    patterns_path = patterns or PATTERNS_PATH
    try:
        text = file.read_text(encoding="utf-8")
        patterns_text = (
            patterns_path.read_text(encoding="utf-8") if patterns_path.exists() else None
        )
    except OSError as exc:
        raise VocabularyError(f"{exc.filename} ist nicht lesbar: {exc}") from exc
    return _parse_vocabulary(text, file.name, patterns_text, patterns_path.name)


@lru_cache(maxsize=8)
def _parse_vocabulary(
    text: str, name: str, patterns_text: str | None, patterns_name: str
) -> Vocabulary:
    """Geparst wird nur, wenn sich der Inhalt ändert.

    Lesen ist billig, das YAML zweier Dateien mit über tausend Zeilen nicht —
    und gebraucht wird das Vokabular bei jedem Eintrag, jeder Abfrage und
    jedem Buch im Regal. Der Schlüssel ist der Inhalt, nicht die Dateizeit:
    zwei schnelle Änderungen können dieselbe Zeit tragen.
    """
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise VocabularyError(f"{name} ist nicht lesbar: {exc}") from exc

    terms: dict[str, Term] = {}
    dimensions: list[tuple[str, str]] = []
    for dimension in data.get("dimensionen") or []:
        name = str(dimension["name"])
        dimensions.append((name, str(dimension.get("frage", ""))))
        for entry in dimension.get("merkmale") or []:
            term_id = str(entry["id"])
            if term_id in terms:
                raise VocabularyError(f"das Merkmal {term_id} steht zweimal im Vokabular")
            terms[term_id] = Term(
                term_id, str(entry["name"]), str(entry.get("beschreibung", "")).strip(), name
            )

    families: list[Family] = []
    assigned: dict[str, str] = {}
    for entry in data.get("familien") or []:
        name = str(entry["name"])
        members = tuple(str(term_id) for term_id in entry.get("merkmale") or [])
        for term_id in members:
            if term_id not in terms:
                raise VocabularyError(f"die Familie {name} nennt {term_id}, das es nicht gibt")
            if term_id in assigned:
                raise VocabularyError(
                    f"{term_id} steht in zwei Familien: {assigned[term_id]} und {name}"
                )
            assigned[term_id] = name
        description = str(entry.get("beschreibung", "")).strip()
        families.append(Family(str(entry["id"]), name, members, description))

    if patterns_text is not None:
        _load_patterns(patterns_text, patterns_name, terms, families, dimensions)
    return Vocabulary(terms, tuple(families), tuple(dimensions))


def _load_patterns(
    text: str,
    name: str,
    terms: dict[str, Term],
    families: list[Family],
    dimensions: list[tuple[str, str]],
) -> None:
    """Die Erzählmuster dazuladen: jede Grundhandlung ist Familie und Wort zugleich."""
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise VocabularyError(f"{name} ist nicht lesbar: {exc}") from exc

    family_ids = {family.id for family in families}

    def new(term_id: str, name: str, description: str) -> None:
        if term_id in terms or term_id in family_ids:
            raise VocabularyError(f"{term_id} steht zweimal im Vokabular")
        terms[term_id] = Term(term_id, name, description.strip(), PATTERN_DIMENSION)

    base: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for entry in data.get("familien") or []:
        family_id, name = str(entry["id"]), str(entry["name"])
        new(family_id, name, str(entry.get("beschreibung", "")))
        base[family_id] = [family_id]
        names[family_id] = name
    for entry in data.get("muster") or []:
        term_id, parent = str(entry["id"]), str(entry.get("familie") or "")
        if parent not in base:
            raise VocabularyError(f"das Erzählmuster {term_id} nennt keine Grundhandlung")
        new(term_id, str(entry["name"]), str(entry.get("beschreibung", "")))
        base[parent].append(term_id)

    if base:
        dimensions.append((PATTERN_DIMENSION, "was für eine Geschichte es erzählt"))
        families.extend(
            Family(family_id, names[family_id], tuple(members), terms[family_id].description)
            for family_id, members in base.items()
        )


TEMPLATE = """\
Du legst den Steckbrief eines Buchs an. Er beschreibt, wie sich das Lesen
dieses Buches anfühlt, und gilt für jede Leserin gleich.

Zuerst: Welches Buch ist gemeint? Nenne Titel und Autor so, wie das Buch
wirklich heißt, und bei einer Übersetzung den Originaltitel. Ein Tippfehler im
Namen oder ein deutscher Titel darf dich nicht irreführen. Kennst du das Buch
nicht sicher und liegt kein Text bei, setze "bekannt" auf false und lass alles
andere weg. Liegt ein Klappentext bei, setzt du "bekannt" nie auf false: dann
beschreibst du das Buch nach dem, was dort steht, auch wenn du es nicht kennst.
Verwechsle es nicht mit einem ähnlich klingenden Buch.

Dann die Merkmale. Du wählst sie ausschließlich aus dem Vokabular unten und
gibst ihre id an; neue erfindest du nicht. Eine Leserin wird später sehen,
welche Merkmale du vergeben hast, und auswählen, welche davon sie an diesem Buch
gehalten oder verloren haben. Vergib also die Merkmale, die dieses Buch am
deutlichsten prägen.

Regeln:
- Vier bis acht Merkmale, ohne die Erzählmuster.
- Aus mindestens drei verschiedenen Dimensionen, höchstens drei aus derselben.
  Zähle vor der Antwort nach: hat eine Dimension mehr als drei, lass das mit dem
  geringsten Gewicht weg.
- Erzählmuster gehören nie unter "merkmale", sondern nur unter "erzaehlmuster".
  Was im Vokabular unter "Erzählmuster" steht, ist ein Muster, kein Merkmal.
- Was auf fast jedes Buch seines Genres zutrifft, nimmst du nur, wenn es hier
  deutlich stärker ausgeprägt ist als üblich. Ein Thriller ist nicht schon
  deshalb spannungsgeladen, weil er ein Thriller ist.
- Zu jedem Merkmal schreibst du einen Satz, der zeigt, wo es in DIESEM Buch
  steckt: eine Figur, eine Situation, eine Eigenart. Die Probe: Könnte derselbe
  Satz unter einem anderen Buch stehen, ist er falsch.
- Zu jedem Merkmal nennst du, worauf es beruht: "klappentext" (es steht im
  Text, der beiliegt) oder "wissen" (was du selbst über das Buch weißt). Das
  Wort genügt; zitiere keinen Satz.
- Zu jedem Merkmal nennst du sein "gewicht" in diesem Buch: "praegend" (es
  prägt das ganze Buch, ohne wäre es ein anderes), "deutlich" (es gehört klar
  dazu) oder "rand" (es kommt vor, trägt aber nicht). Meist prägen nur zwei
  oder drei das Buch; wer alles prägend nennt, unterscheidet nichts.
- Nichts erfinden.

Dann die Erzählmuster: was für eine Geschichte das Buch erzählt. Sie stehen
im Vokabular unter "Erzählmuster", jedes eingerückt unter seiner Grundhandlung.
- Ein bis drei, nur was die Geschichte als Ganzes trägt, nicht eine Episode.
- Das genaueste Muster, das zutrifft. Die Grundhandlung selbst vergibst du,
  wenn kein genaueres passt, oder zusätzlich, wenn sie das Buch als Ganzes
  trägt und das genauere Muster nur einen Teil davon.
- Zu jedem Muster ein Satz und ein Beleg wie bei den Merkmalen. Ein Muster
  hat kein Gewicht: es steht nur da, wenn es die Geschichte trägt.
- Ein Muster, das selbst die Wendung ist — etwa eine Erzählstimme, die sich
  erst spät als unzuverlässig erweist —, vergibst du nicht.

Keine Spoiler — die Leserin hat das Buch womöglich noch vor sich:
- Satz und Pitch verraten nichts, was nicht schon der Klappentext oder die
  ersten Seiten preisgeben: keine Wendung, keinen Täter, keinen Tod, kein
  Ende, keine Auflösung eines Rätsels, nicht wie ein Handlungsstrang ausgeht.
- Auch nichts, was die Figuren erst im Lauf der Handlung herausfinden — bei
  einem Krimi etwa, was die Opfer verbindet oder wie der Täter vorgeht.
- Bei einem Band aus einer Reihe auch nichts aus den früheren Bänden, was
  deren Ausgang verrät.
- Im Zweifel beschreibst du, wie es sich liest, statt was geschieht.

Nenne außerdem Genre und Untergenre auf Deutsch, so wie eine Buchhandlung das
Buch einordnen würde.

Und schreib den Pitch: ein bis zwei Sätze, höchstens 180 Zeichen. Zuerst, was
das Buch ist; dann, was es ausmacht. Wähle ein Bild, an dem dieses Buch hängt,
statt es zusammenzufassen. Beschreiben, nicht loben.

--- VOKABULAR ---
{vokabular}
--- ENDE VOKABULAR ---

--- BUCH ---
{buch}
--- ENDE BUCH ---

Antworte ausschließlich mit JSON in genau dieser Form:
{{"bekannt": true, "titel": "...", "autor": "...", "originaltitel": "... oder null",
  "genre": "...", "untergenre": "...", "pitch": "...",
  "merkmale": [{{"id": "...", "satz": "...", "beleg": "...",
                "gewicht": "praegend, deutlich oder rand"}}],
  "erzaehlmuster": [{{"id": "...", "satz": "...", "beleg": "..."}}]}}
"""


def fingerprint(vocabulary: Vocabulary) -> str:
    """Woran man sieht, ob ein gespeicherter Steckbrief noch gilt.

    Je Vokabular einmal gerechnet: dasselbe Vokabular kommt aus dem Zwischen-
    speicher von ``load_vocabulary`` immer als dasselbe Objekt, und der Abdruck
    wird für jedes Buch im Regal gebraucht.
    """
    known = _FINGERPRINTS.get(id(vocabulary))
    if known is not None and known[0] is vocabulary:
        return known[1]
    material = TEMPLATE + vocabulary.prompt_text()
    stamp = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    if len(_FINGERPRINTS) >= 16:
        _FINGERPRINTS.clear()
    # Das Vokabular selbst mit ablegen: so kann seine id nicht an ein anderes
    # Objekt weitergegeben werden, solange der Eintrag lebt.
    _FINGERPRINTS[id(vocabulary)] = (vocabulary, stamp)
    return stamp


_FINGERPRINTS: dict[int, tuple[Vocabulary, str]] = {}


#: Was mit der Leseprobe beiliegt (#76). Im Buchteil, nicht in der festen
#: Anweisung: deren Fingerabdruck entscheidet, ob ein gespeicherter Steckbrief
#: noch gilt, und eine Änderung dort machte jeden alt.
SAMPLE_NOTE = (
    "Leseprobe (der Anfang des Buchs; was du nur aus ihr weißt, belegst du mit "
    '"leseprobe"; auch hier keine Spoiler): '
)
#: Womit ein Merkmal belegt sein darf, wenn eine Leseprobe beilag.
EVIDENCE_WITH_SAMPLE = (*EVIDENCE, "leseprobe")


def prompt(
    title: str,
    author: str | None,
    blurb: str | None,
    vocabulary: Vocabulary,
    sample: str | None = None,
) -> str:
    book = [f"Titel: {title}", f"Autor: {author or '(nicht angegeben)'}"]
    if blurb:
        book.append(f"Klappentext: {blurb}")
    if sample:
        book.append(SAMPLE_NOTE + sample)
    return TEMPLATE.format(vokabular=vocabulary.prompt_text(), buch="\n".join(book))


def _text(value) -> str | None:
    """Ein Feld der Antwort als Text; leer, ``null`` und "null" sind nichts."""
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text.lower() == "null" else text


def _json_object(text: str):
    """Das JSON-Objekt aus einer Modellantwort — mit einer einzigen Nachsicht.

    Das Modell schützt Apostrophe mitunter mit einem Backslash, und das ist in
    JSON kein Escape. Genau diese eine Lesart wird nachgesehen, weil sie keine
    zweite hat. Wer weiter flickt, fängt an zu raten, und dann ist unbewertet
    ehrlicher (ADR 7).

    Gelesen wird das erste vollständige Objekt; was danach kommt, bleibt liegen.
    Ein Hinweis hinter der Antwort kostete sonst den ganzen Steckbrief ("Extra
    data", gemessen am 19.09.2026). Das ist kein Flicken: das Objekt selbst
    bleibt, wie es kam.
    """
    start = text.find("{")
    if start < 0:
        raise PortrayalUnavailable("Antwort enthält kein JSON")
    read = json.JSONDecoder().raw_decode
    try:
        return read(text, start)[0]
    except ValueError as exc:
        try:
            return read(text.replace(r"\'", "'"), start)[0]
        except ValueError:
            raise PortrayalUnavailable(f"Antwort ist kein gültiges JSON: {exc}") from exc


def parse_answer(
    text: str, vocabulary: Vocabulary, evidence: tuple[str, ...] = EVIDENCE
) -> Portrait:
    """Die Antwort des Modells als Steckbrief, mit den Regeln daneben geprüft.

    Ein Merkmal außerhalb des Vokabulars wird nicht übernommen, sondern
    genannt: ein erfundenes Wort könnte keine zwei Bücher je gemeinsam haben.
    Alle anderen Verstöße verwerfen nichts.
    """
    data = _json_object(text)
    if not isinstance(data, dict):
        raise PortrayalUnavailable("Antwort ist kein JSON-Objekt")
    stamp = fingerprint(vocabulary)
    raw = data.get("merkmale") or []
    raw_patterns = data.get("erzaehlmuster") or []

    # Nur ein echtes Ja: "false" als Text ist kein Ja.
    if data.get("bekannt") is not True:
        violations = ("unbekannt, aber Merkmale vergeben",) if raw or raw_patterns else ()
        return Portrait(known=False, fingerprint=stamp, violations=violations)

    traits: list[Trait] = []
    violations: list[str] = []
    # Ein Wort in der falschen Liste wird übernommen und genannt: ob es ein
    # Merkmal oder ein Muster ist, weiß das Vokabular, nicht die Liste.
    for items, expect_pattern in ((raw, False), (raw_patterns, True)):
        for entry in items:
            if not isinstance(entry, dict):
                violations.append("ein Merkmal ohne Form")
                continue
            term_id = str(entry.get("id") or "").strip()
            if term_id not in vocabulary.terms:
                violations.append(f"nicht im Vokabular: {term_id or '(leer)'}")
                continue
            if any(trait.term == term_id for trait in traits):
                violations.append(f"doppelt vergeben: {term_id}")
                continue
            if vocabulary.is_pattern(term_id) != expect_pattern:
                violations.append(f"in der falschen Liste: {term_id}")
            evidence_kind = str(entry.get("beleg") or "").strip()
            if evidence_kind not in evidence:
                violations.append(f"ungültiger Beleg bei {term_id}: {evidence_kind or '(keiner)'}")
            # Ein Gewicht trägt nur ein Merkmal; bei einem Muster wird es nicht
            # gefragt und nicht gelesen (#62). Ein fehlendes oder fremdes Wort
            # steht als Verstoß daneben, das Merkmal bleibt ohne Gewicht.
            weight = None
            if not vocabulary.is_pattern(term_id):
                word = str(entry.get("gewicht") or "").strip()
                weight = WEIGHT_WORDS.get(word)
                if weight is None:
                    violations.append(f"ungültiges Gewicht bei {term_id}: {word or '(keines)'}")
            traits.append(
                Trait(term_id, str(entry.get("satz") or "").strip(), evidence_kind, weight)
            )

    plain_traits = [t for t in traits if not vocabulary.is_pattern(t.term)]
    pattern_count = len(traits) - len(plain_traits)
    if not FEWEST <= len(plain_traits) <= MOST:
        violations.append(f"{len(plain_traits)} Merkmale statt vier bis acht")
    if not FEWEST_PATTERNS <= pattern_count <= MOST_PATTERNS:
        violations.append(f"{pattern_count} Erzählmuster statt eins bis drei")
    dimensions = Counter(vocabulary.terms[trait.term].dimension for trait in plain_traits)
    if plain_traits and len(dimensions) < MIN_DIMENSIONS:
        violations.append(f"nur {len(dimensions)} Dimensionen statt mindestens drei")
    for dimension, count in dimensions.items():
        if count > MOST_PER_DIMENSION:
            violations.append(f"{count} Merkmale aus {dimension}, höchstens drei")

    pitch = _text(data.get("pitch"))
    if pitch is None:
        violations.append("kein Pitch")
    elif len(pitch) > PITCH_MAX:
        violations.append(f"Pitch hat {len(pitch)} Zeichen, höchstens {PITCH_MAX}")

    return Portrait(
        known=True,
        fingerprint=stamp,
        title=_text(data.get("titel")),
        author=_text(data.get("autor")),
        original_title=_text(data.get("originaltitel")),
        genre=_text(data.get("genre")),
        subgenre=_text(data.get("untergenre")),
        pitch=pitch,
        traits=tuple(traits),
        violations=tuple(violations),
    )


def prompt_many(books, vocabulary: Vocabulary) -> str:
    """Eine Anweisung für mehrere Bücher auf einmal (#66).

    Dieselbe Anweisung und dasselbe Vokabular wie bei einem Buch — der
    Fingerabdruck bleibt also derselbe, und ein im Bündel angelegter Steckbrief
    gilt genauso wie ein einzeln angelegter. Vokabular und Regeln gehen einmal
    raus statt je Buch; das sind rund 5500 der rund 6500 Tokens eines Prompts.
    ``books`` sind ``(Titel, Autor:in, Klappentext)``.
    """
    head, rest = TEMPLATE.split("--- BUCH ---", 1)
    shape = rest.split("--- ENDE BUCH ---", 1)[1].format().split("in genau dieser Form:", 1)[1]
    blocks = []
    for number, (title, author, blurb) in enumerate(books, start=1):
        lines = [f"Titel: {title}", f"Autor: {author or '(nicht angegeben)'}"]
        if blurb:
            lines.append(f"Klappentext: {blurb}")
        body = "\n".join(lines)
        blocks.append(f"--- BUCH {number} ---\n{body}\n--- ENDE BUCH {number} ---")
    return (
        head.format(vokabular=vocabulary.prompt_text())
        + f"Es sind {len(blocks)} Bücher. Beschreibe jedes für sich, unabhängig von den anderen; "
        "was du zu einem sagst, darf nichts mit einem anderen zu tun haben.\n\n"
        + "\n\n".join(blocks)
        + "\n\nAntworte ausschließlich mit einem JSON-Objekt, dessen Schlüssel die Nummern der "
        'Bücher sind ("1", "2", …); jeder Wert hat genau diese Form:'
        + shape
    )


def parse_many(text: str, vocabulary: Vocabulary, count: int) -> dict[int, Portrait]:
    """Die Steckbriefe aus einer gebündelten Antwort, nach Nummer.

    Ein Buch, das die Antwort auslässt oder dessen Eintrag krumm ist, fehlt
    einfach: es kostet nur sich selbst, nicht das Bündel. Ganz ohne lesbares
    JSON scheitert das Bündel, aber sauber (``PortrayalUnavailable``).
    """
    data = _json_object(text)
    if not isinstance(data, dict):
        raise PortrayalUnavailable("Antwort ist kein JSON-Objekt")
    portraits: dict[int, Portrait] = {}
    for number in range(1, count + 1):
        entry = data.get(str(number))
        if not isinstance(entry, dict):
            continue
        try:
            portraits[number] = parse_answer(json.dumps(entry, ensure_ascii=False), vocabulary)
        except PortrayalUnavailable:
            continue
    return portraits
