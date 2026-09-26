"""Turning Observations into Deltas.

The comparison is always *latest stored Observation* vs *what we just saw*, never
"since yesterday" — that is what makes a Run stateless with respect to its
schedule (ADR 4). A first sighting has nothing to compare against and is not a
Delta.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Iterable, Mapping, Sequence

from .bundle_deal import BundleAdvantage
from .config import Settings
from .deals import is_strong_deal
from .junk import is_junk
from .models import Availability, Delta, DeltaKind, MatchReason, Observation

#: Kinds worth waking the reader for. Everything else is recorded but silent
#: (ADR 9 §6b: a title going *away* is not news).
NOTIFIABLE: frozenset[DeltaKind] = frozenset(
    {DeltaKind.FIRST_SEEN, DeltaKind.BECAME_AVAILABLE, DeltaKind.PRICE_DROP}
)

#: The two channels the reader did not name a title for. Turning up is not
#: enough here — a discovery has to be a deal to be worth reporting (ADR 19),
#: whereas a Watchlist Entry is reported at any price.
DISCOVERY_REASONS: frozenset[MatchReason] = frozenset(
    {MatchReason.PROFILE_AUTHOR, MatchReason.GENRE_CATEGORY}
)


def worth_announcing(
    observation: Observation,
    settings: Settings | None,
    *,
    bundle_advantage: BundleAdvantage | None = None,
) -> bool:
    """Whether this item may reach the reader at all (ADR 19).

    A Watchlist Entry always may: the reader named this book, and the price is
    not what makes it interesting. **A discovery has to be a deal** — a new
    title from a Reference Author on the same terms as one from a Thema.

    Reference Authors carried an exception for a while, and it was written down
    as temporary: until the rating gate existed, the price was the only sieve
    there was, and it sieves for the wrong thing — applied to the shelves it
    left 106 titles of which nine were by one English-language self-publisher,
    while a new Jo Nesbø at 11,99 € went silent. The gate arrived with ticket 12
    and the exception stayed, in the code, in its own test's name and against
    what ADR 19 says in as many words. It ends here: relevance is the gate's
    question, urgency is the price's, and this function only asks the second.

    Drei Wege sind es: ein Schnaeppchen, ein Buch, das die Bibliothek gerade
    hergibt, **oder** eine Sammelausgabe, die gegenueber ihren Einzelbaenden
    spart (ADR 24). Bei einer Ausleihe ist der Preis gleichgueltig; beim
    Buendel ist der absolute Preis die falsche Frage, denn zwei Baende sind
    nun einmal teurer als einer.

    ``bundle_advantage`` rechnet dieser Weg nicht selbst aus — dafuer braeuchte
    er die Preise anderer Buecher und damit die Datenbank. Der Aufrufer legt
    das Ergebnis dazu; ``bundle_deal.advantage_for`` ist die eine Stelle, die
    es ermittelt.

    Nothing is thrown away. The Observation is stored either way, so a book
    found at 14,99 € waits quietly and speaks up the day it drops.
    """
    if observation.match_reason is MatchReason.WATCHLIST:
        return True
    if is_junk(observation):
        return False
    # Ausleihbar schlaegt jeden Preis: was die Bibliothek hergibt, kostet
    # nichts, und "unter 5,00 EUR" ist dann keine sinnvolle Huerde mehr.
    if observation.availability is Availability.AVAILABLE:
        return True
    if bundle_advantage is not None:
        return True
    return settings is not None and is_strong_deal(observation.price_cents, settings)


#: Was eine Sammelausgabe gegenueber ihren Einzelbaenden spart. Als Funktion
#: hereingereicht, weil die Antwort die Preise *anderer* Buecher braucht und
#: damit die Datenbank — die dieses Modul nicht kennt (ADR 24).
AdvantageOf = Callable[[Observation], BundleAdvantage | None]


def compare(
    current: Observation,
    previous: Observation | None,
    settings: Settings | None = None,
    advantage_of: AdvantageOf | None = None,
) -> list[Delta]:
    """Every change between two Observations of the same item, notifiable or not."""
    advantage = advantage_of(current) if advantage_of else None
    if previous is None:
        # Nothing is lost by staying quiet: the Observation is stored either
        # way, so a book first seen at full price surfaces the day it drops.
        if worth_announcing(current, settings, bundle_advantage=advantage):
            return [Delta(DeltaKind.FIRST_SEEN, current, None)]
        return []

    deltas: list[Delta] = []

    if current.availability is not None and previous.availability is not None:
        if current.availability != previous.availability:
            if current.availability is Availability.AVAILABLE:
                deltas.append(Delta(DeltaKind.BECAME_AVAILABLE, current, previous))
            elif previous.availability is Availability.AVAILABLE:
                deltas.append(Delta(DeltaKind.BECAME_UNAVAILABLE, current, previous))

    if current.price_cents is not None and previous.price_cents is not None:
        if current.price_cents < previous.price_cents:
            # The same bar a first sighting has to clear. Without this the rule
            # was strict at the front door and open at the back: a shelf title
            # slipping from 11,99 € to 11,49 € would have been reported after
            # being kept quiet at 11,99 €.
            if worth_announcing(current, settings, bundle_advantage=advantage):
                deltas.append(Delta(DeltaKind.PRICE_DROP, current, previous))
        elif current.price_cents > previous.price_cents:
            deltas.append(Delta(DeltaKind.PRICE_RISE, current, previous))

    return deltas


def compute_deltas(
    observations: Sequence[Observation],
    previous: Mapping[tuple[str, str], Observation],
    settings: Settings | None = None,
    advantage_of: AdvantageOf | None = None,
) -> list[Delta]:
    """The notifiable Deltas for one Run's worth of Observations."""
    return [
        delta
        for observation in observations
        for delta in compare(
            observation, previous.get(observation.key), settings, advantage_of
        )
        if delta.kind in NOTIFIABLE
    ]


def keys_of(observations: Iterable[Observation]) -> list[tuple[str, str]]:
    return [observation.key for observation in observations]


def suppress_unseeded_interests(
    deltas: Sequence[Delta],
    origin: Mapping[tuple[str, str], int],
    seeded: Container[tuple[str, int]],
) -> list[Delta]:
    """Erstsichtungen aus einem Interesse verschlucken, das noch nie gefegt wurde.

    Loest :func:`suppress_unseeded` ab. Der alte Schluessel war
    ``(source, match_reason, category)``, und ``category`` blieb bei
    Autor:innen leer — **alle** Autor:innen teilten sich also eine Aussaat: die
    erste saete still an, jede weitere meldete ihre ganze Backlist als
    Neuzugaenge. Pro Interesse gefuehrt verhalten sich Autor:in und Thema
    gleich (Ticket 05).

    Ein Fund ohne bekannte Herkunft wird durchgelassen: das ist ein
    Watchlist-Treffer, und der hat keine Aussaat.

    ``seeded`` hält Paare aus Quelle und Interesse: angesät ist je Quelle. Mit
    der Nummer allein galt ein Thema, das beam kannte, auch bei OverDrive als
    angesät — und dessen erster Durchgang flutete den Tagesbericht (#74).
    """
    return [
        delta
        for delta in deltas
        if delta.kind is not DeltaKind.FIRST_SEEN
        or delta.current.match_reason not in DISCOVERY_REASONS
        or origin.get(delta.current.key) is None
        or (delta.current.source, origin[delta.current.key]) in seeded
    ]
