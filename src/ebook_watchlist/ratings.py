"""Woher ein Urteil über ein Buch stammt (Ticket 21, ADR 17).

Ein Urteil, das die Anwendung selbst fällt, wird seit ADR 33 gerechnet und nie
gespeichert (``judging``). Gespeichert wird nur, was ein Mensch sagt: die Sterne
der Leserin und die Durchschnitte fremder Leser:innen. Die Herkunft gehört in
den Schlüssel und nicht in eine Spalte daneben, denn beide dürfen zu einem Buch
nebeneinander stehen, und keines überschreibt das andere.

Dieses Modul steht für sich, damit ``store`` es kennt, ohne das Modell zu
importieren — der Store hat damit nichts zu tun.
"""

from __future__ import annotations

from .models import Observation

#: Die Leserin selbst.
BY_READER = "reader"
#: Die Leserschaft der Onleihe — ein Durchschnitt aus vielen fremden Stimmen,
#: keine Aussage ueber das Leseprofil (Ticket 54). Steht hier und nicht in
#: einer eigenen Tabelle, weil ``rating`` schon nach ``(subject, origin)``
#: geschluesselt ist: eine weitere Quelle ist eine weitere Herkunft (ADR 19).
#:
#: **Je Bibliothek, nicht generisch.** Ein Urteil des Tors haengt an der ISBN,
#: sobald es eine gibt (``subject_of``) — der Quellname faellt dann aus dem
#: Schluessel. Eine Herkunft "library_readers" liesse deshalb zwei Bibliotheken
#: fuer dieselbe ISBN in *dieselbe* Zeile schreiben, und die zweite ueberschriebe
#: die erste bei jedem Lauf, stumm und je nach Reihenfolge der Quellen. Alle
#: fuenf Zeilen im echten Bestand sind ISBN-Zeilen; es waere der Normalfall.
BY_ONLEIHE_READERS = "onleihe_readers"

RATING_ORIGINS: frozenset[str] = frozenset({BY_READER, BY_ONLEIHE_READERS})

#: Fremde Stimmen: kein Urteil gegen das Leseprofil, also auch nicht an eine
#: Profilversion gebunden und von keiner neuen Fassung entwertet.
FOREIGN_ORIGINS: frozenset[str] = frozenset({BY_ONLEIHE_READERS})

#: Was ein Mensch gesagt hat. Verfällt nicht mit einer neuen Profilversion,
#: und wird von keinem Modellurteil überschrieben.
HUMAN_ORIGINS: frozenset[str] = frozenset({BY_READER})

LABELS: dict[str, str] = {
    BY_READER: "deine Bewertung",
    BY_ONLEIHE_READERS: "Leser:innen der Onleihe",
}


def book_subject(book_id: int) -> str:
    """Der Schlüssel, an dem ein Urteil über ein *Buch* hängt.

    Das Tor schlüsselt seine Urteile am Fund (``isbn:…`` oder ``item:…``), weil
    es dreihundert Funde bewertet, von denen die wenigsten je eine Buchzeile
    bekommen (ADR 18). Was die Leserin sagt, gilt dagegen dem Buch: sie vergibt
    ihre Sterne auf der Buchseite, und dieselbe Zahl soll gelten, egal über
    welche Quelle das Buch das nächste Mal auftaucht.
    """
    return f"book:{book_id}"


def subject_of(observation: Observation) -> str:
    """Woran ein Urteil des Tors hängt.

    Die ISBN, wo es eine gibt — dann findet dasselbe Buch sein Urteil auch über
    eine andere Quelle wieder. Sonst der Fund selbst; Bündel und Einzelfolgen
    haben keine ISBN, und für die ist ein Urteil je Quelle ehrlicher als eines,
    das über Titel geraten wäre.
    """
    if observation.isbn:
        return f"isbn:{observation.isbn}"
    return f"item:{observation.source}:{observation.source_item_id}"
