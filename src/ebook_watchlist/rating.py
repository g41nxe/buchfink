"""Das Bewertungstor: passt dieses Buch zur Leserin? (ADR 19, Ticket 12)

Zwei Dokumente tragen das (ADR 21): ``docs/leseprofil.md`` sagt, **wonach**
geurteilt wird — die Beschreibung, die die Leserin selbst geschrieben hat,
mitsamt ihrer Version. ``docs/bewertungsschema.md`` sagt, **wie**; es trägt
keine Version, weil eine Änderung am Verfahren kein Urteil über ein Buch falsch
macht.

Ein Buch wird **einmal** beurteilt; ein Lauf, der es wiedersieht, kostet keinen
Aufruf mehr. Erst eine neue Profilversion macht die Urteile ungültig, und das
ist die eine Änderung, bei der das auch richtig ist.

**Das Tor scheitert nie zu.** Kein Schlüssel, kein Netz, eine Absage, eine
unlesbare Antwort: das Buch gilt als unbewertet und wird trotzdem angezeigt. Ein
Tor, das im Zweifel schließt, verschluckt Neuzugänge stillschweigend — das eine
Verhalten, das dieses Werkzeug nicht haben darf (ADR 7, ADR 15).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import requests
import yaml

from .cleaning import is_truncated
from .deductions import deductions_for
from .models import Observation
from .reasons import THEMA, thema_name

LESEPROFIL_PATH = Path(__file__).resolve().parents[2] / "docs" / "leseprofil.yaml"
#: Das Verfahren, getrennt vom Profil (ADR 21). Nicht versioniert: eine
#: Änderung hier entwertet keine gespeicherte Bewertung.
SCHEME_PATH = Path(__file__).resolve().parents[2] / "docs" / "bewertungsschema.yaml"

#: Voreinstellung. Ein beschränktes Urteil gegen ein mitgeliefertes Profil —
#: dafür ist das kleinste Modell das richtige.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
#: Der Schlüssel kommt aus der Umgebung, bewusst und nur von dort (Ticket 20).
#: ADR 6 sieht eine Secrets-Datei für die Bibliothekskennung vor, weil ein Lauf
#: sich dort *anmelden* muss und die Kennung der Leserin gehört. Dieser
#: Schlüssel gehört dem Host, nicht dem Profil: ein Cron-Job setzt ihn, und
#: eine zweite Fundstelle im Datenverzeichnis wäre ein weiterer Ort, an dem ein
#: Geheimnis versehentlich in ein Backup gerät.
KEY_ENV = "ANTHROPIC_API_KEY"

#: Unter wie vielen Sternen ein Vorschlag gar nicht erst erscheint. Großzügig
#: gesetzt, nicht vorsichtig: wenige gut passende Vorschläge schlagen viele
#: unpassende, und ein leerer Stapel ist ein gutes Ergebnis (ADR 19).
DEFAULT_THRESHOLD = 3

#: Worauf ein Urteil ruht. ``vermutet`` heisst nicht "nicht nachgesehen",
#: sondern "nachgesehen und es steht nirgends" (bewertungsschema.md, 3).
BELEGT, TEILS, VERMUTET = "belegt", "teils", "vermutet"

#: Wie das der Leserin gesagt wird. Die gespeicherten Werte bleiben, wie sie
#: sind — sie stehen im Bewertungsschema, im Prompt und in tausend Zeilen der
#: Datenbank. Gezeigt wird ein Wort, das fuer sich steht: "teils" allein neben
#: vier Sternen beantwortet keine Frage, "teilweise belegt" schon.
CONFIDENCE_LABELS: dict[str, str] = {
    BELEGT: "im Text belegt",
    TEILS: "teilweise belegt",
    VERMUTET: "nur vermutet",
}


def confidence_label(confidence: str) -> str:
    """Das Wort fuer die Leserin. Unbekanntes bleibt, wie es ist."""
    return CONFIDENCE_LABELS.get(confidence, confidence)

# Die Herkunft steht in ``ratings`` — der Store braucht sie und darf
# dieses Modul nicht importieren.


class RatingUnavailable(Exception):
    """Es konnte nicht bewertet werden. Kein Fehler des Buches."""


@dataclass(frozen=True, slots=True)
class Rating:
    #: Ganzzahlig bei eigenen Urteilen; fremde Stimmen bringen
    #: Nachkommastellen mit (Ticket 54).
    stars: float
    reason: str
    #: ``belegt`` | ``teils`` | ``vermutet`` — das Schema verlangt sie, weil ein
    #: Urteil über einen 219 Zeichen langen Anriss etwas anderes ist als eines
    #: über ein gelesenes Buch.
    confidence: str
    profile_version: int
    #: Ein Satz für die Leserin: warum das Buch in Frage kommt. Nicht die
    #: Begründung — die ist ein Protokoll zum Nachprüfen und nennt auch, was
    #: fehlt (bewertungsschema.yaml, "pitch").
    pitch: str = ""
    #: Welche Achsen des Leseprofils das Buch trifft und welche es verfehlt —
    #: als Daten, in der Schreibung des Profils (#12). Der Text sagt es in
    #: normalen Worten; die Namen stehen als Marken darueber. Leer bei
    #: Urteilen von vorher.
    hits: tuple[str, ...] = ()
    misses: tuple[str, ...] = ()
    #: Was der Code nach dem Urteil abgezogen hat, je einen Stern (#28), und
    #: die Sterne des Modells davor. ``None``, wo nichts abging.
    deductions: tuple[str, ...] = ()
    model_stars: float | None = None

    def passes(self, threshold: int) -> bool:
        return self.stars >= threshold

    def withholds(self, threshold: int) -> bool:
        """Ob dieses Urteil ein Buch aus dem Digest nehmen darf.

        Ein **vermutetes** Urteil darf das nicht (bewertungsschema.md, 3): ein
        Buch durchzulassen darf auf Ableitung ruhen, eines zu verschweigen
        nicht. Die Asymmetrie ist der Grund — ein zu Unrecht gezeigtes Buch
        kostet eine Zeile, ein zu Unrecht verschwiegenes ist unsichtbar, und
        die Leserin kann den Fehler nie bemerken.
        """
        # Die Regel steht als ``darf_zurueckhalten_ab`` im Schema; hier steht
        # sie ein zweites Mal, damit ``Rating`` das Dokument nicht kennen muss.
        # ``test_the_code_agrees_with_the_scheme_about_withholding`` hält die
        # beiden zusammen.
        return not self.passes(threshold) and self.confidence != VERMUTET


def leseprofil_version(text: str) -> int:
    """Die Fassung, gegen die geurteilt wird.

    Früher stand sie als Zeile "Profilversion: N" in einem Markdown-Dokument
    und wurde per regulärem Ausdruck herausgefischt. Jetzt ist sie ein Feld —
    und eine Datei ohne dieses Feld ist kein Profil, sondern ein Entwurf.
    """
    try:
        version = yaml.safe_load(text)["version"]
    except (yaml.YAMLError, KeyError, TypeError) as exc:
        raise RatingUnavailable(
            "docs/leseprofil.yaml nennt keine Profilversion"
        ) from exc
    return int(version)


def load_leseprofil(path: Path | None = None) -> tuple[str, int]:
    """Das Leseprofil, gerendert für den Prompt, mit seiner Version.

    Gerendert und nicht roh: das Modell bekommt Anweisungen, keine
    Datenstruktur. Was in der Datei ``belegbar_aus: [klappentext]`` heißt, liest
    es als BELEGBAR AUS: klappentext — dieselbe Auskunft, ohne Einrückungstiefe
    und Listenstriche, die Aufmerksamkeit kosten (wie beim Schema).
    """
    target = path or LESEPROFIL_PATH
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RatingUnavailable(f"Leseprofil nicht lesbar: {exc}") from exc
    version = leseprofil_version(text)
    try:
        data = yaml.safe_load(text)
        fuer_das_modell = {k: v for k, v in data.items() if k != "version"}
    except (yaml.YAMLError, AttributeError) as exc:
        raise RatingUnavailable(f"Leseprofil unbrauchbar: {exc}") from exc
    return _render(fuer_das_modell), version


def leseprofil_axes(path: Path | None = None) -> frozenset[str]:
    """Die Namen der Achsen im Leseprofil — woran ein Urteil seine Marken prueft (#12).

    Ein Name, den es hier nicht gibt, ist ein erfundener Bezug, und genau den
    soll das Einlesen fangen.
    """
    target = path or LESEPROFIL_PATH
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        return frozenset(str(achse["name"]).strip() for achse in data.get("achsen") or ())
    except (OSError, yaml.YAMLError, AttributeError, KeyError, TypeError) as exc:
        raise RatingUnavailable(f"Leseprofil unbrauchbar: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Scheme:
    """Das Bewertungsverfahren — für jedes Profil dasselbe (ADR 21).

    ``text`` geht in den Prompt, die übrigen Felder in den Code. Sie standen
    einmal an vier Stellen in Python und einmal als Prosa im Dokument; ein
    fünfter Wert hätte fünf Änderungen gekostet und die Prosa wäre die sechste
    gewesen, die niemand prüft.

    Ohne Version: eine Änderung am Verfahren ist kein Grund, ein Urteil über
    ein Buch für ungültig zu erklären.
    """

    #: Der ganze Dateiinhalt — für Menschen.
    text: str
    #: Nur die Abschnitte, die das Modell etwas angehen.
    prompt_text: str
    min_stars: int
    max_stars: int
    #: Stärkste zuerst.
    confidences: tuple[str, ...]
    #: Ab dieser Stärke darf ein Urteil ein Buch zurückhalten.
    withhold_from: str
    #: Wie lang ein Pitch höchstens sein darf. Steht im Dokument, nicht hier —
    #: sonst gäbe es die Zahl zweimal (#29).
    pitch_max: int = 200
    #: Nur der Pitch-Abschnitt. Die Nachfrage nach einem besseren Satz braucht
    #: weder Leseprofil noch Sternetabelle — und der billigste Teil eines
    #: Prompts ist der, den man weglässt (#29).
    pitch_rules: str = ""

    @property
    def may_withhold(self) -> frozenset[str]:
        cut = self.confidences.index(self.withhold_from)
        return frozenset(self.confidences[: cut + 1])


def _render(value, level: int = 0) -> str:
    """YAML lesbar machen, ohne YAML zu bleiben.

    Das Modell bekommt Anweisungen, keine Datenstruktur: Einrückungstiefe und
    Listenstriche kosten Aufmerksamkeit, die dem Buch fehlt.
    """
    einzug = "  " * level
    if isinstance(value, dict):
        teile = []
        for key, inner in value.items():
            kopf = str(key).replace("_", " ").upper()
            einzeilig = not isinstance(inner, dict | list) and "\n" not in str(inner).strip()
            if einzeilig:
                teile.append(f"{einzug}{kopf}: {str(inner).strip()}")
            else:
                teile.append(f"{einzug}{kopf}\n{_render(inner, level + 1)}")
        return "\n\n".join(teile)
    if isinstance(value, list):
        return "\n".join(f"{einzug}- {_render(item, level + 1).strip()}" for item in value)
    text = str(value).strip()
    return "\n".join(f"{einzug}{line}" if line else "" for line in text.splitlines())


def _for_the_rater(data: dict) -> str:
    """Nur die Abschnitte, die das Dokument selbst dafür vorsieht.

    Die Gegenprobe etwa betrifft die Pflege des Profils und nicht das Urteil
    über ein Buch; sie im Prompt mitzuschicken hiesse, Aufmerksamkeit für etwas
    auszugeben, das der Bewerter gar nicht tun soll.
    """
    wanted = data.get("fuer_den_bewerter") or [k for k in data if k != "fuer_den_bewerter"]
    return _render({key: data[key] for key in wanted if key in data})


def load_rating_scheme(path: Path | None = None) -> Scheme:
    target = path or SCHEME_PATH
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RatingUnavailable(f"Bewertungsschema nicht lesbar: {exc}") from exc
    try:
        data = yaml.safe_load(text)
        sterne = data["sterne"]
        confidence = data["confidence"]
        return Scheme(
            text=text,
            prompt_text=_for_the_rater(data),
            min_stars=int(sterne["von"]),
            max_stars=int(sterne["bis"]),
            confidences=tuple(str(entry["wert"]) for entry in confidence["werte"]),
            withhold_from=str(confidence["darf_zurueckhalten_ab"]),
            pitch_max=int(data["pitch"]["hoechstens_zeichen"]),
            pitch_rules=_render({"pitch": data["pitch"]}),
        )
    except (yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise RatingUnavailable(f"Bewertungsschema unbrauchbar: {exc}") from exc


#: Wieviele Bücher höchstens in einen Aufruf gehen. Profil und Verfahren sind der weitaus
#: größte Teil eines Prompts — das Buch selbst sind ein paar Zeilen —, also spart
#: ein Bündel nicht ein paar Prozent, sondern den Großteil. Zwanzig, weil eine
#: Antwort, die für zwanzig Bücher je eine belegte Begründung liefern soll,
#: lang genug ist.
BATCH_SIZE = 20

# Die frühere Kurzfassung ("erfinde nichts, sonst confidence vermutet") ist
# gefallen: das Verfahren sagt dasselbe ausführlicher und genauer, und zwei
# Fassungen derselben Regel in einem Prompt sind schlechter als eine.
_HOW_TO_ANSWER = "Kein Text außerhalb des JSON."


def _answer_shape(scheme: Scheme) -> str:
    """Die geforderte Antwortform — Spanne und Werte aus dem Schema.

    Ausgeschrieben standen sie hier zweimal und in der Prüfung ein drittes Mal.
    Ein vierter ``confidence``-Wert im Dokument hätte drei Stellen in Python
    gekostet, die niemand mit dem Dokument abgleicht.
    """
    return (
        f'{{"stars": <{scheme.min_stars}-{scheme.max_stars}>, '
        f'"confidence": "{"|".join(scheme.confidences)}", '
        '"reason": "<hoechstens drei Saetze in normalen Worten, ohne Achsennamen>", '
        '"pitch": "<ein Satz für die Leserin: warum dieses Buch für sie in Frage kommt>", '
        '"trifft": ["<Name einer Achse des Leseprofils>", ...], '
        '"fehlt": ["<Name einer Achse des Leseprofils>", ...]}'
    )


def _facts(observation: Observation) -> list[str]:
    """Die *öffentlichen* Angaben zu einem Buch — mehr nicht.

    Keine Watchlist, kein Besitz, keine Identität der Leserin (ADR 19). Eine
    Stelle, damit Einzel- und Bündelprompt nicht auseinanderlaufen.
    """
    facts = [f"Titel: {observation.title}"]
    if observation.subtitle:
        facts.append(f"Untertitel: {observation.subtitle}")
    if observation.original_title:
        facts.append(f"Originaltitel: {observation.original_title}")
    if observation.publisher:
        # Eine Angabe wie jede andere. Den Abzug fuer Selbstverlag macht der
        # Code nach dem Urteil (#28) — hier stuende er doppelt.
        facts.append(f"Verlag: {observation.publisher}")
    facts.append(f"Autor:in: {observation.author or 'unbekannt'}")
    if observation.series:
        facts.append(f"Reihe: {observation.series}")
    if observation.category:
        # "Thema", nicht "Regal des Shops": das Wort, das die Leserin sieht, ist
        # auch hier das richtige — und der lesbare Name sagt dem Modell mehr als
        # ein Pfad aus dem Shop (Ticket 14, Ticket 20).
        facts.append(f"{THEMA}: {thema_name(observation.category)}")
    if observation.price_cents is not None:
        facts.append(f"Preis: {observation.price_cents / 100:.2f} EUR")
    if observation.blurb:
        # Nicht mehr "vom Shop": seit Ticket 56 liefert auch die Bibliothek einen
        # Klappentext, und dem Modell eine falsche Herkunft zu nennen ist
        # schlimmer, als die Herkunft wegzulassen.
        cut = " (von der Quelle abgeschnitten)" if is_truncated(observation.blurb) else ""
        facts.append(f"Klappentext{cut}: {observation.blurb}")
    if observation.keywords:
        # Von Verlag und Shop: Motive und Vergleichstitel, die weder Titel
        # noch Klappentext nennen (#17).
        facts.append(f"Schlagwörter: {', '.join(observation.keywords)}")
    if observation.sample:
        facts.append(
            "Leseprobe (der Anfang des Buchs selbst, kein Werbetext):\n"
            f"<<<\n{observation.sample}\n>>>"
        )
    else:
        # Ausdruecklich gesagt: ein Modell liest ein Fehlen nicht mit.
        facts.append("Leseprobe: keine Leseprobe vorhanden")
    return facts


def prompt_for(observation: Observation, leseprofil: str, scheme: Scheme) -> str:
    """Was das Modell zu einem einzelnen Buch zu sehen bekommt.

    Dass der Klappentext abgeschnitten ist, wird ausdrücklich gesagt. Ein Modell,
    das nicht weiß, wie dünn seine Grundlage ist, gibt zu sichere Urteile ab.
    """
    facts = _facts(observation)

    return (
        "Du bewertest ein Buch. Das VERFAHREN sagt, wie zu urteilen ist; das "
        "LESEPROFIL sagt, wonach. Halte dich an beides.\n\n"
        f"--- VERFAHREN ---\n{scheme.prompt_text}\n--- ENDE VERFAHREN ---\n\n"
        f"--- LESEPROFIL ---\n{leseprofil}\n--- ENDE LESEPROFIL ---\n\n"
        f"--- BUCH ---\n" + "\n".join(facts) + "\n--- ENDE BUCH ---\n\n"
        "Antworte ausschließlich mit JSON in genau dieser Form:\n"
        + _answer_shape(scheme)
        + "\n\n"
        + _HOW_TO_ANSWER
    )


def prompt_for_many(
    observations: Sequence[Observation], leseprofil: str, scheme: Scheme
) -> str:
    """Ein Aufruf für mehrere Bücher.

    Verfahren und Profil gehen einmal raus statt einmal je Buch — sie sind der
    weitaus größte Teil des Prompts. Jedes Buch bekommt eine Nummer, und die Antwort
    wird darüber zugeordnet: ohne Kennung liesse sich eine Antwort, die ein Buch
    auslässt oder umsortiert, nicht mehr sicher zuordnen.
    """
    blocks = [
        f"--- BUCH {number} ---\n" + "\n".join(_facts(observation))
        for number, observation in enumerate(observations, start=1)
    ]

    return (
        f"Du bewertest {len(observations)} Bücher. Das VERFAHREN sagt, wie zu "
        "urteilen ist; das LESEPROFIL sagt, wonach. Halte dich an beides. "
        "Beurteile jedes Buch für sich; die Reihenfolge sagt nichts über seine "
        "Passung.\n\n"
        f"--- VERFAHREN ---\n{scheme.prompt_text}\n--- ENDE VERFAHREN ---\n\n"
        f"--- LESEPROFIL ---\n{leseprofil}\n--- ENDE LESEPROFIL ---\n\n"
        + "\n\n".join(blocks)
        + "\n--- ENDE BÜCHER ---\n\n"
        "Antworte ausschließlich mit JSON in genau dieser Form, mit der Nummer "
        "des Buches als Schlüssel:\n"
        '{"1": ' + _answer_shape(scheme) + ', "2": {…}}\n\n'
        + _HOW_TO_ANSWER
    )


def _json_object(text: str):
    """Das JSON-Objekt aus einer Modellantwort — mit einer einzigen Nachsicht.

    Das Modell schuetzt Apostrophe in seiner Begruendung mitunter mit einem
    Backslash, und das ist in JSON kein Escape. Gemessen an einem echten
    Urteil ueber "Das Knochenband": fuenf Felder, richtige Sterne, tadellose
    Begruendung — und es kostete das ganze Urteil, im Lauf still als "ohne
    Urteil".

    Genau diese eine Lesart wird nachgesehen, weil sie keine zweite hat. Wer
    weiter flickt, faengt an zu raten, und dann ist unbewertet ehrlicher
    (ADR 7).
    """
    # Gelesen wird das erste vollstaendige Objekt; was danach kommt, bleibt
    # liegen. Ein Hinweis hinter der Antwort kostete sonst das ganze Urteil
    # ("Extra data", gemessen am 2026-09-19). Das ist kein Flicken: das Objekt
    # selbst bleibt, wie es kam.
    anfang = text.find("{")
    if anfang < 0:
        raise RatingUnavailable("Antwort enthält kein JSON")
    lesen = json.JSONDecoder().raw_decode
    try:
        return lesen(text, anfang)[0]
    except ValueError as exc:
        try:
            return lesen(text.replace(r"\'", "'"), anfang)[0]
        except ValueError:
            raise RatingUnavailable(f"Antwort ist kein gültiges JSON: {exc}") from exc


def parse_many(
    text: str,
    observations: Sequence[Observation],
    version: int,
    scheme: Scheme,
    *,
    axes: Collection[str] | None = None,
) -> dict[tuple[str, str], Rating]:
    """Die Antwort auf ein Bündel, buchweise gelesen.

    **Ein unbrauchbarer Eintrag kostet ein Buch, nicht das Bündel.** Ohne das
    machte eine einzige krumme Zeile zwanzig Bücher unbewertet — der Sinn der
    Bündelung wäre dahin, und der Schaden wäre zwanzigmal so groß wie beim
    Einzelaufruf.

    Was fehlt, fehlt: der Aufrufer behandelt jedes Buch ohne Urteil als
    unbewertet und zeigt es trotzdem.
    """
    data = _json_object(text)
    if not isinstance(data, dict):
        raise RatingUnavailable("Antwort ist kein Objekt mit Buchnummern")

    ratings: dict[tuple[str, str], Rating] = {}
    for number, observation in enumerate(observations, start=1):
        entry = data.get(str(number))
        if not isinstance(entry, dict):
            continue
        try:
            ratings[observation.key] = parse_answer(
                json.dumps(entry),
                version,
                scheme,
                axes=axes,
                had_sample=bool(observation.sample),
                publisher=observation.publisher,
            )
        except RatingUnavailable:
            continue
    return ratings


def _axis_list(data: dict, key: str, axes: Collection[str] | None) -> tuple[str, ...]:
    """Eine Achsenliste aus der Antwort, in der Schreibung des Profils."""
    roh = data.get(key) or []
    if not isinstance(roh, list):
        raise RatingUnavailable(f"'{key}' ist keine Liste")
    if axes is None:
        return tuple(str(name).strip() for name in roh if str(name).strip())
    nach_klein = {name.casefold(): name for name in axes}
    gefunden = []
    for name in roh:
        profil = nach_klein.get(str(name).strip().casefold())
        if profil is None:
            raise RatingUnavailable(f"unbekannte Achse {name!r} unter '{key}'")
        gefunden.append(profil)
    return tuple(dict.fromkeys(gefunden))


def parse_answer(
    text: str,
    version: int,
    scheme: Scheme,
    *,
    axes: Collection[str] | None = None,
    had_sample: bool = False,
    publisher: str | None = None,
) -> Rating:
    """Die Antwort des Modells, streng gelesen.

    Eine unlesbare Antwort ist kein Anlass zu raten: sie fuehrt dazu, dass das
    Buch unbewertet bleibt und trotzdem erscheint.

    Drei Proben an den Achsen (#12), und jede verwirft das ganze Urteil statt
    es milde zu lesen — ein falscher Name, der still verschwindet, liesse
    niemanden mehr etwas pruefen:

    * ein Achsenname, den es im Leseprofil nicht gibt,
    * fuenf Sterne und trotzdem ein Eintrag unter ``fehlt``,
    * drei oder mehr Sterne und kein einziger Eintrag unter ``trifft``.

    ``axes`` sind die Namen aus dem Leseprofil. Ohne sie wird die erste Probe
    uebersprungen — gebraucht fuer Tests, die kein Profil laden.

    Die staerkste Gewissheit braucht die Leseprobe (#17). Klappentext und
    Schlagwoerter versprechen, was das Buch vielleicht nicht haelt; wer nur
    sie hatte, wird eine Stufe herabgesetzt statt verworfen — ``had_sample``
    sagt, ob das Buch eine hatte.

    Zuletzt die Abzuege (#28), je einen Stern: erst nach den Proben, denn die
    pruefen, ob das Modell sich selbst widerspricht, und das tut es an seinen
    eigenen Sternen.
    """
    data = _json_object(text)

    try:
        stars = int(data["stars"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RatingUnavailable("Antwort nennt keine Sterne") from exc
    if not scheme.min_stars <= stars <= scheme.max_stars:
        raise RatingUnavailable(
            f"Sterne außerhalb {scheme.min_stars}-{scheme.max_stars}: {stars}"
        )

    confidence = str(data.get("confidence", "")).strip().lower()
    if confidence not in scheme.confidences:
        raise RatingUnavailable(f"unbekannte confidence {confidence!r}")
    if not had_sample and confidence == scheme.confidences[0] and len(scheme.confidences) > 1:
        confidence = scheme.confidences[1]

    reason = str(data.get("reason", "")).strip()
    if not reason:
        raise RatingUnavailable("Antwort nennt keine Begründung")

    hits = _axis_list(data, "trifft", axes)
    misses = _axis_list(data, "fehlt", axes)
    if stars == scheme.max_stars and misses:
        raise RatingUnavailable("fünf Sterne und trotzdem etwas unter 'fehlt'")
    if stars >= 3 and not hits:
        raise RatingUnavailable("drei oder mehr Sterne und nichts unter 'trifft'")

    # Ein fehlender Pitch kostet nicht das ganze Urteil: die Sterne und die
    # Begründung tragen für sich, und ein Buch deswegen unbewertet zu lassen
    # wäre teurer als eine leere Zeile im Digest.
    # Wo nichts mehr abgeht, wird auch nichts verbucht.
    abzuege = deductions_for(publisher) if stars > scheme.min_stars else ()
    return Rating(
        stars=max(scheme.min_stars, stars - len(abzuege)),
        reason=reason,
        confidence=confidence,
        profile_version=version,
        pitch=str(data.get("pitch", "")).strip(),
        hits=hits,
        misses=misses,
        deductions=abzuege,
        model_stars=stars if abzuege else None,
    )


#: Eine Sternzahl im Pitch — die steht daneben und gehört nicht in den Satz.
#: ``fuenf`` steht mit drin, weil ein Modell gelegentlich ohne Umlaut schreibt.
_PITCH_STARS = re.compile(
    r"\b(null|eins?|zwei|drei|vier|f(ue|[uü])nf|[0-5])\s+(von\s+f(ue|[uü])nf|Stern)", re.I
)
#: Das Wort, an dem die Schablone haengt: "…, wo das Profil Härte verlangt".
_PITCH_PROFILE = re.compile(r"\bprofil", re.I)


def pitch_trouble(pitch: str, scheme: Scheme) -> str | None:
    """Woran ein Pitch gegen das Verfahren verstößt — oder ``None`` (#29).

    Nur, was sich eindeutig erkennen lässt. Achsennamen stehen bewusst nicht
    darunter, obwohl das Verfahren sie verbietet: "Enge" und "Tempo" sind
    Namen *und* gewöhnliche Wörter, und der beste Pitch im ganzen Bestand
    enthielt beide. Eine Probe, die gute Sätze verwirft, ist schlechter als
    keine.

    Gemessen an 132 Urteilen traf "Profil" einunddreißig, eine Sternzahl und
    die Länge keines — die beiden letzten sind Wächter, nicht Fallen.
    """
    if not pitch:
        return None
    if _PITCH_PROFILE.search(pitch):
        return "er redet vom Profil statt vom Buch"
    if _PITCH_STARS.search(pitch):
        return "er nennt eine Sternzahl, und die steht schon daneben"
    if len(pitch) > scheme.pitch_max:
        return f"er ist {len(pitch)} Zeichen lang, erlaubt sind {scheme.pitch_max}"
    return None


def pitch_prompt(observation: Observation, scheme: Scheme, pitch: str, trouble: str) -> str:
    """Die Nachfrage nach einem besseren Satz.

    Ohne Leseprofil und ohne Sternetabelle: das Urteil steht ja schon, und
    gebraucht wird nur ein Satz über dieses Buch. Der teure Teil eines
    Prompts ist damit weg.
    """
    return (
        "Du hast dieses Buch schon beurteilt. Nur der eine Satz für die "
        "Leserin — der Pitch — muss neu, denn " + trouble + ".\n\n"
        f"--- SO SOLL ER SEIN ---\n{scheme.pitch_rules}\n--- ENDE ---\n\n"
        "--- BUCH ---\n" + "\n".join(_facts(observation)) + "\n--- ENDE BUCH ---\n\n"
        f"Dein bisheriger Satz war:\n{pitch}\n\n"
        "Antworte mit dem neuen Satz und sonst nichts — keine "
        "Anführungszeichen, keine Erklärung, kein JSON."
    )


def _one_line(text: str) -> str:
    """Die erste Zeile mit Inhalt, ohne Anführungszeichen drumherum."""
    for line in text.splitlines():
        line = line.strip().strip('"').strip("'").strip()
        if line:
            return line
    return ""


def with_better_pitch(
    rating: Rating,
    observation: Observation,
    ask: Callable[[str, int], str],
    scheme: Scheme,
) -> Rating:
    """Einmal nachfragen, wenn der Pitch gegen das Verfahren verstößt (#29).

    **Genau einmal, und was zurückkommt, gilt** — auch wenn es wieder
    verstößt. Lieber ein schwacher Satz als eine leere Zeile: das Verfahren
    sagt selbst "es gibt immer einen Pitch", und in der Liste steht sonst
    nichts über das Buch. Aus demselben Grund kostet ein misslungener zweiter
    Versuch nichts: dann bleibt der erste stehen (ADR 7).

    Sterne und Begründung werden nicht angefasst. Sie waren in Ordnung — die
    Probe gilt einem Satz, nicht dem Urteil.
    """
    trouble = pitch_trouble(rating.pitch, scheme)
    if trouble is None:
        return rating
    try:
        neu = _one_line(ask(pitch_prompt(observation, scheme, rating.pitch, trouble), 200))
    except RatingUnavailable:
        return rating
    return replace(rating, pitch=neu) if neu else rating


class Rater(Protocol):
    """Was der Lauf braucht. Absichtlich klein, damit ein Stub genügt."""

    def rate(self, observation: Observation) -> Rating: ...


def rate_in_batches(
    rater: Rater, observations: Sequence[Observation], *, size: int = BATCH_SIZE
) -> dict[tuple[str, str], Rating]:
    """Bücher bündelweise beurteilen — die eine Stelle, die das Tor benutzt.

    Ein Bewerter, der ``rate_many`` anbietet, wird gebündelt gefragt; wer nur
    ``rate`` kann, wird einzeln gefragt. So bleibt der HTTP-Weg, bei dem ein
    Aufruf fast nichts kostet, unverändert.

    Was nicht zurückkommt, fehlt einfach: der Aufrufer behandelt jedes Buch ohne
    Urteil als unbewertet und zeigt es trotzdem. Auch ein ganzes Bündel, das
    scheitert, kostet deshalb kein einziges Buch die Anzeige.
    """
    ratings: dict[tuple[str, str], Rating] = {}
    many = getattr(rater, "rate_many", None)
    for start in range(0, len(observations), size):
        chunk = list(observations[start : start + size])
        if many is not None:
            try:
                ratings.update(many(chunk))
            except RatingUnavailable as exc:
                # Genannt, nicht verschluckt: ein Buendel, das scheitert,
                # kostet drei Urteile, und ohne den Grund steht spaeter nur
                # "ohne Urteil" da — das sah nach einer Eigenart des Modells
                # aus und war eine abgelaufene Anmeldung.
                print(f"  Buendel ohne Urteil: {exc}", file=sys.stderr)
                continue
            continue
        for observation in chunk:
            try:
                ratings[observation.key] = rater.rate(observation)
            except RatingUnavailable as exc:
                print(f"  {observation.title[:44]}: {exc}", file=sys.stderr)
                continue
    return ratings


@dataclass(slots=True)
class ModelRater:
    """Fragt ein Modell. Keine eigene Bibliothek — die Messages-API ist ein POST."""

    api_key: str
    model: str = DEFAULT_MODEL
    timeout: float = 30.0
    leseprofil: str = ""
    scheme: Scheme | None = None
    version: int = 0
    #: Die Achsennamen des Leseprofils, gegen die ein Urteil geprueft wird (#12).
    axes: frozenset[str] | None = None
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if not self.leseprofil:
            self.leseprofil, self.version = load_leseprofil()
            # Nur mit dem Profil aus der Datei: wer ein eigenes hereinreicht
            # (Tests), bringt keine Achsen mit, und die Namensprobe entfaellt.
            self.axes = leseprofil_axes()
        if self.scheme is None:
            self.scheme = load_rating_scheme()
        if self.session is None:
            self.session = requests.Session()

    def rate(self, observation: Observation) -> Rating:
        rating = parse_answer(
            self.ask(prompt_for(observation, self.leseprofil, self.scheme)),
            self.version,
            self.scheme,
            axes=self.axes,
            had_sample=bool(observation.sample),
            publisher=observation.publisher,
        )
        return with_better_pitch(rating, observation, self.ask, self.scheme)

    def ask(self, prompt: str, max_tokens: int = 300) -> str:
        """Eine Frage, eine Antwort — ohne Leseprofil und ohne Schema.

        Herausgeloest, damit derselbe Weg zum Modell auch fuer etwas anderes
        als ein Urteil taugt: die Baende einer Sammelausgabe wiederzuerkennen
        ist keine Bewertung (ADR 24).
        """
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        try:
            response = self.session.post(
                API_URL, json=payload, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise RatingUnavailable(f"Modell nicht erreichbar: {exc}") from exc
        if response.status_code != 200:
            raise RatingUnavailable(f"Modell antwortete {response.status_code}")
        try:
            blocks = response.json()["content"]
            text = "".join(block.get("text", "") for block in blocks)
        except (ValueError, KeyError, TypeError) as exc:
            raise RatingUnavailable(f"unerwartete Antwortform: {exc}") from exc
        return text


#: Der Weg ohne Schlüssel: Claude Code hat bereits eine Anmeldung, und ``-p``
#: führt genau einen Auftrag aus und beendet sich. Es gibt kein Abo-Guthaben
#: für die API (die Console rechnet getrennt ab), also ist das für ein privates
#: Werkzeug auf dem eigenen Rechner der naheliegende Weg. Die Leserin hat
#: bestätigt, dass sie das so nutzen darf.
CLI_NAME = "claude"
#: Ein Buendel von zwanzig braucht laenger als ein einzelnes Buch — die 34
#: Sekunden einer Einzelmessung sind fast ganz Startkosten, aber die Denkzeit
#: waechst mit jedem Buch. Grosszuegig, weil eine Zeitueberschreitung hier das
#: ganze Buendel unbewertet macht.
CLI_TIMEOUT = 300.0


@dataclass(slots=True)
class ClaudeCodeRater:
    """Fragt die lokal angemeldete Claude-Code-Installation statt der API.

    Kein Schlüssel, kein Guthaben, keine zweite Anmeldung. Dafür ein
    Unterprozess je Buch, und der ist **teuer**: eine Messung an einem echten
    Titel ergab 34 Sekunden — gegenüber wenigen Sekunden für einen POST.

    Das ist tragbar, weil vor dem Tor schon die Preisregel steht: es sieht nur,
    was ohnehin gemeldet würde, und jedes Buch wird genau einmal beurteilt. Der
    Alltag sind einzelne Titel, nicht vierzig — ``rating_budget`` ist die Bremse
    gegen den einmaligen Rückstand, keine Tageserwartung. Genau dieser Rückstand
    ist aber der Fall, in dem der Unterschied weh tut: wer ihn zügig abarbeiten
    will, setzt einen Schlüssel.

    ``--output-format json`` liefert eine Hülle mit dem Ergebnis in ``result``;
    kommt sie nicht, wird die rohe Ausgabe gelesen. Beides landet in derselben
    Auswertung wie die API-Antwort, damit es nur *eine* Stelle gibt, die eine
    Antwort in Sterne übersetzt.
    """

    executable: str = CLI_NAME
    timeout: float = CLI_TIMEOUT
    leseprofil: str = ""
    scheme: Scheme | None = None
    version: int = 0
    #: Die Achsennamen des Leseprofils, gegen die ein Urteil geprueft wird (#12).
    axes: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not self.leseprofil:
            self.leseprofil, self.version = load_leseprofil()
            # Nur mit dem Profil aus der Datei: wer ein eigenes hereinreicht
            # (Tests), bringt keine Achsen mit, und die Namensprobe entfaellt.
            self.axes = leseprofil_axes()
        if self.scheme is None:
            self.scheme = load_rating_scheme()

    def rate(self, observation: Observation) -> Rating:
        prompt = prompt_for(observation, self.leseprofil, self.scheme)
        rating = parse_answer(
            self._ask(prompt),
            self.version,
            self.scheme,
            axes=self.axes,
            had_sample=bool(observation.sample),
            publisher=observation.publisher,
        )
        return with_better_pitch(rating, observation, self.ask, self.scheme)

    def rate_many(
        self, observations: Sequence[Observation]
    ) -> dict[tuple[str, str], Rating]:
        """Ein Aufruf für bis zu :data:`BATCH_SIZE` Bücher.

        Der eigentliche Gewinn: Profil und Verfahren gehen einmal raus statt je
        Buch. Die 34 Sekunden eines Aufrufs sind zudem fast ganz Startkosten
        des Unterprozesses, nicht Denkzeit — zwanzig Bücher kosten kaum mehr
        als eines.
        """
        if not observations:
            return {}
        answer = self._ask(prompt_for_many(observations, self.leseprofil, self.scheme))
        ratings = parse_many(answer, observations, self.version, self.scheme, axes=self.axes)
        # Die Nachfrage gilt je Buch, nicht je Buendel: sie kostet einen
        # kurzen Aufruf fuer den einen Satz, und nur dort, wo er verstoesst.
        zu_buch = {(o.source, o.source_item_id): o for o in observations}
        return {
            key: with_better_pitch(rating, zu_buch[key], self.ask, self.scheme)
            if key in zu_buch
            else rating
            for key, rating in ratings.items()
        }

    def ask(self, prompt: str, max_tokens: int = 300) -> str:
        """Siehe :meth:`ModelRater.ask` — derselbe Weg, andere Leitung.

        ``max_tokens`` steht nur der Form halber in der Signatur: die CLI
        kennt keine solche Grenze.
        """
        return self._ask(prompt)

    def _ask(self, prompt: str) -> str:
        # Der Prompt geht ueber stdin, nicht als Argument: Windows begrenzt
        # eine Kommandozeile auf 32767 Zeichen, und ein Buendel aus Profil,
        # Verfahren und drei ganzen Klappentexten liegt darueber. Python
        # meldete das als FileNotFoundError — woraus hier "claude nicht
        # gefunden" wurde, und zwoelf Buecher fielen mit dieser falschen
        # Begruendung aus dem Lauf.
        command = [self.executable, "-p", "--output-format", "json"]
        # Kein Fenster: die Oberflaeche holt ein Urteil im Hintergrund, und
        # unter Windows blitzte dabei jedes Mal eine Konsole auf.
        ohne_fenster = (
            {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        )
        try:
            completed = subprocess.run(  # noqa: S603 - fester Befehl, kein Shell
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                **ohne_fenster,
            )
        except FileNotFoundError as exc:
            raise RatingUnavailable(f"{self.executable} nicht gefunden") from exc
        except subprocess.TimeoutExpired as exc:
            raise RatingUnavailable(
                f"{self.executable} antwortete nicht in {self.timeout}s"
            ) from exc
        if completed.returncode != 0:
            # Die Huelle nennt den Grund auch dann noch, wenn der Rueckgabewert
            # schon Alarm schlaegt — und sie ist die einzige, die ihn nennt:
            # "Not logged in · Please run /login" stand in stdout, stderr blieb
            # leer, und uebrig blieb die nichtssagende Zeile "claude endete mit
            # 1". Wirft sie nicht, faellt es auf die Zeile darunter zurueck.
            _cli_text(completed.stdout)
            detail = (completed.stderr or "").strip().splitlines()
            raise RatingUnavailable(
                f"{self.executable} endete mit {completed.returncode}"
                + (f": {detail[-1]}" if detail else "")
            )
        return _cli_text(completed.stdout)


def _cli_text(stdout: str) -> str:
    """Die Antwort aus der JSON-Hülle — oder die rohe Ausgabe.

    Die Hülle kann sich ändern; auf ihr Format zu bestehen hiesse, an einer
    fremden Version zu hängen. Fehlt sie oder sieht sie anders aus, geht der
    Text unverändert weiter und ``parse_answer`` sucht sich das JSON darin.

    Eine Ausnahme: die Hülle sagt selbst, wenn etwas schiefging — dann steht in
    ``result`` **die Fehlermeldung** und nicht die Antwort. Ohne diese Prüfung
    wanderte "Failed to authenticate: OAuth session expired" als vermeintliches
    Urteil weiter und scheiterte erst zwei Schritte später an "enthält kein
    JSON". Gemessen an einer abgelaufenen Anmeldung, die genau so aussah — und
    der Rückgabewert war dabei **null**.
    """
    try:
        envelope = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout
    if isinstance(envelope, dict):
        result = envelope.get("result")
        if envelope.get("is_error"):
            grund = result if isinstance(result, str) and result else "ohne Angabe"
            raise RatingUnavailable(f"Claude Code meldet einen Fehler: {grund}")
        if isinstance(result, str):
            return result
    return stdout


def build_rater(model: str | None = None) -> Rater | None:
    """Der Bewerter, falls einer möglich ist — sonst ``None``.

    Zwei Wege, in dieser Reihenfolge:

    1. **Ein API-Schlüssel in der Umgebung.** Schneller, weil ein POST statt
       eines Unterprozesses, und der Weg für einen Rechner ohne Claude Code.
    2. **Die lokal angemeldete Claude-Code-Installation** über ``claude -p``.
       Kein Schlüssel, kein zusätzliches Guthaben — API-Zugang ist in keinem
       Claude-Abo enthalten, die Console rechnet getrennt ab.

    Der Schlüssel geht vor, wo beides da ist: wer ihn setzt, hat sich für ihn
    entschieden. Ist keiner von beiden verfügbar, ist das **kein Fehler**,
    sondern der Zustand ohne Tor — alles bleibt unbewertet und wird gezeigt.
    """
    try:
        leseprofil, version = load_leseprofil()
        scheme = load_rating_scheme()
        # Ausdruecklich mit: wer das Profil hereinreicht, bekommt sonst keine
        # Achsen, und die Namensprobe aus #12 lief nie.
        axes = leseprofil_axes()
    except RatingUnavailable:
        return None

    key = os.environ.get(KEY_ENV)
    if key:
        return ModelRater(
            api_key=key,
            model=model or DEFAULT_MODEL,
            leseprofil=leseprofil,
            scheme=scheme,
            version=version,
            axes=axes,
        )

    executable = shutil.which(CLI_NAME)
    if executable:
        return ClaudeCodeRater(
            executable=executable,
            leseprofil=leseprofil,
            scheme=scheme,
            version=version,
            axes=axes,
        )
    return None
