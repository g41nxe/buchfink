# 29. Ein Zustand hat einen Namen, eine Handlung ein Wort

Eine Buchbeziehung trägt zwei Wörter: den Zustandsnamen („im Besitz"), wo ein
Buch beschrieben wird, und das Knopfwort („Hab ich"), wo entschieden wird. Zwei
Listen, je eine Zuständigkeit, kein Wort auf der anderen Seite.

## Kontext

`RELATION_LABELS` entstand, weil `owned` an vier Stellen vier Namen trug —
„besitze ich", „besessen", „Habe ich", „im Besitz". Die Lösung war *eine*
Liste für alle Ansichten, mit zwei Regeln darüber: Substantive statt
Ich-Sätze, und keine zwei Namen, die sich nur durch ein „nicht" unterscheiden.
Der Design-Review vom 08.09. hat auf dieser Grundlage „Verwerfen" aus dem
Hinweistext des Stapels entfernt, weil der Knopf daneben „Ausgeschlossen" hieß.

Mit der Startseite (Issue #5) bekam dieselbe Handlung einen zweiten Knopf, und
die Frage stellte sich neu: Was steht auf einem Knopf? „Ausgeschlossen" ist die
Antwort auf *„was ist dieses Buch für mich?"* — ein Regalschild, wie Goodreads
und StoryGraph ihre Regale beschriften. Ein Knopf beantwortet eine andere Frage:
*„was tust du damit?"* Darauf antwortet niemand mit einem Regalschild.

Die Nutzerrecherche (docs/research/startseite-tracking-werkzeuge.md) legt nahe,
dass Knöpfe für Ein-Klick-Entscheidungen ein sichtbares Wort brauchen — und
dass dieses Wort die Handlung nennen soll.

## Entscheidung

**Zwei Listen in `relations.py`.** `RELATION_LABELS` bleibt, was es war: der
Zustandsname, gelesen von Buchseite und Profil. Daneben `ACTION_LABELS` mit
einem Wort je Entscheidung — Verwerfen, Hab ich, Beobachten — gelesen von
Stapel, Startseite und dem Watchlist-Menü. `liked` und `disliked` sind kein
Ausgang einer Entscheidung im Stapel und haben kein Knopfwort.

**„Hab ich" verstößt absichtlich gegen „keine Ich-Sätze".** Die Regel galt
für Regalschilder und gilt dort weiter. Auf einem Knopf ist der Ich-Satz die
natürliche Antwort auf die Frage, die der Knopf stellt.

**Kein Wort wandert.** Ein Zustandsname steht nie auf einem Knopf, ein
Knopfwort beschreibt nie ein Buch. Das prüft `test_relations.py` in beide
Richtungen: welche Ansicht aus welcher Liste liest, und dass die beiden
Listen kein Wort teilen.

Verworfen: **eine Liste mit Tätigkeitswörtern für alles.** „Beobachten" als
Regalschild auf der Buchseite liest sich wie eine Aufforderung, nicht wie ein
Zustand. Und: **zwei Wörter je Stelle nach Gefühl.** Genau das war der
Ausgangszustand, den `RELATION_LABELS` beendet hat.

## Folgen

- Die Vorschlagsseite und das Watchlist-Menü sagen dasselbe wie die Startseite.
  Der Hinweistext des Stapels nennt wieder „Verwerfen" — diesmal zu Recht.
- Das Glossar in `CONTEXT.md` trägt die Spalte „on the button".
- Wer eine vierte Ansicht mit Entscheidungsknöpfen baut, liest aus
  `ACTION_LABELS`; wer einen Zustand zeigt, aus `RELATION_LABELS`. Eine dritte
  Liste gibt es nicht.

## Nachtrag (10.09.2026, Issue #9)

**Auf jedem Knopf steht das Knopfwort — auch auf der Buchseite.** Die
Entscheidung oben hatte die Buchseite den Zustandsnamen lesen lassen, weil ihre
fünf Schaltflächen wie Regalschilder gedacht waren. Nebeneinandergestellt hielt
das nicht: auf der Fundseite hieß derselbe Knopf „Beobachten", auf der
Buchseite „in Beobachtung", und beide tun dasselbe. Die eigene Regel des ADR —
*ein Zustandsname steht nie auf einem Knopf* — sprach dabei gegen die eigene
Zuordnung.

`ACTION_LABELS` trägt deshalb jetzt alle fünf Arten. `liked` und `disliked`
behalten ihr Wort aus beiden Listen: „Mag ich" ist Regalschild und Antwort
zugleich. Die Listen dürfen sich also treffen; verboten bleibt der
Rollentausch, und das prüft `test_relations.py` jetzt an den Ansichten statt
an einem Schnittmengen-Vergleich.

**Was gerade gilt, sagt die Farbe.** Der aktive Knopf ist gefüllt. Die Zeile
„Früher: im Besitz, Mag ich" ist von der Buchseite verschwunden: sie sagte, was
gerade *nicht* gilt, an der wichtigsten Stelle der Seite. In der Datenbank
bleiben stillgelegte Beziehungen (ADR 18).

Der Zustandsname bleibt, wo Bücher in Prosa beschrieben werden: Profil,
Tagesbericht, Watchlist-Status.

**Zwei Wörter noch einmal geschärft (10.09.2026).** Aus „Verwerfen" wird
„Ausschließen": verworfen wird ein Vorschlag, ausgeschlossen ein Buch — und
genau das tut der Knopf, bei jeder Quelle und dauerhaft (ADR 18). Aus „Kein
Interesse" wird „Doof": das Gegenstück zu „Mag ich" ist ein Urteil über das
Buch, kein höflicher Rückzug, und „kein Interesse" klang wie „nicht mehr
zeigen" — also wie der Knopf daneben.

Die Reihenfolge auf der Buchseite folgt daraus: vorn die drei, die es auch im
Stapel gibt, hinten die beiden Urteile nach dem Lesen. Sie beantworten eine
andere Frage — nicht „was tue ich damit?", sondern „wie war es?".

**Groß oder klein (28.10.2026).** Ein Knopf mit Rand oder Fläche beginnt groß
(„Verstärken", „Alle", „Los"): er steht für sich wie eine Überschrift. Ein
Textknopf im Satzfluss — unterstrichen, ohne Rand — bleibt klein
(„zurücknehmen", „neu beschreiben"), weil er Teil des Satzes ist. Vorher
standen beide Schreibweisen nebeneinander, mal am selben Ort.
