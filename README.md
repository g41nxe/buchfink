<p align="center">
  <img src="docs/bilder/github.jpg" alt="Banner im Cartoon-Stil: links der Schriftzug BUCHFINK mit dem Slogan Mehr lesen. Weniger suchen., rechts eine warme Schreibtischszene mit dem Vogel-Maskottchen, Bücherstapeln und der geöffneten Watchlist" width="900">
</p>

# Buchfink

**Weniger Suchen. Mehr Lesen.**

Buchfink liest deinen Geschmack aus einem Text, den du selbst geschrieben
hast, und findet damit Bücher, nach denen du nie gesucht hättest. Ein
Sprachmodell liest jeden Fund und schreibt in einem Satz, ob und warum er zu
dir passt — mehr, als jede Kaufhistorie hergibt.

Nebenbei behält es deine Watchlist im Auge, in der Bibliothek und im Shop,
jeden Tag, und meldet sich nur, wenn sich wirklich etwas ändert. Fokus:
deutschsprachige Literatur.

**Eine Seite für heute.** Die Startseite sagt, wann zuletzt geprüft wurde, was
davon jetzt zu haben ist und worüber du entscheiden solltest — mehr nicht. Wie
viele Zeilen dort stehen, entscheidest du. Der Zustand des Werkzeugs steht
woanders und drängt sich nicht auf.

<p align="center">
  <img src="docs/bilder/startseite.jpg" width="800"
       alt="Die Startseite: eine Statuszeile mit dem letzten Lauf, darunter was jetzt zu haben ist und was zu entscheiden ist">
</p>

<p align="center">
  <img src="docs/bilder/vorschlaege.png" width="800"
       alt="Die Vorschlagsseite: Cover, Sterne, ein Satz warum das Buch passt, und drei Zeichen zum Entscheiden">
</p>

**Jeder Stern hat einen Grund.** Kein API-Schlüssel nötig, wenn
Claude Code schon bei dir angemeldet ist — dann urteilt die lokale
Installation.

**Drei Quellen, eine Zeile.** [Onleihe](https://voebb.onleihe.de),
[OverDrive](https://voebb.overdrive.com) und
[beam-shop.de](https://www.beam-shop.de) für jeden Titel gleichzeitig im
Blick, Preis hier, Verfügbarkeit dort. Die beiden Bibliotheken gehören
demselben Verbund und führen trotzdem verschiedene Bestände — vier Titel der
Beispiel-Watchlist stehen nur bei einer von beiden. Weitere Quellen lassen
sich ergänzen, ohne den Kern anzufassen.

<p align="center">
  <img src="docs/bilder/watchlist.png" width="800"
       alt="Die Watchlist: jeder Titel mit Preis oder Verfügbarkeit, Shop- und Bibliotheks-Symbol">
</p>

**Der ganze Verlauf, nicht nur der letzte Preis.** Jede Beobachtung wird
angehängt, nie überschrieben. Jede Liste zeigt ein Buch in derselben Zeile,
und dasselbe Wort steht auf jedem Knopf, der dieselbe Entscheidung trifft.

<p align="center">
  <img src="docs/bilder/buchseite.png" width="800"
       alt="Die Buchseite: was du dazu sagst, wie gut es passt, und die letzten Beobachtungen">
</p>

**Läuft bei dir.** Kein Login, keine gespeicherten Zugangsdaten, keine
Cloud — eine SQLite-Datei auf deinem Rechner oder Raspberry Pi.

## Schnellstart

Voraussetzungen: Python 3.12 oder neuer und [uv](https://docs.astral.sh/uv/).

```bash
uv sync
mkdir -p data && cp examples/*.yaml data/
```

`data/settings.yaml` (Quellen, Schwellwerte), `data/seed.yaml` (Autor:innen
und Themen) und `data/watchlist.yaml` anpassen, dann die Datenbank füllen und
einen ersten Lauf fahren:

```bash
uv run python -m ebook_watchlist.run seed
uv run python -m ebook_watchlist.run
```

Der erste Lauf sät Beobachtungen und schweigt; ab dem zweiten meldet er
Änderungen. Für die Oberfläche einmal die statischen Dateien bauen, dann
starten:

```bash
uv run tailwindcss_install && uv run python -m ebook_watchlist.web.build
uv run python -m ebook_watchlist.web
```

Danach unter `http://<rechner>:8437/` erreichbar, auch vom Telefon im selben
Netz.

## Entwickeln

```bash
uv run pytest && uv run ruff check .
```

Kein Netzzugriff in der Suite; Smoke-Tests gegen die echten Quellen laufen
nur mit `-m live`. Der Code ist englisch, alles Gelesene deutsch — die
Begriffe dazwischen stehen in [CONTEXT.md](CONTEXT.md).

Das Vokabular der Merkmale und Erzählmuster (`vocabulary/merkmale.yaml`,
`vocabulary/erzaehlmuster.yaml`, dazu die Recherche
`vocabulary/story-pattern-vocabularies.md`) liegt **nicht** im Repository: es beruht auf
NoveList, und ob es veröffentlicht werden darf, ist ungeklärt (#59). Ohne
diese Dateien gibt es keinen Steckbrief und keine Erstaufnahme; die Tests dazu
werden übersprungen. Ein anderes Verzeichnis lässt sich mit
`EBW_VOCABULARY_DIR` angeben.

## Betrieb

Läuft am besten als täglicher Cron- oder Zeitplaner-Job, eine Dateisperre
verhindert doppelte Läufe. Fertige Vorlagen für Windows und Linux/Raspberry
Pi: [docs/betrieb.md](docs/betrieb.md).

## Dokumentation

**Das Werkzeug verstehen**

- [docs/rundgang.md](docs/rundgang.md) — **hier anfangen**: was das Werkzeug
  kann und wie es funktioniert, ohne den Code zu lesen
- [CONTEXT.md](CONTEXT.md) — Glossar, englischer Name und deutsches Wort
- [docs/adr/](docs/adr) — alle Entscheidungen, mit Kontext und Konsequenzen

**Den Geschmack einstellen**

Dein Leseprofil entsteht in der Oberfläche, aus deinen Büchern (Erstaufnahme)
und ändert sich beim Nachschärfen auf der Buchseite; es liegt in der Datenbank.
Eine Datei dafür gibt es nicht.

- [docs/bewertungsschema.yaml](docs/bewertungsschema.yaml) — die Zahlen, mit
  denen der Code daraus Sterne rechnet: Gewichte, Sternetabelle und die
  Schwelle, ab der ein Vorschlag im Stapel bleibt

**Geschichte und Recherche**

- [docs/offene-punkte.md](docs/offene-punkte.md) — was fehlt, und welche
  Behauptungen sich unterwegs als falsch erwiesen haben
- [docs/research/](docs/research) — Recherche zu den Schnittstellen von VÖBB
  und beam-shop, zu Metadatenquellen und deren Rechtslage

## Für Agenten

Einstieg in [CLAUDE.md](CLAUDE.md) und [docs/agents/](docs/agents).

## Lizenz

[MIT](LICENSE).
