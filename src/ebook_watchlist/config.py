"""Phase 1 configuration: ``profile.yaml`` and ``watchlist.yaml`` are the source
of truth (ADR 10). Anything missing or malformed fails loudly — a silently empty
watchlist looks exactly like "no deals today"."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import paths


class ConfigError(Exception):
    """Raised for a missing, unreadable, or structurally invalid config file."""


@dataclass(frozen=True, slots=True)
class Profile:
    slug: str
    name: str
    strong_deal_max_cents: int = 500
    deal_max_cents: int = 1000
    min_discount_pct: int = 25
    #: Wie viele Urteile ein Lauf höchstens einholt (ADR 19, Ticket 20). Der
    #: erste Lauf mit einem Schlüssel trifft einen Rückstand von dreihundert
    #: Entdeckungen; er soll ihn über Tage abarbeiten, nicht am Stück. Was das
    #: Budget übrig lässt, gilt als unbewertet und wird gezeigt.
    rating_budget: int = 40
    #: Wie viele ISBNs ein Lauf hoechstens bei der DNB nachschlaegt. Die
    #: DNB dokumentiert keine zulaessige Anfragefrequenz — der Rueckstand
    #: wird deshalb ueber mehrere Laeufe abgearbeitet (Ticket 42).
    dnb_budget: int = 50
    #: Wieviele Bücher in einen Modellaufruf gehen. Profil und Verfahren sind
    #: der weitaus größte Teil des Prompts, also spart ein Bündel den Großteil.
    #: Aber ein Modell, das zwanzig Dinge in einer Antwort beurteilt, ankert
    #: aneinander — deshalb einstellbar, damit sich das messen lässt.
    rating_batch_size: int = 20
    #: Welches Modell urteilt. ``None`` heißt: das voreingestellte kleine.
    rating_model: str | None = None
    #: Wie viele Zeilen die Startseite je Spalte zeigt. Fünf Angebote und drei
    #: Entscheidungen: StoryGraph und BookWyrm ziehen bei fünf dieselbe Linie,
    #: und ein Stapel von drei Entscheidungen bleibt eine Aufgabe statt einer
    #: Liste. Einstellbar, weil das vom Bildschirm abhängt und nicht vom
    #: Werkzeug — der Rest hängt am Verweis darunter (Issue #5).
    home_offers: int = 5
    home_suggestions: int = 3
    #: Die Kadenz: wie viele Stunden zwischen zwei Rundgängen mindestens
    #: liegen. Ein Lauf, den eine Maschine anstößt, prüft sie gegen den letzten
    #: Eintrag im Journal und tut sonst nichts — das ist die ganze Taktung, es
    #: gibt keinen Zeitplaner (ADR 4). Die Leserin selbst hält sie nicht auf.
    #:
    #: Zwanzig und nicht vierundzwanzig: sonst schöbe sich der tägliche Lauf um
    #: jede angebrochene Minute nach hinten, bis er einen Tag überspringt.
    run_every_hours: int = 20
    #: Swept every Run.
    reference_authors: list[str] = field(default_factory=list)
    #: Swept once a week — the long tail, where a missed day costs nothing.
    extended_authors: list[str] = field(default_factory=list)
    #: Monday is 0. The day the extended list is swept on.
    extended_sweep_weekday: int = 6
    genre_categories: list[str] = field(default_factory=list)
    no_gos: list[str] = field(default_factory=list)
    #: Books the reader named as good. Dormant like ``no_gos`` — nothing reads
    #: these yet. They are the raw material for judging whether a *discovered*
    #: title fits the reader rather than merely their shelves (ADR 13), and the
    #: profile only sharpens as the list grows, so they are worth keeping from
    #: the first day.
    liked_books: list[str] = field(default_factory=list)
    #: Die Gegenprobe. Ein Profil, das nur aus Zustimmung gebaut ist, weiß
    #: nicht, wo seine Grenze verläuft — am wertvollsten ist hier ein Buch, das
    #: auf dem Papier gepasst hätte (ADR 17). Ebenfalls dormant.
    disliked_books: list[str] = field(default_factory=list)
    #: In welchen Sprachen ein Fund in Frage kommt, als Code der DNB (ISO
    #: 639-2: ``ger``, ``eng``, ``fre``). Ein Fund, den die DNB ausdruecklich
    #: in einer anderen Sprache fuehrt, kommt nicht in den Stapel und kostet
    #: kein Urteil (#10). Watchlist-Titel sind ausgenommen.
    languages: tuple[str, ...] = ("ger",)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Appended to the outgoing User-Agent so a site operator can reach you.
    #: Opt-in — nothing personal is sent unless you put it here yourself.
    contact: str | None = None

    def authors_to_sweep(self, include_extended: bool) -> list[str]:
        if not include_extended:
            return list(self.reference_authors)
        extra = [a for a in self.extended_authors if a not in self.reference_authors]
        return [*self.reference_authors, *extra]


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    title: str
    author: str | None = None
    #: Die ISBN des Buches, sofern eine bekannt ist. Sie entsteht **aus** einer
    #: gelungenen Zuordnung und kann eine offene deshalb nicht lösen — gemessen:
    #: die vier Watchlist-Bücher mit ISBN sind genau die vier aufgelösten. Ihr
    #: Nutzen ist der Widerspruch: eine andere ISBN heißt anderes Buch.
    isbn: str | None = None
    check_library: bool = True
    check_shop: bool = True
    active: bool = True
    notes: str | None = None
    resolved_links: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Phase 1 identity. Phase 2 replaces this with a database id (ADR 5)."""
        return f"{self.title}|{self.author or ''}".casefold()


@dataclass(frozen=True, slots=True)
class OwnedBook:
    """Eine Zeile aus ``owned.yaml``.

    ``stars`` und ``why`` sind das Urteil eines Modells, nicht das der Leserin
    — siehe :func:`load_owned`. ``hinweis`` ist etwas anderes als eine
    Unsicherheit über das Urteil: er bittet um Gegenprüfung der *Identifikation*
    ("heißt der Band im Handel wirklich so?").
    """

    title: str
    author: str | None = None
    stars: int | None = None
    why: str | None = None
    hinweis: str | None = None


def _load_yaml(path: Path, what: str) -> Any:
    if not path.exists():
        raise ConfigError(f"{what} not found at {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{what} at {path} is not valid YAML: {exc}") from exc
    if data is None:
        raise ConfigError(f"{what} at {path} is empty")
    return data


def _require(mapping: dict[str, Any], key: str, what: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"{what} is missing the required field {key!r}")
    return mapping[key]


def _str_list(mapping: dict[str, Any], key: str, what: str) -> list[str]:
    value = mapping.get(key) or []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{what}: {key!r} must be a list of strings")
    return value


def _languages(mapping: dict[str, Any], what: str) -> tuple[str, ...]:
    """Sprachcodes, wie die DNB sie liefert — und nur die.

    Streng, weil ein falscher Code still wirkt: ``de`` statt ``ger`` hiesse,
    dass die DNB *jeden* deutschen Fund als fremd meldet, und der Stapel waere
    ohne Fehlermeldung leer.
    """
    value = mapping.get("languages", ["ger"])
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(code, str) and len(code) == 3 and code.isalpha()
                   and code.islower() for code in value)
    ):
        raise ConfigError(
            f"{what}: 'languages' must be a non-empty list of three-letter ISO 639-2 "
            f"codes as the DNB delivers them (ger, eng, fre …), got {value!r}"
        )
    return tuple(value)


def _positive_int(mapping: dict[str, Any], key: str, default: int, what: str) -> int:
    value = mapping.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{what}: {key!r} must be a positive integer, got {value!r}")
    return value


def _percentage(mapping: dict[str, Any], key: str, default: int, what: str) -> int:
    """A discount threshold. Zero is a real setting — "any drop in the band
    counts" — so it is allowed here, unlike for the price ceilings."""
    value = mapping.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 100:
        raise ConfigError(f"{what}: {key!r} must be a whole percentage from 0 to 99, got {value!r}")
    return value


def _reference_authors(data: dict[str, Any], what: str) -> tuple[list[str], list[str]]:
    """``reference_authors`` is either a plain list or a core/extended split::

        reference_authors:
          core: [...]       # every Run
          extended: [...]   # once a week
    """
    raw = data.get("reference_authors")
    if raw is None or isinstance(raw, list):
        return _str_list(data, "reference_authors", what), []
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{what}: 'reference_authors' must be a list, or a mapping of core/extended"
        )
    unknown = set(raw) - {"core", "extended"}
    if unknown:
        raise ConfigError(
            f"{what}: 'reference_authors' has unknown key(s) {sorted(unknown)} "
            "— expected 'core' and/or 'extended'"
        )
    return (
        _str_list(raw, "core", f"{what}: reference_authors"),
        _str_list(raw, "extended", f"{what}: reference_authors"),
    )


def load_profile(path: Path | None = None) -> Profile:
    path = path or paths.profile_path()
    data = _load_yaml(path, "profile.yaml")
    if not isinstance(data, dict):
        raise ConfigError(f"profile.yaml at {path} must be a mapping")

    what = "profile.yaml"
    core_authors, extended_authors = _reference_authors(data, what)
    weekday = data.get("extended_sweep_weekday", 6)
    if not isinstance(weekday, int) or isinstance(weekday, bool) or not 0 <= weekday <= 6:
        raise ConfigError(
            f"{what}: 'extended_sweep_weekday' must be 0 (Monday) to 6 (Sunday), got {weekday!r}"
        )

    profile = Profile(
        slug=str(_require(data, "slug", what)),
        name=str(_require(data, "name", what)),
        strong_deal_max_cents=_positive_int(data, "strong_deal_max_cents", 500, what),
        deal_max_cents=_positive_int(data, "deal_max_cents", 1000, what),
        min_discount_pct=_percentage(data, "min_discount_pct", 25, what),
        rating_budget=_positive_int(data, "rating_budget", 40, what),
        dnb_budget=_positive_int(data, "dnb_budget", 50, what),
        rating_batch_size=_positive_int(data, "rating_batch_size", 20, what),
        rating_model=str(data["rating_model"]) if data.get("rating_model") else None,
        home_offers=_positive_int(data, "home_offers", 5, what),
        home_suggestions=_positive_int(data, "home_suggestions", 3, what),
        run_every_hours=_positive_int(data, "run_every_hours", 20, what),
        reference_authors=core_authors,
        extended_authors=extended_authors,
        extended_sweep_weekday=weekday,
        genre_categories=_str_list(data, "genre_categories", what),
        no_gos=_str_list(data, "no_gos", what),
        liked_books=_str_list(data, "liked_books", what),
        disliked_books=_str_list(data, "disliked_books", what),
        languages=_languages(data, what),
        sources=data.get("sources") or {},
        contact=str(data["contact"]) if data.get("contact") else None,
    )
    if profile.strong_deal_max_cents >= profile.deal_max_cents:
        raise ConfigError(
            "profile.yaml: strong_deal_max_cents must be below deal_max_cents "
            f"({profile.strong_deal_max_cents} >= {profile.deal_max_cents})"
        )
    if not isinstance(profile.sources, dict):
        raise ConfigError("profile.yaml: 'sources' must be a mapping of source name to options")
    return profile


def load_dismissals(path: Path | None = None) -> dict[str, frozenset[str]]:
    """Suggestions the reader has permanently waved away, per Source::

        beam:
          - "1278797"

    The one config file that is genuinely optional — an absent file just means
    nothing has been dismissed yet.
    """
    path = path or paths.dismissed_path()
    if not path.exists():
        return {}

    data = _load_yaml(path, "dismissed.yaml")
    if not isinstance(data, dict):
        raise ConfigError(f"dismissed.yaml at {path} must map a source name to a list of ids")

    dismissals: dict[str, frozenset[str]] = {}
    for source, ids in data.items():
        if not isinstance(ids, list):
            raise ConfigError(f"dismissed.yaml: entries for {source!r} must be a list")
        dismissals[str(source)] = frozenset(str(item) for item in ids)
    return dismissals


def load_owned(path: Path | None = None) -> list[OwnedBook]:
    """Bücher im Besitz, mit einem Urteil dazu — ``owned.yaml`` (Ticket 21).

    Die Sterne darin sind **Maschinenurteile**. Sie entstanden im Gespräch,
    gegen dasselbe Profil, das das Bewertungstor benutzt, und nicht dadurch,
    dass die Leserin sie vergeben hätte. Der Unterschied ist der Grund, aus dem
    die Herkunft im Schlüssel steht (ADR 17): eine 4 von ihr ist eine Tatsache,
    eine 4 von einem Modell ein Vorschlag.

    Optional wie ``dismissed.yaml``: wer nichts einträgt, besitzt nichts, was
    das Werkzeug wissen müsste.
    """
    path = path or paths.owned_path()
    if not path.exists():
        return []

    data = _load_yaml(path, "owned.yaml")
    if not isinstance(data, list):
        raise ConfigError(f"owned.yaml at {path} must be a list of entries")

    owned: list[OwnedBook] = []
    for index, raw in enumerate(data, start=1):
        what = f"owned.yaml entry #{index}"
        if not isinstance(raw, dict):
            raise ConfigError(f"{what} must be a mapping")
        stars = raw.get("stars")
        if stars is not None and (
            not isinstance(stars, int) or isinstance(stars, bool) or not 0 <= stars <= 5
        ):
            raise ConfigError(f"{what}: 'stars' must be a whole number from 0 to 5, got {stars!r}")
        owned.append(
            OwnedBook(
                title=str(_require(raw, "title", what)).strip(),
                author=str(raw.get("author") or "").strip() or None,
                stars=stars,
                why=str(raw["why"]).strip() if raw.get("why") else None,
                hinweis=str(raw["hinweis"]).strip() if raw.get("hinweis") else None,
            )
        )
    return owned


def load_watchlist(path: Path | None = None) -> list[WatchlistEntry]:
    path = path or paths.watchlist_path()
    data = _load_yaml(path, "watchlist.yaml")
    if isinstance(data, dict):
        data = data.get("entries")
    if not isinstance(data, list):
        raise ConfigError(f"watchlist.yaml at {path} must be a list of entries")

    entries: list[WatchlistEntry] = []
    for index, raw in enumerate(data, start=1):
        what = f"watchlist.yaml entry #{index}"
        if not isinstance(raw, dict):
            raise ConfigError(f"{what} must be a mapping")
        links = raw.get("resolved_links") or {}
        if not isinstance(links, dict):
            raise ConfigError(f"{what}: 'resolved_links' must be a mapping of source to URL")
        # Blank-but-present fields are a common hand-editing slip; treating them
        # as absent keeps every consumer from having to re-check.
        author = str(raw.get("author") or "").strip() or None
        entries.append(
            WatchlistEntry(
                title=str(_require(raw, "title", what)).strip(),
                author=author,
                check_library=bool(raw.get("check_library", True)),
                check_shop=bool(raw.get("check_shop", True)),
                active=bool(raw.get("active", True)),
                notes=str(raw["notes"]) if raw.get("notes") else None,
                resolved_links={str(k): str(v) for k, v in links.items()},
            )
        )

    seen: set[str] = set()
    for entry in entries:
        if entry.key in seen:
            raise ConfigError(
                f"watchlist.yaml has a duplicate entry: {entry.title} / {entry.author}"
            )
        seen.add(entry.key)
    return entries
