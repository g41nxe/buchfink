# 43. Bessere Regeln verwerfen keine Steckbriefe

Der Fingerabdruck eines Steckbriefs rechnet künftig das Vokabular und die Form
der Antwort, nicht mehr den Wortlaut der Anweisung. Eine besser formulierte
Regel gilt für jeden neuen Steckbrief, ohne die vorhandenen zu verwerfen. Ein
neuer Steckbrief mit weniger Regelverstößen ersetzt einen alten. Einzelheiten
in #69 und #95.

## Kontext

ADR 33 band die Gültigkeit eines Steckbriefs an einen Fingerabdruck über
Anweisung und Vokabular: änderte sich eins von beiden, galt jeder gespeicherte
Steckbrief als veraltet und wurde beim nächsten Bedarf neu angelegt. Bei rund
100 Steckbriefen war das tragbar. Am 26.10.2026 sind es 500 (467 Bücher), und
221 davon (47 %) tragen mindestens einen Regelverstoß — 129 Mal „nur 2
Dimensionen statt mindestens drei“.

Eine geschärfte Anweisung hätte alle 467 Bücher neu beschreiben lassen: rund 60
Bündel über das Abo, gut zwei Stunden Modellzeit, und jedes Urteil hätte sich
dabei verschieben können (Streuung, #81). Deshalb blieb die Anweisung seit dem
26.09. unverändert, obwohl die Verbesserungen bekannt waren.

Gemessen ohne Modellaufruf: die Steckbriefe mit zu wenigen Dimensionen haben
kaum kürzere Klappentexte (Median 720 gegen 821 Zeichen, unter 400 Zeichen
27 % gegen 29 %) und sind kaum häufiger Heftromane (13 % gegen 8 %). Der Text
gäbe die dritte Dimension meist her; das Modell hält die Regel nicht ein.

## Entscheidung

- **Der Fingerabdruck rechnet das Vokabular und die Form der Antwort** (die
  Pflichtfelder), nicht den Wortlaut der Regeln. Ein anderes Vokabular oder ein
  neues Pflichtfeld macht weiter alles ungültig: dann bedeuten die Wörter etwas
  anderes.
- **Ein neuer Steckbrief mit Text und weniger Regelverstößen ersetzt einen
  alten** desselben Buchs. Bisher galt: der neueste mit Text, und einer ohne
  Text ersetzt nie einen mit Text — das bleibt; neu ist, dass unter mehreren mit
  Text die Zahl der Verstöße vor dem Alter zählt.
- **Steckbriefe mit Verstößen werden nach und nach neu beschrieben**, innerhalb
  des Budgets, das ein Lauf ohnehin hat — zuerst die mit „nur 1–2 Dimensionen“.
- **Freiwillige Felder ändern den Fingerabdruck nicht.** „Form“ (Kurzgeschichte,
  Novelle, Roman) bringen neue Steckbriefe mit; fehlt es, ist die Form unbekannt.
  Wo beam oder die DNB eine Seitenzahl nennen, entscheidet die (ADR 34); die Form
  springt nur ein, wo keine bekannt ist.
- **Eine geänderte Anweisung wird vorher gemessen**: am Prüfstand
  (`docs/research/prototyp/regeln.py`, acht Bücher an der Schwelle, je sechs
  Steckbriefe alt und neu). Die Verstöße müssen sinken, die Streuung darf nicht
  steigen; sonst bleibt die alte. Dass die Streuung *sinkt*, verlangen wir
  nicht: sie liegt am Modell, nicht am Wortlaut (#81).

## Messung vom 26.10.2026

Die erste geschärfte Anweisung (Dimensionen nachzählen, Pitch höchstens 160
Zeichen, Form) gegen die vom 26.09.:

| | vorher | nachher |
|---|---|---|
| Steckbriefe mit Verstoß | 34 von 48 | 7 von 48 |
| „zu wenige Dimensionen“ | 20 | 1 |
| ⌀ Abstand zweier Urteile desselben Buchs | 7,9 Punkte | 8,8 Punkte |
| Paare, die über die Schwelle kippen | 36 von 115 (31 %) | 40 von 120 (33 %) |

Die Streuung blieb im Rauschen gleich, die Verstöße fielen um vier Fünftel;
die neue Anweisung gilt. Die Form nannte das Modell in 43 von 48 Fällen, immer
„roman“ — die acht Bücher sind Romane.

## Konsequenzen

- Alte und neue Steckbriefe stehen eine Weile nebeneinander, nach leicht
  verschiedenen Regeln entstanden. Wegen der Streuung (#81) ist das ohnehin so.
- Wer den Fingerabdruck ändern will, muss sich fragen, ob sich eine *Bedeutung*
  ändert oder nur eine Formulierung.
- Die Prüfung der Regeln (`Portrait.violations`) wird damit zur Grundlage, welcher
  Steckbrief gilt — ein Verstoß verwirft weiter nichts (ADR 33), entscheidet aber
  zwischen zweien.
