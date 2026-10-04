"""Das freie Genre der gespeicherten Steckbriefe auf die Liste abbilden (ADR 37, #89).

Einmalig: danach wählt das Modell selbst aus `docs/genres.yaml` (#90), und
diese Regeln werden nicht gepflegt. Gelesen werden Genre und Untergenre, wie
das Modell sie geschrieben hat; die erste Regel, die passt, gewinnt — die
feineren stehen deshalb oben. Was keine Regel trifft, bekommt das „General"
seiner Gruppe, wenn die Gruppe zu erkennen ist, sonst kein Genre.

Kein Modellaufruf. Der Freitext bleibt im Steckbrief stehen, der Code kommt
daneben; die Übersicht `overview` zeigt der Leserin vor dem Schreiben, was
woraus wird.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

#: (Code, Muster im kleingeschriebenen „Genre | Untergenre"). Reihenfolge zählt.
RULES: tuple[tuple[str, str], ...] = (
    # Psychologischer Horror vor dem Psychothriller: sonst fängt „psycho" ihn.
    ("FIC015050", r"psychologischer horror|psycho-?horror"),
    # Thriller — die Untergenres zuerst, „Psycho" vor dem übrigen Thriller.
    ("FIC031100", r"domestic|familien-?thriller|nachbarschafts?-?thriller|ehe-?thriller"),
    ("FIC031080", r"psycho|psychologisch"),
    ("FIC006000", r"spionage|agenten|polit-?thriller|politthriller"),
    ("FIC036000", r"techno|wissenschafts?-?thriller|öko-?thriller|medizin|bio-?thriller"),
    ("FIC031070", r"übernatürlich(er)? thriller|mystery-thriller|supernatural thriller"),
    ("FIC031010", r"serienm|serienkiller|forensi|procedural-thriller|ermittler-?thriller"
                  r"|crime-?thriller"),
    # Krimi
    ("FIC022070", r"cosy|cozy|gemütlich|wohlfühl"),
    ("DE-REGIONALKRIMI", r"regional|heimat|küsten|insel|ostsee|nordsee|alpen|eifel|provinz"),
    ("FIC022020", r"polizei|procedural"),
    ("FIC022080", r"skandinav|nordic|scandi|schweden|norweg|island|irland"),
    ("FIC060000", r"schwarzhumor|kriminalkomödie|krimikomödie|humorvoller krimi"
                  r"|(krimi|kriminal)[^|]*\|[^|]*(komödie|satir|humor)"),
    # Science-Fiction und Dystopie
    ("FIC028030", r"space opera|weltraum"),
    ("FIC028050", r"military"),
    ("FIC028100", r"cyberpunk"),
    ("FIC028070", r"post-?apokalyp|apokalyp"),
    ("FIC055000", r"dystop"),
    # Fantasy
    ("FIC027030", r"romantasy|fantasy-?romance|romantische fantasy"),
    ("FIC009060", r"urban fantasy"),
    ("FIC009070", r"dark fantasy|grimdark"),
    ("FIC009020", r"high fantasy|epische fantasy|epic fantasy|heroische|sword|epos"),
    # Horror
    ("FIC015030", r"kreatur|monster"),
    ("FIC015040", r"übernatürlich|supernatural|paranormal|dämon|geister|okkult|folk horror|spuk"),
    # Liebesroman
    ("FIC027020", r"contemporary romance|liebeskomödie|romantische komödie|liebesroman|romance"),
    # Biografie vor den Gruppen: „Erinnerungen" ist kein Roman.
    ("BIO000000", r"biograf|autobiograf|memoir|erinnerung|zeitzeug"),
    # Gruppen, deren Untergenre keine Regel trifft: ihr „General" — vor den
    # Allerweltswörtern „Abenteuer", „Satire", „historisch", damit „Fantasy |
    # Abenteuer" Fantasy bleibt.
    ("FIC028000", r"science|sci-?fi"),
    ("FIC009000", r"fantasy"),
    ("FIC015000", r"horror"),
    ("FIC022000", r"historischer krimi"),
    ("FIC014000", r"historisch"),
    ("FIC002000", r"abenteuer"),
    ("FIC016000", r"humor|komödie|satir"),
    ("FIC019000", r"gegenwart|gesellschaft|familienroman|familiensaga|literarisch|literary"),
    ("FIC031000", r"thriller|suspense"),
    ("FIC022000", r"krimi|crime|mystery|detektiv|kriminalroman"),
)

_COMPILED = tuple((code, re.compile(pattern)) for code, pattern in RULES)


def genre_code(genre: str | None, subgenre: str | None) -> str | None:
    """Der Code zu einem freien Genre, oder ``None``."""
    text = f"{genre or ''} | {subgenre or ''}".casefold()
    for code, pattern in _COMPILED:
        if pattern.search(text):
            return code
    return None


def overview(pairs: Iterable[tuple[str | None, str | None]]) -> list[tuple[str | None, str, int]]:
    """(Code, „Genre | Untergenre", Anzahl) für jede vorkommende Schreibweise,
    nach Code und Häufigkeit — zum Durchsehen vor dem Schreiben."""
    counts = Counter((genre or "", subgenre or "") for genre, subgenre in pairs)
    rows = [
        (genre_code(genre, subgenre), f"{genre} | {subgenre}".strip(" |"), n)
        for (genre, subgenre), n in counts.items()
    ]
    return sorted(rows, key=lambda row: (row[0] or "~", -row[2], row[1]))
