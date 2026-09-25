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
        zeilen = []
        for name, frage in self.dimensions:
            zeilen.append(f"{name} ({frage}):")
            if name == PATTERN_DIMENSION:
                for family in self.families:
                    if not family.members or not self.is_pattern(family.members[0]):
                        continue
                    for index, term_id in enumerate(family.members):
                        term = self.terms[term_id]
                        einzug = "  " if index == 0 else "    "
                        zeilen.append(f"{einzug}{term.id}: {term.name} — {term.description}")
                continue
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


def worth_asking_again(portrait: Portrait, *, text_now: bool) -> bool:
    """Ob ein gespeicherter Steckbrief noch einmal gefragt werden darf.

    Nur ein **unbekanntes** Buch, das ohne Text beschrieben wurde, und nur, wenn
    jetzt einer da ist: ein Watchlist-Titel wird beim Anlegen mit Titel und
    Autor:in allein gefragt, der Klappentext kommt erst mit dem ersten Lauf
    (fünf Bücher am 25.09.2026). Ein „unbekannt“ mit Text bleibt stehen — ein
    zweiter Versuch mit demselben Text brächte dasselbe und kostete einen
    Aufruf. Eine Zeile aus der Zeit vor diesem Vermerk (``None``) gilt als ohne
    Text beschrieben.
    """
    return not portrait.known and portrait.with_text is not True and text_now


def load_vocabulary(path: Path | None = None, patterns: Path | None = None) -> Vocabulary:
    """Das Vokabular, geprüft: jede id einmal, jede Familie mit echten Merkmalen.

    Merkmale und Erzählmuster zusammen; fehlt die Datei der Erzählmuster, gibt
    es eben keine.
    """
    datei = path or VOCABULARY_PATH
    muster = patterns or PATTERNS_PATH
    try:
        text = datei.read_text(encoding="utf-8")
        muster_text = muster.read_text(encoding="utf-8") if muster.exists() else None
    except OSError as exc:
        raise VocabularyError(f"{exc.filename} ist nicht lesbar: {exc}") from exc
    return _parse_vocabulary(text, datei.name, muster_text, muster.name)


@lru_cache(maxsize=8)
def _parse_vocabulary(
    text: str, name: str, muster_text: str | None, muster_name: str
) -> Vocabulary:
    """Geparst wird nur, wenn sich der Inhalt ändert.

    Lesen ist billig, das YAML zweier Dateien mit über tausend Zeilen nicht —
    und gebraucht wird das Vokabular bei jedem Eintrag, jeder Abfrage und
    jedem Buch im Regal. Der Schlüssel ist der Inhalt, nicht die Dateizeit:
    zwei schnelle Änderungen können dieselbe Zeit tragen.
    """
    try:
        daten = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise VocabularyError(f"{name} ist nicht lesbar: {exc}") from exc

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
        beschreibung = str(eintrag.get("beschreibung", "")).strip()
        families.append(Family(str(eintrag["id"]), name, members, beschreibung))

    if muster_text is not None:
        _load_patterns(muster_text, muster_name, terms, families, dimensions)
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
        daten = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise VocabularyError(f"{name} ist nicht lesbar: {exc}") from exc

    familien_ids = {family.id for family in families}

    def neu(term_id: str, name: str, beschreibung: str) -> None:
        if term_id in terms or term_id in familien_ids:
            raise VocabularyError(f"{term_id} steht zweimal im Vokabular")
        terms[term_id] = Term(term_id, name, beschreibung.strip(), PATTERN_DIMENSION)

    grund: dict[str, list[str]] = {}
    namen: dict[str, str] = {}
    for eintrag in daten.get("familien") or []:
        family_id, name = str(eintrag["id"]), str(eintrag["name"])
        neu(family_id, name, str(eintrag.get("beschreibung", "")))
        grund[family_id] = [family_id]
        namen[family_id] = name
    for eintrag in daten.get("muster") or []:
        term_id, familie = str(eintrag["id"]), str(eintrag.get("familie") or "")
        if familie not in grund:
            raise VocabularyError(f"das Erzählmuster {term_id} nennt keine Grundhandlung")
        neu(term_id, str(eintrag["name"]), str(eintrag.get("beschreibung", "")))
        grund[familie].append(term_id)

    if grund:
        dimensions.append((PATTERN_DIMENSION, "was für eine Geschichte es erzählt"))
        families.extend(
            Family(family_id, namen[family_id], tuple(members), terms[family_id].description)
            for family_id, members in grund.items()
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
    bekannt = _FINGERPRINTS.get(id(vocabulary))
    if bekannt is not None and bekannt[0] is vocabulary:
        return bekannt[1]
    stoff = TEMPLATE + vocabulary.prompt_text()
    abdruck = hashlib.sha256(stoff.encode("utf-8")).hexdigest()[:16]
    if len(_FINGERPRINTS) >= 16:
        _FINGERPRINTS.clear()
    # Das Vokabular selbst mit ablegen: so kann seine id nicht an ein anderes
    # Objekt weitergegeben werden, solange der Eintrag lebt.
    _FINGERPRINTS[id(vocabulary)] = (vocabulary, abdruck)
    return abdruck


_FINGERPRINTS: dict[int, tuple[Vocabulary, str]] = {}


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


def parse_answer(text: str, vocabulary: Vocabulary) -> Portrait:
    """Die Antwort des Modells als Steckbrief, mit den Regeln daneben geprüft.

    Ein Merkmal außerhalb des Vokabulars wird nicht übernommen, sondern
    genannt: ein erfundenes Wort könnte keine zwei Bücher je gemeinsam haben.
    Alle anderen Verstöße verwerfen nichts.
    """
    daten = _json_object(text)
    if not isinstance(daten, dict):
        raise PortrayalUnavailable("Antwort ist kein JSON-Objekt")
    abdruck = fingerprint(vocabulary)
    roh = daten.get("merkmale") or []
    roh_muster = daten.get("erzaehlmuster") or []

    # Nur ein echtes Ja: "false" als Text ist kein Ja.
    if daten.get("bekannt") is not True:
        verstoesse = ("unbekannt, aber Merkmale vergeben",) if roh or roh_muster else ()
        return Portrait(known=False, fingerprint=abdruck, violations=verstoesse)

    traits: list[Trait] = []
    verstoesse: list[str] = []
    # Ein Wort in der falschen Liste wird übernommen und genannt: ob es ein
    # Merkmal oder ein Muster ist, weiß das Vokabular, nicht die Liste.
    for liste, soll_muster in ((roh, False), (roh_muster, True)):
        for eintrag in liste:
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
            if vocabulary.is_pattern(term_id) != soll_muster:
                verstoesse.append(f"in der falschen Liste: {term_id}")
            beleg = str(eintrag.get("beleg") or "").strip()
            if beleg not in EVIDENCE:
                verstoesse.append(f"ungültiger Beleg bei {term_id}: {beleg or '(keiner)'}")
            # Ein Gewicht trägt nur ein Merkmal; bei einem Muster wird es nicht
            # gefragt und nicht gelesen (#62). Ein fehlendes oder fremdes Wort
            # steht als Verstoß daneben, das Merkmal bleibt ohne Gewicht.
            gewicht = None
            if not vocabulary.is_pattern(term_id):
                wort = str(eintrag.get("gewicht") or "").strip()
                gewicht = WEIGHT_WORDS.get(wort)
                if gewicht is None:
                    verstoesse.append(f"ungültiges Gewicht bei {term_id}: {wort or '(keines)'}")
            traits.append(
                Trait(term_id, str(eintrag.get("satz") or "").strip(), beleg, gewicht)
            )

    merkmale = [t for t in traits if not vocabulary.is_pattern(t.term)]
    muster = len(traits) - len(merkmale)
    if not FEWEST <= len(merkmale) <= MOST:
        verstoesse.append(f"{len(merkmale)} Merkmale statt vier bis acht")
    if not FEWEST_PATTERNS <= muster <= MOST_PATTERNS:
        verstoesse.append(f"{muster} Erzählmuster statt eins bis drei")
    dimensionen = Counter(vocabulary.terms[trait.term].dimension for trait in merkmale)
    if merkmale and len(dimensionen) < MIN_DIMENSIONS:
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
