# 34. Die Seitenzahl gehört der ISBN, nicht der Quelle

Eine Seitenzahl, die irgendeine Quelle zu einer ISBN nennt, gilt für jeden Fund
mit dieser ISBN. Gelesen wird sie, wo sie ohnehin vorbeikommt; eine zusätzliche
Anfrage gibt es nur in einem engen Fall. Die Einzelheiten stehen in #82.

## Kontext

Die Kurzgeschichten-Regel (#73) greift nach der Seitenzahl der Detailseite oder
nach einem Wort im Titel. Die Seitenzahl kannte bis hier nur beam. Am 26.09.2026
kam *Broken House – Düstere Ahnung* (Gillian Flynn) von OverDrive als
Autorenfund in den Stapel, 4★ — der Steckbrief nannte es selbst ein
„Thriller-Fragment"; beam führt es mit 40 Seiten.

Gemessen am Bestand (03.10.2026):

| Quelle | Funde | mit Seitenzahl | was die Quelle nennt |
|---|---|---|---|
| beam | 622 | 70 | „Seitenzahl" auf der Detailseite |
| Onleihe | 78 | 0 | „Umfang: 320 S." auf der Detailseite — geholt, nicht gelesen |
| OverDrive | 115 | 0 | nichts; die Dateigröße taugt nicht (die 40-Seiten-Geschichte hat 5,1 MB, ein Roman 2,6 MB) |

Die DNB nennt die Seitenzahl in Feld 300 manchmal („Online-Ressource,
416 Seiten"), manchmal nicht — bei *Broken House* nur „Online-Ressource". 29 der
115 OverDrive-Funde kennt auch beam.

## Entscheidung

1. **Die Seitenzahl wird über die ISBN weitergereicht.** Dieselbe ISBN ist
   dieselbe Ausgabe. Steckbrief und Urteil teilen sich die ISBN schon
   (ADR 19); die Seitenzahl folgt ihnen. Reihenfolge: die eigene Quelle, dann
   eine andere Quelle mit derselben ISBN, dann die DNB — sie zuletzt, weil ihre
   Angabe manchmal zur gedruckten Ausgabe gehört.
2. **Die Onleihe-Detailseite wird gelesen.** Das Tor holt sie ohnehin.
3. **Die DNB liefert ihre Seitenzahl mit.** Sie wird je ISBN ohnehin gefragt;
   Feld 300 kostet keine Anfrage, nur eine Spalte in `dnb_record`.
4. **Für einen Bibliotheksfund ohne Seitenzahl holt das Tor die beam-Detailseite**
   — nur für Funde, die gleich einen Steckbrief bekommen, nur wenn keine
   Seitenzahl bekannt ist, und nur wenn beam die ISBN schon gezeigt hat. Gesucht
   wird nicht: eine Suche je Buch für einen unsicheren Treffer wäre teurer als
   der Steckbrief, den sie spart. Die Seite kostet eine Anfrage; der Steckbrief
   einer Kurzgeschichte, den sie erspart, kostet einen Modellaufruf.
5. **Ohne Seitenzahl gilt ein Buch als Roman.** Unbekannt ist nicht kurz. Die
   Lücke bleibt bei OverDrive groß und wird hingenommen.

## Erwogen und verworfen

- **beam per ISBN durchsuchen**, auch wenn beam das Buch noch nicht gezeigt hat:
  eine Suche je Buch, für einen unsicheren Treffer.
- **Die Dateigröße als Ersatz:** widerlegt am Beispiel selbst.
- **Das Modell die Form nennen lassen** („Kurzgeschichte", „Novelle",
  „Roman"): es hat das Fragment bei *Broken House* aus dem Klappentext erkannt,
  das Feld würde die Lücke schließen. Es änderte aber den Fingerabdruck und alle
  Steckbriefe veralteten; deshalb vorgemerkt für die nächste Änderung der
  Anweisung (#69), nicht einzeln gebaut.

## Folgen

- „Umfang" heißt im Code nur noch `scope` beim Gegengewicht; `pages` heißt
  Seitenzahl (Glossar).
- Eine Kurzgeschichte von OverDrive wird nur erkannt, wenn beam oder die DNB sie
  kennen oder ihr Titel es sagt.
