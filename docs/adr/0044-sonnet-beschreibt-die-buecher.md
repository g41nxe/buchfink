# 44. Sonnet beschreibt die Bücher

Die Steckbriefe schreibt künftig Sonnet statt Haiku, auf beiden Wegen zum
Modell (`claude -p` und API). Haiku bleibt über `rating_model` wählbar. Löst
die Modellwahl aus ADR 33 ab („Haiku bleibt der Standard“).

## Kontext

ADR 33 hatte Haiku und Sonnet an Regelverstößen und Tempo gemessen: Sonnet
senkte die Verstöße kaum und war damals langsamer (148 gegen 123 Sekunden je
Bündel). Gemessen, wie stark *dasselbe Buch* bei zwei Beschreibungen
streut, wurde nicht.

Diese Streuung ist das größte verbliebene Qualitätsproblem. #81 hatte sie am
Urteil gemessen und das Mitteln mehrerer Steckbriefe verworfen (21 statt 25 %
falsche Seite der Schwelle für dreifache Kosten); Temperatur 0 geht über
`claude -p` nicht. Bei der Probe der eigenen Fassung des Vokabulars (#59)
teilten zwei Haiku-Steckbriefe desselben Buchs nur 30 % ihrer Erzählmuster.

## Messung (31.10.2026)

20 Funde mit Klappentext, quer durch die Genres, eigene Fassung des
Vokabulars, je zwei Züge desselben Modells, nichts gespeichert:

| | Haiku | Sonnet |
|---|---|---|
| gleiche Erzählmuster (Jaccard) | 0,52 | 0,78 |
| gleiche Grundhandlungen | 0,77 | 0,78 |
| gleiche Merkmalsfamilien | 0,49 | 0,73 |
| Abstand der Urteile | 8,9 Punkte | 3,6 Punkte |
| Urteil wechselt die Seite der Schwelle | 7 von 18 | 4 von 20 |
| Dauer für 20 Bücher (`claude -p`) | 347 s | 164 und 169 s |

Bei Haiku fielen zwei Bücher heraus, weil ein Zug „unbekannt“ lieferte.

## Entscheidung

- `CLI_DEFAULT_MODEL` ist `sonnet`, `DEFAULT_MODEL` ist `claude-sonnet-5-5`.
- Der Fingerabdruck eines Steckbriefs rechnet das Modell nicht mit (ADR 43):
  vorhandene Haiku-Steckbriefe bleiben gültig. Wer die stabileren will, lässt
  den Bestand neu beschreiben; bei der Umstellung am 31.10.2026 geschah das
  für die eigene Fassung des Vokabulars.
- Das Etikett „knapp“ (#81) bleibt: auch mit Sonnet wechseln Urteile nahe der
  Schwelle die Seite, nur seltener.

## Folgen

- Die Urteile sind mehr als doppelt so stabil; ein Buch springt seltener in
  den Stapel hinein oder aus ihm heraus.
- Über `claude -p` verbraucht ein Steckbrief mehr vom Abo-Kontingent. Über die
  API kostet er mehr als mit Haiku; wer dort sparen muss, setzt
  `rating_model: claude-haiku-5-5`.
- Dass Sonnet in der Messung schneller war, ist zwei Läufe stark und kein
  Versprechen.
