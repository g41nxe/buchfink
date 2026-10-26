"""Der Steckbrief-Ersteller: beschreibt ein Buch mit dem festen Vokabular (ADR 33, #52).

Ein Modell sieht jedes Buch genau einmal und vergibt Merkmale; alles Weitere
rechnet der Code. Der ``Portrayer`` ist die eine Stelle, die dafür ein Modell
fragt: Buch hinein, ``Portrait`` heraus. Das Vokabular, die Anweisung und das
Lesen der Antwort stehen in :mod:`portrait`; wie der Text zum Modell kommt, ist
das Innenleben dieses Moduls — über die API oder über die lokal angemeldete
Claude-Code-Installation.

**Das Tor scheitert nie zu.** Kein Schlüssel, kein Netz, eine Absage, eine
unlesbare Antwort: das Buch bleibt unbeschrieben und wird trotzdem angezeigt. Ein
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from ..models import Observation
from .portrait import (
    ANSWER_SCHEMA,
    EVIDENCE,
    EVIDENCE_WITH_SAMPLE,
    MAX_TOKENS,
    Parts,
    Portrait,
    PortrayalUnavailable,
    Vocabulary,
    many_schema,
    parse_answer,
    parse_many,
    prompt,
    prompt_many,
    prompt_many_parts,
    prompt_parts,
)

#: Voreinstellung: eine beschränkte Aufgabe gegen ein mitgeliefertes Vokabular,
#: dafür ist das kleinste Modell das richtige. Haiku 5.5 statt 4.5 (#102):
#: ein Zehntel des Preises (0,10 $ / 0,50 $ je Million Tokens bis 100 000
#: Tokens Anweisung) und besser im Befolgen von Regeln. Es denkt von selbst;
#: wie viel, sagt ``EFFORT`` — ein festes Denkbudget lehnt es ab.
DEFAULT_MODEL = "claude-haiku-5-5"
#: Mittel ist die Voreinstellung des Modells; ausdrücklich gesetzt, damit ein
#: anderes Modell nicht still anders denkt.
EFFORT = "medium"
#: Platz für Denken *und* Antwort: das Denken zählt mit, und ein zu knapper
#: Deckel schnitte den Steckbrief ab.
API_MAX_TOKENS = 16_000
#: Wie oft der Stand eines Batches erfragt wird, und wie lange höchstens.
BATCH_POLL_SECONDS = 30
BATCH_GIVE_UP_SECONDS = 2 * 60 * 60
#: Der Schlüssel kommt aus der Umgebung, bewusst und nur von dort (Ticket 20).
#: ADR 6 sieht eine Secrets-Datei für die Bibliothekskennung vor, weil ein Lauf
#: sich dort *anmelden* muss und die Kennung der Leserin gehört. Dieser
#: Schlüssel gehört dem Host, nicht dem Profil: ein Cron-Job setzt ihn, und
#: eine zweite Fundstelle im Datenverzeichnis wäre ein weiterer Ort, an dem ein
#: Geheimnis versehentlich in ein Backup gerät.
KEY_ENV = "ANTHROPIC_API_KEY"

#: Der Weg ohne Schlüssel: Claude Code hat bereits eine Anmeldung, und ``-p``
#: führt genau einen Auftrag aus und beendet sich. Es gibt kein Abo-Guthaben
#: für die API (die Console rechnet getrennt ab), also ist das für ein privates
#: Werkzeug auf dem eigenen Rechner der naheliegende Weg.
CLI_NAME = "claude"
CLI_TIMEOUT = 300.0
#: Der Alias, den die CLI auflöst: dasselbe kleine Modell wie auf dem API-Weg.
CLI_DEFAULT_MODEL = "haiku"
#: Wie viel das Modell vor der Antwort nachdenken darf. Gemessen an einem echten
#: Fund (Haiku): ohne Denken 12 s und fünf Regelverstöße im Steckbrief, mit
#: bis zu 2048 Tokens 24 s und ein bis zwei, mit unbegrenztem Denken 2 Minuten,
#: 12 000 Ausgabe-Tokens und kaum besser.
CLI_THINKING_TOKENS = 2048
#: Wie viele Bücher in einen Aufruf gehen (#66). Ein Bündel legt Vokabular und
#: Regeln (rund 5500 Tokens) einmal statt je Buch aufs Papier und spart den
#: Prozessstart; dafür wächst die Antwort mit jedem Buch.
BATCH_SIZE = 8
#: Die eigene, kurze Anweisung ersetzt die von Claude Code selbst.
CLI_SYSTEM_PROMPT = "Du antwortest ausschließlich mit dem verlangten JSON."


class Channel(Protocol):
    """Text hinein, Text heraus — die Leitung zum Modell."""

    def ask(self, text: str, max_tokens: int = MAX_TOKENS) -> str: ...


@dataclass(slots=True)
class ApiChannel:
    """Fragt die Messages-API über das offizielle SDK (#102).

    Drei Dinge, die der Weg über die Kommandozeile nicht kann:

    - **Zwischenspeicher:** Regeln, Vokabular und Genre-Liste stehen als
      Systemtext vorn und werden gecacht — rund 5500 Tokens, die ein Aufruf
      danach zu einem Zehntel zahlt.
    - **Festes Schema:** die Form der Antwort legt ``output_config.format``
      fest, statt dass das Modell sie aus dem Text abliest. Ob die Merkmale im
      Vokabular stehen, prüft danach :func:`parse_answer`, wie auf jedem Weg.
    - **Batch** für ``ebw rate``: zum halben Preis, dafür nicht sofort.
    """

    api_key: str
    model: str = DEFAULT_MODEL
    timeout: float = 600.0
    #: Ein `anthropic.Anthropic` — in Tests ersetzt.
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)

    def _params(self, parts: Parts, schema: dict | None, max_tokens: int) -> dict:
        output: dict = {"effort": EFFORT}
        if schema is not None:
            output["format"] = {"type": "json_schema", "schema": schema}
        return {
            "model": self.model,
            "max_tokens": max(max_tokens, API_MAX_TOKENS),
            "system": [{"type": "text", "text": parts.stable,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": parts.variable}],
            "output_config": output,
        }

    def ask(self, text: str, max_tokens: int = MAX_TOKENS) -> str:
        """Ein Text ohne Teilung und ohne Schema — der allgemeine Weg (`Channel`)."""
        return self.ask_parts(Parts(stable="", variable=text), None, max_tokens)

    def ask_parts(self, parts: Parts, schema: dict | None, max_tokens: int = MAX_TOKENS) -> str:
        """Geteilt und mit Schema fragen. Gestreamt, damit ein großer Deckel
        keine Zeitüberschreitung auslöst."""
        import anthropic

        params = self._params(parts, schema, max_tokens)
        if not parts.stable:
            del params["system"]
        try:
            with self.client.messages.stream(**params) as stream:
                message = stream.get_final_message()
        except anthropic.APIConnectionError as exc:
            raise PortrayalUnavailable(f"Modell nicht erreichbar: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise PortrayalUnavailable(f"Modell antwortete {exc.status_code}") from exc
        return _message_text(message)

    def batch(
        self, requests: dict[str, tuple[Parts, dict | None]], *,
        poll_seconds: float = BATCH_POLL_SECONDS, give_up_seconds: float = BATCH_GIVE_UP_SECONDS,
    ) -> dict[str, str]:
        """Viele Anfragen als ein Batch (#102): halber Preis, Ergebnis später.

        Zurück kommt die Antwort je Schlüssel. Was scheitert, abläuft oder
        nach ``give_up_seconds`` noch offen ist, fehlt — es kostet nur sich
        (ADR 7). Die Reihenfolge der Ergebnisse ist beliebig; gelesen wird
        nach Schlüssel.
        """
        import time

        import anthropic

        try:
            created = self.client.messages.batches.create(requests=[
                {"custom_id": key, "params": self._params(parts, schema, MAX_TOKENS)}
                for key, (parts, schema) in requests.items()
            ])
            started = time.monotonic()
            while True:
                status = self.client.messages.batches.retrieve(created.id).processing_status
                if status == "ended":
                    break
                if time.monotonic() - started > give_up_seconds:
                    self.client.messages.batches.cancel(created.id)
                    return {}
                time.sleep(poll_seconds)
            answers: dict[str, str] = {}
            for entry in self.client.messages.batches.results(created.id):
                if entry.result.type != "succeeded":
                    continue
                try:
                    answers[entry.custom_id] = _message_text(entry.result.message)
                except PortrayalUnavailable:
                    continue
            return answers
        except anthropic.APIConnectionError as exc:
            raise PortrayalUnavailable(f"Modell nicht erreichbar: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise PortrayalUnavailable(f"Modell antwortete {exc.status_code}") from exc


def _message_text(message) -> str:
    """Der Text einer Antwort — Denkblöcke sind nicht die Antwort."""
    if message.stop_reason == "refusal":
        raise PortrayalUnavailable("Modell hat abgelehnt")
    if message.stop_reason == "max_tokens":
        raise PortrayalUnavailable("Antwort abgeschnitten (max_tokens)")
    text = "".join(block.text for block in message.content if block.type == "text")
    if not text:
        raise PortrayalUnavailable("Antwort ohne Text")
    return text


@dataclass(slots=True)
class CliChannel:
    """Fragt die lokal angemeldete Claude-Code-Installation statt der API.

    Kein Schlüssel, kein Guthaben, keine zweite Anmeldung. Dafür ein
    Unterprozess je Aufruf, und der ist **teuer**: eine Messung an einem echten
    Titel ergab 34 Sekunden, gegenüber wenigen Sekunden für einen POST. Das ist
    tragbar, weil vor dem Tor schon die Preisregel steht und jedes Buch genau
    einmal beschrieben wird; ``rating_budget`` ist die Bremse gegen den
    einmaligen Rückstand. Wer ihn zügig abarbeiten will, setzt einen Schlüssel.

    ``--output-format json`` liefert eine Hülle mit dem Ergebnis in ``result``;
    kommt sie nicht, wird die rohe Ausgabe gelesen.
    """

    executable: str = CLI_NAME
    timeout: float = CLI_TIMEOUT
    model: str = CLI_DEFAULT_MODEL
    thinking_tokens: int = CLI_THINKING_TOKENS

    def ask(self, text: str, max_tokens: int = MAX_TOKENS) -> str:
        """``max_tokens`` begrenzt die Antwort nicht (die CLI kennt keine solche
        Grenze), bestimmt aber das Denkbudget: es gilt je Buch, also wächst es mit
        der erwarteten Antwort — ein Bündel von acht braucht nicht dasselbe Budget
        wie ein einzelnes Buch."""
        # Der Text geht über stdin, nicht als Argument: Windows begrenzt eine
        # Kommandozeile auf 32767 Zeichen. Python meldete das als
        # FileNotFoundError, woraus "claude nicht gefunden" wurde, und zwölf
        # Bücher fielen mit dieser falschen Begründung aus dem Lauf.
        # Schlank: ohne die Anweisung, die Werkzeuge, die Einstellungen und die
        # MCP-Server der angemeldeten Installation, und mit dem konfigurierten
        # kleinen Modell. Der bloße Aufruf kostete gemessen rund 61 000
        # Eingabe-Tokens und 0,33 $ je Buch, so 10 800 Tokens und 0,03 $.
        command = [
            self.executable, "-p", "--output-format", "json",
            "--model", self.model,
            "--tools", "",
            "--system-prompt", CLI_SYSTEM_PROMPT,
            "--strict-mcp-config",
            "--setting-sources", "",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]
        books = max(1, round(max_tokens / MAX_TOKENS))
        environment = {
            **os.environ,
            "MAX_THINKING_TOKENS": str(self.thinking_tokens * books),
        }
        # Kein Fenster: die Oberfläche holt einen Steckbrief im Hintergrund, und
        # unter Windows blitzte dabei jedes Mal eine Konsole auf.
        no_window = (
            {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        )
        try:
            completed = subprocess.run(  # noqa: S603 - fester Befehl, keine Shell
                command,
                input=text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=environment,
                **no_window,
            )
        except FileNotFoundError as exc:
            raise PortrayalUnavailable(f"{self.executable} nicht gefunden") from exc
        except subprocess.TimeoutExpired as exc:
            raise PortrayalUnavailable(
                f"{self.executable} antwortete nicht in {self.timeout}s"
            ) from exc
        if completed.returncode != 0:
            # Die Hülle nennt den Grund auch dann noch, wenn der Rückgabewert
            # schon Alarm schlägt — und sie ist die einzige, die ihn nennt:
            # "Not logged in · Please run /login" stand in stdout, stderr blieb
            # leer. Wirft sie nicht, fällt es auf die Zeile darunter zurück.
            _cli_text(completed.stdout)
            detail = (completed.stderr or "").strip().splitlines()
            raise PortrayalUnavailable(
                f"{self.executable} endete mit {completed.returncode}"
                + (f": {detail[-1]}" if detail else "")
            )
        return _cli_text(completed.stdout)


def _cli_text(stdout: str) -> str:
    """Die Antwort aus der JSON-Hülle — oder die rohe Ausgabe.

    Die Hülle kann sich ändern; auf ihr Format zu bestehen hieße, an einer
    fremden Version zu hängen. Fehlt sie oder sieht sie anders aus, geht der
    Text unverändert weiter, und ``parse_answer`` sucht sich das JSON darin.

    Eine Ausnahme: die Hülle sagt selbst, wenn etwas schiefging — dann steht in
    ``result`` **die Fehlermeldung** und nicht die Antwort. Ohne diese Prüfung
    wanderte "Failed to authenticate: OAuth session expired" als vermeintliche
    Antwort weiter und scheiterte erst später an "enthält kein JSON", und der
    Rückgabewert war dabei **null**.
    """
    try:
        envelope = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout
    if isinstance(envelope, dict):
        result = envelope.get("result")
        if envelope.get("is_error"):
            reason = result if isinstance(result, str) and result else "ohne Angabe"
            raise PortrayalUnavailable(f"Claude Code meldet einen Fehler: {reason}")
        if isinstance(result, str):
            return result
    return stdout


@dataclass(slots=True)
class Portrayer:
    """Beschreibt Bücher: Titel, Autor:in und Klappentext hinein, ein ``Portrait`` heraus.

    Speichern tut der Aufrufer. Einmal je Buch gefragt wird an den Aufrufstellen
    entschieden: sie sehen zuerst nach, ob es schon einen Steckbrief gibt.
    """

    channel: Channel
    vocabulary: Vocabulary
    batch_size: int = BATCH_SIZE
    #: Holt den Anfang einer Leseprobe zu ihrer Adresse, oder nichts (#76).
    #: Ohne ihn gibt es keine zweite Stufe.
    samples: Callable[[str], str | None] | None = None

    def portray(
        self, title: str, author: str | None, blurb: str | None, sample: str | None = None
    ) -> Portrait:
        """Einmal fragen, die Antwort lesen.

        Über die API geteilt und mit Schema (#102), über die Kommandozeile als
        der eine Text wie bisher.
        """
        if isinstance(self.channel, ApiChannel):
            answer = self.channel.ask_parts(
                prompt_parts(title, author, blurb, self.vocabulary, sample), ANSWER_SCHEMA
            )
        else:
            answer = self.channel.ask(
                prompt(title, author, blurb, self.vocabulary, sample), MAX_TOKENS
            )
        evidence = EVIDENCE_WITH_SAMPLE if sample else EVIDENCE
        return replace(
            parse_answer(answer, self.vocabulary, evidence),
            with_text=bool(blurb),
            with_sample=bool(sample) or None,
        )

    def with_sample(self, observation: Observation, portrait: Portrait) -> Portrait:
        """Die zweite Stufe (#76): unbekannt trotz Text, und der Shop hat eine
        Leseprobe — dann genau einmal noch mit ihrem Anfang fragen.

        Ohne Probe, oder wenn sie sich nicht lesen lässt, bleibt es beim ersten
        Steckbrief: nichts wird erfunden.
        """
        if portrait.known or not portrait.with_text or portrait.with_sample:
            return portrait
        if self.samples is None or not observation.sample_url:
            return portrait
        text = self.samples(observation.sample_url)
        if not text:
            return portrait
        return self.portray(*self._book(observation), sample=text)

    @staticmethod
    def _book(observation: Observation) -> tuple[str, str | None, str | None]:
        """Was das Modell von einem Fund zu sehen bekommt.

        Titel und Klappentext gehen mit; wo es sie gibt, auch der Originaltitel
        und die Schlagwörter (#17) — ein Buch, das das Modell nur unter dem
        englischen Titel kennt, bliebe sonst unbekannt.
        """
        title = observation.title
        if observation.original_title:
            title += f" (Originaltitel: {observation.original_title})"
        blurb = observation.blurb
        if observation.keywords:
            keywords = f"Schlagwörter: {', '.join(observation.keywords)}"
            blurb = f"{blurb}\n{keywords}" if blurb else keywords
        return title, observation.author, blurb

    def portray_find(self, observation: Observation) -> Portrait:
        """Einen Fund beschreiben (#48), wenn nötig mit der Leseprobe (#76)."""
        return self.with_sample(observation, self.portray(*self._book(observation)))

    def portray_finds(
        self, observations: Sequence[Observation], *, batch: bool = False
    ) -> dict[tuple[str, str], Portrait]:
        """Mehrere Funde beschreiben, bis zu ``batch_size`` je Aufruf (#66).

        Zurück kommt der Steckbrief je Beobachtungs-Schlüssel. Was fehlt, ist
        unbeschrieben geblieben: ein Bündel, das scheitert, kostet nur seine
        Bücher, und ein Buch, das die Antwort auslässt oder krumm beschreibt,
        nur sich selbst — nie mehr (ADR 7).

        ``batch``: über die API als Batch, zum halben Preis und ohne Bündeln —
        das Vokabular kostet dank Zwischenspeicher ohnehin nur einmal (#102).
        Nur für ``ebw rate``: ein Batch kann eine Stunde brauchen, und das Tor
        im Lauf wartet nicht so lange. Über die Kommandozeile gilt es nicht.
        """
        if batch and isinstance(self.channel, ApiChannel) and observations:
            return self._portray_batch(observations)
        results: dict[tuple[str, str], Portrait] = {}
        size = max(1, self.batch_size)
        for start in range(0, len(observations), size):
            chunk = list(observations[start : start + size])
            try:
                if len(chunk) == 1:
                    results[chunk[0].key] = self.portray_find(chunk[0])
                    continue
                books = [self._book(o) for o in chunk]
                if isinstance(self.channel, ApiChannel):
                    answer = self.channel.ask_parts(
                        prompt_many_parts(books, self.vocabulary), many_schema(len(chunk)),
                        MAX_TOKENS * len(chunk),
                    )
                else:
                    answer = self.channel.ask(
                        prompt_many(books, self.vocabulary), MAX_TOKENS * len(chunk)
                    )
                for number, portrait in parse_many(answer, self.vocabulary, len(chunk)).items():
                    book = chunk[number - 1]
                    portrait = replace(portrait, with_text=bool(self._book(book)[2]))
                    try:
                        results[book.key] = self.with_sample(book, portrait)
                    except PortrayalUnavailable:
                        results[book.key] = portrait
            except PortrayalUnavailable:
                continue
        return results

    def _portray_batch(
        self, observations: Sequence[Observation]
    ) -> dict[tuple[str, str], Portrait]:
        assert isinstance(self.channel, ApiChannel)
        by_id = {}
        for observation in observations:
            by_id.setdefault(_batch_id(observation), observation)
        answers = self.channel.batch({
            key: (prompt_parts(*self._book(o), self.vocabulary), ANSWER_SCHEMA)
            for key, o in by_id.items()
        })
        results: dict[tuple[str, str], Portrait] = {}
        for key, answer in answers.items():
            observation = by_id[key]
            try:
                portrait = replace(parse_answer(answer, self.vocabulary),
                                   with_text=bool(self._book(observation)[2]))
            except PortrayalUnavailable:
                continue
            try:
                results[observation.key] = self.with_sample(observation, portrait)
            except PortrayalUnavailable:
                results[observation.key] = portrait
        return results


def _batch_id(observation: Observation) -> str:
    """Ein Schlüssel, wie ihn die Batch-API annimmt: Buchstaben, Ziffern, - und _."""
    raw = f"{observation.source}-{observation.source_item_id}"
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:64]


def build_portrayer(model: str | None, vocabulary: Vocabulary) -> Portrayer | None:
    """Der Steckbrief-Ersteller, falls ein Weg zum Modell da ist — sonst ``None``.

    Zwei Wege, in dieser Reihenfolge:

    1. **Ein API-Schlüssel in der Umgebung.** Schneller, weil ein POST statt
       eines Unterprozesses, und der Weg für einen Rechner ohne Claude Code.
    2. **Die lokal angemeldete Claude-Code-Installation** über ``claude -p``.
       Kein Schlüssel, kein zusätzliches Guthaben.

    Der Schlüssel geht vor, wo beides da ist: wer ihn setzt, hat sich für ihn
    entschieden. Ist keiner von beiden verfügbar, ist das **kein Fehler**,
    sondern der Zustand ohne neue Steckbriefe — alles bleibt unbeschrieben und
    wird gezeigt.
    """
    key = os.environ.get(KEY_ENV)
    if key:
        return Portrayer(ApiChannel(api_key=key, model=model or DEFAULT_MODEL), vocabulary)
    executable = shutil.which(CLI_NAME)
    if executable:
        return Portrayer(
            CliChannel(executable=executable, model=model or CLI_DEFAULT_MODEL), vocabulary
        )
    return None
