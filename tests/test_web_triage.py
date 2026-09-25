"""Der Vorschlagsstapel (Ticket 08).

Der Vorgang, den ein Gespräch am schlechtesten kann und ein Formular am besten.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import describe, give_profile, needs_vocabulary
from ebook_watchlist import paths
from ebook_watchlist.config import load_settings
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.ratings import subject_of
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app, sorting
from ebook_watchlist.web import triage as view

NOW = datetime(2026, 9, 4, 21, 0)


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False, follow_redirects=True)


@pytest.fixture
def db(data_dir: Path) -> Store:
    return Store(paths.db_path())


def found(
    db: Store,
    *,
    item_id: str = "1",
    title: str = "Ein Fund",
    author: str = "Wer Auch Immer",
    price: int | None = 399,
    isbn: str | None = None,
    reason: MatchReason = MatchReason.GENRE_CATEGORY,
    source: str = "beam",
    blurb: str | None = "Ein Schiff, allein im Dunkeln.",
) -> Observation:
    observation = Observation(
        source=source,
        source_item_id=item_id,
        title=title,
        author=author,
        match_reason=reason,
        price_cents=price,
        isbn=isbn,
        blurb=blurb,
        category="belletristik/krimi-thriller/psychothriller",
        url=f"https://beam.invalid/{item_id}",
    )
    run_id = db.start_run("test", "cli", NOW)
    db.append(run_id, "test", [observation], NOW)
    return observation


# --- der Stapel -------------------------------------------------------------


def test_a_discovery_shows_up_with_what_is_known(client: TestClient, db: Store) -> None:
    found(db, title="Der Kannibalenhügel", author="Viktor Sauer")

    body = client.get("/suggestions").text

    assert "Der Kannibalenhügel" in body
    assert "Viktor Sauer" in body
    assert "3,99 €" in body
    assert "Ein Schiff, allein im Dunkeln." in body


def test_the_page_says_why_each_find_is_there(client: TestClient, db: Store) -> None:
    """Dieselben Worte wie im Digest, aus einer Stelle (Ticket 14)."""
    found(db, reason=MatchReason.PROFILE_AUTHOR)
    assert "Autor:in" in client.get("/suggestions").text


def test_junk_never_reaches_the_pile(client: TestClient, db: Store) -> None:
    found(db, item_id="ok", title="Ein echter Fund")
    found(db, item_id="j1", title="3 Gruselkrimis: A / B / C")
    found(db, item_id="j2", title="Gratis dabei", price=0)

    body = client.get("/suggestions").text

    assert "Ein echter Fund" in body
    assert "3 Gruselkrimis" not in body
    # "ausgeblendet" steht seit #31 einmal vor der Aufzaehlung statt am
    # ersten Eintrag — verworfen wird weiterhin nichts.
    assert "ausgeblendet" in body
    assert "Sammelbände und Gratistitel" in body


def test_a_find_in_another_language_leaves_the_pile(client: TestClient, db: Store) -> None:
    """Die DNB fuehrt ihn ausdruecklich englisch — kein Kandidat fuer ein
    deutschsprachiges Profil, und keine Aufgabe (#10)."""
    from ebook_watchlist.dnb import Record

    found(db, item_id="de", title="Ein deutscher Fund", isbn="9783000000001")
    found(db, item_id="en", title="An English Find", isbn="9780000000001")
    db.save_dnb("9783000000001", Record(title="Ein deutscher Fund", language="ger"), NOW)
    db.save_dnb("9780000000001", Record(title="An English Find", language="eng"), NOW)

    body = client.get("/suggestions").text

    assert "Ein deutscher Fund" in body
    assert "An English Find" not in body
    assert "1 in anderen Sprachen" in body


def test_the_pile_can_be_filtered_by_origin(client: TestClient, db: Store) -> None:
    found(db, item_id="a", title="Vom Autor", reason=MatchReason.PROFILE_AUTHOR)
    found(db, item_id="t", title="Vom Thema", reason=MatchReason.GENRE_CATEGORY)

    body = client.get("/suggestions?anlass=profile_author").text

    assert "Vom Autor" in body
    assert "Vom Thema" not in body


def test_a_watchlist_title_is_not_a_suggestion(client: TestClient, db: Store) -> None:
    found(db, title="Beobachtet", reason=MatchReason.WATCHLIST)
    assert "Beobachtet" not in client.get("/suggestions").text


# --- entscheiden ------------------------------------------------------------


def test_a_decision_creates_the_book_and_the_relation(client: TestClient, db: Store) -> None:
    found(db, item_id="7", title="Der Kannibalenhügel", author="Viktor Sauer")

    client.post("/suggestions/decide", data={"kind": "owned", "keys": ["beam:7"]})

    book = next(b for b in db.books() if b.title == "Der Kannibalenhügel")
    kinds = {row.kind for row in db.relations_of("test", book.id) if row.active}
    assert str(RelationKind.OWNED) in kinds


def test_a_decided_find_never_comes_back(client: TestClient, db: Store) -> None:
    found(db, item_id="7", title="Der Kannibalenhügel")

    client.post("/suggestions/decide", data={"kind": "dismissed", "keys": ["beam:7"]})

    assert "Der Kannibalenhügel" not in client.get("/suggestions").text


def test_a_decided_find_takes_its_cover_along(client: TestClient, db: Store) -> None:
    """Beim Hinzufuegen zur Watchlist ging das Titelbild verloren: der Stapel
    rechnet den Dateinamen aus der Adresse aus, die Watchlist-Zeile fragt die
    `book`-Zeile — und die kannte ihn nicht. Geholt wird nichts (ADR 3), das
    Bild liegt laengst da; es bekommt nur einen Besitzer."""
    from ebook_watchlist import paths
    from ebook_watchlist.covers import file_name
    from ebook_watchlist.models import Observation

    url = "https://beam.invalid/media/9783104911854_200x200.jpg"
    ordner = paths.covers_dir()
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / file_name(url)).write_bytes(b"x")
    run_id = db.start_run("test", "cli", NOW)
    db.append(
        run_id,
        "test",
        [
            Observation(
                source="beam",
                source_item_id="7",
                title="Mit Bild",
                author="Wer Auch Immer",
                match_reason=MatchReason.GENRE_CATEGORY,
                price_cents=399,
                blurb="Ein Schiff, allein im Dunkeln.",
                cover_url=url,
            )
        ],
        NOW,
    )

    client.post("/suggestions/decide", data={"kind": "watching", "keys": ["beam:7"]})

    book_id = db.book_by_source_item("beam", "7")
    assert db.book(book_id).cover_file == file_name(url)


def test_dismissing_suppresses_the_book_at_every_source(client: TestClient, db: Store) -> None:
    """Die alte dismissed.yaml konnte nur "dieser Shop soll das nicht mehr
    zeigen" — dasselbe Buch bei der Onleihe wäre wiedergekommen (ADR 18)."""
    isbn = "9783104911854"
    found(db, item_id="7", title="Der Kannibalenhügel", isbn=isbn)
    found(db, item_id="99", title="Der Kannibalenhügel", isbn=isbn, source="onleihe")

    client.post("/suggestions/decide", data={"kind": "dismissed", "keys": ["beam:7"]})

    pile = view.pending(db, load_settings())
    assert all(item.isbn != isbn for item in pile.items)


def test_several_finds_are_decided_at_once(client: TestClient, db: Store) -> None:
    for number in range(3):
        found(db, item_id=str(number), title=f"Fund {number}")

    client.post(
        "/suggestions/decide",
        data={"kind": "dismissed", "keys": ["beam:0", "beam:1", "beam:2"]},
    )

    body = client.get("/suggestions").text
    assert "Fund 0" not in body and "Fund 2" not in body


def test_an_existing_book_is_matched_rather_than_duplicated(client: TestClient, db: Store) -> None:
    """Jede Buchanlage sucht zuerst — sonst verteilen sich die Beziehungen
    eines Buchs auf zwei Zeilen (ADR 18)."""
    before = len(db.books())
    found(db, item_id="7", title="Die sieben Schwestern", author="Lucinda Riley")

    client.post("/suggestions/decide", data={"kind": "owned", "keys": ["beam:7"]})

    assert len(db.books()) == before


def test_the_source_link_is_recorded(client: TestClient, db: Store) -> None:
    """Sonst stünde derselbe Fund beim nächsten Lauf wieder im Stapel."""
    found(db, item_id="7", title="Der Kannibalenhügel")

    client.post("/suggestions/decide", data={"kind": "owned", "keys": ["beam:7"]})

    book = next(b for b in db.books() if b.title == "Der Kannibalenhügel")
    link = db.get_book_source(book.id, "beam")
    assert link is not None and link.source_item_id == "7"


def test_deciding_nothing_changes_nothing(client: TestClient, db: Store) -> None:
    before = len(db.books())
    client.post("/suggestions/decide", data={"kind": "dismissed"})
    assert len(db.books()) == before


def test_an_unknown_key_is_ignored_not_fatal(client: TestClient, db: Store) -> None:
    response = client.post(
        "/suggestions/decide", data={"kind": "owned", "keys": ["beam:gibtsnicht"]}
    )
    assert response.status_code == 200


def test_an_unknown_action_is_refused(client: TestClient, db: Store) -> None:
    """400 statt 500: die Art ist falsch, nicht der Server. Und geprueft wird,
    bevor irgendetwas entsteht — sonst blieb eine Buch-Zeile ohne Beziehung
    zurueck."""
    found(db, item_id="7")
    response = client.post(
        "/suggestions/decide", data={"kind": "verschlungen", "keys": ["beam:7"]}
    )
    assert response.status_code == 400
    assert db.book_by_source_item("beam", "7") is None


def test_the_title_leads_to_the_page_of_the_find(client: TestClient, db: Store) -> None:
    """Eine Buchseite gibt es vor der Entscheidung nicht (ADR 18) — die
    Fundseite schon, und dort steht die Begruendung des Tors."""
    found(db, item_id="7", title="Der Kannibalenhügel")

    body = client.get("/suggestions").text

    assert 'href="/discovery/beam/7"' in body
    marker = body.index('href="/discovery/beam/7"')
    assert "Der Kannibalenhügel" in body[marker : marker + 400]


def test_clicking_the_title_does_not_tick_the_checkbox(client: TestClient, db: Store) -> None:
    """Die ganze Zeile bleibt das Label fuers Kaestchen — ein Link darin muss
    das Umschalten unterdruecken, sonst waehlt ein Klick auf den Titel aus,
    statt zur Fundseite zu fuehren."""
    found(db, item_id="7")

    body = client.get("/suggestions").text

    start = body.index('href="/discovery/beam/7"')
    assert "stopPropagation" in body[body.rindex("<a", 0, start) : body.index(">", start)]


# --- das Telefon ohne Mehrfachauswahl (#13) ----------------------------------


def _tag_um(body: str, merkmal: str) -> str:
    """Das oeffnende Element, in dem ``merkmal`` steht."""
    stelle = body.index(merkmal)
    return body[body.rindex("<", 0, stelle) : body.index(">", stelle) + 1]


def test_the_phone_has_no_selection_bar(client: TestClient, db: Store) -> None:
    """Die Leiste kostete auf dem Telefon 121 von 812 Pixeln, dauerhaft — fuer
    einen Sonderfall, der am Rechner bequemer ist. Unter ``sm`` faellt sie weg."""
    found(db, item_id="7")

    body = client.get("/suggestions").text

    leiste = _tag_um(body, "sticky bottom-0")
    assert "hidden" in leiste.split('"')[1].split()
    assert "sm:flex" in leiste


def test_on_the_phone_a_tap_on_the_row_ticks_nothing(client: TestClient, db: Store) -> None:
    """Die ganze Zeile ist das Label des Kaestchens. Es nur zu verstecken,
    reicht deshalb nicht: ein verborgenes Kaestchen wird beim Tippen auf die
    Zeile trotzdem angehakt. Abgeschaltet reagiert es auf keinen Klick — und
    ohne Alpine bleibt alles wie vorher."""
    found(db, item_id="7")

    body = client.get("/suggestions").text

    kaestchen = _tag_um(body, 'name="keys"')
    assert ':disabled="klein"' in kaestchen
    assert "matchMedia" in _tag_um(body, 'id="pile"')


# --- eine Zeile, eine Entscheidung (Issue #9) -------------------------------


def test_each_row_carries_the_three_decisions(client: TestClient, db: Store) -> None:
    """Neben der Mehrfachauswahl: wer nur diesen einen Fund meint, soll ihn
    nicht erst ankreuzen muessen."""
    found(db, item_id="7", title="Der Kannibalenhügel")

    body = client.get("/suggestions").text

    assert 'hx-post="/suggestions/beam/7/decide"' in body
    for kind in ("dismissed", "owned", "watching"):
        assert f'value="{kind}"' in body


def test_a_row_decision_touches_exactly_one_find(client: TestClient, db: Store) -> None:
    """Der Zeilenknopf betrifft immer genau einen Titel — angehakte Zeilen
    bleiben unberuehrt, auch wenn sie im selben Formular stehen."""
    found(db, item_id="7", title="Der Kannibalenhügel")
    found(db, item_id="8", title="Ein anderer Fund")

    client.post("/suggestions/beam/7/decide", data={"kind": "owned"})

    titel = {book.title for book in db.books()}
    assert "Der Kannibalenhügel" in titel
    assert "Ein anderer Fund" not in titel


def test_a_row_decision_answers_with_nothing_so_the_row_disappears(
    client: TestClient, db: Store
) -> None:
    """htmx tauscht die Zeile gegen die Antwort — leer heisst: weg damit."""
    found(db, item_id="7")

    response = client.post("/suggestions/beam/7/decide", data={"kind": "dismissed"})

    assert response.status_code == 200
    assert response.text.strip() == ""


def test_an_unknown_find_in_a_row_decision_is_refused(client: TestClient, db: Store) -> None:
    response = client.post("/suggestions/beam/gibtsnicht/decide", data={"kind": "owned"})

    assert response.status_code == 404


def test_the_selection_counter_recounts_when_a_row_vanishes(
    client: TestClient, db: Store
) -> None:
    """Verschwindet eine angehakte Zeile, zaehlte der Zaehler sonst Geister."""
    found(db, item_id="7")

    body = client.get("/suggestions").text

    assert "htmx:after-swap.window" in body


# --- die Zusammenstellung für sich -----------------------------------------


def test_the_pile_counts_what_it_does_not_show(db: Store) -> None:
    for number in range(60):
        found(db, item_id=f"n{number}", title=f"Fund {number}")

    pile = view.pending(db, load_settings(), limit=50)

    assert len(pile.items) == 50
    assert pile.total >= 60


# --- flüchtiger Browserzustand (Ticket 23) ----------------------------------


def test_alpine_is_actually_loaded(client: TestClient) -> None:
    """Der Build holte Alpine und kein Template lud es — 55 KB Abhängigkeit
    ohne Nutzen. Entweder eine Seite braucht es, oder es fliegt raus (ADR 20)."""
    assert "vendor/alpine.min.js" in client.get("/suggestions").text


def test_the_pile_counts_what_is_ticked_in_the_browser(client: TestClient, db: Store) -> None:
    """Bei fünfzig Zeilen ist "wie viele habe ich angehakt" die Frage vor jedem
    Knopfdruck — und reiner Browserzustand: kein Server kennt sie."""
    found(db)
    body = client.get("/suggestions").text

    assert 'x-data="{' in body
    assert 'x-text="chosen"' in body
    assert ':disabled="chosen === 0"' in body


@needs_vocabulary
def test_without_alpine_the_page_stays_a_plain_form(client: TestClient, db: Store) -> None:
    """x-cloak verbirgt, was ohne Alpine sinnlos wäre. Fällt das Skript aus,
    fehlt der Zähler — die Seite funktioniert weiter."""
    found(db)
    body = client.get("/suggestions").text

    assert "x-cloak" in body
    assert '<form method="post" action="/suggestions/decide"' in body


# --- die Zeile wie in der Übersicht (Vorschlagsseite) -----------------------


# --- die Zeile, wie in der Übersicht -----------------------------------------


def urteil(db: Store, observation: Observation, *, stars: int, pitch: str) -> None:
    """Dem Fund einen Steckbrief legen, der mit dem Testprofil auf diese Sterne
    kommt. Das Profil liegt beim ersten Aufruf in der Datenbank — ohne es
    urteilt niemand (ADR 33, Punkt 8)."""
    if db.reading_profile(load_settings().slug) is None:
        give_profile(db)
    describe(db, subject_of(observation), stars, pitch)


@needs_vocabulary
def test_the_pitch_replaces_the_blurb(client: TestClient, db: Store) -> None:
    """Der Klappentext sagt, wovon das Buch handelt — der steht im Shop. Hier
    zählt, warum es für diese Leserin in Frage kommt."""
    beobachtet = found(db, title="Der Kannibalenhügel", blurb="Ein Schiff, allein im Dunkeln.")
    urteil(db, beobachtet, stars=4, pitch="Ein Ermittler am Limit, und die Jagd beginnt sofort.")

    body = client.get("/suggestions").text

    assert "Ein Ermittler am Limit" in body
    assert "Ein Schiff, allein im Dunkeln." not in body


def test_without_a_judgement_the_blurb_still_shows(client: TestClient, db: Store) -> None:
    """Solange das Tor nicht gelaufen ist, ist der Klappentext besser als
    nichts."""
    found(db, blurb="Ein Schiff, allein im Dunkeln.")

    assert "Ein Schiff, allein im Dunkeln." in client.get("/suggestions").text


@needs_vocabulary
def test_the_stars_of_the_gate_are_shown(client: TestClient, db: Store) -> None:
    beobachtet = found(db, title="Der Kannibalenhügel")
    urteil(db, beobachtet, stars=4, pitch="Kurz und knapp.")

    body = client.get("/suggestions").text

    assert "4 von 5" in body
    assert "ic-star" in body


def test_an_unjudged_find_shows_no_stars(client: TestClient, db: Store) -> None:
    """Null Sterne wären eine Aussage. "Noch nicht bewertet" ist keine."""
    found(db, title="Der Kannibalenhügel")

    assert "aus deinem Leseprofil gerechnet" not in client.get("/suggestions").text


def test_the_row_carries_a_cover_and_the_source_symbol(client: TestClient, db: Store) -> None:
    """Dieselbe Sprache wie auf der Watchlist: grün Bibliothek, bernstein Shop."""
    found(db, title="Der Kannibalenhügel", price=399)

    body = client.get("/suggestions").text

    assert "ic-shop" in body
    assert "ic-tag" in body  # Schnäppchen-Abzeichen auf dem Cover, 3,99 €
    assert "text-amber" in body


def test_a_long_title_is_shortened_in_the_row_and_whole_on_the_find_page(
    client: TestClient, db: Store
) -> None:
    """Ein Viertel der Titel der Quelle traegt einen ganzen Werbesatz hinter
    einem Strich. Ungekuerzt wuchs eine Zeile dadurch auf das Doppelte ihrer
    Nachbarin, und die Liste liess sich nicht mehr ueberfliegen. Verloren geht
    nichts: die Fundseite zeigt den ganzen Titel, einen Klick entfernt."""
    langer_titel = (
        "Schwarzweiß | Er ist ein kranker Mörder. "
        "Und er hat es auf deine Tochter abgesehen."
    )
    found(db, item_id="lang", title=langer_titel)

    liste = client.get("/suggestions").text
    vor_dem_titel = liste[: liste.index(langer_titel)]
    titelabsatz = vor_dem_titel[vor_dem_titel.rindex("<p ") :]
    assert "line-clamp-2" in titelabsatz, titelabsatz

    vor_dem_pitch = liste[: liste.index("Ein Schiff, allein im Dunkeln.")]
    pitchabsatz = vor_dem_pitch[vor_dem_pitch.rindex("<p ") :]
    assert "line-clamp-3" in pitchabsatz, pitchabsatz

    assert langer_titel in client.get("/discovery/beam/lang").text


def test_the_page_shows_ten_not_fifty(client: TestClient, db: Store) -> None:
    """Der Stapel wird vom Tor ohnehin neu erzeugt — gezeigt wird nur, was auch
    bewertet werden muss."""
    for number in range(15):
        found(db, item_id=f"n{number}", title=f"Fund {number}")

    pile = view.pending(db, load_settings())

    assert len(pile.items) == view.PAGE_SIZE == 10
    assert pile.total >= 15


@needs_vocabulary
def test_the_best_stand_at_the_top(client: TestClient, db: Store) -> None:
    """Sonst faengt der Stapel mit dem an, was das Profil gerade abgelehnt hat."""
    schwaecher = found(db, item_id="a", title="Der schwaechere Fund")
    stark = found(db, item_id="b", title="Der stärkere Fund")
    urteil(db, schwaecher, stars=3, pitch="Traegt eine Sache.")
    urteil(db, stark, stars=4, pitch="Genau die kaputte Stimme.")

    titel = [item.title for item in view.pending(db, load_settings()).items]

    assert titel.index("Der stärkere Fund") < titel.index("Der schwaechere Fund")


@needs_vocabulary
def test_an_unjudged_find_sinks_below_the_judged(client: TestClient, db: Store) -> None:
    """Ohne Urteil ist es keine Empfehlung, sondern eine offene Frage."""
    found(db, item_id="a", title="Ohne Urteil")
    bewertet = found(db, item_id="b", title="Mit Urteil")
    urteil(db, bewertet, stars=3, pitch="Traegt eine Sache.")

    titel = [item.title for item in view.pending(db, load_settings()).items]

    assert titel.index("Mit Urteil") < titel.index("Ohne Urteil")


@needs_vocabulary
def test_what_the_gate_holds_back_is_not_a_task(client: TestClient, db: Store) -> None:
    """Dieselbe Schwelle wie im Digest. Was dich nie erreicht, ist keine
    Aufgabe — und die Seite sagt, wie viel sie deshalb verschweigt."""
    schwach = found(db, item_id="a", title="Schwacher Fund")
    stark = found(db, item_id="b", title="Starker Fund")
    urteil(db, schwach, stars=2, pitch="Nur Genre-Naehe.")
    urteil(db, stark, stars=3, pitch="Traegt eine Sache ueberzeugend.")

    pile = view.pending(db, load_settings())
    body = client.get("/suggestions").text

    assert [item.title for item in pile.items] == ["Starker Fund"]
    assert pile.hidden_weak == 1
    assert "1 unter drei Sternen" in body
    assert "Schwacher Fund" not in body


def test_an_unjudged_find_is_never_hidden_as_weak(client: TestClient, db: Store) -> None:
    """ "Noch nicht beurteilt" ist etwas anderes als "passt nicht"."""
    found(db, item_id="a", title="Ohne Urteil")

    pile = view.pending(db, load_settings())

    assert [item.title for item in pile.items] == ["Ohne Urteil"]
    assert pile.hidden_weak == 0


@needs_vocabulary
def test_the_page_uses_the_same_threshold_as_the_digest(client: TestClient, db: Store) -> None:
    """Zwei Ansichten desselben Stapels mit zwei Schwellen waeren genau die
    Drift, die dieses Projekt schon dreimal eingefangen hat."""
    from ebook_watchlist.facets import load_weights

    knapp = found(db, item_id="a", title="Genau an der Schwelle")
    urteil(db, knapp, stars=load_weights().gate_stars, pitch="Gerade so.")

    assert [i.title for i in view.pending(db, load_settings()).items] == ["Genau an der Schwelle"]


def test_a_title_beginning_with_a_number_word_is_read_as_a_bundle(
    client: TestClient, db: Store
) -> None:
    """Beim Schreiben dieser Tests selbst hineingelaufen: "Drei Sterne" trifft
    das Bündelmuster, das für "Drei Gruselkrimis" gedacht ist. Ein echter Titel
    wie "Drei Tage im Mai" verschwände genauso — hier festgehalten, damit die
    Grenze des Filters sichtbar bleibt."""
    found(db, item_id="a", title="Drei Sterne")

    pile = view.pending(db, load_settings())

    assert pile.items == ()
    assert pile.hidden_junk == 1


def test_a_suggestion_with_a_fetched_cover_shows_it(client: TestClient, db: Store) -> None:
    """Die Vorlage uebergab fest ``none`` als Bilddatei — der Stapel konnte
    kein Cover zeigen, gleichgueltig was in den Daten stand. Aufgefallen ist es
    erst, als 25 geholte Bilder auf der Seite unsichtbar blieben."""
    from ebook_watchlist import paths
    from ebook_watchlist.covers import file_name

    url = "https://beam.invalid/media/9783104911854_200x200.jpg"
    found(db, title="Mit Bild", blurb="Ein Schiff, allein im Dunkeln.")
    db.session()  # noqa: B018 - nur damit die Datei nach dem Anlegen entsteht
    ordner = paths.covers_dir()
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / file_name(url)).write_bytes(b"x")

    # Die Adresse muss an der Beobachtung stehen, sonst kann die Seite den
    # Namen gar nicht ausrechnen.
    run_id = db.start_run("test", "cli", NOW)
    db.append(
        run_id,
        "test",
        [
            Observation(
                source="beam",
                source_item_id="1",
                title="Mit Bild",
                author="Wer Auch Immer",
                match_reason=MatchReason.GENRE_CATEGORY,
                price_cents=399,
                blurb="Ein Schiff, allein im Dunkeln.",
                cover_url=url,
            )
        ],
        NOW,
    )

    body = client.get("/suggestions").text
    assert f"/covers/{file_name(url)}" in body


# --- Sammelausgaben (ADR 24) ------------------------------------------------


def test_a_bundle_says_so_and_names_its_volumes(client: TestClient, db: Store) -> None:
    """Sonst sieht eine Sammelausgabe aus wie der gesuchte Einzelband — und
    genau das war der Grund fuer ADR 24."""
    found(db, title='Der Kruzifix-Killer / Der Vollstrecker', author='Chris Carter')

    body = client.get('/suggestions').text

    assert '2 Bände' in body
    assert 'Der Kruzifix-Killer, Der Vollstrecker' in body


def test_a_bundle_without_volume_titles_only_states_the_fact(
    client: TestClient, db: Store
) -> None:
    """"3in1 Bundle" nennt keinen Bandtitel. Eine Zahl zu erfinden waere
    schlimmer als die blosse Tatsache — gemessen liest ein Zaehler am Titel
    mindestens drei von neunzehn falsch.

    Als Fund einer Referenzautor:in, nicht vom Themenregal: dort ist ein
    Buendel Ramsch und wird ausgeblendet (ADR 24, junk.py).
    """
    found(
        db,
        title='David Hunter: 3in1 Bundle',
        author='Simon Beckett',
        reason=MatchReason.PROFILE_AUTHOR,
    )

    body = client.get('/suggestions').text

    assert 'Sammelausgabe' in body


def test_an_ordinary_title_carries_no_bundle_badge(client: TestClient, db: Store) -> None:
    found(db, title='Der Kruzifix-Killer', author='Chris Carter')

    body = client.get('/suggestions').text

    assert 'Sammelausgabe' not in body
    assert 'Bände' not in body


# --- sortieren (#37) --------------------------------------------------------


def test_the_stack_offers_every_sort_key(client: TestClient, db: Store) -> None:
    found(db)
    body = client.get("/suggestions").text

    assert "Sortiert nach" in body
    for order in sorting.SUGGESTIONS:
        assert order.label in body


def test_the_address_decides_the_order(client: TestClient, db: Store) -> None:
    # Beide unter der Schnaeppchen-Grenze: was nie gemeldet wuerde, steht
    # auch nicht im Stapel (ADR 19) — und waere dann nicht zu sortieren.
    found(db, item_id="teuer", title="Kostet viel", price=499)
    found(db, item_id="billig", title="Kostet wenig", price=199)

    body = client.get("/suggestions?sortiert=preis").text

    assert body.index("Kostet wenig") < body.index("Kostet viel")


def test_sorting_happens_before_the_page_is_cut(client: TestClient, db: Store) -> None:
    """Sonst zeigte die Seite die ersten fuenfzig einer zufaelligen Reihe,
    nur huebsch geordnet."""
    for nummer in range(5):
        found(db, item_id=str(nummer), title=f"Fund {nummer}", price=100 + nummer)

    pile = view.pending(db, load_settings(), limit=2, sort="preis")

    assert [item.title for item in pile.items] == ["Fund 0", "Fund 1"]
    assert pile.total == 5


def test_the_filter_keeps_the_order(client: TestClient, db: Store) -> None:
    """Wer auf "Themen" klickt, behaelt seine Reihenfolge."""
    found(db)
    body = client.get("/suggestions?sortiert=preis").text

    assert "anlass=genre_category" in body
    assert "sortiert=preis" in body


def test_a_decision_returns_to_the_same_order(client: TestClient, db: Store) -> None:
    """Sonst steht man nach dem Ausschliessen in einer anders geordneten Liste
    als der, aus der man gewaehlt hat."""
    fund = found(db, item_id="weg", title="Nichts fuer mich")

    antwort = TestClient(
        create_app(), raise_server_exceptions=False, follow_redirects=False
    ).post(
        "/suggestions/decide",
        data={
            "kind": str(RelationKind.DISMISSED),
            "keys": [f"{fund.source}:{fund.source_item_id}"],
            "sortiert": "preis",
        },
    )

    assert antwort.headers["location"] == "/suggestions?sortiert=preis"


def test_the_default_order_stays_out_of_the_links(client: TestClient, db: Store) -> None:
    found(db)
    assert "sortiert=sterne" not in client.get("/suggestions").text


def test_sorting_by_occasion_works_against_the_real_type(
    client: TestClient, db: Store
) -> None:
    """Der Schlüssel vergleicht `str(item.reason)` mit "profile_author".

    Die Einheitsprobe in ``test_web_sorting`` reicht eine Zeichenkette herein
    und hätte einen Typwechsel nie bemerkt — hier kommt ein echter
    ``MatchReason`` durch die ganze Seite.
    """
    found(db, item_id="thema", title="Aus dem Regal", reason=MatchReason.GENRE_CATEGORY)
    found(db, item_id="autor", title="Von wem ich lese", reason=MatchReason.PROFILE_AUTHOR)

    body = client.get("/suggestions?sortiert=anlass").text

    assert body.index("Von wem ich lese") < body.index("Aus dem Regal")


def test_a_book_by_an_ai_author_never_reaches_the_stack(
    client: TestClient, db: Store
) -> None:
    """Und es kostet kein Urteil: gefiltert wird vor dem Tor (#31)."""
    found(db, item_id="ki", title="Die Glocke von Kirchberg", author="Matze K",
          blurb="Der Autor verwendet zum Erstellen seiner Texte meistens "
                "künstliche Intelligenz.")
    found(db, item_id="echt", title="Ein handgeschriebener Fund", author="Wer Auch Immer")

    body = client.get("/suggestions").text

    assert "Ein handgeschriebener Fund" in body
    assert "Die Glocke von Kirchberg" not in body
    assert "1 KI-erzeugt" in body


def test_the_whole_work_goes_not_just_the_declaring_title(
    client: TestClient, db: Store
) -> None:
    """Die Angabe steht nur auf der Detailseite, und die wird allein für
    Bücher geholt, die gleich beurteilt werden — ohne den Schluss auf die
    Autorenschaft bliebe der Rest des Werks stehen."""
    found(db, item_id="mit", title="Mit Detailseite", author="Matze K",
          blurb="Matze K. ist ein deutscher KI-Autor.")
    found(db, item_id="ohne", title="Nur ein Teaser", author="Matze K",
          blurb="Im Jahr 2100 verändert sich Pegau.")

    body = client.get("/suggestions").text

    assert "Nur ein Teaser" not in body
    assert "2 KI-erzeugt" in body




# --- das Urteil rechnet der Code (#48) ------------------------------------------


@needs_vocabulary
def test_the_stack_orders_by_percent_not_by_stars(client: TestClient, db: Store) -> None:
    """Zwei Funde mit denselben Sternen stehen nach ihrer Prozentzahl."""
    middling = found(db, item_id="a", title="Der mittlere Fund")
    strong = found(db, item_id="b", title="Der starke Fund")
    urteil(db, middling, stars=4, pitch="Trägt drei Muster.")
    urteil(db, strong, stars=5, pitch="Trägt die Facette.")

    items = view.pending(db, load_settings()).items

    assert [i.title for i in items] == ["Der starke Fund", "Der mittlere Fund"]
    assert items[0].percent > items[1].percent


@needs_vocabulary
def test_the_row_shows_the_percent_beside_the_stars(client: TestClient, db: Store) -> None:
    urteil(db, found(db, title="Der Kannibalenhügel"), stars=4, pitch="Kurz und knapp.")

    body = client.get("/suggestions").text

    assert "56 %" in body  # die ganze Facette "gezeichnete Figur · hart"
    assert "aus deinem Leseprofil gerechnet" in body


@needs_vocabulary
def test_a_new_profile_reorders_the_stack_without_asking_the_model(
    client: TestClient, db: Store
) -> None:
    """Eine neue Fassung wirkt sofort auf alles, weil der Code rechnet
    (Abnahme in #48)."""
    from ebook_watchlist.facets import Liked, ReadingProfile

    urteil(db, found(db, item_id="a", title="Trägt eine Sache"), stars=2, pitch="Eins.")
    assert view.pending(db, load_settings()).hidden_weak == 1

    # Jetzt mag sie auch das Poetische, über das die Form vorher nichts wusste.
    give_profile(db, profile=ReadingProfile(
        facets=(), counterweights=(),
        liked=(Liked("brooding"), Liked("lyrical")),
    ))

    pile = view.pending(db, load_settings())

    assert [i.title for i in pile.items] == ["Trägt eine Sache"]
    assert pile.hidden_weak == 0


def test_without_a_profile_nothing_is_judged_and_the_page_says_so(
    client: TestClient, db: Store
) -> None:
    """Ohne Leseprofil keine Sterne, kein Vorfilter, und die Seite nennt den
    Weg (ADR 33, Punkt 8)."""
    found(db, item_id="b", title="Beta")
    found(db, item_id="a", title="Alpha")

    pile = view.pending(db, load_settings())
    body = client.get("/suggestions").text

    assert pile.no_profile and all(i.stars is None for i in pile.items)
    assert "data-no-profile" in body and "Erstaufnahme machen" in body


@needs_vocabulary
def test_with_a_profile_the_page_does_not_send_her_back_to_the_intake(
    client: TestClient, db: Store
) -> None:
    give_profile(db)
    found(db, title="Ein Fund")

    assert "data-no-profile" not in client.get("/suggestions").text


def test_the_hidden_count_names_the_threshold_of_the_scheme() -> None:
    assert view.Pile((), 0, 0, hidden_weak=2, threshold=4).hidden == ((2, "unter vier Sternen"),)


def test_a_pile_with_an_unreadable_vocabulary_does_not_blame_the_missing_profile(
    client: TestClient, db: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Es gibt ein Profil, nur das Vokabular fehlt: "erst die Erstaufnahme
    machen" wäre dann falsch."""
    from ebook_watchlist import judging
    from ebook_watchlist.facets import Liked, ReadingProfile

    db.put_reading_profile(
        load_settings().slug, ReadingProfile((), (), (Liked("quest"),)), cause="Test", now=NOW
    )
    monkeypatch.setattr(judging, "load_vocabulary", lambda: (_ for _ in ()).throw(
        judging.VocabularyError("fehlt")))
    found(db, title="Ein Fund")

    pile = view.pending(db, load_settings())

    assert not pile.no_profile
    assert "data-no-profile" not in client.get("/suggestions").text
