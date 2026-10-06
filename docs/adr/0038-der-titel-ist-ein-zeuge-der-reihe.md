# 38. Der Titel ist ein Zeuge der Reihe, und eine Sammelausgabe erbt sie

Was ADR 35 als vierte Herkunft vorsah, wird gebaut: Untertitel und Titel
nennen die Reihe, wenn sie es in einer von zwei festen Formen tun. Ein
Sammelausgabe erbt die Reihe seiner Bände und sagt, welche er enthält (#94).

## Kontext

Vier Fälle vom 06.10.2026, in denen eine Reihe nicht erkannt wurde:

| Buch | was die Quelle sagt | woran es scheitert |
|---|---|---|
| Tad Williams, *Spät dran am Jüngsten Tag* | Untertitel „Bobby Dollar 3" (beam) | `series` leer; Untertitel liefert nur die Bandnummer |
| Tad Williams, *Das Reich der Grasländer 1* | Untertitel „Der letzte König von Osten Ard 2" | keine Quelle nennt die Reihe |
| Chris Carter, Hunter-und-Garcia-Bände | beam ohne ISBN, Untertitel, Reihe | kein Zeuge; eigene Probe nötig |
| Jo Nesbø, *Kakerlaken / Rotkehlchen* | Untertitel „… Band 2 und 3" | Sammelausgabe; „Kakerlaken" hängt an der Reihe, der Band nicht |

ADR 35 nennt den Titel als Herkunft mit dem niedrigsten Rang, `MidSeries`
liest ihn schon für die Bandnummer (`named_volume`, `volume_of(subtitle)`).
Eine Zuordnung schreibt daraus niemand. Die DNB hätte drei der vier Fälle
beantwortet, aber ihr Budget (50 je Lauf) erreicht die ISBNs erst nach
Wochen, und beam-Titel ohne ISBN nie.

Gemessen am Bestand (882 beam-Titel, 447 Untertitel):

- **Untertitel „Name n", „Name Band n"**, Zusatz hinter „|" abgeschnitten:
  30 Treffer. 27 sind Reihen (alle Tad-Williams-Zyklen, *Mysterien der
  Heide*, *Asterion-Zyklus*, BattleTech-Reihen). Drei sind Rauschen:
  „Folge 26", „Band 1", „Band 2 und 3".
- **Titel „Name. Band n", „Name - Band n: Untertitel"**: 24 Treffer, alle
  Reihen (*Otherland*, *Shadowmarch*, *The Heritage Universe*, *Crissis
  Tagebücher*).
- **Prosa** „Band 4 der David-Hunter-Reihe", „Der fünfte Band in der
  Bestsellerreihe um Dr. David Hunter": vier Treffer, vier Formulierungen.

## Entscheidung

### Zwei Formen, eine Herkunft

Eine Zuordnung mit Herkunft `title` entsteht aus

1. dem **Untertitel**, wenn er, bis zum ersten „|", auf „Name n" oder
   „Name Band n" endet, oder
2. dem **Titel**, wenn er „Name. Band n" oder „Name - Band n …" lautet.

`n` ist eine Zahl bis 99, „Band" darf auch „Bd.", „Teil" oder „Buch"
heißen. Eine nackte Zahl im Titel („Die Hexenholzkrone 1") zählt nicht — das
ist ein geteilter Band, keine Reihe; dieselbe Grenze wie bei `named_volume`.

Die Zuordnung legt eine Reihe an, wie Onleihe und OverDrive es aus ihrem
Namen tun; der Schlüssel folgt ADR 35 und gilt je Autor:in. Drei Sperren:

- Nach der Schlüsselregel muss vom Namen mehr als ein Strukturwort bleiben:
  `band`, `folge`, `teil`, `buch`, `episode`, `special`, `nummer` allein sind
  kein Name. Das fängt „Folge 26" und „Band 1".
- Hinter der Zahl darf kein „und", „&" oder „-" folgen: „Band 2 und 3" nennt
  zwei Bände, also eine Sammelausgabe (siehe unten), keine Nummer.
- Ohne ISBN keine Zuordnung — die Zuordnung ist je ISBN (ADR 35).

Der Rang bleibt der niedrigste: nennt die DNB, OverDrive oder die Onleihe
dieselbe ISBN, gilt deren Band. Geschrieben wird der Titel-Zeuge trotzdem
immer, auch neben einem Namen der Quelle — wer vorgeht, entscheidet das
Lesen, und ein Name ohne Band lässt den Band vom Titel gelten. Die Prosa-Form wird nicht gelesen; vier
Treffer in vier Formulierungen rechtfertigen keine Regel.

### Eine Sammelausgabe erbt die Reihe seiner Bände

Eine Sammelausgabe (`looks_like_bundle`, ADR 24) kennt ihre Bände auf zwei
Wegen, in dieser Reihenfolge: die DNB nennt sie als ISBN (`dnb_contains`,
mindestens zwei — wie beim Preisvergleich, ADR 24), sonst zerfällt der Titel an Schrägstrichen (`volume_titles`), und jeder Teil
wird gegen die Sichtungen derselben Autor:in gehalten — ein Teil, der dort
kein Buch ist, ist keiner (dieselbe Selbstkorrektur wie beim Preisvergleich).

Hängt mindestens ein gefundener Band an einer Reihe, bekommt der Sammelausgabe
eine Zuordnung mit Herkunft `bundle` und dem Band als Spanne, „2–3". Der
Folgeband-Filter liest daraus wie bisher die erste Zahl: eine Sammelausgabe mit
Band 1 ist ein Einstieg, einer ab Band 2 nicht.

Abgeleitet wird je Lauf hinter dem Snapshot, wie `_series_from_dnb`: aus dem,
was gespeichert ist, ohne Anfrage, bei jedem Lauf neu — ein Band, der nach dem
Sammelausgabe gesehen wird, holt ihn beim nächsten Lauf nach.

### Was der Sammelausgabe sagt

Fundseite und Stapelkarte zeigen je enthaltenem Band eine Zeile: den Titel
und, falls sie eine Beziehung zu ihm hat, ihr Regalschild („in Beobachtung",
„im Besitz", „Ausgeschlossen" — `relations.RELATION_LABELS`); gelten mehrere,
das, was sie hat, vor dem, was sie vorhat. Ein Band ohne Beziehung steht nur
mit Titel.
Gezeigt wird, was gefunden wurde; eine Sammelausgabe, deren Bände keine Quelle
kennt, bekommt keine Zeile und keine Schätzung.

## Erwogen und verworfen

- **Nur an bekannte Reihen hängen**: enger, aber *Osten Ard* bliebe ohne
  Reihe, weil keine Quelle sie je nennt. Die Sperren fangen das Rauschen
  des Bestands vollständig.
- **Im Quellparser lesen** (beam setzt `series` selbst): dann hätte die
  Zuordnung die Herkunft `beam`, und der Rang aus ADR 35 wäre falsch. Gelesen
  wird zentral in `series.py`, für jede Quelle gleich.
- **Den Klappentext lesen** („Harry Hole ermittelt im Bundle"): kein Zeuge,
  sondern Werbung. Bleibt beim Steckbrief.
- **Die Prosa-Form**: siehe oben.
- **Sammelausgabe als eigenes Ticket**: beide Hälften brauchen dieselbe
  Zuordnung und dieselbe Kopfzeile; getrennt wären es zwei Reviews am
  selben Code.

## Offen

Die Carter-Bände bei beam haben keine ISBN (246 von 882 beam-Titeln). Ob die
Detailseite sie an anderer Stelle nennt, klärt eine Probe an einer Seite —
außerhalb dieses Tickets.
