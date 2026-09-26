"""The single entrypoint: ``python -m ebook_watchlist.run`` (ADR 4, ADR 12).

Cron, the CLI, and later the UI's "Run now" button all land here. There is no
scheduler inside — the host's scheduler decides *when*, this decides *what
changed*.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from filelock import FileLock, Timeout

from . import gate, paths
from .bundle_deal import advantage_finder
from .cleaning import clean_blurb
from .config import (
    ConfigError,
    Settings,
    load_dismissals,
    load_owned,
    load_seed,
    load_settings,
    load_watchlist,
)
from .configuration import NotSeeded
from .configuration import load as load_configuration
from .covers import CoverStore, fetch_for_books, fetch_for_candidates, file_name
from .diff import compute_deltas, keys_of, suppress_unseeded_interests
from .digest import GateNote, build_digest
from .dismissals import dismissed_books
from .dismissals import resolve as resolve_dismissals
from .dnb import Dnb, OriginalTitles
from .evidence import gather as gather_evidence
from .facets import load_weights
from .http import HttpClient, RateLimited, build_user_agent
from .models import Observation, SourceFailure
from .portrait import VocabularyError, fingerprint, load_vocabulary
from .portrayer import build_portrayer
from .render import render_html, render_text
from .seed import sow
from .sources import build_sources
from .sources.base import RunContext
from .store import ENTRY_TRIGGER, Store

EXIT_OK = 0
EXIT_ALREADY_RUNNING = 0
EXIT_CONFIG_ERROR = 2
EXIT_SOURCE_FAILURE = 1

EXTENDED_SWEEP_KEY = "last_extended_sweep"
#: Past this, the weekly sweep happens on the next Run whatever day it is.
EXTENDED_SWEEP_OVERDUE = timedelta(days=7)


def _survive_a_narrow_console() -> None:
    """Never lose a whole Run's Digest to a console that cannot render an arrow.

    Windows still hands us a cp1252 stdout, which raises on "→" and on the
    warning sign in the error heading. The HTML digest is always written in full
    UTF-8; this only softens what the terminal gets.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream not reconfigurable
            pass


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ebw", description="Run one check cycle.")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "doctor", "sources", "seed", "dismissals", "rate", "judge"],
        help=(
            "'run' checks everything; 'doctor' only asks each Source whether it still "
            "parses; 'sources' lists them and can pause one; 'seed' imports the YAML "
            "files into the database once; 'dismissals' resolves the leftover product "
            "numbers from dismissed.yaml into Book Relations; 'judge' holds named "
            "titles or a YAML list against the Reading Profile"
        ),
    )
    parser.add_argument(
        "titles",
        nargs="*",
        metavar="TITEL",
        help=(
            "für 'judge': Titel, jeder als eigenes Argument, mit Autor:in nach einem "
            "senkrechten Strich (\"Der Schwarm | Frank Schätzing\")"
        ),
    )
    parser.add_argument(
        "--datei",
        dest="file",
        type=Path,
        default=None,
        metavar="PFAD",
        help=(
            "für 'judge': eine YAML-Liste von Einträgen mit title und author; stars und "
            "why werden hineingeschrieben, Kommentare und Reihenfolge bleiben"
        ),
    )
    parser.add_argument(
        "--nur-bekannte",
        dest="known_only",
        action="store_true",
        help="für 'judge': das Modell nicht fragen — ein Titel ohne Steckbrief bleibt offen",
    )
    parser.add_argument(
        "--anzahl",
        dest="count",
        type=int,
        default=10,
        metavar="N",
        help="wie viele Vorschläge 'rate' beschreibt (Voreinstellung 10)",
    )
    parser.add_argument("--enable", metavar="QUELLE", help="eine pausierte Quelle wieder aufnehmen")
    parser.add_argument("--disable", metavar="QUELLE", help="eine Quelle pausieren")
    parser.add_argument(
        "--skip-probes",
        action="store_true",
        help="do not self-check the Sources before the Run",
    )
    parser.add_argument(
        "--fruehestens-nach",
        dest="not_within_hours",
        type=float,
        default=None,
        metavar="STUNDEN",
        help=(
            "nicht laufen, wenn der letzte Lauf weniger als so viele Stunden "
            "her ist. Voreinstellung: die Kadenz aus dem Profil "
            "('run_every_hours') bei '--trigger cron', sonst keine Grenze. "
            "0 schaltet sie ab"
        ),
    )
    parser.add_argument(
        "--trigger",
        default="cli",
        choices=["cli", "cron", "ui"],
        help="what fired this Run; recorded on the run row",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="override the data directory for this invocation",
    )
    return parser.parse_args(argv)


def _probe(
    sources, store: Store | None = None, now: datetime | None = None
) -> tuple[list, list[SourceFailure]]:
    """Ask every Source whether its parsers still recognise a known-good page.

    A Source that fails here is sat out for the Run: half-reading a redesigned
    site would write nonsense into the Snapshot and quietly poison every future
    diff (ADR 7).

    The outcome is recorded rather than printed and forgotten (Ticket 03), so
    the Dashboard can tell a Source that just broke from one that has been
    broken for a week.
    """
    healthy, failures = [], []
    at = now or datetime.now()
    for source in sources:
        message = None
        try:
            source.probe()
        except Exception as exc:  # noqa: BLE001 - deliberate: isolate one Source
            message = f"Selbsttest fehlgeschlagen — {type(exc).__name__}: {exc}"
            failures.append(SourceFailure(source=source.name, message=message))
        else:
            healthy.append(source)
        if store is not None:
            store.record_probe(source.name, ok=message is None, error=message, now=at)
    return healthy, failures


def _partition_enabled(sources, store: Store) -> tuple[list, list[str]]:
    """Sources the reader has paused are sat out — and named for it.

    Silently skipping one would look exactly like a quiet day at that shop,
    which is the failure mode this tool exists to avoid (ADR 15).
    """
    active, paused = [], []
    for source in sources:
        if store.is_enabled(source.name):
            active.append(source)
        else:
            paused.append(source.name)
    return active, paused


def _collect(
    sources, settings, watchlist, context: RunContext
) -> tuple[list[Observation], list[SourceFailure]]:
    """Poll every Source. One failing Source does not stop the others (ADR 7)."""
    observations: list[Observation] = []
    failures: list[SourceFailure] = []
    for source in sources:
        try:
            observations.extend(source.collect(settings, watchlist, context))
        except Exception as exc:  # noqa: BLE001 - deliberate: isolate one Source
            failures.append(
                SourceFailure(source=source.name, message=f"{type(exc).__name__}: {exc}")
            )
    # One place, every Source, before anything is compared or stored. Cleaning
    # inside each parser would mean two implementations that drift (Ticket 16).
    return [_cleaned(observation) for observation in observations], failures


def _cleaned(observation: Observation) -> Observation:
    blurb = clean_blurb(observation.blurb)
    if blurb == observation.blurb:
        return observation
    return replace(observation, blurb=blurb)


def _ask_the_library(
    store: Store, client: HttpClient, settings: Settings, *, spent: int = 0
) -> None:
    """Die DNB nach dem fragen, was keine Quelle sagt (Ticket 42).

    Einmal je ISBN und höchstens ``dnb_budget`` je Lauf. Der Rückstand von
    388 ISBNs ist damit nach acht Läufen abgearbeitet, ohne dass ein einzelner
    Lauf auffällt — dieselbe Bauweise wie ``rating_budget`` beim Tor.

    Die Zurückhaltung hat keinen technischen Grund: die DNB dokumentiert
    **keine** zulässige Anfragefrequenz. Wo niemand sagt, was erlaubt ist,
    fragt man wenig — dieselbe Überlegung wie bei der Pause zwischen zwei
    Shop-Anfragen.

    Läuft **hinter** dem Snapshot, wie die Titelbilder: eine unerreichbare
    Bibliothek darf keine Geschichte kosten.

    ``spent`` ist, was die Zuordnung der Watchlist-Titel schon gefragt hat
    (#77): ein Budget je Lauf, nicht eines je Stelle.
    """
    rest = settings.dnb_budget - spent
    pending = store.isbns_without_dnb(settings.slug, rest) if rest > 0 else []
    if not pending:
        _series_from_dnb(store)
        return

    library = Dnb(client=client)
    now = datetime.now()
    found = 0
    for isbn in pending:
        try:
            record = library.about(isbn)
        except RateLimited:
            # 429 heisst Halt, und zwar fuer alles Weitere.
            print("DNB: gedrosselt — Rest übersprungen", file=sys.stderr)
            break
        except Exception as exc:  # noqa: BLE001 - eine Auskunft, nicht der Lauf
            print(f"DNB {isbn}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        # Auch das Schweigen wird festgehalten, sonst fragt der naechste Lauf
        # dieselbe ISBN erneut.
        store.save_dnb(isbn, record, now)
        found += 1 if record else 0
    print(f"DNB: {len(pending)} gefragt, {found} beantwortet")
    _series_from_dnb(store)


def _series_from_dnb(store: Store) -> None:
    """Reihe und Band auf die Buecher, auch wenn heute nichts gefragt wurde.

    Was frueher von der DNB kam, hat vielleicht noch kein Buch erreicht — und
    ein Lauf ohne neue ISBN kehrt vorher zurueck. Kostet keine Anfrage (#10).
    """
    if series_count := store.series_from_dnb():
        print(f"DNB: {series_count} Reihen übernommen")


def _without_foreign_languages(store: Store, deltas, settings: Settings) -> list:
    """Was die DNB ausdruecklich in einer fremden Sprache fuehrt, faellt weg (#10).

    Dieselbe Regel wie im Stapel, aus einer Stelle (`language.is_foreign`):
    unbekannt ist nie fremd, und ein Watchlist-Titel bleibt immer.
    """
    from .language import is_foreign, language_finder

    language_of = language_finder(store)
    kept = [d for d in deltas if not is_foreign(d.current, settings, language_of)]
    if gone := len(deltas) - len(kept):
        print(f"Sprache: {gone} Funde in anderen Sprachen übergangen")
    return kept


def _without_ai_authors(store: Store, deltas) -> list:
    """Wer seine Texte von einer Maschine schreiben laesst, faellt weg (#31).

    Vor dem Tor, aus demselben Grund wie die Sprache: ein solches Buch ist
    kein Kandidat, gleich was es kostet — und sechsundzwanzig davon hatten je
    einen Modellaufruf verbraucht, bevor sie unter der Schwelle landeten.
    """
    from .authorship import ai_authors, is_ai_authored

    authors = ai_authors(store)
    if not authors:
        return list(deltas)
    kept = [d for d in deltas if not is_ai_authored(d.current, authors)]
    if gone := len(deltas) - len(kept):
        print(f"Autorenschaft: {gone} KI-erzeugte Funde uebergangen")
    return kept


def _apply_gate(store: Store, deltas, settings: Settings, now: datetime, sources=()):
    """Entdeckungen gegen das Leseprofil prüfen (ADR 19, ADR 33, #48).

    Ohne Profil wird nicht geurteilt, und der Tagesbericht sagt es. Ohne
    Schlüssel gibt es keine neuen Steckbriefe, aber was schon einen hat, wird
    gerechnet — der Rest bleibt unbewertet und wird gezeigt.

    Die Quellen gehen mit, damit das Tor den ganzen Klappentext holen kann,
    bevor es beschreibt: die Kachel einer Trefferliste trägt im Median 197
    Zeichen und ist zu 85 % abgeschnitten, die Detailseite rund das Zehnfache.
    Es sind höchstens so viele Anfragen wie das Budget Bücher zulässt.
    """
    from .judging import rated_books
    from .taste_form import learn

    try:
        vocabulary = load_vocabulary()
        weights = load_weights()
    except (VocabularyError, OSError, KeyError, ValueError, yaml.YAMLError) as exc:
        print(f"Bewertung übersprungen: {exc}", file=sys.stderr)
        return deltas, gate.unrated_report(deltas)

    profile = store.reading_profile(settings.slug)
    portrayer = build_portrayer(settings.rating_model, vocabulary) if profile is not None else None
    form = (
        learn(
            profile,
            rated_books(store, settings.slug, vocabulary, weights, fingerprint(vocabulary)),
            vocabulary,
            weights,
        )
        if profile is not None
        else None
    )

    if portrayer is not None:
        # Die zweite Stufe (#76): unbekannt trotz Klappentext, dann einmal mit
        # dem Anfang der Leseprobe, sofern der Shop eine verlinkt.
        from .sample import fetcher

        portrayer.samples = fetcher(HttpClient(user_agent=build_user_agent(settings.contact)))

    kept, report = gate.apply(
        deltas,
        store=store,
        profile=profile,
        vocabulary=vocabulary,
        weights=weights,
        portrayer=portrayer.portray_finds if portrayer is not None else None,
        threshold=weights.gate_stars,
        budget=settings.rating_budget,
        now=now,
        form=form,
        evidence=(
            lambda observations: gather_evidence(store, settings, observations, sources)
        )
        if sources
        else None,
    )
    if report.held_back or report.over_budget:
        # Für das Log. Was die Leserin sehen muss, steht im Digest — stderr
        # wirft ein Cron-Job weg (Ticket 20).
        print(
            f"Bewertungstor: {report.held_back} unter {report.threshold} Sternen "
            f"zurückgehalten, {report.over_budget} über dem Budget "
            f"({report.rated} beschrieben, {report.reused} aus dem Speicher)",
            file=sys.stderr,
        )
    return kept, report


def _write_html(digest, generated_at: datetime) -> Path:
    directory = paths.digests_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"digest-{generated_at:%Y-%m-%d}.html"
    if target.exists():
        # A second Run on the same day must not silently erase the first one's
        # digest; the plain daily name stays the one a cron job produces.
        target = directory / f"digest-{generated_at:%Y-%m-%d-%H%M}.html"
    target.write_text(render_html(digest), encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    _survive_a_narrow_console()
    args = _parse_args(argv)
    if args.data_dir is not None:
        os.environ["EBW_DATA_DIR"] = str(args.data_dir)

    try:
        settings = load_settings()
        # Die Watchlist-Datei ist Saatgut (ADR 10) und wird nur noch fuer den
        # Import gebraucht. Sie weiterhin bei jedem Lauf zu verlangen hiesse,
        # dass "nur noch Saatgut" nicht stimmt: wer sie nach dem Import
        # loescht, koennte gar nicht mehr laufen.
        watchlist = load_watchlist() if args.command == "seed" else []
        client = HttpClient(user_agent=build_user_agent(settings.contact))
        sources = build_sources(settings, client)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    paths.data_dir().mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(paths.lock_path()), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        print("another Run is already in progress — exiting", file=sys.stderr)
        return EXIT_ALREADY_RUNNING

    try:
        if args.command == "doctor":
            return _doctor(sources)
        if args.command == "sources":
            return _sources(sources, enable=args.enable, disable=args.disable)
        if args.command == "seed":
            return _seed(settings, watchlist)
        if args.command == "dismissals":
            return _dismissals(settings, sources)
        if args.command == "rate":
            return _rate(settings, args.count, sources, client)
        if args.command == "judge":
            return _judge(settings, args.titles, args.file, ask=not args.known_only)
        if too_soon := _too_soon(settings, datetime.now(), _gap(args, settings)):
            print(too_soon)
            return EXIT_OK
        try:
            return _run(
                settings,
                watchlist,
                sources,
                client=client,
                trigger=args.trigger,
                skip_probes=args.skip_probes,
            )
        except NotSeeded as exc:
            # Kein stiller Rückfall auf YAML: sonst liefe der Lauf monatelang
            # gegen eine Datei, von der alle annehmen, sie sei abgelöst.
            print(f"{exc}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
    finally:
        lock.release()


def _gap(args, settings) -> float:
    """Wie viele Stunden dieser Aufruf abwarten muss.

    Die Taktung steckt nicht im Wirt, sondern hier: das Journal weiss, wann
    zuletzt gelaufen wurde, und die Kadenz steht im Profil
    (``run_every_hours``). Ein Wirt darf deshalb dumm sein und oft rufen — er
    fragt, der Lauf entscheidet. Das ist zugleich der einzige Weg, auf dem
    eine geaenderte Kadenz sofort gilt, ohne dass irgendwo ein Zeitplan
    nachgezogen werden muss (ADR 4).

    Die Grenze gilt der **Maschine**, nicht der Leserin. Wer `ebw` tippt oder
    auf der Startseite "Lauf jetzt starten" drueckt, hat sich entschieden —
    ein Knopf, der den ganzen Tag ueber nichts tut, ist kaputt, egal wie gut
    der Grund ist. Ausdruecklich gesetzt gewinnt die Zahl in jedem Fall.
    """
    if args.not_within_hours is not None:
        return args.not_within_hours
    return settings.run_every_hours if args.trigger == "cron" else 0


def _too_soon(settings, now: datetime, hours: float) -> str:
    """Ob seit dem letzten Rundgang zu wenig Zeit vergangen ist.

    Zurück kommt der Satz, der das erklärt — leer heißt: los.

    Gezählt werden nur Rundgänge. Ein **Eintrag** ist keiner: den schreiben der
    enge Lauf und das Nachladen eines Klappentextes, und zählten sie mit, fiele
    der tägliche Lauf aus, weil die Leserin abends einmal „nachsehen" gedrückt
    hat (dieselbe Unterscheidung wie in ``last_finished_run``).

    Kein Fehler, sondern eine Auskunft: der Rückgabewert bleibt 0. Wer zu dicht
    taktet, tut ja nichts Falsches — er ist nur zu eifrig, und eine
    Fehlermeldung dafür machte aus jedem zweiten Cron-Lauf einen Alarm.
    """
    if hours <= 0:
        return ""
    last = next(
        (
            run
            for run in Store(paths.db_path()).recent_runs(settings.slug, limit=20)
            if run.trigger != ENTRY_TRIGGER
        ),
        None,
    )
    if last is None or last.started_at is None:
        return ""
    if now - last.started_at >= timedelta(hours=hours):
        return ""
    return (
        f"Lauf übersprungen — der letzte ist von {last.started_at:%d.%m. %H:%M} "
        f"und damit keine {hours:g} Stunden her (--fruehestens-nach 0 läuft trotzdem)."
    )


def _dismissals(settings, sources) -> int:
    """Die übrig gebliebenen Produktnummern zu Beziehungen machen (Ticket 17).

    Bewusst ein eigener Unterbefehl und kein Lauf: eine Handvoll Nummern einmal
    aufzulösen rechtfertigt kein Fegen aller Regale, und ein Lauf würde die
    Arbeit bei jedem Aufruf wiederholen.

    Eine pausierte Quelle wird nicht gefragt (Ticket 23).
    """
    store = Store(paths.db_path())
    # Der Schalter gilt auch hier. Er heisst "frag diese Quelle nicht", und
    # eine Ausnahme fuer einen einmaligen Auflöser stand nirgends geschrieben
    # (Ticket 23). Was ohne Anfrage geht, geht weiterhin; der Rest wird
    # gemeldet, statt still auszufallen.
    active, paused = _partition_enabled(sources, store)
    report = resolve_dismissals(
        store,
        active,
        load_dismissals(),
        profile_slug=settings.slug,
        now=datetime.now(),
        paused=paused,
    )

    for row in report.resolved:
        mark = "schon aufgelöst" if row.already_known else "aufgelöst      "
        author = f" — {row.author}" if row.author else ""
        print(f"  {mark}  {row.source}:{row.source_item_id}  {row.title}{author}")
    print(f"\n  {report.requests} Anfrage(n) gestellt, {len(report.resolved)} Nummer(n) zugeordnet")

    if report.needs_attention:
        print(f"\n  {len(report.unresolved)} Nummer(n) ließen sich nicht auflösen:")
        for line in report.unresolved:
            print(f"    - {line}")
        # Ein Rückgabewert ungleich null, damit ein Cron-Job nicht "fertig"
        # meldet, während eine Ablehnung unter den Tisch gefallen ist.
        return EXIT_SOURCE_FAILURE
    return EXIT_OK


def _record_foreign_ratings(store: Store, observations: Sequence[Observation]) -> None:
    """Was fremde Leser:innen sagen, neben das eigene Urteil stellen (Ticket 54).

    Keine eigene Tabelle: ``rating`` ist bereits nach ``(subject, origin)``
    geschluesselt, und genau darauf kommt eine weitere Quelle spaeter dazu
    (ADR 19). Die Bibliothek ist die vierte Herkunft neben Modell, Gespraech
    und Leserin.

    ``profile_version`` ist **0**: eine fremde Durchschnittsnote ist kein
    Urteil gegen das Leseprofil und veraltet deshalb auch nicht mit einer
    neuen Fassung.

    Die Anzahl steht daneben und wird nicht in eine Stufe uebersetzt: gemessen
    an Google Books ruhen fuenf von sieben Bewertungen unseres Korpus auf einer
    **einzigen** Stimme (``docs/research/reader-ratings-sources.md``). Wo die
    Anzahl fehlt, wird nichts geschrieben — ein Schnitt ohne sie ist keine
    Auskunft.
    """
    from .ratings import BY_ONLEIHE_READERS, subject_of

    now = datetime.now()
    for observation in observations:
        if observation.rating is None or not observation.rating_votes:
            continue
        votes = observation.rating_votes
        store.put_rating(
            subject_of(observation),
            stars=observation.rating,
            # "belegt" heisst im Schema "aus Daten oder geprueter Quelle
            # nachgewiesen" — und das ist eine Durchschnittsnote der Onleihe,
            # gleich wie viele Stimmen dahinterstehen. Wie belastbar sie ist,
            # sagt nicht diese Stufe, sondern die Zahl daneben. Hier stand
            # vorher eine Grenze von zehn Stimmen: eine erfundene Zahl, und
            # damit genau das, was beim Grillen ausgeschlossen wurde.
            confidence="belegt",
            reason=f"Durchschnitt der Leser:innen aus {votes} Stimmen",
            profile_version=0,
            now=now,
            origin=BY_ONLEIHE_READERS,
            votes=votes,
        )


def _fetch_suggestion_covers(
    store: Store, settings: Settings, client: HttpClient
) -> None:
    """Titelbilder fuer den Stapel — genau fuer die, die stehen bleiben.

    Anders als ``covers.fetch_for_books``: eine Entdeckung hat keine ``book``-Zeile, an
    der ein Dateiname haengen koennte. Der Name ergibt sich aus der Adresse
    (``covers.file_name``), die Seite sieht ihn auf der Platte nach — geholt
    werden muss er trotzdem einmal.

    Gefragt wird der Stapel selbst, nicht die eben gefaellten Urteile: was
    unter der Schwelle liegt, steht dort ohnehin nicht mehr drin (Ticket 19).
    Damit haengen die Bilder am Stapel und nicht daran, dass gerade etwas zu
    beurteilen war — sonst bekaeme ein vollstaendig beurteilter Stapel nie
    seine Bilder.
    """
    from .web import triage

    covers = CoverStore(paths.covers_dir())
    keys = {item.key for item in triage.pending(store, settings, limit=10_000).items}
    pending = [
        observation.cover_url
        for observation in store.latest_discoveries(settings.slug)
        if f"{observation.source}:{observation.source_item_id}" in keys
        and observation.cover_url
    ]
    if not pending:
        return

    # Nur, was noch nicht daliegt, kostet eine Anfrage — und nur das heißt "geholt".
    missing = [url for url in dict.fromkeys(pending) if not covers.has(file_name(url))]
    print(f"{len(missing)} von {len(set(pending))} Titelbildern fehlen …")
    fetched = 0
    for url in missing:
        try:
            if covers.fetch(client, url):
                fetched += 1
        except RateLimited:
            print("Titelbilder: der Shop drosselt — Rest übersprungen", file=sys.stderr)
            return
        except Exception as exc:  # noqa: BLE001 - bewusst: ein Bild ist Beiwerk
            print(f"Titelbild: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"  {fetched} geholt")


def _rate(settings: Settings, how_many: int, sources, client: HttpClient) -> int:
    """Den Rückstand beschreiben, für den Stapel (Ticket 19, #48).

    Das Tor im Lauf sieht nur **Erstsichtungen**. Was einmal im Snapshot steht,
    erzeugt beim nächsten Lauf kein Delta mehr — der angesammelte Rückstand ist
    für das Tor also unsichtbar, und ohne diesen Weg bliebe er es für immer.
    Seit #48 legt dieser Weg die fehlenden **Steckbriefe** an, statt Sterne zu
    vergeben: das Urteil rechnet der Code.

    Beschrieben wird nur, was auch gemeldet würde — der Stapel folgt derselben
    Regel wie der Digest (Schnäppchen oder ausleihbar). Von 358 offenen Funden
    bleiben damit 107; die übrigen 251 kosten weder eine Anfrage noch einen
    Steckbrief, denn sie erreichen die Leserin ohnehin nicht. Fällt ein Preis,
    sind sie wieder da.

    Für genau diese Bücher wird der **ganze** Klappentext nachgeladen. Die
    Kachel trägt im Median 197 Zeichen und ist zu 85 % abgeschnitten; die
    Detailseite trägt rund das Zehnfache. Eine Anfrage je Buch, und nur hier —
    beim Sammeln wären es dreihundert.

    Ohne Leseprofil wird nichts beschrieben (ADR 33, Punkt 8): es gäbe nichts,
    wogegen sich rechnen ließe.
    """
    from .judging import load_judge
    from .ratings import subject_of
    from .web import triage

    store = Store(paths.db_path())
    judge = load_judge(store, settings.slug)
    if judge is None:
        print(
            "Kein Leseprofil (oder kein lesbares Vokabular): erst die Erstaufnahme "
            "machen, dann gibt es etwas, wogegen sich rechnen ließe.",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR
    portrayer = build_portrayer(settings.rating_model, judge.vocabulary)
    if portrayer is None:
        print(
            "Kein Weg zum Modell: weder ANTHROPIC_API_KEY noch eine angemeldete "
            "Claude-Code-Installation gefunden.",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    # Der ganze Stapel, nicht die erste Seite: er ist bestbewertet-zuerst
    # sortiert, Unbeschriebenes steht hinten. Auf ``how_many`` gekürzt wird
    # deshalb erst **nach** dem Aussortieren — sonst bekäme dieser Weg genau
    # die Bücher, die schon einen Steckbrief haben, und nie die offenen.
    pile = triage.pending(store, settings, limit=10_000).items
    keys = {item.key for item in pile}
    finds = [
        observation
        for observation in store.latest_discoveries(settings.slug)
        if f"{observation.source}:{observation.source_item_id}" in keys
    ]

    # Ein Steckbrief zum heutigen Vokabular steht: ihn noch einmal zu holen
    # kostet eine Detailseite und einen Modellaufruf für dieselbe Antwort. Ein
    # Steckbrief zu einem *älteren* Vokabular gilt nicht mehr und wird neu
    # angelegt (ADR 33).
    portraits = judge.portraits(store, [subject_of(o) for o in finds])
    finds = [o for o in finds if subject_of(o) not in portraits]
    if not finds:
        print("Nichts offen — jeder Vorschlag im Stapel hat einen Steckbrief.")
        _fetch_suggestion_covers(store, settings, client)
        return EXIT_OK
    finds = finds[:how_many]

    finds = gather_evidence(store, settings, finds, sources)
    print(f"{len(finds)} Vorschläge …")

    now = datetime.now()
    distribution: dict[int, int] = {}
    violations = flawed = 0
    described = portrayer.portray_finds(finds)
    for observation in finds:
        portrait = described.get(observation.key)
        if portrait is None:
            print(f"  ohne Steckbrief  {observation.title[:52]}")
            continue
        store.put_portrait(subject_of(observation), portrait, now=now)
        violations += len(portrait.violations)
        flawed += bool(portrait.violations)
        verdict = judge.verdict(portrait)
        if verdict is None:
            print(f"  unbekannt  {observation.title[:52]}")
            continue
        distribution[verdict.stars] = distribution.get(verdict.stars, 0) + 1
        print(
            f"  {'★' * verdict.stars}{'☆' * (5 - verdict.stars)} {verdict.percent:>3} %"
            f" {observation.title[:52]}"
        )
        # Ein fehlender Kurztext kostet den Steckbrief nichts, aber er wird
        # genannt: still fehlend hieße, eine Lücke auf der Seite nie zu bemerken.
        print(f"            {portrait.pitch or 'OHNE PITCH'}")
        if portrait.violations:
            print(f"            Regelverstoß: {'; '.join(portrait.violations)}")

    # Eine Bewertung, die nicht unterscheidet, ist wertlos — deshalb steht die
    # Verteilung da und nicht nur die Zahl der Steckbriefe.
    summary = ", ".join(
        f"{stars}★ ×{count}" for stars, count in sorted(distribution.items(), reverse=True)
    )
    print(f"\n  Verteilung: {summary or 'keine'}")
    print(f"  Regelverstöße: {violations} in {flawed} von {len(described)} Steckbriefen")

    _fetch_suggestion_covers(store, settings, client)
    return EXIT_OK


def _judge(settings: Settings, titles: Sequence[str], file: Path | None, *, ask: bool) -> int:
    """Genannte Titel oder eine YAML-Liste gegen das Profil halten (#67).

    Der Code urteilt; das Modell beschreibt höchstens, was noch keinen
    Steckbrief hat, und auch das nur auf Wunsch. Ohne Profil wird nichts
    geraten (ADR 33, Punkt 8).
    """
    from .judge_titles import Entry, judge_titles, read_entries, update_yaml
    from .judging import load_judge

    if file is None and not titles:
        print("Nichts zu beurteilen: Titel nennen oder --datei angeben.", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    try:
        text = file.read_text(encoding="utf-8") if file is not None else ""
        entries = read_entries(text) if file is not None else []
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    for named in titles:
        title, _, author = named.partition("|")
        entries.append(Entry(title.strip(), author.strip() or None))

    store = Store(paths.db_path())
    judge = load_judge(store, settings.slug)
    if judge is None:
        print(
            "Kein Leseprofil (oder kein lesbares Vokabular): erst die Erstaufnahme "
            "machen, dann gibt es etwas, wogegen sich rechnen ließe.",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR
    portrayer = build_portrayer(settings.rating_model, judge.vocabulary) if ask else None
    if ask and portrayer is None:
        print("Kein Weg zum Modell: nur beurteilt, was einen Steckbrief hat.", file=sys.stderr)

    results = judge_titles(store, entries, judge, portrayer, now=datetime.now(), ask=ask)
    for result in results:
        name = result.entry.title + (f" | {result.entry.author}" if result.entry.author else "")
        if result.verdict is None:
            print(f"  {result.source:<10} {name}")
            continue
        verdict = result.verdict
        print(f"  {'★' * verdict.stars}{'☆' * (5 - verdict.stars)} {name}  ({result.source})")
        print(f"            {verdict.why}")
        if verdict.pitch:
            print(f"            {verdict.pitch}")

    if file is not None:
        file.write_text(update_yaml(text, results), encoding="utf-8")
        judged = sum(1 for r in results if r.verdict is not None)
        print(f"\n  {file}: {judged} von {len(results)} Einträgen beurteilt")
    return EXIT_OK


def _seed(settings, watchlist) -> int:
    """Die YAML-Dateien in die Datenbank überführen (Ticket 05).

    Wiederholbar: ein zweiter Aufruf legt nichts doppelt an und setzt nichts
    zurück, was inzwischen woanders geändert wurde.
    """
    store = Store(paths.db_path())
    seed_data = load_seed()
    if seed_data.is_empty:
        # Sonst stehen unten vier Nullen, und das sieht aus wie ein Fehler
        # statt wie eine fehlende Datei (#36).
        print(f"  seed.yaml nennt nichts ({paths.seed_path()}) — nur watchlist.yaml wird gelesen.")
    report = sow(store, settings, seed_data, watchlist, owned=load_owned())

    print(f"  {report.books:>4}  Bücher neu angelegt")
    print(f"  {report.relations:>4}  Beziehungen")
    print(f"  {report.interests:>4}  Interessen")
    if report.needs_attention:
        print(f"\n  {len(report.unresolved)} Einträge brauchen Aufmerksamkeit:")
        for item in report.unresolved:
            print(f"    - {item}")
        print("\n  Nicht geraten: diese Zeilen nennen kein Buch, das sich")
        print("  zweifelsfrei auflösen ließe (ADR 8).")
    return EXIT_OK


def _sources(sources, *, enable: str | None, disable: str | None) -> int:
    """List the Sources with their health, and pause or resume one.

    The switch exists so a Source that has broken can be stopped without
    editing a file and without commenting out configuration — which is how a
    pause becomes permanent by forgetting.
    """
    store = Store(paths.db_path())
    known = {source.name for source in sources}
    now = datetime.now()

    for name, wanted in ((enable, True), (disable, False)):
        if name is None:
            continue
        if name not in known:
            print(
                f"unbekannte Quelle {name!r} (bekannt: {', '.join(sorted(known))})",
                file=sys.stderr,
            )
            return EXIT_CONFIG_ERROR
        store.set_enabled(name, wanted, now=now)
        print(f"{name}: {'aufgenommen' if wanted else 'pausiert'}")

    for source in sources:
        row = store.source(source.name)
        if row is None:
            print(f"  ?         {source.name}  (noch nie gelaufen)")
            continue
        if not row.enabled:
            state = "pausiert"
        elif row.last_probe_ok is None:
            state = "?       "
        else:
            state = "ok      " if row.last_probe_ok else "FEHLER  "
        seen = f"{row.last_probe_at:%d.%m. %H:%M}" if row.last_probe_at else "nie"
        streak = (
            f"  seit {row.consecutive_failures} Prüfungen" if row.consecutive_failures > 1 else ""
        )
        print(f"  {state}  {source.name}  zuletzt {seen}{streak}")
        if row.last_error:
            print(f"            {row.last_error}")
    return EXIT_OK


def _doctor(sources) -> int:
    """Say, per Source, whether its parsers still recognise a known-good page.

    The verdict is written down as well as printed (Ticket 03): a doctor run is
    the same evidence as a Run's probe, and throwing it away is why the
    Dashboard had to infer health from Run failures.
    """
    store = Store(paths.db_path())
    active, paused = _partition_enabled(sources, store)
    _, failures = _probe(active, store, datetime.now())

    broken = {failure.source for failure in failures}
    for source in sources:
        if source.name in paused:
            state = "pausiert"
        elif source.name in broken:
            state = "FEHLER  "
        else:
            state = "ok      "
        row = store.source(source.name)
        streak = ""
        if row is not None and row.consecutive_failures > 1:
            streak = f"  (seit {row.consecutive_failures} Prüfungen)"
        print(f"  {state}  {source.name}{streak}")
    for failure in failures:
        print(f"\n{failure.source}: {failure.message}", file=sys.stderr)
    return EXIT_SOURCE_FAILURE if failures else EXIT_OK


def _should_sweep_extended(settings, store: Store, now: datetime) -> bool:
    """The weekly long tail, on the configured day.

    A Run that never happened must not cost a whole week, so a sweep that is
    more than seven days overdue happens on the next Run whatever day it is —
    the same schedule-statelessness the diff has (ADR 4).
    """
    if not settings.extended_authors:
        return False
    last = store.get_state(settings.slug, EXTENDED_SWEEP_KEY)
    if last is None:
        return True
    if now - last >= EXTENDED_SWEEP_OVERDUE:
        return True
    return now.weekday() == settings.extended_sweep_weekday and last.date() != now.date()


def _run(
    settings,
    watchlist,
    sources,
    *,
    client: HttpClient,
    trigger: str,
    skip_probes: bool = False,
) -> int:
    store = Store(paths.db_path())
    started_at = datetime.now()

    # Die Konfiguration kommt aus der Datenbank; YAML ist Saatgut (ADR 10).
    # Kein stiller Rueckfall: eine leere Datenbank heisst "noch nicht
    # importiert", und das gehoert gesagt.
    configured = load_configuration(store, settings)
    settings = configured.settings
    watchlist = configured.watchlist

    # Signing the row with our pid is what lets anyone else — the Dashboard's
    # "Run now" panel, above all — tell a Run still working from one that was
    # killed before it could write an ending (Ticket 10).
    run_id = store.start_run(settings.slug, trigger, started_at, pid=os.getpid())

    sources, paused = _partition_enabled(sources, store)
    for name in paused:
        print(f"{name}: pausiert — übersprungen", file=sys.stderr)

    probe_failures: list[SourceFailure] = []
    if not skip_probes:
        sources, probe_failures = _probe(sources, store, started_at)

    sweep_extended = _should_sweep_extended(settings, store, started_at)
    context = RunContext(
        profile_slug=settings.slug,
        store=store,
        now=started_at,
        # Aus den Beziehungen, nicht aus der YAML: eine Ablehnung gilt dem Buch
        # und damit jeder Quelle, nicht der Nummer eines Shops (Ticket 17).
        dismissed=dismissed_books(store, settings.slug),
        sweep_extended=sweep_extended,
        interests={
            (row.key, row.value): row.id
            for table in (configured.author_interests, configured.genre_category_interests)
            for row in table.values()
        },
        # Der Originaltitel einer uebersetzten Ausgabe, fuer Watchlist-Titel
        # in der Originalsprache (#77) — aus demselben Budget wie das
        # Nachschlagen hinter dem Snapshot.
        original_titles=OriginalTitles(
            store, Dnb(client=client), budget=settings.dnb_budget, now=started_at
        ),
    )
    observations, failures = _collect(sources, settings, watchlist, context)
    failures = [*probe_failures, *failures]
    if sweep_extended and not failures:
        store.set_state(settings.slug, EXTENDED_SWEEP_KEY, started_at)
    # Ein Watchlist-Eintrag kommt ohne ISBN aus der YAML; die Beobachtung
    # bringt sie mit. Erst dadurch bekommt das Buch die Identitaet, an der zwei
    # Quellen sich treffen koennen (ADR 18).
    for observation in observations:
        if observation.book_id and observation.isbn:
            store.learn_isbn(observation.book_id, observation.isbn)
    previous = store.latest_observations(settings.slug, keys_of(observations))
    # Angesaet ist je *Quelle*: ein Interesse, das beam kennt, ist der Onleihe
    # deswegen nicht vertraut. Vorher genuegte "irgendeine Quelle", und die
    # zweite Quelle haette dieselbe Backlist noch einmal gemeldet.
    seeded = {
        interest_id
        for source_name, interest_id in context.swept
        if store.is_interest_seeded(interest_id, source_name)
    }
    # Einmal gebaut, von Vergleich und Tagesbericht benutzt: sonst meldet der
    # Stapel einen Buendelvorteil, den der Tagesbericht nicht kennt.
    bundle_advantage = advantage_finder(store, settings)
    deltas = suppress_unseeded_interests(
        compute_deltas(observations, previous, settings, bundle_advantage),
        context.origin,
        seeded,
    )

    store.append(run_id, settings.slug, observations, started_at)

    # Erst die Geschichte, dann das Beiwerk. Vorher standen die Titelbilder
    # davor, und ein 403 auf ein Bild riss den Lauf ab, bevor eine einzige
    # Beobachtung geschrieben war — dieselbe Regel wie beim Tor eine Zeile
    # weiter unten: ein Ausfall kostet nie Geschichte.
    fetch_for_books(store, client, observations)
    _record_foreign_ratings(store, observations)
    fetch_for_candidates(store, settings.slug, client)
    _ask_the_library(store, client, settings, spent=context.original_titles.spent)

    # Hinter der DNB-Abfrage, denn erst jetzt ist die Sprache neuer Funde
    # bekannt — und vor dem Tor, damit ein fremdsprachiger Fund kein Urteil
    # kostet (#10).
    deltas = _without_foreign_languages(store, deltas, settings)
    deltas = _without_ai_authors(store, deltas)

    # Das Tor sitzt hinter dem Snapshot: ein Ausfall kostet ein Urteil, nie
    # Geschichte. Und hinter der Preisregel: ein Buch zu bewerten, das ohnehin
    # niemand zu sehen bekommt, waere Verschwendung (ADR 19).
    deltas, gate_report = _apply_gate(store, deltas, settings, started_at, sources)

    # Erst hinter dem Tor, denn erst dann steht fest, was im Stapel bleibt.
    # Bis hierher wurden Bilder fuer Funde nur beim Beurteilen des Rueckstands
    # geholt — das Tor im Lauf beurteilt aber selbst, und was es durchliess,
    # stand danach ohne Bild da.
    _fetch_suggestion_covers(store, settings, client)

    for source_name, interest_id in context.swept:
        store.mark_interest_seeded(interest_id, source_name, now=started_at)

    last_run = store.last_finished_run(settings.slug, run_id)
    digest = build_digest(
        profile_name=settings.name,
        generated_at=started_at,
        since=last_run.started_at if last_run else None,
        deltas=deltas,
        failures=failures,
        attention=context.attention,
        settings=settings,
        judgements=gate_report.judgements,
        gate=GateNote(
            held_back=gate_report.held_back,
            threshold=gate_report.threshold,
            over_budget=gate_report.over_budget,
            unrated=gate_report.unrated,
            no_profile=gate_report.no_profile,
            short_stories=gate_report.short_stories,
        ),
    )

    finished_at = datetime.now()
    status = "error" if failures else "ok"
    store.finish_run(
        run_id,
        status=status,
        delta_count=len(deltas),
        finished_at=finished_at,
        error="; ".join(f.message for f in failures) or None,
    )

    # Nothing changed and nothing broke — stay quiet.
    if digest.is_empty:
        return EXIT_OK

    print(render_text(digest))
    _write_html(digest, started_at)
    return EXIT_SOURCE_FAILURE if failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
