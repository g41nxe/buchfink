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
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Protocol

import requests

from .models import Observation
from .portrait import (
    MAX_TOKENS,
    Portrait,
    PortrayalUnavailable,
    Vocabulary,
    parse_answer,
    prompt,
)

#: Voreinstellung: eine beschränkte Aufgabe gegen ein mitgeliefertes Vokabular,
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
#: Die eigene, kurze Anweisung ersetzt die von Claude Code selbst.
CLI_SYSTEM_PROMPT = "Du antwortest ausschließlich mit dem verlangten JSON."


class Channel(Protocol):
    """Text hinein, Text heraus — die Leitung zum Modell."""

    def ask(self, text: str, max_tokens: int = MAX_TOKENS) -> str: ...


@dataclass(slots=True)
class ApiChannel:
    """Fragt die Messages-API. Keine eigene Bibliothek — sie ist ein POST."""

    api_key: str
    model: str = DEFAULT_MODEL
    timeout: float = 60.0
    session: requests.Session = field(default_factory=requests.Session)

    def ask(self, text: str, max_tokens: int = MAX_TOKENS) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": text}],
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
            raise PortrayalUnavailable(f"Modell nicht erreichbar: {exc}") from exc
        if response.status_code != 200:
            raise PortrayalUnavailable(f"Modell antwortete {response.status_code}")
        try:
            blocks = response.json()["content"]
            return "".join(block.get("text", "") for block in blocks)
        except (ValueError, KeyError, TypeError) as exc:
            raise PortrayalUnavailable(f"unerwartete Antwortform: {exc}") from exc


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
        """``max_tokens`` steht nur der Form halber da: die CLI kennt keine
        solche Grenze."""
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
        environment = {**os.environ, "MAX_THINKING_TOKENS": str(self.thinking_tokens)}
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

    def portray(self, title: str, author: str | None, blurb: str | None) -> Portrait:
        """Einmal fragen, die Antwort lesen."""
        answer = self.channel.ask(prompt(title, author, blurb, self.vocabulary), MAX_TOKENS)
        return parse_answer(answer, self.vocabulary)

    def portray_find(self, observation: Observation) -> Portrait:
        """Einen Fund beschreiben (#48).

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
        return self.portray(title, observation.author, blurb)


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
