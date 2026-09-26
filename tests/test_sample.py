"""Die Leseprobe: der Anfang des Buchs, aus einer EPUB-Datei gelesen (#17).

Die Proben hier sind von Hand gebaute, winzige EPUBs. Eine echte Probe wiegt
ein Megabyte, fast alles Bilder — als Fixture waere sie Ballast, und was
geprueft wird, ist das Lesen der Struktur, nicht ein bestimmter Verlag.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from ebook_watchlist.http import FetchError, NotFound, RateLimited
from ebook_watchlist.sample import SAMPLE_WORDS, fetch_opening, opening

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def page(text: str) -> str:
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title>'
        f"<style>p {{ color: red }}</style></head><body><p>{text}</p></body></html>"
    )


def epub(*pages: tuple[str, str], spine: list[str] | None = None) -> bytes:
    """Ein EPUB mit diesen Seiten; ``spine`` gibt die Lesereihenfolge vor."""
    ids = [name for name, _ in pages]
    manifest = "".join(
        f'<item id="{name}" href="text/{name}.xhtml" media-type="application/xhtml+xml"/>'
        for name in ids
    )
    itemrefs = "".join(f'<itemref idref="{name}"/>' for name in (spine or ids))
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        f"<manifest>{manifest}</manifest><spine>{itemrefs}</spine></package>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", opf)
        for name, text in pages:
            archive.writestr(f"OEBPS/text/{name}.xhtml", page(text))
    return buffer.getvalue()


CHAPTER = " ".join(["Regen"] * 400)


def test_the_opening_skips_the_front_matter() -> None:
    """Titelei, Impressum, "Über das Buch" sind kurz und sagen nichts darüber,
    wie das Buch erzählt. Gelesen wird ab der ersten Seite mit Erzähltext."""
    probe = epub(
        ("cover", "Dark Matter"),
        ("impressum", "© 2016 Goldmann. ISBN 978-3-641-17142-1"),
        ("kapitel1", "Eins. " + CHAPTER),
    )

    assert opening(probe).startswith("Eins. Regen")


def test_the_spine_decides_the_order_not_the_archive() -> None:
    """Die Reihenfolge im Archiv ist zufällig; die Lesereihenfolge steht im
    ``spine`` der OPF-Datei."""
    probe = epub(
        ("b", "Zwei. " + CHAPTER),
        ("a", "Eins. " + CHAPTER),
        spine=["a", "b"],
    )

    text = opening(probe)

    assert text.index("Eins.") < text.index("Zwei.")


def test_the_opening_is_cut_at_a_word_limit() -> None:
    """Ein paar tausend Wörter zeigen Stimme und Tempo. Die ganzen fünfzig
    Seiten einer Probe kosteten je Buch das Zehnfache im Prompt."""
    probe = epub(*[(f"k{n}", CHAPTER) for n in range(20)])

    assert len(opening(probe).split()) == SAMPLE_WORDS


def test_markup_and_styles_do_not_reach_the_text() -> None:
    text = opening(epub(("k", "Eins &amp; zwei. " + CHAPTER)))

    assert "Eins & zwei." in text
    assert "<" not in text
    assert "color" not in text


@pytest.mark.parametrize("broken", [b"kein zip", b"PK\x03\x04 abgebrochen"])
def test_a_broken_file_is_no_sample(broken: bytes) -> None:
    """Eine kaputte Probe kostet das Buch die Probe, nicht das Urteil."""
    assert opening(broken) is None


def test_a_sample_without_prose_is_none() -> None:
    assert opening(epub(("cover", "Dark Matter"), ("impressum", "ISBN"))) is None


class Client:
    def __init__(self, answer: bytes | Exception) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.asked.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_fetching_reads_the_file_behind_the_address() -> None:
    client = Client(epub(("k", "Eins. " + CHAPTER)))

    assert fetch_opening(client, "https://example.org/probe.epub").startswith("Eins.")
    assert client.asked == ["https://example.org/probe.epub"]


@pytest.mark.parametrize("failure", [FetchError("weg"), NotFound("404")])
def test_a_missing_sample_is_none(failure: Exception) -> None:
    assert fetch_opening(Client(failure), "https://example.org/probe.epub") is None


def test_throttling_is_passed_on() -> None:
    """429 heißt Halt für alles Weitere (ADR 7) — auch hier."""
    with pytest.raises(RateLimited):
        fetch_opening(Client(RateLimited("429")), "https://example.org/probe.epub")
