"""Woher ein Urteil über ein Buch stammt (Ticket 21, ADR 17).

Solange es nur eine Herkunft gab — das Bewertungstor —, war die Frage
entbehrlich. Mit den dreizehn Urteilen aus ``owned.yaml`` und den Sternen, die
die Leserin selbst vergibt, sind es drei, und der Unterschied ist nicht
kosmetisch:

    Eine 4 von der Leserin ist eine Tatsache.
    Eine 4 vom Modell ist ein Vorschlag.

Deshalb gehört die Herkunft in den Schlüssel und nicht in eine Spalte daneben:
beide dürfen zu einem Buch nebeneinander stehen, und keines überschreibt das
andere.

Dieses Modul steht für sich, damit ``store`` es kennt, ohne ``rating`` zu
importieren — dort hängt das Modell dran, und der Store hat damit nichts zu tun.
"""

from __future__ import annotations

from .models import Observation

#: Das Bewertungstor im Lauf (ADR 19).
BY_MODEL = "model"
#: Im Gespräch vergeben, gegen dasselbe Profil — die dreizehn aus
#: ``owned.yaml``. Maschinenurteile, auch wenn sie im Gespräch entstanden.
BY_CONVERSATION = "conversation"
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

RATING_ORIGINS: frozenset[str] = frozenset(
    {BY_MODEL, BY_CONVERSATION, BY_READER, BY_ONLEIHE_READERS}
)

#: Fremde Stimmen: kein Urteil gegen das Leseprofil, also auch nicht an eine
#: Profilversion gebunden und von keiner neuen Fassung entwertet.
FOREIGN_ORIGINS: frozenset[str] = frozenset({BY_ONLEIHE_READERS})

#: Wessen Urteil ueberhaupt gegen das Leseprofil faellt — und deshalb mit einer
#: neuen Fassung veraltet. Weder was ein Mensch sagt noch was fremde Leser:innen
#: im Schnitt vergeben, gehoert dazu. Eine Liste, damit die Versionspruefung
#: nicht an drei Stellen verschieden gezogen wird (Ticket 54).
PROFILE_BOUND: frozenset[str] = frozenset({BY_MODEL, BY_CONVERSATION})

#: Was ein Mensch gesagt hat. Verfällt nicht mit einer neuen Profilversion,
#: und wird von keinem Modellurteil überschrieben.
HUMAN_ORIGINS: frozenset[str] = frozenset({BY_READER})

LABELS: dict[str, str] = {
    # Nicht "vom Werkzeug bewertet": *wer* gemessen hat, ist die kleinere
    # Auskunft — die groessere ist, *woran* gemessen wurde. Und ein Wort statt
    # dreien: neben den Sternen steht ohnehin, worauf das Urteil ruht.
    BY_MODEL: "Leseprofil",
    # Dieselbe Beschriftung wie das Tor: die dreizehn Urteile aus
    # ``owned.yaml`` sind im Gespraech entstanden, gefaellt hat sie aber das
    # Modell, gegen dasselbe Leseprofil. Bis #13 hiessen sie "deine
    # Bewertung", genau wie die Sterne, die die Leserin selbst vergibt — und
    # verhielten sich doch anders: sie veralten mit dem Profil
    # (PROFILE_BOUND), ihre eigenen Sterne nie. Der Schluessel bleibt
    # getrennt, damit man ihre Herkunft weiterhin findet.
    BY_CONVERSATION: "Leseprofil",
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
