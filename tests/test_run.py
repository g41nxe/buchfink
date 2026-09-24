"""End-to-end walking-skeleton tests: config in, Snapshot written, Digest out."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from filelock import FileLock

from conftest import needs_vocabulary, portrayer_via
from ebook_watchlist import paths
from ebook_watchlist.digest import build_digest
from ebook_watchlist.models import SourceFailure
from ebook_watchlist.run import EXIT_CONFIG_ERROR, EXIT_OK, EXIT_SOURCE_FAILURE, main
from ebook_watchlist.store import Store


def digest_files(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "digests").glob("*.html"))


def test_the_first_run_reports_the_watched_titles_it_found(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Watchlist Entry is news at any price (ADR 19). Discoveries are not:
    the shelves are seeded quietly and stay out of this first Digest."""
    assert main([]) == EXIT_OK

    out = capsys.readouterr().out
    assert "Erster Check" in out
    assert "Der Schwarm" in out
    assert len(digest_files(data_dir)) == 1
    assert paths.db_path().exists()


def test_second_unchanged_run_stays_silent(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([])
    capsys.readouterr()
    after_first = digest_files(data_dir)

    assert main([]) == EXIT_OK
    assert capsys.readouterr().out == ""
    assert digest_files(data_dir) == after_first


def test_a_price_drop_produces_a_digest(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    capsys.readouterr()

    fixture = data_dir / "fake-source.yaml"
    fixture.write_text(
        fixture.read_text(encoding="utf-8").replace("price_cents: 1299", "price_cents: 499"),
        encoding="utf-8",
    )

    assert main([]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Der Schwarm" in out
    assert "12,99 € → 4,99 €" in out
    assert "Änderungen seit letztem Check" in out

    # The first Run already wrote today's Digest, so the second is kept beside
    # it rather than overwriting it.
    today = f"digest-{datetime.now():%Y-%m-%d}"
    written = digest_files(data_dir)
    assert len(written) == 2
    assert {path.name for path in written} == {
        f"{today}.html",
        f"{today}-{datetime.now():%H%M}.html",
    }
    dropped = next(path for path in written if path.name != f"{today}.html")
    assert "4,99" in dropped.read_text(encoding="utf-8")


def test_availability_change_produces_a_digest(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([])
    capsys.readouterr()

    fixture = data_dir / "fake-source.yaml"
    fixture.write_text(
        fixture.read_text(encoding="utf-8").replace(
            "availability: unavailable", "availability: available"
        ),
        encoding="utf-8",
    )

    assert main([]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Die sieben Schwestern" in out
    assert "jetzt verfügbar" in out


def test_a_broken_source_is_reported_not_swallowed(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (data_dir / "fake-source.yaml").write_text("not: a list\n", encoding="utf-8")

    assert main([]) == EXIT_SOURCE_FAILURE
    captured = capsys.readouterr()
    assert "⚠️ Fehler" in captured.out
    assert "must be a list of items" in captured.out
    assert len(digest_files(data_dir)) == 1


def test_missing_config_fails_loudly(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (data_dir / "settings.yaml").unlink()
    assert main([]) == EXIT_CONFIG_ERROR
    assert "config error" in capsys.readouterr().err


def test_a_second_concurrent_run_backs_off(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    held = FileLock(str(paths.lock_path()), timeout=0)
    held.acquire()
    try:
        assert main([]) == EXIT_OK
        assert "already in progress" in capsys.readouterr().err
    finally:
        held.release()


def test_output_survives_a_console_that_cannot_render_the_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows hands us a cp1252 stdout, which raises on the price arrow. Losing
    a whole Run's Digest at the very last step is not an acceptable failure."""
    from ebook_watchlist.run import _survive_a_narrow_console

    class Narrow:
        def __init__(self) -> None:
            self.kwargs: dict = {}

        def reconfigure(self, **kwargs) -> None:
            self.kwargs = kwargs

    class Plain:
        """A stream with no reconfigure at all — must simply be left alone."""

    narrow, plain = Narrow(), Plain()
    monkeypatch.setattr("ebook_watchlist.run.sys.stdout", narrow)
    monkeypatch.setattr("ebook_watchlist.run.sys.stderr", plain)

    _survive_a_narrow_console()

    assert narrow.kwargs == {"errors": "replace"}


def test_a_run_fetches_the_images_of_its_own_pile(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Bilder des Stapels wurden nur beim Beurteilen des Rueckstands
    geholt. Das Tor im Lauf beurteilt aber selbst — was es durchliess, stand
    danach ohne Bild da, bis zufaellig jemand den Rueckstand beurteilte. Im
    echten Stapel hatten deshalb neun von sechsundzwanzig Funden keins, und
    alle neun stammten aus demselben Lauf."""
    from ebook_watchlist import run as run_modul

    gerufen: list[str] = []
    monkeypatch.setattr(
        run_modul,
        "_fetch_suggestion_covers",
        lambda store, settings, client: gerufen.append(settings.slug),
    )

    assert main([]) == EXIT_OK
    assert gerufen == ["test"]


def test_run_journal_records_every_run(data_dir: Path) -> None:
    main([])
    main([])

    from ebook_watchlist.store import RunRow, Store

    store = Store(paths.db_path())
    with store.session() as session:
        runs = session.query(RunRow).order_by(RunRow.id).all()
        assert [run.status for run in runs] == ["ok", "ok"]
        assert all(run.finished_at is not None for run in runs)
        assert all(run.trigger == "cli" for run in runs)


def test_the_gate_gets_the_sources_from_the_run(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beide Enden sind geprueft — das Tor ruft den Rueckruf, das Nachladen
    legt keinen Rundgang an. Dazwischen liegt die Weitergabe der Quellen, und
    faellt sie beim naechsten Umbau weg, urteilt das Tor stillschweigend
    wieder auf dem Anriss."""
    from ebook_watchlist import gate
    from ebook_watchlist import run as run_modul

    gereicht: list[bool] = []
    echtes_tor = gate.apply

    def beobachtet(deltas, **kwargs):
        gereicht.append(kwargs.get("evidence") is not None)
        return echtes_tor(deltas, **kwargs)

    monkeypatch.setattr(run_modul.gate, "apply", beobachtet)
    monkeypatch.setattr(run_modul, "build_portrayer", portrayer_via(object()))

    assert main([]) == EXIT_OK
    assert gereicht == [True]


def test_reloading_a_blurb_does_not_look_like_a_run(data_dir: Path) -> None:
    """Der Klappentext wird jetzt mitten im Lauf nachgeladen, und dabei
    entsteht eine eigene Zeile im Journal — die Beobachtung muss ja an einem
    Lauf haengen. Sie darf aber nicht als *der* letzte Lauf gelten: sie ist
    frueher fertig als der Rundgang, der sie angestossen hat, und die
    Startseite haette danach "zuletzt geprueft … 0 Aenderungen" gemeldet.

    Dieselbe Unterscheidung wie beim engen Lauf aus Ticket 51: ein Eintrag ist
    kein Rundgang."""
    from datetime import datetime

    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.evidence import gather as _with_evidence
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.sources.fake import FakeSource
    from ebook_watchlist.store import ENTRY_TRIGGER, Store

    store, settings = Store(paths.db_path()), load_settings()
    rundgang = store.start_run(settings.slug, "cli", datetime.now())
    store.finish_run(rundgang, status="ok", delta_count=3, finished_at=datetime.now())
    angerissen = Observation(
        source="fake",
        source_item_id="fake-2",
        title="Der Schwarm",
        match_reason=MatchReason.GENRE_CATEGORY,
        price_cents=1299,
        blurb="Manche Menschen haben Geheimnisse…",
    )

    quelle = FakeSource(data_dir / "fake-source.yaml")
    _with_evidence(store, settings, [angerissen], [quelle])

    laeufe = store.recent_runs(settings.slug)
    assert laeufe[0].id == rundgang, "das Nachladen gilt als letzter Lauf"
    assert all(lauf.trigger != ENTRY_TRIGGER for lauf in laeufe)


def test_a_second_digest_on_the_same_day_does_not_erase_the_first(data_dir: Path) -> None:
    """A manual re-run must not silently overwrite what the cron job produced."""
    from ebook_watchlist.run import _write_html

    digests = data_dir / "digests"
    digest = build_digest(
        profile_name="T",
        generated_at=datetime(2026, 9, 4, 6, 0),
        since=None,
        deltas=[],
        failures=[SourceFailure(source="x", message="kaputt")],
    )

    first = _write_html(digest, datetime(2026, 9, 4, 6, 0))
    second = _write_html(digest, datetime(2026, 9, 4, 18, 30))

    assert first.name == "digest-2026-09-04.html"
    assert second.name == "digest-2026-09-04-1830.html"
    assert first.exists() and second.exists()
    assert {p.name for p in digests.iterdir()} == {first.name, second.name}


# --- den Rueckstand beschreiben (Ticket 19, #48) ---------------------------


@needs_vocabulary
def test_describing_the_backlog_asks_only_about_what_has_no_portrait(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Der Stapel ist bestbewertet-zuerst sortiert, Unbeschriebenes steht hinten.
    Wer die erste Seite nimmt, bekommt genau die Buecher, die schon einen
    Steckbrief haben — und die offenen nie. ``ebw rate`` legt seit #48 die
    fehlenden Steckbriefe an, statt Sterne zu vergeben."""
    from conftest import describe, give_profile
    from ebook_watchlist import run as run_module
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.portrait import Portrait, Trait, fingerprint, load_vocabulary
    from ebook_watchlist.store import Store

    now = datetime(2026, 9, 5, 9, 0)
    store = Store(paths.db_path())

    def fund(item_id: str) -> Observation:
        return Observation(
            source="beam",
            source_item_id=item_id,
            title=f"Fund {item_id}",
            author="Wer Auch Immer",
            match_reason=MatchReason.GENRE_CATEGORY,
            price_cents=399,
            blurb="Ein Schiff, allein im Dunkeln. " * 20,
            url=f"https://beam.invalid/{item_id}",
        )

    run_id = store.start_run("test", "cli", now)
    store.append(run_id, "test", [fund("alt"), fund("neu")], now)
    give_profile(store)
    describe(store, "item:beam:alt", 4, "Kurz und gut.")
    vocabulary = load_vocabulary()
    asked: list[Observation] = []

    def portray_finds(observations):
        asked.extend(observations)
        traits = tuple(Trait(t, f"Satz zu {t}", "wissen") for t in ("quest", "adventure"))
        return {
            o.key: Portrait(known=True, fingerprint=fingerprint(vocabulary), pitch="Neu.",
                            traits=traits)
            for o in observations
        }

    monkeypatch.setattr(
        run_module, "build_portrayer",
        lambda model=None, vocabulary=None: SimpleNamespace(
            vocabulary=vocabulary, portray_finds=portray_finds
        ),
    )

    assert main(["rate"]) == EXIT_OK

    assert [o.source_item_id for o in asked] == ["neu"]
    assert store.portrait("item:beam:neu", fingerprint(vocabulary)) is not None
    out = capsys.readouterr().out
    assert "Fund neu" in out and "Neu." in out and "51 %" in out  # zwei Muster: 0,51


@needs_vocabulary
def test_describing_the_backlog_needs_a_profile(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ohne Profil wird nichts beurteilt (ADR 33, Punkt 8) — und nichts
    beschrieben, das sich nicht rechnen liesse."""
    from ebook_watchlist import run as run_module

    monkeypatch.setattr(run_module, "build_portrayer", portrayer_via(object()))

    assert main(["rate"]) == EXIT_CONFIG_ERROR
    assert "Leseprofil" in capsys.readouterr().err


# --- ein Rundgang am Tag reicht ---------------------------------------------


def test_a_cron_run_right_after_another_is_skipped(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Der Ausloeser, der zu dicht taktet: das Einstiegsskript des Containers
    ruft bei jedem Start. Fuenf Neubauten an einem Nachmittag ergaben fuenf
    volle Laeufe gegen die echten Quellen in 25 Minuten."""
    assert main(["--trigger", "cron"]) == EXIT_OK
    vorher = len(Store(paths.db_path()).recent_runs("test"))

    assert main(["--trigger", "cron"]) == EXIT_OK

    assert "übersprungen" in capsys.readouterr().out
    # Kein zweiter Eintrag im Journal: ein uebersprungener Lauf ist keiner.
    assert len(Store(paths.db_path()).recent_runs("test")) == vorher


def test_the_reader_is_not_held_back(data_dir: Path) -> None:
    """Die Grenze gilt der Maschine. Wer tippt oder drueckt, hat sich
    entschieden — ein Knopf, der den ganzen Tag nichts tut, ist kaputt."""
    assert main(["--trigger", "cron"]) == EXIT_OK
    vorher = len(Store(paths.db_path()).recent_runs("test"))

    assert main(["--trigger", "ui"]) == EXIT_OK

    assert len(Store(paths.db_path()).recent_runs("test")) > vorher


def test_the_cadence_from_the_profile_is_what_counts(data_dir: Path) -> None:
    """Die Kadenz ist eine Einstellung, keine Konstante im Code — derselbe
    Abstand entscheidet je nach Profil verschieden."""
    store = Store(paths.db_path())
    store.start_run("test", "cron", datetime.now() - timedelta(hours=2))
    vorher = len(store.recent_runs("test"))

    # Voreinstellung sind 20 Stunden; zwei sind zu wenig.
    assert main(["--trigger", "cron"]) == EXIT_OK
    assert len(Store(paths.db_path()).recent_runs("test")) == vorher

    profil = (data_dir / "settings.yaml").read_text(encoding="utf-8")
    (data_dir / "settings.yaml").write_text(
        profil + "\nrun_every_hours: 1\n", encoding="utf-8"
    )

    assert main(["--trigger", "cron"]) == EXIT_OK
    assert len(Store(paths.db_path()).recent_runs("test")) > vorher


def test_the_gap_can_be_named_and_switched_off(data_dir: Path) -> None:
    assert main(["--trigger", "cron"]) == EXIT_OK
    vorher = len(Store(paths.db_path()).recent_runs("test"))

    # Ausdruecklich gesetzt gewinnt die Zahl — in beide Richtungen.
    assert main(["--trigger", "ui", "--fruehestens-nach", "20"]) == EXIT_OK
    assert len(Store(paths.db_path()).recent_runs("test")) == vorher

    assert main(["--trigger", "cron", "--fruehestens-nach", "0"]) == EXIT_OK
    assert len(Store(paths.db_path()).recent_runs("test")) > vorher


def test_a_find_in_another_language_never_reaches_the_gate(data_dir: Path) -> None:
    """Zwischen DNB-Abfrage und Bewertungstor: was die DNB ausdruecklich
    englisch fuehrt, kostet kein Urteil (#10). Der Watchlist-Titel in
    derselben Sprache bleibt."""
    from datetime import datetime

    from ebook_watchlist import paths
    from ebook_watchlist import run as run_modul
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.dnb import Record
    from ebook_watchlist.models import Delta, DeltaKind, MatchReason, Observation
    from ebook_watchlist.store import Store

    now = datetime(2026, 9, 19, 12, 0)
    store = Store(paths.db_path())
    store.save_dnb("9780000000001", Record(title="A Book", language="eng"), now)

    def neu(nummer: str, grund: MatchReason) -> Delta:
        return Delta(kind=DeltaKind.FIRST_SEEN, previous=None, current=Observation(
            source="beam", source_item_id=nummer, title="A Book", match_reason=grund,
            isbn="9780000000001"))

    fund, gewollt = neu("1", MatchReason.GENRE_CATEGORY), neu("2", MatchReason.WATCHLIST)

    bleibt = run_modul._without_foreign_languages(store, [fund, gewollt], load_settings())

    assert bleibt == [gewollt]


def test_the_portrayer_gets_keywords_and_original_title_but_no_sample(data_dir: Path) -> None:
    """Die Belege für den Steckbrief (#17) kommen aus zwei Ecken: Schlagwörter
    von der Detailseite, Originaltitel und weitere Schlagwörter aus dem, was die
    DNB schon gesagt hat. Die Leseprobe wird seit #68 nicht mehr geholt — auch
    nicht, wenn die Quelle einen Verweis darauf trägt. Keine Anfrage an die DNB
    hier: gefragt wird sie an ihrer eigenen Stelle im Lauf, mit ihrem Budget."""
    from ebook_watchlist import paths
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.dnb import Record
    from ebook_watchlist.evidence import gather as _with_evidence
    from ebook_watchlist.models import MatchReason, Observation
    from ebook_watchlist.sources.base import Item
    from ebook_watchlist.store import Store

    store, settings = Store(paths.db_path()), load_settings()
    store.save_dnb(
        "9783641171421",
        Record(original_title="Dark Matter", keywords=("Quantenphysik", "Space Opera")),
        datetime.now(),
    )

    class Client:
        def get_bytes(self, url: str) -> bytes:  # pragma: no cover - darf nie gerufen werden
            raise AssertionError(f"die Leseprobe wird nicht mehr geholt: {url}")

    class Quelle:
        name = "beam"
        client = Client()

        def item(self, source_item_id: str) -> Item:
            return Item(
                source_item_id=source_item_id,
                title="Der Zeitenläufer",
                blurb="Der ganze Klappentext.",
                sample_url="https://beam.invalid/probe.epub",
                keywords=("Space Opera", "Dune"),
            )

    fund = Observation(
        source="beam",
        source_item_id="7",
        title="Der Zeitenläufer",
        match_reason=MatchReason.GENRE_CATEGORY,
        isbn="9783641171421",
        blurb="Der ganze Klappentext.",
    )

    (belegt,) = _with_evidence(store, settings, [fund], [Quelle()])

    assert belegt.keywords == ("Space Opera", "Dune", "Quantenphysik")
    assert belegt.original_title == "Dark Matter"


def test_ai_authored_finds_cost_no_judgement(data_dir: Path) -> None:
    """Vor dem Tor, aus demselben Grund wie die Sprache (#31).

    Gemessen am Bestand: sechsundzwanzig Urteile waren fuer Titel eines
    einzigen KI-Autors ausgegeben, im Schnitt fuer 1,8 Sterne.
    """
    from datetime import datetime

    from ebook_watchlist import paths
    from ebook_watchlist import run as run_modul
    from ebook_watchlist.models import Delta, DeltaKind, MatchReason, Observation
    from ebook_watchlist.store import Store

    now = datetime(2026, 9, 23, 12, 0)
    store = Store(paths.db_path())
    # Eine gesehene Detailseite — mehr braucht die Ableitung nicht.
    run_id = store.start_run("test", "cli", now)
    store.append(run_id, "test", [Observation(
        source="beam", source_item_id="0", title="Mit Detailseite", author="Matze K",
        match_reason=MatchReason.GENRE_CATEGORY,
        blurb="Matze K. ist ein deutscher KI-Autor.")], now)

    def neu(nummer: str, autor: str, grund: MatchReason) -> Delta:
        return Delta(kind=DeltaKind.FIRST_SEEN, previous=None, current=Observation(
            source="beam", source_item_id=nummer, title=f"Buch {nummer}", author=autor,
            match_reason=grund, blurb="Ein kurzer Teaser."))

    ki = neu("1", "Matze K", MatchReason.GENRE_CATEGORY)
    echt = neu("2", "Wer Auch Immer", MatchReason.GENRE_CATEGORY)
    eigener = neu("3", "Matze K", MatchReason.WATCHLIST)

    bleibt = run_modul._without_ai_authors(store, [ki, echt, eigener])

    # Der Titel ohne eigene Selbstauskunft faellt ueber die Autorenschaft weg;
    # was die Leserin selbst benannt hat, bleibt.
    assert bleibt == [echt, eigener]


# --- das Tor im Lauf urteilt im Code (#48) ---------------------------------


def _finds():
    from ebook_watchlist.models import Delta, DeltaKind, MatchReason, Observation

    def find(number: str) -> Delta:
        return Delta(
            DeltaKind.FIRST_SEEN,
            Observation(
                source="beam", source_item_id=number, title=f"Fund {number}",
                match_reason=MatchReason.GENRE_CATEGORY, isbn=f"97800000000{number}",
            ),
            None,
        )

    return find("1"), find("2")


def _portraits(vocabulary, by_title):
    from ebook_watchlist.portrait import Portrait, Trait, fingerprint

    def portrayer(observation):
        terms = by_title[observation.title]
        return Portrait(
            known=True, fingerprint=fingerprint(vocabulary), pitch="Ein Buch.",
            traits=tuple(Trait(t, f"Satz zu {t}", "wissen") for t in terms),
        )

    return portrayer


def _profile(store):
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.facets import Facet, Liked, ReadingProfile

    store.put_reading_profile(
        load_settings().slug,
        ReadingProfile(
            facets=(Facet(("brooding", "harsh"), ("Leichenblässe", "Sharp Objects")),),
            counterweights=(),
            liked=(Liked("brooding"), Liked("harsh")),
        ),
        cause="Test", now=datetime(2026, 9, 24, 12, 0),
    )


@needs_vocabulary
def test_the_run_judges_finds_from_the_profile_in_the_database(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ebook_watchlist import run as run_modul
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.portrait import load_vocabulary

    store, settings = Store(paths.db_path()), load_settings()
    _profile(store)
    vocabulary = load_vocabulary()
    good, poor = _finds()
    portrayer = _portraits(
        vocabulary, {"Fund 1": ("brooding", "gritty"), "Fund 2": ("leisurely", "lyrical")}
    )
    monkeypatch.setattr(
        run_modul, "build_portrayer",
        lambda model=None, vocabulary=None: SimpleNamespace(
            portray_finds=lambda observations: {o.key: portrayer(o) for o in observations}
        ),
    )

    kept, report = run_modul._apply_gate(store, [good, poor], settings, datetime.now())

    assert kept == [good]
    assert (report.held_back, report.rated, report.threshold) == (1, 2, 3)
    assert report.judgements[good.current.key].stars >= 4


@needs_vocabulary
def test_the_run_without_a_profile_judges_nothing_and_asks_nobody(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ebook_watchlist import run as run_modul
    from ebook_watchlist.config import load_settings

    def never(model=None, vocabulary=None):
        raise AssertionError("ohne Profil braucht es keinen Steckbrief-Ersteller")

    monkeypatch.setattr(run_modul, "build_portrayer", never)
    store, settings = Store(paths.db_path()), load_settings()
    deltas = list(_finds())

    kept, report = run_modul._apply_gate(store, deltas, settings, datetime.now())

    assert kept == deltas and report.no_profile


@needs_vocabulary
def test_the_run_without_a_rater_still_judges_what_has_a_portrait(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ebook_watchlist import run as run_modul
    from ebook_watchlist.config import load_settings
    from ebook_watchlist.portrait import load_vocabulary
    from ebook_watchlist.ratings import subject_of

    store, settings = Store(paths.db_path()), load_settings()
    _profile(store)
    vocabulary = load_vocabulary()
    good, poor = _finds()
    described = _portraits(vocabulary, {"Fund 1": ("brooding", "gritty"),
                                        "Fund 2": ("leisurely", "lyrical")})
    store.put_portrait(subject_of(poor.current), described(poor.current),
                       now=datetime.now())
    monkeypatch.setattr(run_modul, "build_portrayer", lambda model=None, vocabulary=None: None)

    kept, report = run_modul._apply_gate(store, [good, poor], settings, datetime.now())

    assert kept == [good]
    assert (report.held_back, report.unrated) == (1, 1)
