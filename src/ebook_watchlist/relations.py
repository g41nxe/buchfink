"""Das Vokabular für Beziehungen und Interessen (ADR 18, Ticket 05).

Beides ist Freitext in der Datenbank und wird hier gegen die Liste der Handler
geprüft, die etwas damit anfangen können. Ein Schlüssel, den niemand bedient,
ist ein Konfigurationsfehler und muss beim Laden laut scheitern: ein Interesse
unter ``autor`` statt ``author`` würde sonst nie abgefragt, und **nichts würde
das sagen**.

Warum nicht als Enum in der Spalte? Weil ein dritter Entdeckungskanal —
Verlag, Reihe, Schlagwort — dann eine Migration kostet statt eines Handlers.
Die Prüfung gehört in den Lader, nicht ins Schema.
"""

from __future__ import annotations

from enum import StrEnum


class RelationKind(StrEnum):
    """Was die Leserin zu einem Buch sagt.

    Mehrere gelten gleichzeitig, und das ist der Normalfall, nicht die
    Ausnahme: *Cold Eternity* ist ``owned`` **und** war ``watching``. Eine
    einzelne Statusspalte hätte das nicht ausdrücken können.
    """

    WATCHING = "watching"
    OWNED = "owned"
    LIKED = "liked"
    DISLIKED = "disliked"
    DISMISSED = "dismissed"


#: Wie eine Beziehung gegenueber der Leserin heisst — **eine** Liste, aus der
#: alle Ansichten lesen.
#:
#: Vorher schrieb sich jedes Modul seine eigene, und die waren
#: auseinandergelaufen: ``owned`` hiess "besitze ich" auf der Buchseite,
#: "besessen" im Profil, "Habe ich" im Stapel und "im Besitz" im
#: Watchlist-Menue. Vier Namen fuer dieselbe Sache entstehen nicht aus
#: Absicht, sondern daraus, dass es vier Stellen gab.
#:
#: Substantive, keine Ich-Saetze: Goodreads und StoryGraph benennen ihre
#: Regale genauso ("Gelesen", "Aktuelle Lektuere"). Und keine zwei Namen, die
#: sich nur durch ein "nicht" unterscheiden — die sehen beim Ueberfliegen
#: gleich aus.
RELATION_LABELS: dict[RelationKind, str] = {
    RelationKind.WATCHING: "in Beobachtung",
    RelationKind.OWNED: "im Besitz",
    RelationKind.LIKED: "Mag ich",
    RelationKind.DISLIKED: "Kein Interesse",
    RelationKind.DISMISSED: "Ausgeschlossen",
}


#: Was auf dem **Knopf** steht, der ein Buch in eine Beziehung bringt —
#: auf *jedem* Knopf: Stapel, Startseite, Watchlist-Menue, Fund- und Buchseite
#: (Issue #5, ADR 29 mit Nachtrag).
#:
#: Zwei Listen mit klarer Zustaendigkeit, nicht vier Fassungen einer. Der
#: Zustandsname oben antwortet auf "was ist dieses Buch fuer mich?" und steht,
#: wo Buecher beschrieben werden — im Profil, in "Frueher: …", im Tagesbericht
#: — wie ein Regalschild. Der Knopf antwortet auf "was tust du damit?" und
#: traegt ein Taetigkeitswort. "Hab ich" verstoesst absichtlich gegen die Regel
#: oben: die galt fuer Regalschilder; auf einem Knopf ist der Ich-Satz die
#: Antwort, nicht der Name.
#:
#: Bei `liked` und `disliked` fallen beide Rollen auf dasselbe Wort: "Mag ich"
#: ist Regalschild und Antwort zugleich. Das ist keine Drift, sondern ein Wort,
#: das beides kann — die Listen duerfen sich treffen, sie duerfen nur nicht
#: die Rollen tauschen.
ACTION_LABELS: dict[RelationKind, str] = {
    # "Ausschliessen", nicht "Verwerfen": verworfen wird ein Vorschlag,
    # ausgeschlossen ein Buch — und genau das tut der Knopf, bei jeder Quelle
    # und dauerhaft (ADR 18). Der Zustandsname daneben heisst "Ausgeschlossen".
    RelationKind.DISMISSED: "Ausschließen",
    RelationKind.OWNED: "Hab ich",
    RelationKind.WATCHING: "Beobachten",
    RelationKind.LIKED: "Mag ich",
    # "Doof" statt "Kein Interesse": das Gegenstueck zu "Mag ich" ist ein
    # Urteil ueber das Buch, kein hoeflicher Rueckzug — und "kein Interesse"
    # klingt wie "nicht mehr zeigen", was der Knopf daneben tut.
    RelationKind.DISLIKED: "Doof",
}


def label_of(kind: RelationKind | str) -> str:
    """Wie diese Beziehung heisst. Unbekanntes bleibt, wie es ist."""
    try:
        return RELATION_LABELS[RelationKind(kind)]
    except ValueError:  # pragma: no cover - nur bei einer fremden Art
        return str(kind)


def labelled(*kinds: RelationKind) -> tuple[tuple[str, str], ...]:
    """``(schluessel, name)`` in der angegebenen Reihenfolge."""
    return tuple((str(kind), RELATION_LABELS[kind]) for kind in kinds)


#: Was geschehen ist, in der Ruecknahme-Zeile — ein Satz, kein Knopfwort.
#: "Hab ich" steht auf dem Knopf, "als vorhanden vermerkt" im Rueckblick.
#: Steht hier und nicht in einer der Seiten: Startseite und Watchlist bieten
#: dieselbe Ruecknahme an, und zwei Tabellen waeren zwei, die auseinanderlaufen.
#: Von der Watchlist genommen, ohne etwas über das Buch zu sagen (#72). Keine
#: eigene Art: ein stillgelegtes ``watching`` mit ``removed`` im Beutel, damit
#: es nicht als pausiert auf der Liste stehen bleibt.
REMOVED = "removed"
#: Das Knopfwort dazu, neben den Wörtern der Arten (``ACTION_LABELS``).
REMOVED_ACTION = "von der Watchlist nehmen"

DONE_LABELS: dict[str, str] = {
    REMOVED: "von der Watchlist genommen",
    str(RelationKind.DISMISSED): "verworfen",
    str(RelationKind.OWNED): "als vorhanden vermerkt",
    str(RelationKind.WATCHING): "in Beobachtung genommen",
}


def labelled_actions(*kinds: RelationKind) -> tuple[tuple[str, str], ...]:
    """``(schluessel, knopfwort)`` in der angegebenen Reihenfolge."""
    return tuple((str(kind), ACTION_LABELS[kind]) for kind in kinds)


class InterestKey(StrEnum):
    """Wo das Werkzeug nach neuen Büchern sehen soll.

    Referenzautor:in und Thema beantworten dieselbe Frage und sind deshalb eine
    Tabelle. Sie sind die zwei Entdeckungskanäle und erzeugen die zwei
    Entdeckungs-Anlässe.
    """

    AUTHOR = "author"
    #: Der Wert ``"thema"`` steht so in der Datenbank (``interest.key``) und
    #: bleibt ein Datenwert: der Name im Code folgt dem Glossar, der
    #: gespeicherte Wert wird nicht migriert (ADR 22, Nachtrag vom 26.09.2026).
    GENRE_CATEGORY = "thema"


RELATION_KINDS: frozenset[str] = frozenset(kind.value for kind in RelationKind)
INTEREST_KEYS: frozenset[str] = frozenset(key.value for key in InterestKey)

#: ``core`` wird jeden Lauf gefegt, ``extended`` einmal die Woche. Das ist
#: nicht autorenspezifisch — ein Thema könnte genauso wöchentlich laufen —,
#: deshalb steht es in ``details`` und nicht in einer eigenen Spalte (ADR 18).
TIERS: frozenset[str] = frozenset({"core", "extended"})

#: Worauf ein Watchlist-Eintrag eingeschraenkt sein kann. Bewusst die *Art*
#: einer Quelle und nicht ihr Name: wie eine Bibliothek heisst, entscheidet
#: die Konfiguration, und ein Import darf keine Namen erfinden.
RESTRICTIONS: frozenset[str] = frozenset({"library", "shop"})

#: Was die Leserin zu einem gelesenen Buch sagt, je eine Liste von Familien
#: (#79): was fehlte (``add``), was für sie nicht stimmt (``drop``), und was
#: sie nur an diesem Buch gestört hat (``here``, aus dem Nachschärfen).
REASON_KINDS: tuple[str, ...] = ("add", "drop", "here")


class ConfigurationError(Exception):
    """Ein Wert, den kein Handler bedient. Laut, nicht geduldet."""


def check_relation_kind(kind: str) -> str:
    if kind not in RELATION_KINDS:
        raise ConfigurationError(
            f"unbekannte Beziehung {kind!r} (bekannt: {', '.join(sorted(RELATION_KINDS))})"
        )
    return kind


def check_interest_key(key: str) -> str:
    if key not in INTEREST_KEYS:
        raise ConfigurationError(
            f"unbekanntes Interesse {key!r} (bekannt: {', '.join(sorted(INTEREST_KEYS))})"
        )
    return key


def check_details(key: str, details: dict) -> dict:
    """Der Beutel wird geprüft, nicht nur die Spalten.

    ``tier: "extendet"`` würde eine wöchentliche Autor:in stillschweigend in die
    tägliche Liste befördern, und ``activ: false`` würde ganz ignoriert. Beides
    sind Tippfehler, die sich nur durch verändertes Verhalten bemerkbar machten
    — die teuerste Art, einen Fehler zu finden (ADR 18).
    """
    unknown = set(details) - {
        "tier", "sources", "note", "restrict", "known_missing", "reasons", "removed"
    }
    if unknown:
        raise ConfigurationError(
            f"unbekannte Angaben zu {key!r}: {', '.join(sorted(unknown))} "
            "(bekannt: known_missing, note, reasons, removed, restrict, sources, tier)"
        )
    if "removed" in details and not isinstance(details["removed"], bool):
        raise ConfigurationError(f"'removed' bei {key!r} ist ja oder nein")
    reasons = details.get("reasons")
    if reasons is not None and not (
        isinstance(reasons, dict)
        and set(reasons) <= set(REASON_KINDS)
        and all(
            isinstance(v, list) and all(isinstance(f, str) for f in v) for v in reasons.values()
        )
    ):
        raise ConfigurationError(
            f"'reasons' bei {key!r} muss je {', '.join(REASON_KINDS)} eine Liste von Familien sein"
        )
    restrict = details.get("restrict")
    if restrict is not None and restrict not in RESTRICTIONS:
        raise ConfigurationError(
            f"unbekannte Einschraenkung {restrict!r} bei {key!r} "
            f"(bekannt: {', '.join(sorted(RESTRICTIONS))})"
        )
    tier = details.get("tier")
    if tier is not None and tier not in TIERS:
        raise ConfigurationError(
            f"unbekannte Stufe {tier!r} bei {key!r} (bekannt: {', '.join(sorted(TIERS))})"
        )
    sources = details.get("sources")
    if sources is not None and not (
        isinstance(sources, list) and all(isinstance(name, str) for name in sources)
    ):
        raise ConfigurationError(f"'sources' bei {key!r} muss eine Liste von Namen sein")
    return details
