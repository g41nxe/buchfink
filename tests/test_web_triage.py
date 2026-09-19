"""Der Vorschlagsstapel (Ticket 08).

Der Vorgang, den ein Gespräch am schlechtesten kann und ein Formular am besten.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist import paths
from ebook_watchlist.config import load_profile
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.relations import RelationKind
from ebook_watchlist.store import Store
from ebook_watchlist.web import create_app
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

    body = client.get("/vorschlaege").text

    assert "Der Kannibalenhügel" in body
    assert "Viktor Sauer" in body
    assert "3,99 €" in body
    assert "Ein Schiff, allein im Dunkeln." in body


def test_the_page_says_why_each_find_is_there(client: TestClient, db: Store) -> None:
    """Dieselben Worte wie im Digest, aus einer Stelle (Ticket 14)."""
    found(db, reason=MatchReason.PROFILE_AUTHOR)
    assert "Autor:in" in client.get("/vorschlaege").text


def test_junk_never_reaches_the_pile(client: TestClient, db: Store) -> None:
    found(db, item_id="ok", title="Ein echter Fund")
    found(db, item_id="j1", title="3 Gruselkrimis: A / B / C")
    found(db, item_id="j2", title="Gratis dabei", price=0)

    body = client.get("/vorschlaege").text

    assert "Ein echter Fund" in body
    assert "3 Gruselkrimis" not in body
    assert "Gratistitel ausgeblendet" in body


def test_the_pile_can_be_filtered_by_origin(client: TestClient, db: Store) -> None:
    found(db, item_id="a", title="Vom Autor", reason=MatchReason.PROFILE_AUTHOR)
    found(db, item_id="t", title="Vom Thema", reason=MatchReason.GENRE_CATEGORY)

    body = client.get("/vorschlaege?anlass=profile_author").text

    assert "Vom Autor" in body
    assert "Vom Thema" not in body


def test_a_watchlist_title_is_not_a_suggestion(client: TestClient, db: Store) -> None:
    found(db, title="Beobachtet", reason=MatchReason.WATCHLIST)
    assert "Beobachtet" not in client.get("/vorschlaege").text


# --- entscheiden ------------------------------------------------------------


def test_a_decision_creates_the_book_and_the_relation(client: TestClient, db: Store) -> None:
    found(db, item_id="7", title="Der Kannibalenhügel", author="Viktor Sauer")

    client.post("/vorschlaege/entscheiden", data={"kind": "owned", "keys": ["beam:7"]})

    book = next(b for b in db.books() if b.title == "Der Kannibalenhügel")
    kinds = {row.kind for row in db.relations_of("test", book.id) if row.active}
    assert str(RelationKind.OWNED) in kinds


def test_a_decided_find_never_comes_back(client: TestClient, db: Store) -> None:
    found(db, item_id="7", title="Der Kannibalenhügel")

    client.post("/vorschlaege/entscheiden", data={"kind": "dismissed", "keys": ["beam:7"]})

    assert "Der Kannibalenhügel" not in client.get("/vorschlaege").text


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

    client.post("/vorschlaege/entscheiden", data={"kind": "watching", "keys": ["beam:7"]})

    book_id = db.book_by_source_item("beam", "7")
    assert db.book(book_id).cover_file == file_name(url)


def test_dismissing_suppresses_the_book_at_every_source(client: TestClient, db: Store) -> None:
    """Die alte dismissed.yaml konnte nur "dieser Shop soll das nicht mehr
    zeigen" — dasselbe Buch bei der Onleihe wäre wiedergekommen (ADR 18)."""
    isbn = "9783104911854"
    found(db, item_id="7", title="Der Kannibalenhügel", isbn=isbn)
    found(db, item_id="99", title="Der Kannibalenhügel", isbn=isbn, source="onleihe")

    client.post("/vorschlaege/entscheiden", data={"kind": "dismissed", "keys": ["beam:7"]})

    pile = view.pending(db, load_profile())
    assert all(item.isbn != isbn for item in pile.items)


def test_several_finds_are_decided_at_once(client: TestClient, db: Store) -> None:
    for number in range(3):
        found(db, item_id=str(number), title=f"Fund {number}")

    client.post(
        "/vorschlaege/entscheiden",
        data={"kind": "dismissed", "keys": ["beam:0", "beam:1", "beam:2"]},
    )

    body = client.get("/vorschlaege").text
    assert "Fund 0" not in body and "Fund 2" not in body


def test_an_existing_book_is_matched_rather_than_duplicated(client: TestClient, db: Store) -> None:
    """Jede Buchanlage sucht zuerst — sonst verteilen sich die Beziehungen
    eines Buchs auf zwei Zeilen (ADR 18)."""
    before = len(db.books())
    found(db, item_id="7", title="Die sieben Schwestern", author="Lucinda Riley")

    client.post("/vorschlaege/entscheiden", data={"kind": "owned", "keys": ["beam:7"]})

    assert len(db.books()) == before


def test_the_source_link_is_recorded(client: TestClient, db: Store) -> None:
    """Sonst stünde derselbe Fund beim nächsten Lauf wieder im Stapel."""
    found(db, item_id="7", title="Der Kannibalenhügel")

    client.post("/vorschlaege/entscheiden", data={"kind": "owned", "keys": ["beam:7"]})

    book = next(b for b in db.books() if b.title == "Der Kannibalenhügel")
    link = db.get_book_source(book.id, "beam")
    assert link is not None and link.source_item_id == "7"


def test_deciding_nothing_changes_nothing(client: TestClient, db: Store) -> None:
    before = len(db.books())
    client.post("/vorschlaege/entscheiden", data={"kind": "dismissed"})
    assert len(db.books()) == before


def test_an_unknown_key_is_ignored_not_fatal(client: TestClient, db: Store) -> None:
    response = client.post(
        "/vorschlaege/entscheiden", data={"kind": "owned", "keys": ["beam:gibtsnicht"]}
    )
    assert response.status_code == 200


def test_an_unknown_action_is_refused(client: TestClient, db: Store) -> None:
    """400 statt 500: die Art ist falsch, nicht der Server. Und geprueft wird,
    bevor irgendetwas entsteht — sonst blieb eine Buch-Zeile ohne Beziehung
    zurueck."""
    found(db, item_id="7")
    response = client.post(
        "/vorschlaege/entscheiden", data={"kind": "verschlungen", "keys": ["beam:7"]}
    )
    assert response.status_code == 400
    assert db.book_by_source_item("beam", "7") is None


def test_the_title_leads_to_the_page_of_the_find(client: TestClient, db: Store) -> None:
    """Eine Buchseite gibt es vor der Entscheidung nicht (ADR 18) — die
    Fundseite schon, und dort steht die Begruendung des Tors."""
    found(db, item_id="7", title="Der Kannibalenhügel")

    body = client.get("/vorschlaege").text

    assert 'href="/discovery/beam/7"' in body
    marker = body.index('href="/discovery/beam/7"')
    assert "Der Kannibalenhügel" in body[marker : marker + 400]


def test_clicking_the_title_does_not_tick_the_checkbox(client: TestClient, db: Store) -> None:
    """Die ganze Zeile bleibt das Label fuers Kaestchen — ein Link darin muss
    das Umschalten unterdruecken, sonst waehlt ein Klick auf den Titel aus,
    statt zur Fundseite zu fuehren."""
    found(db, item_id="7")

    body = client.get("/vorschlaege").text

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

    body = client.get("/vorschlaege").text

    leiste = _tag_um(body, "sticky bottom-0")
    assert "hidden" in leiste.split('"')[1].split()
    assert "sm:flex" in leiste


def test_on_the_phone_a_tap_on_the_row_ticks_nothing(client: TestClient, db: Store) -> None:
    """Die ganze Zeile ist das Label des Kaestchens. Es nur zu verstecken,
    reicht deshalb nicht: ein verborgenes Kaestchen wird beim Tippen auf die
    Zeile trotzdem angehakt. Abgeschaltet reagiert es auf keinen Klick — und
    ohne Alpine bleibt alles wie vorher."""
    found(db, item_id="7")

    body = client.get("/vorschlaege").text

    kaestchen = _tag_um(body, 'name="keys"')
    assert ':disabled="klein"' in kaestchen
    assert "matchMedia" in _tag_um(body, 'id="pile"')


# --- eine Zeile, eine Entscheidung (Issue #9) -------------------------------


def test_each_row_carries_the_three_decisions(client: TestClient, db: Store) -> None:
    """Neben der Mehrfachauswahl: wer nur diesen einen Fund meint, soll ihn
    nicht erst ankreuzen muessen."""
    found(db, item_id="7", title="Der Kannibalenhügel")

    body = client.get("/vorschlaege").text

    assert 'hx-post="/vorschlaege/beam/7/entscheiden"' in body
    for kind in ("dismissed", "owned", "watching"):
        assert f'value="{kind}"' in body


def test_a_row_decision_touches_exactly_one_find(client: TestClient, db: Store) -> None:
    """Der Zeilenknopf betrifft immer genau einen Titel — angehakte Zeilen
    bleiben unberuehrt, auch wenn sie im selben Formular stehen."""
    found(db, item_id="7", title="Der Kannibalenhügel")
    found(db, item_id="8", title="Ein anderer Fund")

    client.post("/vorschlaege/beam/7/entscheiden", data={"kind": "owned"})

    titel = {book.title for book in db.books()}
    assert "Der Kannibalenhügel" in titel
    assert "Ein anderer Fund" not in titel


def test_a_row_decision_answers_with_nothing_so_the_row_disappears(
    client: TestClient, db: Store
) -> None:
    """htmx tauscht die Zeile gegen die Antwort — leer heisst: weg damit."""
    found(db, item_id="7")

    response = client.post("/vorschlaege/beam/7/entscheiden", data={"kind": "dismissed"})

    assert response.status_code == 200
    assert response.text.strip() == ""


def test_an_unknown_find_in_a_row_decision_is_refused(client: TestClient, db: Store) -> None:
    response = client.post("/vorschlaege/beam/gibtsnicht/entscheiden", data={"kind": "owned"})

    assert response.status_code == 404


def test_the_selection_counter_recounts_when_a_row_vanishes(
    client: TestClient, db: Store
) -> None:
    """Verschwindet eine angehakte Zeile, zaehlte der Zaehler sonst Geister."""
    found(db, item_id="7")

    body = client.get("/vorschlaege").text

    assert "htmx:after-swap.window" in body


# --- die Zusammenstellung für sich -----------------------------------------


def test_the_pile_counts_what_it_does_not_show(db: Store) -> None:
    for number in range(60):
        found(db, item_id=f"n{number}", title=f"Fund {number}")

    pile = view.pending(db, load_profile(), limit=50)

    assert len(pile.items) == 50
    assert pile.total >= 60


# --- flüchtiger Browserzustand (Ticket 23) ----------------------------------


def test_alpine_is_actually_loaded(client: TestClient) -> None:
    """Der Build holte Alpine und kein Template lud es — 55 KB Abhängigkeit
    ohne Nutzen. Entweder eine Seite braucht es, oder es fliegt raus (ADR 20)."""
    assert "vendor/alpine.min.js" in client.get("/vorschlaege").text


def test_the_pile_counts_what_is_ticked_in_the_browser(client: TestClient, db: Store) -> None:
    """Bei fünfzig Zeilen ist "wie viele habe ich angehakt" die Frage vor jedem
    Knopfdruck — und reiner Browserzustand: kein Server kennt sie."""
    found(db)
    body = client.get("/vorschlaege").text

    assert 'x-data="{' in body
    assert 'x-text="chosen"' in body
    assert ':disabled="chosen === 0"' in body


def test_without_alpine_the_page_stays_a_plain_form(client: TestClient, db: Store) -> None:
    """x-cloak verbirgt, was ohne Alpine sinnlos wäre. Fällt das Skript aus,
    fehlt der Zähler — die Seite funktioniert weiter."""
    found(db)
    body = client.get("/vorschlaege").text

    assert "x-cloak" in body
    assert '<form method="post" action="/vorschlaege/entscheiden"' in body


# --- die Zeile wie in der Übersicht (Vorschlagsseite) -----------------------


# --- die Zeile, wie in der Übersicht -----------------------------------------


def urteil(db: Store, observation: Observation, *, stars: int, pitch: str) -> None:
    from ebook_watchlist.ratings import BY_MODEL, subject_of

    db.put_rating(
        subject_of(observation),
        stars=stars,
        confidence="teils",
        reason="Begründung zum Nachprüfen.",
        profile_version=1,
        now=NOW,
        origin=BY_MODEL,
        pitch=pitch,
    )


def test_the_pitch_replaces_the_blurb(client: TestClient, db: Store) -> None:
    """Der Klappentext sagt, wovon das Buch handelt — der steht im Shop. Hier
    zählt, warum es für diese Leserin in Frage kommt."""
    beobachtet = found(db, title="Der Kannibalenhügel", blurb="Ein Schiff, allein im Dunkeln.")
    urteil(db, beobachtet, stars=4, pitch="Ein Ermittler am Limit, und die Jagd beginnt sofort.")

    body = client.get("/vorschlaege").text

    assert "Ein Ermittler am Limit" in body
    assert "Ein Schiff, allein im Dunkeln." not in body


def test_without_a_judgement_the_blurb_still_shows(client: TestClient, db: Store) -> None:
    """Solange das Tor nicht gelaufen ist, ist der Klappentext besser als
    nichts."""
    found(db, blurb="Ein Schiff, allein im Dunkeln.")

    assert "Ein Schiff, allein im Dunkeln." in client.get("/vorschlaege").text


def test_the_stars_of_the_gate_are_shown(client: TestClient, db: Store) -> None:
    beobachtet = found(db, title="Der Kannibalenhügel")
    urteil(db, beobachtet, stars=4, pitch="Kurz und knapp.")

    body = client.get("/vorschlaege").text

    assert "4 von 5" in body
    assert "ic-star" in body


def test_an_unjudged_find_shows_no_stars(client: TestClient, db: Store) -> None:
    """Null Sterne wären eine Aussage. "Noch nicht bewertet" ist keine."""
    found(db, title="Der Kannibalenhügel")

    assert "von 5 — Urteil des Werkzeugs" not in client.get("/vorschlaege").text


def test_the_row_carries_a_cover_and_the_source_symbol(client: TestClient, db: Store) -> None:
    """Dieselbe Sprache wie auf der Watchlist: grün Bibliothek, bernstein Shop."""
    found(db, title="Der Kannibalenhügel", price=399)

    body = client.get("/vorschlaege").text

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

    liste = client.get("/vorschlaege").text
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

    pile = view.pending(db, load_profile())

    assert len(pile.items) == view.PAGE_SIZE == 10
    assert pile.total >= 15


def test_the_best_stand_at_the_top(client: TestClient, db: Store) -> None:
    """Sonst faengt der Stapel mit dem an, was das Profil gerade abgelehnt hat."""
    schwaecher = found(db, item_id="a", title="Der schwaechere Fund")
    stark = found(db, item_id="b", title="Der stärkere Fund")
    urteil(db, schwaecher, stars=3, pitch="Traegt eine Sache.")
    urteil(db, stark, stars=4, pitch="Genau die kaputte Stimme.")

    titel = [item.title for item in view.pending(db, load_profile()).items]

    assert titel.index("Der stärkere Fund") < titel.index("Der schwaechere Fund")


def test_an_unjudged_find_sinks_below_the_judged(client: TestClient, db: Store) -> None:
    """Ohne Urteil ist es keine Empfehlung, sondern eine offene Frage."""
    found(db, item_id="a", title="Ohne Urteil")
    bewertet = found(db, item_id="b", title="Mit Urteil")
    urteil(db, bewertet, stars=3, pitch="Traegt eine Sache.")

    titel = [item.title for item in view.pending(db, load_profile()).items]

    assert titel.index("Mit Urteil") < titel.index("Ohne Urteil")


def test_what_the_gate_holds_back_is_not_a_task(client: TestClient, db: Store) -> None:
    """Dieselbe Schwelle wie im Digest. Was dich nie erreicht, ist keine
    Aufgabe — und die Seite sagt, wie viel sie deshalb verschweigt."""
    schwach = found(db, item_id="a", title="Schwacher Fund")
    stark = found(db, item_id="b", title="Starker Fund")
    urteil(db, schwach, stars=2, pitch="Nur Genre-Naehe.")
    urteil(db, stark, stars=3, pitch="Traegt eine Sache ueberzeugend.")

    pile = view.pending(db, load_profile())
    body = client.get("/vorschlaege").text

    assert [item.title for item in pile.items] == ["Starker Fund"]
    assert pile.hidden_weak == 1
    assert "1 unter drei Sternen" in body
    assert "Schwacher Fund" not in body


def test_an_unjudged_find_is_never_hidden_as_weak(client: TestClient, db: Store) -> None:
    """ "Noch nicht beurteilt" ist etwas anderes als "passt nicht"."""
    found(db, item_id="a", title="Ohne Urteil")

    pile = view.pending(db, load_profile())

    assert [item.title for item in pile.items] == ["Ohne Urteil"]
    assert pile.hidden_weak == 0


def test_the_page_uses_the_same_threshold_as_the_digest(client: TestClient, db: Store) -> None:
    """Zwei Ansichten desselben Stapels mit zwei Schwellen waeren genau die
    Drift, die dieses Projekt schon dreimal eingefangen hat."""
    from ebook_watchlist.rating import DEFAULT_THRESHOLD

    knapp = found(db, item_id="a", title="Genau an der Schwelle")
    urteil(db, knapp, stars=DEFAULT_THRESHOLD, pitch="Gerade so.")

    assert [i.title for i in view.pending(db, load_profile()).items] == ["Genau an der Schwelle"]


def test_a_title_beginning_with_a_number_word_is_read_as_a_bundle(
    client: TestClient, db: Store
) -> None:
    """Beim Schreiben dieser Tests selbst hineingelaufen: "Drei Sterne" trifft
    das Bündelmuster, das für "Drei Gruselkrimis" gedacht ist. Ein echter Titel
    wie "Drei Tage im Mai" verschwände genauso — hier festgehalten, damit die
    Grenze des Filters sichtbar bleibt."""
    found(db, item_id="a", title="Drei Sterne")

    pile = view.pending(db, load_profile())

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

    body = client.get("/vorschlaege").text
    assert f"/covers/{file_name(url)}" in body


# --- Sammelausgaben (ADR 24) ------------------------------------------------


def test_a_bundle_says_so_and_names_its_volumes(client: TestClient, db: Store) -> None:
    """Sonst sieht eine Sammelausgabe aus wie der gesuchte Einzelband — und
    genau das war der Grund fuer ADR 24."""
    found(db, title='Der Kruzifix-Killer / Der Vollstrecker', author='Chris Carter')

    body = client.get('/vorschlaege').text

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

    body = client.get('/vorschlaege').text

    assert 'Sammelausgabe' in body


def test_an_ordinary_title_carries_no_bundle_badge(client: TestClient, db: Store) -> None:
    found(db, title='Der Kruzifix-Killer', author='Chris Carter')

    body = client.get('/vorschlaege').text

    assert 'Sammelausgabe' not in body
    assert 'Bände' not in body
