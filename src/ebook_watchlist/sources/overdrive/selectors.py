"""Jeder OverDrive-spezifische String an einer Stelle (ADR 7).

Dieselbe Rolle wie ``onleihe/selectors.py``, nur tragen die Konstanten hier
Pfade, Abfrageparameter und Feldnamen statt CSS-Selektoren: OverDrive liefert
den Katalog als JSON. Baut OverDrive um, ist dieses Modul der ganze Diff.

Recherche: ``docs/research/overdrive-interface.md``.
"""

from __future__ import annotations

#: Die JSON-Schnittstelle. Die Seite ``voebb.overdrive.com`` baut ihre Treffer
#: im Browser zusammen und traegt im HTML keine einzige Trefferkarte; dieselben
#: Daten stehen hier ohne Umweg und ohne Schluessel.
BASE = "https://thunder.api.overdrive.com/v2/"

#: Welche Einrichtung. Steht auf jeder Seite der Instanz als
#: ``window.OverDrive.libraryKey``.
LIBRARY = "voebb"

#: Wohin die Leserin klickt. Nicht die Schnittstelle — eine API-Adresse ist
#: fuer einen Menschen keine Auskunft.
TITLE_URL = "https://voebb.overdrive.com/media/{title_id}"

SEARCH_PATH = "libraries/{library}/media"
TITLE_PATH = "libraries/{library}/media/{title_id}"
#: Eine Sammlung der Bibliothek, etwa „Lucky Day" (#74): ein Aufruf, alle Titel,
#: ohne Schlüssel. Der Parameter ``collection=`` an der Suche wird ignoriert —
#: nur dieser Weg trägt (gemessen am 25.09.2026).
COLLECTION_PATH = "libraries/{library}/collections/{collection}"
#: Was aus einer Sammlung ein Vorschlag sein darf: ein E-Book auf Deutsch.
COLLECTION_TYPE = "ebook"
COLLECTION_LANGUAGE = "de"

#: Nur, was jetzt ausleihbar ist (#74): die Facette „Available now".
AVAILABLE_ONLY = {"showOnlyAvailable": "true"}
#: Die neuesten zuerst — für Neuzugänge je Thema.
NEWLY_ADDED = {"sortBy": "newlyadded"}
#: Thema der Leserin (ein Pfad des Shops) → Thema bei OverDrive (#74). Gesucht
#: wird ein Stichwort im letzten Abschnitt des Pfads; ein Thema ohne Eintrag
#: wird bei OverDrive nicht gesucht. Die Kennungen stehen in der Facette
#: ``subjects`` der Suchantwort (gemessen am 26.09.2026).
GENRES: dict[str, str] = {
    # Code der Genre-Liste → Thema bei OverDrive (ADR 37). OverDrive kennt keine
    # Untergenres; erhoben am 04.10.2026 aus der Facette `subjects`
    # (docs/research/genres-der-quellen.md).
    "FIC031000": "100",  # Thriller
    "FIC022000": "57",   # Mystery
    "FIC028000": "80",   # Science Fiction
    "FIC055000": "80",   # Dystopien stehen dort unter Science Fiction
    "FIC009000": "24",   # Fantasy
    "FIC015000": "38",   # Horror
    "FIC027000": "77",   # Romance
    "FIC014000": "115",  # Historical Fiction
    "FIC016000": "123",  # Humor (Fiction)
    "FIC019000": "49",   # Literature
    # Keine Biografie: der Parser behält bei einem Thema nur Belletristik
    # (`parse.FICTION_CODES`), dort fände sie nie etwas (Review 04.10.2026).
}

#: Nur EPUB-E-Books, wie bei der Onleihe (``media: [ebook]``).
#: ``ebook-epub-adobe`` ist das Format, das die Leserin auf einem E-Reader
#: oeffnen kann; ``ebook-overdrive`` ist der Browser-Leser derselben Ausgabe.
SEARCH_PARAMS: dict[str, str] = {
    "format": "ebook-epub-adobe",
}

#: Zuerst wird nur deutsch gesucht. Entfaellt fuer die zweite Suche nach
#: einem Watchlist-Titel, die die deutsche nicht zuordnen konnte (#77) — ein
#: Titel, den die Leserin selbst benannt hat, ist nie fremd.
LANGUAGE_PARAMS: dict[str, str] = {
    "language": "de",
}

#: Die Sprache einer Karte (``languages[].id``) in den Codes der DNB (ISO
#: 639-2/B), damit eine Sprache ueberall gleich heisst. Was hier fehlt,
#: bleibt ungesagt — behaupten ist schlimmer als schweigen.
LANGUAGE_CODES: dict[str, str] = {
    "de": "ger",
    "en": "eng",
    "fr": "fre",
    "es": "spa",
    "it": "ita",
    "nl": "dut",
    "sv": "swe",
    "da": "dan",
    "no": "nor",
    "pl": "pol",
    "pt": "por",
    "tr": "tur",
    "ru": "rus",
    "ja": "jpn",
}

#: Wie viele Treffer je Seite. Thunder erlaubt bis 100 und antwortet darueber
#: mit 400; zwanzig reicht fuer eine Zuordnung und haelt die Antwort klein.
PER_PAGE = 20

#: Der Selbsttest. Ein Titel, den diese Bibliothek fuehrt — geprueft wird, dass
#: die Felder noch da sind, nie welche Werte sie tragen.
PROBE_TITLE_ID = "3222096"
PROBE_QUERY = "Der Zeitenläufer"
