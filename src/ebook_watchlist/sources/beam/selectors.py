"""Every beam-shop-specific string in one place (ADR 7).

Sourced from ``docs/research/beam-shop-interface.md``. The shop is Shopware 5,
so these are the stock Shopware listing classes with a custom theme on top —
they are shared by search results, category listings and author hubs alike.
"""

from __future__ import annotations

BASE = "https://www.beam-shop.de/"
SEARCH_PATH = "search"
AUTHOR_HUB_PATH = "autor-innenwelt/{slug}/"
#: The way to a product page when a product id is all we have. The speaking
#: address carries the category path and the slug, and a bare number says
#: neither; Shopware's own detail route needs only the number and redirects to
#: the speaking one (Ticket 17).
DETAIL_PATH = "detail/index/sArticle/{product_id}"

#: Shopware ignores queries shorter than this and renders an empty result page.
MIN_QUERY_LENGTH = 4
#: ``n`` is clamped to this server-side; asking for more just wastes the request.
MAX_PAGE_SIZE = 100
#: What we ask for when resolving a single title — enough to see past the noise
#: without pulling a megabyte of HTML.
SEARCH_PAGE_SIZE = 48

SORT_BY_RELEASE_DATE = "1"

# --- product tile ---------------------------------------------------------

#: Each product appears two or three times in the DOM (overlay, image and list
#: slots), so tiles must be deduplicated by order number.
TILE = ".product--box[data-ordernumber]"
TILE_TITLE = "a.product--title"
TILE_SUBTITLE = ".product--subtitle"
TILE_AUTHOR = "a.product--author"
TILE_PRICE = ".price--default"
TILE_NOTE_BUTTON = "[data-note-article]"
TILE_BADGE = ".product--badge"
TILE_DESCRIPTION = ".product--description"
#: Das Cover. Lazy geladen, also steht die echte Adresse im srcset-Attribut
#: und nicht im src, das nur ein Platzhalterpixel traegt.
TILE_IMAGE = "a.product--image img"

ATTR_ORDER_NUMBER = "data-ordernumber"
ATTR_CATEGORY_ID = "data-category-id"
ATTR_PRODUCT_ID = "data-note-article"
ATTR_SRCSET = "data-srcset"

# --- product detail page --------------------------------------------------

#: A detail page embeds well over a hundred cross-sell tiles carrying the same
#: classes as the product itself, so every detail selector must be scoped to
#: this container or it will read a recommendation's price instead.
DETAIL_SCOPE = ".product--details"
DETAIL_TITLE = ".product--title"
DETAIL_PRICE_META = 'meta[itemprop="price"]'
#: Die Bestellnummer des Hauptprodukts — dieselbe Form wie auf der Kachel, und
#: im Gegensatz zur ISBN-Liste liegt sie innerhalb des Produktblocks. Auf der
#: ganzen Seite stehen 63 Bestellnummern, hier genau eine.
DETAIL_ORDER_NUMBER = 'input[name="sAdd"]'
#: Auf der Detailseite ist das Bild groesser (600x600 statt 200x200).
DETAIL_IMAGE = "img[data-srcset], img[srcset]"
#: Paketseiten zeigen die Baende mit schlichtem ``src``, ohne ``srcset``.
DETAIL_IMAGE_PLAIN = "img[src]"
#: Die Autor:in auf der Produktseite. Anders als die Kachel traegt der
#: Produktblock keine ``product--author``-Klasse; der Link auf die
#: Autorensuche ist innerhalb des Blocks der einzige seiner Art. Nach der
#: Beschriftung zu greifen hiesse, an einer deutschen UI-Zeichenkette zu
#: haengen, die ein Theme-Update umformuliert.
DETAIL_AUTHOR = 'a[href*="saltFieldLimitation=author"]'
#: Die sprechende Adresse der Seite. Wer ueber die Produktnummer kommt, kennt
#: sie nicht — die Seite selbst nennt sie.
DETAIL_CANONICAL = 'link[rel="canonical"]'
#: Der ganze Klappentext. Die Kachel traegt nur einen Anriss von rund 200
#: Zeichen mit "... Mehr" am Ende; hier stehen im Median das Zehnfache.
DETAIL_DESCRIPTION = "[itemprop=description]"
#: Unter ``[itemprop=description]`` haengen **zwei** Kinder: der sichtbare
#: Anriss und der eingeklappte volle Text. Fuer eine Leserin im Browser ist
#: immer nur eins davon da — ``get_text()`` ueber den Elternknoten nimmt
#: beides und schreibt den Anfang doppelt in die Datenbank (Ticket 40).
DETAIL_DESCRIPTION_FULL = ".description--full"
DETAIL_DESCRIPTION_PREVIEW = ".description--preview"
#: Die Leseprobe als EPUB, verlinkt unter "Downloads" (#17).
DETAIL_SAMPLE = 'a.link--download[href$=".epub"]'
#: Die Schlagwoerter des Shops — Motive, Vergleichstitel, dazu Autor und Titel.
DETAIL_KEYWORDS = 'meta[name="keywords"]'

# --- listing --------------------------------------------------------------

LISTING = ".listing"
ATTR_PAGES = "data-pages"

# --- literals -------------------------------------------------------------

AUTHOR_PREFIX = "von "
BADGE_NEW = "NEU"
BADGE_PREORDER = "Vorbestellbar"

# --- doctor probe ---------------------------------------------------------

PROBE_QUERY = "Krieg der Klone Scalzi"
