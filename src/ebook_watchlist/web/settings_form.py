"""Das Formular „Einstellungen“ auf der Übersicht (#100, #104).

Welche Felder es gibt, wie sie heißen und wie aus der Eingabe ein Wert wird.
Ob ein Wert *gilt*, entscheidet nicht dieses Modul, sondern
`config.load_settings` — dieselben Regeln wie für die Datei. Die Route
speichert, lädt zur Probe und nimmt bei einem Fehler alles zurück.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import EDITABLE, Settings
from ..language import LANGUAGE_NAMES


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str
    #: ``int``, ``euro`` (Eingabe in Euro, gespeichert in Cent), ``url`` oder
    #: ``languages`` (Namen in Rangfolge, gespeichert als ISO 639-2).
    kind: str = "int"
    unit: str = ""
    hint: str = ""


FIELDS: tuple[Field, ...] = (
    Field("languages", "Lesesprachen", kind="languages",
          hint="In Rangfolge, etwa „deutsch, englisch“. Vorschläge in anderen Sprachen "
               "erscheinen nicht; die Watchlist sucht zuerst in der ersten."),
    Field("run_every_hours", "Lauf alle", unit="Stunden",
          hint="Der Hintergrunddienst prüft alle 15 Minuten, ob ein Lauf fällig ist."),
    Field("home_offers", "Startseite: Angebote", unit="Zeilen"),
    Field("home_suggestions", "Startseite: Vorschläge", unit="Zeilen"),
    Field("suggestions_shown", "Vorschläge zuerst", unit="Zeilen",
          hint="Weitere lädt „Weitere 10 anzeigen“ am Ende."),
    Field("strong_deal_max_cents", "Schnäppchen bis", kind="euro", unit="€"),
    Field("deal_max_cents", "Angebot bis", kind="euro", unit="€"),
    Field("min_discount_pct", "Angebot ab", unit="% Rabatt"),
    Field("rating_budget", "Urteile je Lauf", unit="höchstens"),
    Field("dnb_budget", "DNB-Anfragen je Lauf", unit="höchstens"),
    Field("public_url", "Adresse von Buchfink", kind="url",
          hint="Für den Link in Benachrichtigungen, etwa http://192.168.178.20:8437 — "
               "localhost trägt auf dem Telefon nicht. Leer: kein Link."),
)

assert {f.key for f in FIELDS} == set(EDITABLE), "jedes änderbare Feld braucht eine Zeile"


class BadInput(ValueError):
    """Eine Eingabe, die keine Zahl oder Adresse ist."""


def shown(settings: Settings) -> dict[str, str]:
    """Was in den Feldern steht: der Wert, der gerade gilt."""
    out: dict[str, str] = {}
    for f in FIELDS:
        value = getattr(settings, f.key)
        if f.kind == "euro":
            out[f.key] = f"{value / 100:.2f}".replace(".", ",")
        elif f.kind == "languages":
            out[f.key] = ", ".join(LANGUAGE_NAMES.get(str(c), str(c)) for c in value)
        else:
            out[f.key] = "" if value is None else str(value)
    return out


def parse(form: dict[str, str]) -> dict:
    """Aus den Feldern, die mitkamen, die Werte zum Speichern.

    Ein leeres Adressfeld nimmt die Adresse zurück (``None``); ein leeres
    Zahlenfeld lässt die Zahl, wie sie ist.
    """
    values: dict = {}
    for f in FIELDS:
        if f.key not in form:
            continue
        raw = form[f.key].strip()
        if f.kind == "url":
            values[f.key] = raw or None
            continue
        if f.kind == "languages":
            if raw:
                values[f.key] = _language_codes(f, raw)
            continue
        if not raw:
            continue
        try:
            if f.kind == "euro":
                values[f.key] = round(float(raw.replace(",", ".")) * 100)
            else:
                values[f.key] = int(raw)
        except ValueError as exc:
            raise BadInput(f"„{f.label}“: {raw!r} ist keine Zahl") from exc
    return values


_BY_NAME = {name.casefold(): code for code, name in LANGUAGE_NAMES.items()}


def _language_codes(f: Field, raw: str) -> list[str]:
    """„Englisch, deutsch“ → ``["eng", "ger"]``; ein Code geht auch."""
    codes = []
    for word in (w.strip().casefold() for w in raw.split(",")):
        if not word:
            continue
        code = _BY_NAME.get(word) or (word if word in LANGUAGE_NAMES else None)
        if code is None:
            raise BadInput(f"„{f.label}“: {word!r} ist keine Sprache, die Buchfink kennt")
        if code not in codes:
            codes.append(code)
    if not codes:
        raise BadInput(f"„{f.label}“: mindestens eine Sprache")
    return codes
