"""Der Vorteil einer Sammelausgabe gegenüber den Einzelbänden (ADR 24).

Die dritte Art von Angebot. Ein **Schnäppchen** vergleicht einen Preis mit
einer Grenze, ein **Preissturz** ein Produkt mit sich selbst — beides sieht
eine Sammelausgabe nie, weil sie in absoluten Zahlen teurer ist als jeder
Einzelband. Hier wird sie mit *anderen Produkten* verglichen:

    Der Kruzifix-Killer / Der Vollstrecker   12,99 €
    Der Kruzifix-Killer                      10,99 €
    Der Vollstrecker                         10,99 €
                                             -------
    zusammen                                 21,98 €  →  41 % gespart

Es braucht dafür **keine neue Schwelle**: ``min_discount_pct`` aus dem Profil
tut es. Gemessen an den vier echten Sammelausgaben im Bestand liegen die
Ersparnisse bei 25 bis 45 % — die 25 % von "Achtsam morden (5in1)" sind der
Härtetest dafür, dass die Regel nicht großzügig ist.

Zwei Bedingungen, beide aus ADR 24, beide aus dem Betrieb begründet:

**Nichts wird geraten.** Sind nicht *alle* enthaltenen Bände mit Preis
bekannt, gibt es keinen Vorteil — kein geschätzter Vergleichspreis, keine
hochgerechnete Bandzahl. Ein erfundener Vergleich wäre schlimmer als keine
Meldung.

**Kein Ramsch vom Themenregal.** Von 19 Sammelausgaben im Bestand sind 14
Massenware („5 Spuk Thriller", „2 Gruselkrimis"). Gemeldet wird nur, was an
einem Watchlist-Titel oder einer Referenzautor:in hängt — dieselbe Linie, die
``junk.py`` schon zieht.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config import Settings
from .matching.bundles import looks_like_bundle, volume_titles
from .models import MatchReason, Observation

#: Anlässe, bei denen eine Sammelausgabe überhaupt gemeldet werden darf.
REPORTABLE = frozenset({MatchReason.WATCHLIST, MatchReason.PROFILE_AUTHOR})


@dataclass(frozen=True, slots=True)
class BundleAdvantage:
    """Was die Sammelausgabe gegenüber den Einzelbänden spart."""

    volumes: tuple[str, ...]
    #: Was die Bände einzeln zusammen kosten.
    singles_cents: int
    #: Was die Sammelausgabe kostet.
    price_cents: int

    @property
    def saved_cents(self) -> int:
        return self.singles_cents - self.price_cents

    @property
    def saved_pct(self) -> int:
        return round(self.saved_cents * 100 / self.singles_cents)

    @property
    def summary(self) -> str:
        """Ein Satz für Tagesbericht und Stapel."""
        anzahl = len(self.volumes)
        return (
            f"{anzahl} Bände für {self.price_cents / 100:.2f} € "
            f"statt {self.singles_cents / 100:.2f} € — {self.saved_pct} % gespart"
        ).replace(".", ",")


def advantage_for(
    observation: Observation,
    settings: Settings,
    price_of: Callable[[str], int | None],
    *,
    contained: Callable[[str], tuple[str, ...]] | None = None,
    price_of_isbn: Callable[[str], int | None] | None = None,
) -> BundleAdvantage | None:
    """Der Vorteil dieser Sammelausgabe — oder ``None``.

    ``price_of`` schlägt den Einzelpreis zu einem Bandtitel nach. Als Funktion
    übergeben, damit die Rechnung ohne Datenbank prüfbar bleibt und die eine
    Stelle, die sucht, austauschbar ist.
    """
    if observation.match_reason not in REPORTABLE:
        return None
    if observation.price_cents is None or observation.price_cents <= 0:
        return None
    if not looks_like_bundle(observation.title):
        return None

    # Der beste Weg zuerst: sagt die DNB, welche ISBNs drinstecken, gibt es
    # nichts zu raten und nichts zu vergleichen — die ISBN ist exakt
    # (MARC 770, ADR 25). Erst wenn sie schweigt, wird der Name gelesen.
    if contained is not None and price_of_isbn is not None and observation.isbn:
        aus_der_bibliothek = contained(observation.isbn)
        if len(aus_der_bibliothek) >= 2:
            aus_preisen = [price_of_isbn(isbn) for isbn in aus_der_bibliothek]
            if all(preis and preis > 0 for preis in aus_preisen):
                return _vorteil(
                    observation,
                    settings,
                    aus_der_bibliothek,
                    sum(preis for preis in aus_preisen if preis),
                )
            return None

    bände = volume_titles(observation.title)
    if len(bände) < 2:
        return None

    preise = [price_of(titel) for titel in bände]
    # Alle oder keiner: ein fehlender Einzelpreis macht die Summe zu einer
    # Schätzung, und geschätzt wird hier nicht.
    if any(preis is None or preis <= 0 for preis in preise):
        return None

    einzeln = sum(preis for preis in preise if preis is not None)
    return _vorteil(observation, settings, bände, einzeln)


def _vorteil(
    observation: Observation,
    settings: Settings,
    bände: tuple[str, ...],
    einzeln: int,
) -> BundleAdvantage | None:
    """Die Rechnung selbst — gleich, ob die Bände Titel oder ISBNs sind."""
    if observation.price_cents is None or einzeln <= observation.price_cents:
        return None
    vorteil = BundleAdvantage(
        volumes=bände, singles_cents=einzeln, price_cents=observation.price_cents
    )
    return vorteil if vorteil.saved_pct >= settings.min_discount_pct else None


def advantage_finder(store, settings):
    """Eine Funktion, die zu einer Beobachtung ihren Buendelvorteil sagt.

    Einmal gebaut, viele Male gefragt: die Preistabellen werden hier **einmal**
    geholt und nicht je Buch. Dieselbe Funktion bedient den Stapel, den
    Tagesbericht und die Meldelogik — sonst gaebe es den Vorteil an einer
    Stelle und an der anderen nicht, und genau das war der Fall (Review nach
    1.0).

    Der Quellenname wird **gefragt**, nicht hingeschrieben: Preise zweier
    Shops zu addieren waere eine Summe, die niemand bezahlen kann, also wird
    je Shop verglichen.
    """
    from .sources import registry

    tabellen = [
        (
            store.latest_prices_by_title(settings.slug, name),
            store.prices_by_isbn(settings.slug, name),
        )
        for name in registry.shops(settings)
    ]

    def finde(observation):
        for nach_titel, nach_isbn in tabellen:
            vorteil = advantage_for(
                observation,
                settings,
                nach_titel.get,
                contained=store.contained_isbns,
                price_of_isbn=nach_isbn.get,
            )
            if vorteil is not None:
                return vorteil
        return None

    return finde
