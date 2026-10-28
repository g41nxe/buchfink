"""Wo es ein Buch gibt, darf nicht nur die Farbe sagen (Review 28.10., #118).

„Nicht im Katalog“ stand als stumpfes Zeichen in `text-rule` da: 1,35:1 im
Hellen, und den Unterschied zu „gefunden“ trug allein die Farbe. Wer Farben
schlecht unterscheidet, sah zwei gleiche Zeichen.
"""

from __future__ import annotations

from types import SimpleNamespace

from ebook_watchlist.web.app import TEMPLATES


def _render(found: bool) -> str:
    group = SimpleNamespace(library=True, found=found, url=None, count=1,
                            hint="Onleihe: nicht im Katalog")
    template = TEMPLATES.env.from_string(
        '{% from "_source_icons.html" import source_icons %}{{ source_icons(groups) }}'
    )
    return template.render(groups=[group])


def test_a_source_without_the_book_is_struck_through() -> None:
    html = _render(found=False)

    assert "data-missing" in html
    assert 'class="sr-only">nicht verfügbar<' in html


def test_a_source_without_the_book_stays_readable() -> None:
    assert "text-rule" not in _render(found=False)


def test_a_source_with_the_book_carries_no_stroke() -> None:
    assert "data-missing" not in _render(found=True)
