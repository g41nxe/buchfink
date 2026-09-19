"""The single entrypoint: ``python -m ebook_watchlist.run`` (ADR 4, ADR 12).

Cron, the CLI, and later the UI's "Run now" button all land here. There is no
scheduler inside — the host's scheduler decides *when*, this decides *what
changed*.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from filelock import FileLock, Timeout

from . import gate, paths
from .bundle_deal import advantage_finder
from .cleaning import clean_blurb
from .config import ConfigError, Profile, load_dismissals, load_owned, load_profile, load_watchlist
from .configuration import NotSeeded
from .configuration import load as load_configuration
from .covers import CoverStore, fetch_for_books
from .covers import file_name as cover_file_name
from .diff import compute_deltas, keys_of, suppress_unseeded_interests
from .digest import GateNote, build_digest
from .dismissals import dismissed_books
from .dismissals import resolve as resolve_dismissals
from .http import HttpClient, RateLimited, build_user_agent
from .models import Observation, SourceFailure
from .rating import DEFAULT_THRESHOLD, RatingUnavailable, build_rater, load_leseprofil
from .render import render_html, render_text
from .seed import seed
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
        choices=["run", "doctor", "sources", "seed", "dismissals", "rate"],
        help=(
            "'run' checks everything; 'doctor' only asks each Source whether it still "
            "parses; 'sources' lists them and can pause one; 'seed' imports the YAML "
            "files into the database once; 'dismissals' resolves the leftover product "
            "numbers from dismissed.yaml into Book Relations"
        ),
    )
    parser.add_argument(
        "--anzahl",
        type=int,
        default=10,
        metavar="N",
        help="wie viele Vorschläge 'rate' beurteilt (Voreinstellung 10)",
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
    sources, profile, watchlist, context: RunContext
) -> tuple[list[Observation], list[SourceFailure]]:
    """Poll every Source. One failing Source does not stop the others (ADR 7)."""
    observations: list[Observation] = []
    failures: list[SourceFailure] = []
    for source in sources:
        try:
            observations.extend(source.collect(profile, watchlist, context))
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


def _ask_the_library(store: Store, client: HttpClient, profile: Profile) -> None:
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
    """
    from .dnb import Dnb

    offen = store.isbns_without_dnb(profile.slug, profile.dnb_budget)
    if not offen:
        _series_from_dnb(store)
        return

    bibliothek = Dnb(client=client)
    now = datetime.now()
    gefunden = 0
    for isbn in offen:
        try:
            datensatz = bibliothek.about(isbn)
        except RateLimited:
            # 429 heisst Halt, und zwar fuer alles Weitere.
            print("DNB: gedrosselt — Rest übersprungen", file=sys.stderr)
            break
        except Exception as exc:  # noqa: BLE001 - eine Auskunft, nicht der Lauf
            print(f"DNB {isbn}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        # Auch das Schweigen wird festgehalten, sonst fragt der naechste Lauf
        # dieselbe ISBN erneut.
        store.save_dnb(isbn, datensatz, now)
        gefunden += 1 if datensatz else 0
    print(f"DNB: {len(offen)} gefragt, {gefunden} beantwortet")
    _series_from_dnb(store)


def _series_from_dnb(store: Store) -> None:
    """Reihe und Band auf die Buecher, auch wenn heute nichts gefragt wurde.

    Was frueher von der DNB kam, hat vielleicht noch kein Buch erreicht — und
    ein Lauf ohne neue ISBN kehrt vorher zurueck. Kostet keine Anfrage (#10).
    """
    if reihen := store.series_from_dnb():
        print(f"DNB: {reihen} Reihen übernommen")


def _without_foreign_languages(store: Store, deltas, profile: Profile) -> list:
    """Was die DNB ausdruecklich in einer fremden Sprache fuehrt, faellt weg (#10).

    Dieselbe Regel wie im Stapel, aus einer Stelle (`language.is_foreign`):
    unbekannt ist nie fremd, und ein Watchlist-Titel bleibt immer.
    """
    from .language import is_foreign, language_finder

    sprache_von = language_finder(store)
    bleibt = [d for d in deltas if not is_foreign(d.current, profile, sprache_von)]
    if weg := len(deltas) - len(bleibt):
        print(f"Sprache: {weg} Funde in anderen Sprachen übergangen")
    return bleibt


def _apply_gate(store: Store, deltas, profile: Profile, now: datetime, sources=()):
    """Entdeckungen gegen das Leseprofil pruefen (ADR 19).

    Ohne Schluessel gibt es kein Tor — dann bleibt alles unbewertet und wird
    gezeigt. Das ist der Zustand vor Ticket 12 und ausdruecklich erlaubt.

    Die Quellen gehen mit, damit das Tor den ganzen Klappentext holen kann,
    bevor es urteilt: die Kachel einer Trefferliste traegt im Median 197
    Zeichen und ist zu 85 % abgeschnitten, die Detailseite rund das Zehnfache.
    Es sind hoechstens so viele Anfragen wie das Budget Buecher zulaesst, und
    es sind dieselben, die der Rueckstands-Schritt sonst spaeter stellt.
    """
    rater = build_rater(profile.rating_model)
    if rater is None:
        return deltas, gate.unrated_report(deltas)
    try:
        _, version = load_leseprofil()
    except RatingUnavailable as exc:
        print(f"Bewertung übersprungen: {exc}", file=sys.stderr)
        return deltas, gate.unrated_report(deltas)

    kept, report = gate.apply(
        deltas,
        store=store,
        rater=rater,
        profile_version=version,
        threshold=DEFAULT_THRESHOLD,
        budget=profile.rating_budget,
        batch_size=profile.rating_batch_size,
        now=now,
        full_blurbs=(
            lambda observations: _with_full_blurbs(store, profile, observations, sources)
        )
        if sources
        else None,
    )
    if report.held_back or report.over_budget:
        # Fuer das Log. Was die Leserin sehen muss, steht im Digest — stderr
        # wirft ein Cron-Job weg (Ticket 20).
        print(
            f"Bewertungstor: {report.held_back} unter {DEFAULT_THRESHOLD} Sternen "
            f"zurückgehalten, {report.over_budget} über dem Budget "
            f"({report.rated} bewertet, {report.reused} aus dem Speicher)",
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
        profile = load_profile()
        # Die Watchlist-Datei ist Saatgut (ADR 10) und wird nur noch fuer den
        # Import gebraucht. Sie weiterhin bei jedem Lauf zu verlangen hiesse,
        # dass "nur noch Saatgut" nicht stimmt: wer sie nach dem Import
        # loescht, koennte gar nicht mehr laufen.
        watchlist = load_watchlist() if args.command == "seed" else []
        client = HttpClient(user_agent=build_user_agent(profile.contact))
        sources = build_sources(profile, client)
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
            return _seed(profile, watchlist)
        if args.command == "dismissals":
            return _dismissals(profile, sources)
        if args.command == "rate":
            return _rate(profile, args.anzahl, sources, client)
        if zu_frueh := _too_soon(profile, datetime.now(), _gap(args, profile)):
            print(zu_frueh)
            return EXIT_OK
        try:
            return _run(
                profile,
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


def _gap(args, profile) -> float:
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
    if args.fruehestens_nach is not None:
        return args.fruehestens_nach
    return profile.run_every_hours if args.trigger == "cron" else 0


def _too_soon(profile, now: datetime, stunden: float) -> str:
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
    if stunden <= 0:
        return ""
    letzter = next(
        (
            run
            for run in Store(paths.db_path()).recent_runs(profile.slug, limit=20)
            if run.trigger != ENTRY_TRIGGER
        ),
        None,
    )
    if letzter is None or letzter.started_at is None:
        return ""
    if now - letzter.started_at >= timedelta(hours=stunden):
        return ""
    return (
        f"Lauf übersprungen — der letzte ist von {letzter.started_at:%d.%m. %H:%M} "
        f"und damit keine {stunden:g} Stunden her (--fruehestens-nach 0 läuft trotzdem)."
    )


def _dismissals(profile, sources) -> int:
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
        profile_slug=profile.slug,
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


def _with_full_blurbs(store: Store, profile: Profile, observations, sources):
    """Den ganzen Klappentext holen — eine Anfrage je Buch, und nur hier.

    Angehängt statt überschrieben: der Snapshot wird nie umgeschrieben
    (ADR 5). Der Shop *hat* das gesagt, nur auf einer anderen Seite, und damit
    ist es eine Beobachtung wie jede andere. Preis und Verfügbarkeit kommen
    ebenfalls von dort — weicht der Preis ab, ist das eine echte Änderung und
    keine erfundene.

    Was schon einen ganzen Klappentext trägt, wird nicht noch einmal geholt.
    """
    from .cleaning import is_truncated

    by_name = {source.name: source for source in sources}
    offen = [o for o in observations if is_truncated(o.blurb) or not o.blurb]
    if not offen:
        return observations

    print(f"{len(offen)} Klappentexte nachladen …")
    now = datetime.now()
    # Als Eintrag, nicht als Rundgang: die Beobachtungen brauchen eine Zeile
    # im Journal, aber diese Zeile darf nicht als *der* letzte Lauf gelten.
    # Seit das Tor die Klappentexte mitten im Lauf nachlaedt, waere sie sonst
    # genau das — frueher fertig als der Rundgang, der sie angestossen hat,
    # und die Startseite meldete "zuletzt geprueft … 0 Aenderungen"
    # (dieselbe Unterscheidung wie beim engen Lauf, Ticket 51).
    run_id = store.start_run(profile.slug, ENTRY_TRIGGER, now, pid=os.getpid())
    geholt: dict[tuple[str, str], Observation] = {}
    frisch: list[Observation] = []
    for observation in offen:
        source = by_name.get(observation.source)
        if source is None:
            continue
        try:
            item = source.item(observation.source_item_id)
        except RateLimited:
            # 429 heisst Halt, und zwar fuer alles Weitere — dieselbe Regel wie
            # bei den Titelbildern und bei der DNB (ADR 7). Seit das Tor die
            # Texte mitten im Lauf nachlaedt, waeren es sonst vierzig
            # abgelehnte Anfragen hintereinander an dieselbe Quelle.
            print("Klappentexte: die Quelle drosselt — Rest übersprungen", file=sys.stderr)
            break
        except Exception as exc:  # noqa: BLE001 - ein Buch, nicht der Stapel
            print(f"  {observation.title[:44]}: {type(exc).__name__}", file=sys.stderr)
            continue
        if item is None or not item.blurb:
            continue
        # Die Detailseite traegt auch das groessere Titelbild (600x600 statt
        # 200x200 auf der Kachel). Sie ist schon geholt — es hier fallen zu
        # lassen hiesse, sie fuer dasselbe Bild ein zweites Mal zu holen.
        voller = replace(
            observation,
            blurb=item.blurb,
            cover_url=item.cover_url or observation.cover_url,
            observed_at=now,
        )
        geholt[observation.key] = voller
        frisch.append(voller)

    if frisch:
        store.append(run_id, profile.slug, frisch, now)
    store.finish_run(run_id, status="ok", delta_count=0, finished_at=datetime.now())
    return [geholt.get(o.key, o) for o in observations]


def _record_foreign_ratings(store: Store, observations: Sequence[Observation]) -> None:
    """Was fremde Leser:innen sagen, neben das eigene Urteil stellen (Ticket 54).

    Keine eigene Tabelle: ``rating`` ist bereits nach ``(subject, origin)``
    geschluesselt, und genau darauf kommt eine weitere Quelle spaeter dazu
    (ADR 19). Die Bibliothek ist die vierte Herkunft neben Modell, Gespraech
    und Leserin.

    ``profile_version`` ist **0**: eine fremde Durchschnittsnote ist kein
    Urteil gegen das Leseprofil und veraltet deshalb auch nicht mit einer
    neuen Fassung. Und ``ebw rate`` schlaegt ausdruecklich ``(subject,
    BY_MODEL)`` nach, sieht diese Zeilen also gar nicht.

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
        stimmen = observation.rating_votes
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
            reason=f"Durchschnitt der Leser:innen aus {stimmen} Stimmen",
            profile_version=0,
            now=now,
            origin=BY_ONLEIHE_READERS,
            votes=stimmen,
        )


def _fetch_candidate_covers(store: Store, profile: Profile, client: HttpClient) -> None:
    """Titelbilder fuer die Ausgaben, zwischen denen die Leserin waehlen soll.

    Ticket 41 haengt die Bildadresse an jeden Kandidaten — vergleichen ist eine
    Frage ans Auge —, aber niemand holte die Bilder: Cover werden aus
    **Beobachtungen** geholt, und ein Kandidat ist keine. Dass es trotzdem
    aussah, als funktioniere es, lag daran, dass die Bilder der ersten
    Kandidatengruppe beim Bauen der Entwuerfe von Hand im Ordner gelandet
    waren.

    Die Oberflaeche holt nichts nach (ADR 3): sie sieht den Namen auf der
    Platte nach, und was fehlt, wird als gezeichneter Ruecken gezeigt. Geholt
    wird deshalb hier, im Lauf.

    Es sind wenige: gezeigt werden nur die Kandidaten, die der Matcher nicht
    auseinanderhalten konnte, hoechstens fuenf je offener Frage. Was schon
    dalag, kostet keine Anfrage — ``CoverStore.fetch`` sieht zuerst nach.
    """
    covers = CoverStore(paths.covers_dir())
    offen: list[str] = []
    for row in store.unsure_links(profile.slug):
        try:
            details = json.loads(row.details or "{}")
        except ValueError:  # pragma: no cover - defekte Zeile
            continue
        for kandidat in details.get("candidates") or []:
            url = kandidat.get("cover_url")
            if url and not covers.has(cover_file_name(url)):
                offen.append(url)
    if not offen:
        return

    print(f"{len(offen)} Titelbilder für offene Zuordnungen …")
    geholt = 0
    for url in dict.fromkeys(offen):
        try:
            if covers.fetch(client, url):
                geholt += 1
        except RateLimited:
            print("Titelbilder: der Shop drosselt — Rest übersprungen", file=sys.stderr)
            return
        except Exception as exc:  # noqa: BLE001 - bewusst: ein Bild ist Beiwerk
            print(f"Titelbild: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"  {geholt} geholt")


def _fetch_suggestion_covers(
    store: Store, profile: Profile, client: HttpClient
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
    keys = {item.key for item in triage.pending(store, profile, limit=10_000).items}
    offen = [
        observation.cover_url
        for observation in store.latest_discoveries(profile.slug)
        if f"{observation.source}:{observation.source_item_id}" in keys
        and observation.cover_url
    ]
    if not offen:
        return

    print(f"{len(offen)} Titelbilder …")
    geholt = 0
    for url in dict.fromkeys(offen):
        try:
            if covers.fetch(client, url):
                geholt += 1
        except RateLimited:
            print("Titelbilder: der Shop drosselt — Rest übersprungen", file=sys.stderr)
            return
        except Exception as exc:  # noqa: BLE001 - bewusst: ein Bild ist Beiwerk
            print(f"Titelbild: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"  {geholt} geholt")


def _rate(profile: Profile, wieviele: int, sources, client: HttpClient) -> int:
    """Den Rückstand beurteilen, ohne eine Quelle zu fragen (Ticket 19).

    Das Tor im Lauf sieht nur **Erstsichtungen**. Was einmal im Snapshot steht,
    erzeugt beim nächsten Lauf kein Delta mehr — der angesammelte Rückstand ist
    für das Tor also unsichtbar, und ohne diesen Weg bliebe er es für immer.

    Beurteilt wird nur, was auch gemeldet würde — der Stapel folgt derselben
    Regel wie der Digest (Schnäppchen oder ausleihbar). Von 358 offenen Funden
    bleiben damit 107; die übrigen 251 kosten weder eine Anfrage noch ein
    Urteil, denn sie erreichen die Leserin ohnehin nicht. Fällt ein Preis, sind
    sie wieder da.

    Für genau diese Bücher wird der **ganze** Klappentext nachgeladen. Die
    Kachel trägt im Median 197 Zeichen und ist zu 85 % abgeschnitten; die
    Detailseite trägt rund das Zehnfache. Eine Anfrage je Buch, und nur hier —
    beim Sammeln wären es dreihundert.
    """
    from .rating import load_leseprofil, rate_in_batches
    from .ratings import BY_MODEL, VIA_BACKLOG, subject_of
    from .web import triage

    store = Store(paths.db_path())
    rater = build_rater(profile.rating_model)
    if rater is None:
        print(
            "Kein Bewerter: weder ANTHROPIC_API_KEY noch eine angemeldete "
            "Claude-Code-Installation gefunden.",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    # Der ganze Stapel, nicht die erste Seite: er ist bestbewertet-zuerst
    # sortiert, Unbeurteiltes steht hinten. Auf ``wieviele`` gekuerzt wird
    # deshalb erst **nach** dem Aussortieren — sonst bekaeme dieser Weg genau
    # die Buecher, die schon ein Urteil haben, und nie die offenen.
    stapel = triage.pending(store, profile, limit=10_000).items
    keys = {item.key for item in stapel}
    beobachtungen = [
        observation
        for observation in store.latest_discoveries(profile.slug)
        if f"{observation.source}:{observation.source_item_id}" in keys
    ]

    # Ein Urteil zur aktuellen Profilversion steht; es noch einmal zu holen
    # kostet eine Detailseite und einen Modellaufruf fuer dieselbe Antwort.
    # Ein Urteil zu einer *aelteren* Version steht nicht mehr fuer den
    # heutigen Geschmack — das wird neu beurteilt (Ticket 25).
    version = load_leseprofil()[1]
    vorhanden = store.ratings_for(subject_of(o) for o in beobachtungen)
    beobachtungen = [
        observation
        for observation in beobachtungen
        if (urteil := vorhanden.get((subject_of(observation), BY_MODEL))) is None
        or urteil.profile_version != version
    ]
    if not beobachtungen:
        print("Nichts offen — jeder Vorschlag im Stapel hat ein Urteil.")
        _fetch_suggestion_covers(store, profile, client)
        return EXIT_OK
    beobachtungen = beobachtungen[:wieviele]

    beobachtungen = _with_full_blurbs(store, profile, beobachtungen, sources)
    print(f"{len(beobachtungen)} Vorschläge, Bündel zu {profile.rating_batch_size} …")
    urteile = rate_in_batches(rater, beobachtungen, size=profile.rating_batch_size)

    now = datetime.now()
    verteilung: dict[int, int] = {}
    for observation in beobachtungen:
        rating = urteile.get(observation.key)
        if rating is None:
            print(f"  ohne Urteil  {observation.title[:52]}")
            continue
        store.put_rating(
            subject_of(observation),
            stars=rating.stars,
            confidence=rating.confidence,
            reason=rating.reason,
            profile_version=rating.profile_version,
            now=now,
            origin=BY_MODEL,
            pitch=rating.pitch,
            via=VIA_BACKLOG,
            hits=rating.hits,
            misses=rating.misses,
        )
        verteilung[rating.stars] = verteilung.get(rating.stars, 0) + 1
        print(
            f"  {'★' * rating.stars}{'☆' * (5 - rating.stars)} {rating.confidence:<9}"
            f" {observation.title[:52]}"
        )
        # Ein fehlender Pitch kostet kein Urteil (die Sterne tragen für sich),
        # aber er wird genannt: still fehlend hiesse, eine Lücke auf der Seite
        # nie zu bemerken.
        print(f"            {rating.pitch or 'OHNE PITCH'}")

    # Eine Bewertung, die nicht unterscheidet, ist wertlos — deshalb steht die
    # Verteilung da und nicht nur die Zahl der Urteile.
    gezaehlt = ", ".join(
        f"{sterne}★ ×{anzahl}" for sterne, anzahl in sorted(verteilung.items(), reverse=True)
    )
    print(f"\n  Verteilung: {gezaehlt or 'keine'}")

    _fetch_suggestion_covers(store, profile, client)
    return EXIT_OK


def _seed(profile, watchlist) -> int:
    """Die YAML-Dateien in die Datenbank überführen (Ticket 05).

    Wiederholbar: ein zweiter Aufruf legt nichts doppelt an und setzt nichts
    zurück, was inzwischen woanders geändert wurde.
    """
    store = Store(paths.db_path())
    report = seed(store, profile, watchlist, owned=load_owned())

    print(f"  {report.books:>4}  Bücher neu angelegt")
    print(f"  {report.relations:>4}  Beziehungen")
    print(f"  {report.interests:>4}  Interessen")
    print(f"  {report.ratings:>4}  Urteile aus owned.yaml (im Gespräch vergeben)")
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


def _should_sweep_extended(profile, store: Store, now: datetime) -> bool:
    """The weekly long tail, on the configured day.

    A Run that never happened must not cost a whole week, so a sweep that is
    more than seven days overdue happens on the next Run whatever day it is —
    the same schedule-statelessness the diff has (ADR 4).
    """
    if not profile.extended_authors:
        return False
    last = store.get_state(profile.slug, EXTENDED_SWEEP_KEY)
    if last is None:
        return True
    if now - last >= EXTENDED_SWEEP_OVERDUE:
        return True
    return now.weekday() == profile.extended_sweep_weekday and last.date() != now.date()


def _run(
    profile,
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
    configured = load_configuration(store, profile)
    profile = configured.profile
    watchlist = configured.watchlist

    # Signing the row with our pid is what lets anyone else — the Dashboard's
    # "Run now" panel, above all — tell a Run still working from one that was
    # killed before it could write an ending (Ticket 10).
    run_id = store.start_run(profile.slug, trigger, started_at, pid=os.getpid())

    sources, paused = _partition_enabled(sources, store)
    for name in paused:
        print(f"{name}: pausiert — übersprungen", file=sys.stderr)

    probe_failures: list[SourceFailure] = []
    if not skip_probes:
        sources, probe_failures = _probe(sources, store, started_at)

    sweep_extended = _should_sweep_extended(profile, store, started_at)
    context = RunContext(
        profile_slug=profile.slug,
        store=store,
        now=started_at,
        # Aus den Beziehungen, nicht aus der YAML: eine Ablehnung gilt dem Buch
        # und damit jeder Quelle, nicht der Nummer eines Shops (Ticket 17).
        dismissed=dismissed_books(store, profile.slug),
        sweep_extended=sweep_extended,
        interests={
            (row.key, row.value): row.id
            for table in (configured.author_interests, configured.thema_interests)
            for row in table.values()
        },
    )
    observations, failures = _collect(sources, profile, watchlist, context)
    failures = [*probe_failures, *failures]
    if sweep_extended and not failures:
        store.set_state(profile.slug, EXTENDED_SWEEP_KEY, started_at)
    # Ein Watchlist-Eintrag kommt ohne ISBN aus der YAML; die Beobachtung
    # bringt sie mit. Erst dadurch bekommt das Buch die Identitaet, an der zwei
    # Quellen sich treffen koennen (ADR 18).
    for observation in observations:
        if observation.book_id and observation.isbn:
            store.learn_isbn(observation.book_id, observation.isbn)
    previous = store.latest_observations(profile.slug, keys_of(observations))
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
    buendelvorteil = advantage_finder(store, profile)
    deltas = suppress_unseeded_interests(
        compute_deltas(observations, previous, profile, buendelvorteil),
        context.origin,
        seeded,
    )

    store.append(run_id, profile.slug, observations, started_at)

    # Erst die Geschichte, dann das Beiwerk. Vorher standen die Titelbilder
    # davor, und ein 403 auf ein Bild riss den Lauf ab, bevor eine einzige
    # Beobachtung geschrieben war — dieselbe Regel wie beim Tor eine Zeile
    # weiter unten: ein Ausfall kostet nie Geschichte.
    fetch_for_books(store, client, observations)
    _record_foreign_ratings(store, observations)
    _fetch_candidate_covers(store, profile, client)
    _ask_the_library(store, client, profile)

    # Hinter der DNB-Abfrage, denn erst jetzt ist die Sprache neuer Funde
    # bekannt — und vor dem Tor, damit ein fremdsprachiger Fund kein Urteil
    # kostet (#10).
    deltas = _without_foreign_languages(store, deltas, profile)

    # Das Tor sitzt hinter dem Snapshot: ein Ausfall kostet ein Urteil, nie
    # Geschichte. Und hinter der Preisregel: ein Buch zu bewerten, das ohnehin
    # niemand zu sehen bekommt, waere Verschwendung (ADR 19).
    deltas, gate_report = _apply_gate(store, deltas, profile, started_at, sources)

    # Erst hinter dem Tor, denn erst dann steht fest, was im Stapel bleibt.
    # Bis hierher wurden Bilder fuer Funde nur beim Beurteilen des Rueckstands
    # geholt — das Tor im Lauf beurteilt aber selbst, und was es durchliess,
    # stand danach ohne Bild da.
    _fetch_suggestion_covers(store, profile, client)

    for source_name, interest_id in context.swept:
        store.mark_interest_seeded(interest_id, source_name, now=started_at)

    last_run = store.last_finished_run(profile.slug, run_id)
    digest = build_digest(
        profile_name=profile.name,
        generated_at=started_at,
        since=last_run.started_at if last_run else None,
        deltas=deltas,
        failures=failures,
        attention=context.attention,
        profile=profile,
        judgements=gate_report.judgements,
        gate=GateNote(
            held_back=gate_report.held_back,
            threshold=DEFAULT_THRESHOLD,
            over_budget=gate_report.over_budget,
            unrated=gate_report.unrated,
            shown_unsure=gate_report.shown_unsure,
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
