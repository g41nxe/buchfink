# Offene Punkte und was unterwegs schiefging

Stand 2026-09-19, nach #10. Zwei Listen: **was noch nicht stimmt oder fehlt**, und
**welche Behauptungen sich als falsch herausgestellt haben**. Die zweite ist
die nützlichere — sie sagt, wo dieses Projekt zum Irrtum neigt.

Die Tickets liegen in GitHub Issues (`gh issue list`); die älteren bis
Ticket 56 in `.scratch/ebook-watchlist-phase2/issues/`, nicht im Repository.

---

## 1. Was fehlt oder noch nicht stimmt

### Das Bewertungstor: 109 echte Urteile (Ticket 27)

Gelaufen, gegen Profilversion 2, über die lokal angemeldete
Claude-Code-Installation — ein Schlüssel wurde nicht gebraucht.

| | |
|---|---|
| Verteilung | 5★ ×1, 4★ ×11, 3★ ×14, 2★ ×39, 1★ ×24, 0★ ×20 |
| Sicherheit | belegt 41, teils 67, vermutet 1 |
| zurückgehalten (unter 3, nicht `vermutet`) | 83 |
| trotz Unsicherheit gezeigt | 0 |

**Das Tor unterscheidet.** Es bewertet nicht alles gleich, und die Spitze ist
dünn besetzt statt großzügig: ein einziger Fünfsterner (*Macbeth*, Jo Nesbø)
unter 109. Als Kontrolle bekam *Die Verlorenen* — vom Leser gelesen und
gemocht — 4 von 5. Die Skala trägt also oben und die Regale sind wirklich dünn.

**Liest das Modell die Gewichtung aus der Prosa?** Nach Durchsicht
zurückgehaltener Begründungen: ja. Sie nennen die Achsen beim Namen, in der
Reihenfolge des Profils, und sie unterscheiden **belegt von erschlossen** —
zu *Katz und Maus* steht ausdrücklich, dass der Reihenzusammenhang
„erschlossen (nicht im Klappentext belegt)" ist. Zu *Die atmenden Schächte
von Lugau*: „Ensemble statt einer Stimme" und „der Klappentext *listet*
Jahreszahlen, Schächte, Spinnmühle — erklärte statt erzählter Welt".

Damit bleibt **ADR 21 bei seiner Ablehnung eines Ableitungsschritts**: die
Achsen aus der Prosa maschinell zu extrahieren wäre eine Lösung für ein
Problem, das die Messung nicht zeigt.

Zwei Einschränkungen, die dazugehören:

- **Das Tor selbst hat im Lauf noch nichts entschieden.** Alle 109 Urteile
  stammen aus `ebw rate` (dem Rückstandsweg). Der Lauf sieht nur
  Erstsichtungen, und die Regale waren abgegrast — der scharfe Lauf erzeugte
  null Deltas. Geprüft ist damit der Bewertungsweg, nicht `_decide`.
- **Die Regel „ab `teils` darf zurückgehalten werden" hat nie gegriffen.**
  Das einzige `vermutet` liegt *über* der Schwelle. Das Sicherheitsventil,
  das ein unsicheres Urteil davon abhält, ein Buch zu verstecken, ist bisher
  Theorie — 1 von 109.

### Mit #10 geschlossen (19.09.2026)

- **Die DNB ist angebunden** — und ihre Auskunft wird jetzt auch benutzt:
  - **Sprache.** Ein Fund, den die DNB ausdrücklich in einer anderen Sprache
    führt als im Profil (`languages`, voreingestellt `ger`), kommt nicht in
    den Stapel und kostet kein Urteil. Unbekannt gilt nie als fremd.
  - **Reihe und Band** landen in leeren Feldern am Buch und stehen im Kopf der
    Buchseite.
- **Titelbild:** ein neues ersetzt das vorhandene nur, wenn es mehr Bildpunkte
  hat, gemessen am Dateikopf. Vier von 24 Büchern saßen auf 200 Pixeln fest.
- **Ein Modellurteil trägt seinen Weg** (`via`: Lauf, Rückstand, Buchseite).
  Erst damit lässt sich messen, ob das Tor im Lauf etwas entscheidet.
- **Gestrichen:** das Ziel „Testsuite unter zehn Sekunden“ (unabhängige Tests
  sind mehr wert als die halbe Minute) und die Frage nach der DNB-Frequenz
  (50 je Lauf mit Pausen, harter Halt bei 429, bisher keine Abweisung).
- **Die Bildrechte beim Shop** verantwortet der Betreiber selbst; keine offene
  Aufgabe des Werkzeugs.

### Mit Ticket 23 geschlossen

- **Schreibweisen auf der Buch-Zeile.** `find_or_create_book` behält jetzt die
  bessere Schreibweise **derselben** Person; ein anderer Name bleibt liegen.
  *Cold Eternity* und *Providence* heißen wieder `S.A. Barnes` und `Max Barry`.
- **Alpine.** Es wird geladen und trägt den Fall, den ADR 20 selbst nennt: der
  Vorschlagsstapel zählt, was angehakt ist, und kennt "alle" und "keine".
- **`CONTEXT.md`.** Bewertungstor, Urteil (mit Herkunft), Maßstab und
  Fund stehen im Glossar.
- **Der `dismissals`-Befehl** achtet den Quellen-Schalter. Was ohne Anfrage
  geht, geht weiter; der Rest wird gemeldet statt still zu scheitern.

---

## 2. Behauptungen, die sich als falsch erwiesen haben

Diese Liste ist wichtiger als die erste. Jede Zeile ist ein Fall, in dem etwas
plausibel klang, aufgeschrieben wurde und dann durch Messung fiel.

### Über die eigenen Daten

**Die Sterne in `owned.yaml` sind Maschinenurteile, nicht die der Leserin.**
Ticket 21 hieß zuerst „deine eigenen Sterne". Sie entstanden im Gespräch, von
einem Modell, gegen denselben Maßstab, den das Tor benutzt. Sie als menschlich
zu importieren hätte dreizehn Vorschläge dauerhaft zu Tatsachen gemacht — an
genau der Stelle, die ADR 17 einbaut, um das zu verhindern.

**Und sie tragen kein `confidence`-Feld.** Das Ticket behauptete es. Ein
einziger Eintrag trägt einen `hinweis`, und der bittet um Gegenprüfung der
Identifikation — etwas ganz anderes.

**„Die ISBN verbindet die Quellen."** Aus *einem* Buch geschlossen. Gemessen an
zweien: eines teilt die ISBN, eines nicht. Der Matcher-Rückfall ist der
Normalfall, nicht der Randfall. ADR 18 trägt die Korrektur mit Zahlen.

**316 Funde sind nicht der tägliche Stapel.** Ich hatte sie so
beschriftet. Es ist ein einmaliger Rückstand plus die Abrufmenge je Lauf; der
tägliche Zuwachs war **null**.

### Über Messungen

**„Die Testsuite braucht 88 Sekunden."** Sie brauchte 11,7. Frei erfunden.

**„Google Books findet nichts."** `429 Quota exceeded` ist kein Befund. Mit
Schlüssel: 13 von 30.

**„Die DNB hat keine Reihen und keine Cover."** Eine Aussage über meine
Abfrage, nicht über die DNB: `oai_dc` trägt beides nicht. Mit `MARC21-xml`
kommen Reihen, und Cover liegen hinter einem eigenen Dienst.

**„Der DNB-Cover-Dienst ist nutzbar."** Die DNB sagt selbst, dass sie diese
Bilder weder besitzt noch speichert und dass die Vereinbarung *Bibliotheken*
berechtigt.

### Über den eigenen Entwurf

**„Das Urteil gehört an die `book`-Zeile" (ADR 19).** Hätte dreihundert
ungeprüfte Buch-Zeilen pro Lauf erzwungen — genau das, was ADR 18 abgelehnt
hatte.

**Der Bündelfilter hätte echte Bücher weggeworfen.** „Zahl am Anfang" trifft
`5 Cottages`, `7 Momente in Angst`, `21 – Fremder Schatten`. Die stehen jetzt
als Gegenprobe im Test.

**Der Freitext-Trenner machte „Band 1" zur Autorin.** Der Ausdruck teilt an der
letzten Trennung, weil der Name hinten steht — ein angehängter Bandzusatz sieht
von hinten aus wie ein Name.

**Die Preisregel tut nicht, was sie verspricht.** „Funde nur als Schnäppchen"
heißt praktisch „unter 5,00 €", weil die Buchpreisbindung Streichpreise
verbietet und ein neuer Fund keine Vorgeschichte hat. Angewandt ließ sie neun
Titel eines Selfpublishers durch und schwieg zu einem neuen Nesbø.

### Über den eigenen Entwurf, zweiter Durchgang

**Eine Regel im ADR ist keine Regel im Code.** ADR 20 beschrieb die
Arbeitsteilung zwischen HTMX und Alpine so genau, dass „welche Zeilen sind
angehakt" wörtlich als Alpine-Fall dasteht. Acht Tickets lang wurde Alpine
geholt, gepinnt — und von keinem Template geladen. Es fiel niemandem auf, weil
nichts fehlte: eine ungenutzte Abhängigkeit sieht aus wie eine benutzte.

**Die uneinheitlichen Autorennamen waren kein Anzeigeproblem.** Notiert war
„der Shop liefert `Barnes, S. A.`". Die Ursache war, *wer zuerst da war*: den
Buch-Eintrag legte der einmalige Auflöser aus `dismissed.yaml` an, und
`find_or_create_book` überschrieb nie etwas. Die Regel dafür lag seit Ticket 16
ungenutzt in `cleaning.py`.

### Fehler in ausgeliefertem Code

- **Alle Autor:innen teilten sich eine Aussaat** — eine neue Referenzautor:in
  meldete ihre ganze Backlist als Neuzugänge.
- **Der Matcher hielt Teilmengen für Treffer** (`token_set_ratio` = 100).
- **Ein Watchlist-Titel wurde bei der ersten Sichtung verschwiegen**, außer er
  war schon billig.
- **Streng an der Vordertür, offen an der Hintertür**: die Erstsichtung
  brauchte einen Deal, ein Preissturz nicht.
- **`beam` und `onleihe` sind dreimal in die Oberfläche gerutscht** — Watchlist,
  Buchseite, Übersicht. Dreimal dieselbe Entscheidung, dreimal eine übersehen.
  Jetzt beantwortet die Registry sie.
- **Der Import erfand Quellennamen** aus `check_library` / `check_shop`.
- **Eine Einschränkung ließ sich setzen, aber nie aufheben.**
- **Das Stylesheet hatte keine Version** — ein Browser behielt seine alte Kopie,
  und das sah überzeugend nach kaputtem Template aus.
- **Ein frischer Klon konnte nicht bauen**: die Fehlermeldung nannte einen
  Befehl, der selbst nicht laufen konnte.
- **Eine Migration verwies auf eine Tabelle, die eine spätere fallen ließ** —
  jedes Upgrade von Version 0 wäre gestorben.
- **Das Ablehnungs-Nachschlagewerk wuchs mit dem Stapel** (~2,5 s je Lauf bei
  dreihundert).
- **`ic-dots` fehlte im Sprite** — ein Menü mit unsichtbarem Griff.

- **Die DNB fragte nie nach den eigenen Büchern.** Gefragt wurde „zuletzt
  gesehen zuerst“, 50 je Lauf — und jeder Lauf sieht Hunderte neuer Funde
  *nach* den Watchlist-Titeln. Die ISBNs der eigenen Bücher wurden bei jedem
  Lauf wieder verdrängt: 34 Bücher mit ISBN, **einer** davon mit Datensatz.
  Aufgefallen erst, als die Reihe aufs Buch sollte und bei einem ankam.
- **„Das kleinere Titelbild überschreibt das größere“** stand in dieser Liste
  und stimmte nicht mehr: alle Stellen prüften längst, ob schon ein Bild da
  ist. Das echte Problem war die Kehrseite — das erste Bild gewann für immer.

---

## 3. Woran man das erkennt

Ein Muster zieht sich durch: **plausibel klingende Aussagen über Daten, die
niemand angesehen hat.** Fast jeder Eintrag oben ist so entstanden — eine
Stichprobe von eins, eine Abfrage mit dem falschen Schema, ein Muster, das an
den vorhandenen Beispielen funktionierte.

Was zuverlässig geholfen hat: **an den echten Daten messen, bevor die Regel
geschrieben wird.** Der Bündelfilter, die Preisregel und die Metadatenquellen
sind alle drei erst durch Zahlen richtig geworden — und alle drei klangen
vorher überzeugend.
