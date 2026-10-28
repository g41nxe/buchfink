"""Bilder und Zeichen der Merkmalsfamilien (#55).

Sie liegen neben dem Vokabular und wie dieses nicht in Git (#59). Fehlen sie,
sieht jede Seite aus wie vorher; liegen sie da, trägt die Karte der
Erstaufnahme ihr Bild und jede Familie ihr Zeichen.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ebook_watchlist.web import family_art
from ebook_watchlist.web.app import TEMPLATES, create_app

SIGN = '<path fill="currentColor" d="M2 2h20v20H2z"/>'


@pytest.fixture
def art(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ein Bild und ein Zeichen für „hart“, sonst nichts."""
    pictures, signs = tmp_path / "bilder", tmp_path / "zeichen"
    pictures.mkdir()
    signs.mkdir()
    (pictures / "harsh.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    (signs / "harsh.svg").write_text(SIGN, encoding="utf-8")
    monkeypatch.setattr(family_art, "PICTURES_DIR", pictures)
    monkeypatch.setattr(family_art, "SIGNS_DIR", signs)
    # Jinja hält das importierte `_family_pill.html` samt dem `family_art`, das
    # beim ersten Import galt; ohne Leeren sähe dieser Test das des vorigen.
    if TEMPLATES.env.cache is not None:
        TEMPLATES.env.cache.clear()
    return tmp_path


def _card(family_id: str) -> str:
    """Die Karte von Bildschirm 3, gerendert mit dem echten Makro."""
    pill = SimpleNamespace(family_id=family_id, name="hart", on=False, boosted=False,
                           frequent=False, pattern=False)
    k = SimpleNamespace(pill=pill, description="Gewalt, ohne Beschönigung.",
                        strength="trägt", level=2, evidence=[])
    template = TEMPLATES.env.from_string(
        '{% from "_family_pill.html" import family_card %}{{ family_card(k, 3, True) }}'
    )
    return template.render(k=k)


def test_the_sprite_holds_one_symbol_per_sign(art) -> None:
    sprite = str(family_art.load().sprite)

    assert '<symbol id="fz-harsh" viewBox="0 0 24 24">' in sprite
    assert SIGN in sprite


def test_without_the_folder_there_is_nothing_to_show(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(family_art, "PICTURES_DIR", tmp_path / "fehlt")
    monkeypatch.setattr(family_art, "SIGNS_DIR", tmp_path / "fehlt")

    loaded = family_art.load()

    assert str(loaded.sprite) == ""
    assert loaded.picture("harsh") is None
    assert str(loaded.sign("harsh")) == ""


def test_the_intake_card_shows_the_picture_instead_of_the_sign(art, data_dir) -> None:
    create_app()

    card = _card("harsh")

    assert 'src="/familien/harsh.jpg"' in card
    # Bild und Zeichen zeigen dasselbe Motiv; auf der Karte genügt das Bild.
    assert "#fz-" not in card
    # Das Herz bleibt — es ist der Zustand der Karte, nur rückt es ans Ende.
    assert 'href="#ic-heart"' in card


def test_without_a_picture_the_card_carries_the_sign(art, data_dir) -> None:
    (art / "zeichen" / "dark.svg").write_text(SIGN, encoding="utf-8")
    create_app()

    card = _card("dark")

    assert "/familien/" not in card
    assert 'href="#fz-dark"' in card


def test_a_family_without_art_keeps_the_plain_card(art, data_dir) -> None:
    create_app()

    card = _card("funny")

    assert "/familien/" not in card
    assert "#fz-" not in card


def test_the_pictures_are_served_and_the_sprite_is_on_every_page(art, data_dir) -> None:
    client = TestClient(create_app())

    picture = client.get("/familien/harsh.jpg")
    page = client.get("/")

    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/jpeg"
    assert 'id="fz-harsh"' in page.text


def test_the_evidence_toggle_says_whether_it_is_open(art, data_dir) -> None:
    """„Belege“ klappt auf und zu; das muss auch vorgelesen werden (#118)."""
    create_app()

    card = _card("harsh")

    assert 'aria-expanded="false"' in card
    assert ":aria-expanded=" in card


def test_a_locked_boost_says_why_where_it_is_seen(art, data_dir) -> None:
    """Warum „Verstärken“ gesperrt ist, sagte nur ein `title` — auf dem Telefon
    nie zu sehen (#118). Der Grund steht jetzt daneben."""
    create_app()
    pill = SimpleNamespace(family_id="harsh", name="hart", on=True, boosted=False,
                           frequent=False, pattern=False)
    k = SimpleNamespace(pill=pill, description="", strength="trägt", level=2, evidence=[])
    card = TEMPLATES.env.from_string(
        '{% from "_family_pill.html" import family_card %}{{ family_card(k, 3, False) }}'
    ).render(k=k)

    assert ">schon drei verstärkt<" in card


# --- Die übrigen Orte (#117) -----------------------------------------------------


def _overview(family_id: str) -> str:
    pill = SimpleNamespace(family_id=family_id, name="hart", side="for",
                           weight_word="deutlich", sentence="")
    c = SimpleNamespace(groups=[SimpleNamespace(dimension="Stimmung", pills=[pill])])
    return TEMPLATES.env.from_string(
        '{% from "_comparison.html" import overview %}{{ overview(c) }}'
    ).render(c=c)


def _bridge(family_id: str) -> str:
    mine = SimpleNamespace(family_id=family_id, name="hart", value=1.0, hit=True)
    b = SimpleNamespace(mine=[mine], book=[], links=[])
    return TEMPLATES.env.from_string(
        '{% from "_comparison.html" import bridge %}{{ bridge(b) }}'
    ).render(b=b)


def test_the_rating_pills_carry_the_sign_before_the_word(art, data_dir) -> None:
    create_app()

    html = _overview("harsh")

    assert html.index("#fz-harsh") < html.index(">hart")
    assert "fz-inline" in html


def test_the_coverage_list_carries_the_sign(art, data_dir) -> None:
    create_app()

    assert "#fz-harsh" in _bridge("harsh").split("data-bridge-list", 1)[1].split("</ul>", 1)[0]


def test_without_a_sign_the_pills_stay_as_they_were(art, data_dir) -> None:
    create_app()

    assert "#fz-" not in _overview("funny")
    assert "#fz-" not in _bridge("funny").split("data-bridge-list", 1)[1].split("</ul>", 1)[0]


def test_the_profile_names_what_you_like_with_its_sign(art, data_dir) -> None:
    from conftest import give_profile
    from ebook_watchlist import paths
    from ebook_watchlist.store import Store

    client = TestClient(create_app())
    give_profile(Store(paths.db_path()))

    liked = client.get("/profile").text.split("Das magst du", 1)[1].split("</section>", 1)[0]

    assert "#fz-harsh" in liked


def _profile_page(liked, counterweights) -> str:
    from conftest import give_profile
    from ebook_watchlist import paths
    from ebook_watchlist.judging.facets import ReadingProfile
    from ebook_watchlist.store import Store

    client = TestClient(create_app())
    give_profile(Store(paths.db_path()),
                 profile=ReadingProfile(facets=(), counterweights=counterweights, liked=liked))
    return client.get("/profile").text


def test_a_boosted_family_wears_a_shower_of_stars(art, data_dir) -> None:
    """Der Stern vor dem Namen stand neben dem Familienzeichen — zwei Symbole
    hintereinander. Verstärkt heißt jetzt: Sterne im Hintergrund der Pille."""
    from ebook_watchlist.judging.facets import Liked

    page = _profile_page((Liked("harsh", True),), ())
    liked = page.split("Das magst du", 1)[1].split("</section>", 1)[0]

    assert "pill-boosted" in liked
    assert "#ic-star" not in liked
    assert "#fz-harsh" in liked


def test_a_counterweight_carries_its_sign_instead_of_the_ban_icon(art, data_dir) -> None:
    """Die Karte heißt schon „Zählt gegen ein Buch“; das Verbotszeichen vor
    jedem Namen sagte es ein zweites Mal. Dort steht jetzt die Familie."""
    from ebook_watchlist.judging.facets import Counterweight

    page = _profile_page((), (Counterweight(("harsh",)),))
    against = page.split("Zählt gegen ein Buch", 1)[1].split("</section>", 1)[0]

    assert "#ic-ban" not in against
    assert "#fz-harsh" in against
