"""Ein Zeichen je Beziehung — eine Stelle für alle Seiten.

Dieselbe Sache soll überall gleich aussehen: das Fernglas heißt „beobachten"
im Stapel, auf der Startseite, auf der Fundseite und auf der Buchseite. Vorher
kannte nur der Stapel drei davon, und die Buchseite gar keins.

Die Zeichen liegen bewusst *nicht* bei ``RELATION_LABELS`` in ``relations.py``:
ein Sprite-Name ist Oberfläche, und das Modul darunter soll nichts davon
wissen (ADR 22 trennt Bezeichner und Anzeige, nicht Fach und Darstellung —
diese Trennung kommt aus ADR 20).
"""

from __future__ import annotations

from ..relations import REMOVED, RelationKind

#: Sprite-Namen aus ``base.html``. Keins ist anderswo besetzt: ``ic-play``
#: heißt in der Watchlist-Zeile „aktivieren", ``ic-user`` steht im Profil für
#: Autor:innen.
RELATION_ICONS: dict[str, str] = {
    # Fernglas statt Lupe: die Lupe sagt „suchen", das Fernglas „im Blick
    # behalten" — und genau das ist der Unterschied zur Suche im Shop.
    str(RelationKind.WATCHING): "ic-binoculars",
    str(RelationKind.OWNED): "ic-check",
    str(RelationKind.LIKED): "ic-heart",
    # Ein durchgestrichener Kreis, kein zweites Kreuz: „Kein Interesse" ist
    # ein Urteil über das Buch, „Ausgeschlossen" eine Anweisung ans Werkzeug.
    str(RelationKind.DISLIKED): "ic-ban",
    str(RelationKind.DISMISSED): "ic-x",
    # Eine Liste mit Minus: vom Zettel streichen, ohne Urteil über das Buch (#72).
    REMOVED: "ic-unlist",
}
