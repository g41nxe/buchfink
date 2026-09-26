# 22. Zwei Vokabulare: eines für den Code, eines für die Leserin

Der Code und das Glossar bleiben englisch. Alles, was die Leserin liest, ist
deutsch — und für jeden englischen Fachbegriff gibt es genau **ein** deutsches
Wort, das im Glossar danebensteht.

## Context

Die Oberfläche spricht deutsch, `CONTEXT.md` spricht englisch. Beides für sich
ist konsistent; in Fließtext rutschen sie ineinander, und dann steht in einem
deutschen Satz „Lauf/Tor/Digest".

Gezählt, statt geschätzt:

| Fläche | deutsch | englisch |
|---|---|---|
| Oberfläche (Templates) | Lauf 13, Schnäppchen 5, Urteil 4, Vorschlag 2 | **Digest 4** |
| README | Lauf 7 | Run 18, Deal 8, Digest 5, Snapshot 4, Observation 3 |

Die Oberfläche war also fast sauber — mit *einem* Eindringling. Die README war
die eigentliche Baustelle: sie sprach die Codebegriffe, während die Anwendung
deutsch mit der Leserin redet.

Dazu ein Wackler ohne Sprachgrenze: *Fund* und *Entdeckung* standen für
dieselbe Sache.

## Decision

**Der Code bleibt englisch.** Klassennamen, Tabellen, Routen, Dateinamen. Ein
deutsch-englischer Mischcode wäre schlimmer als die Sprachgrenze, und das
Glossar beschreibt den Code.

**Alles Gelesene wird deutsch.** Oberfläche, Tagesbericht, README, `docs/`.

**Das Glossar trägt beide.** Jeder Eintrag nennt hinter dem englischen Namen
sein deutsches Wort — das ist die Brücke, die bisher fehlte.

Die Zuordnung:

| Code / Glossar | Leserin |
|---|---|
| Run | Lauf |
| Digest | **Tagesbericht** |
| Rating Gate | Bewertungstor, kurz „das Tor" |
| Rating | Urteil |
| Observation | Beobachtung |
| Discovery | **Fund** |
| Snapshot | **Aufzeichnung** |
| Deal / Strong Deal | Schnäppchen |
| Reading Profile | Leseprofil |
| Rating Scheme | Bewertungsschema |
| Reference Author | Referenzautor:in |
| Genre Category | Thema |

**Fund und Vorschlag sind nicht dasselbe.** Ein **Fund** ist, was ein Lauf
gesehen hat. Ein **Vorschlag** ist ein Fund, der auf eine Entscheidung wartet —
also einer, der es durch Müllfilter, Preisregel und Tor geschafft hat. Das
benutzten wir schon halb unbewusst; jetzt ist es festgelegt.

**In einem Kommentar zählt, wovon die Rede ist.** Wer das Codeobjekt meint,
schreibt `Digest` in Backticks. Wer die Sache meint, die bei der Leserin
ankommt, schreibt Tagesbericht. Deshalb bleiben Kommentare, die eine Klasse
benennen, wie sie sind.

## Consequences

- Eine Umbenennung im Code steht ausdrücklich **nicht** an. Der Preis dafür
  wäre eine Migration und ein Bruch mit ADR 16 (Migrationen werden nur
  angehängt) — für null Gewinn bei der Leserin.
- Wer ein neues Wort einführt, trägt es ins Glossar, oder es gibt zwei.
- Die Tabelle oben ist die Prüfliste für jede neue Seite und jeden neuen Text.

> **Nachtrag vom 24.09.2026: „Der Code bleibt englisch" gilt auch innerhalb
> einer Funktion.** `facets.py`, `intake.py` und `sharpening.py` hatten sich
> lokale Helferfunktionen (`karte`, `pille`, `familien`, `belege`, `pruefen`)
> und lokale Variablen (`traeger`, `gemocht`, `weg`, `wahl`, `bild`, `buch`, …)
> auf Deutsch angewöhnt — nirgends festgelegt, nur eingerissen, solange
> niemand hinschaute. Klassennamen, Tabellen, Routen und Dateinamen blieben
> dabei englisch; nur was innerhalb einer Funktion lebt, war unausgesprochen
> ausgenommen.
>
> Diese Ausnahme gibt es nicht mehr. Englisch gilt für **jeden** Bezeichner im
> Code — auch für eine verschachtelte Funktion, die nur zwei Zeilen weiter
> unten gebraucht wird, und für die Variable, die ihr Ergebnis aufnimmt.
> Deutsch bleibt, wo es ohnehin hingehört: in Docstrings, Kommentaren und
> Fehlermeldungen, die die Leserin oder die Log-Ausgabe zu lesen bekommt — und
> in den Schlüsseln von Config- und Profildateien (`docs/bewertungsschema.yaml`,
> `docs/leseprofil.yaml`), die ein eigenes, unverändertes Datenformat sind und
> keine Codebezeichner.
>
> Jinja-Templates sind davon vorerst unberührt: die Vorlagen unter
> `src/ebook_watchlist/web/templates/` reichen den Kontext-Schlüssel `wahl`
> weiter (aus `app.py`s `_choosing`), und ihn samt allen `wahl.*`-Zugriffen zu
> übersetzen ist eine eigene, größere Änderung über mehrere Dateien hinweg —
> noch offen.

> **Nachtrag vom 25.09.2026: die Vorlagen sind nachgezogen (#65).** Was oben
> noch offen stand, ist umgesetzt: die Kontext-Schlüssel aus `app.py`, die
> Makros samt Parametern, die Partial-Dateinamen (`_book_row.html`,
> `_state_button.html`, …), die `{% set %}`-Locals und Schleifenvariablen
> sowie die `data-*`-Marken, an denen die Tests abtasten, heißen englisch.
>
> Eine Grenze wurde dabei gezogen: **Leseformat ist kein Bezeichner.** Was in
> der Adresse steht (`?anlass=`, `?nur=unklar`, `?sortiert=preis`), was ein
> Formular als Wert schickt (`was=bestaetigen`), der Schlüssel im
> Browserspeicher (`sortiert:/watchlist`), CSS-Klassen und `id`-Werte sind
> Teil dessen, was die Leserin sieht oder als Lesezeichen behält, und
> bleiben deutsch. Versteckte Formularfelder, die nur zwischen Vorlage und
> Route reisen (`back`), sind dagegen Code.

> **Nachtrag vom 26.09.2026: der Rest nach #65 (#70).** Die Kernmodule, die
> Quellen-Parser und die Tests heißen jetzt englisch, bis in die lokale
> Variable. Umbenannt wurde über den Tokenizer, Strings, Kommentare und
> Docstrings blieben unberührt. Wo ein Bezeichner nach außen reicht, bleibt
> der Wert, und nur der Name im Code wechselt:
>
> - **`THEMA` heißt `GENRE_CATEGORY`**, wie das Glossar es führt
>   (`InterestKey.GENRE_CATEGORY`, `reasons.genre_category_name`,
>   `Overview.genre_categories`, …). Der **gespeicherte Wert `"thema"`**
>   in `interest.key` bleibt, wie er ist: ein Datenwert, kein Bezeichner. Eine
>   angehängte Migration (ADR 16) wäre möglich, brächte der Leserin aber
>   nichts und jeder Sicherung einen zweiten Schlüssel; sie unterbleibt.
>   Das Wort, das die Leserin liest, heißt im Code `GENRE_CATEGORY_WORD` und
>   lautet weiter „Thema".
> - **Das Leseformat der Oberfläche ist jetzt englisch** und nimmt damit die
>   Grenze vom 25.09. zurück, soweit sie das Leseformat deutsch hielt: in der
>   Adresse `?sort=price`, `?only=unsure`, `/?undo_discovery=…&discovery_kind=…`
>   (die Schlüssel `open`, `free`, `price`, `new`, `stars`, `reason`, `title`,
>   `author`), im Browserspeicher `sort:/watchlist`, in den Vorlagen die
>   `id`-Werte (`entry-…`, `portrait-status`, `book-status-…`, `rename`,
>   `intake-next`, `run-slot`), die CSS-Klassen (`pill`, `tap`, `pick`,
>   `strip`, `tile-image`, `blurb-box`, `when-open`, …) und die
>   Alpine-Zustände. Was die Leserin *liest* — Beschriftungen, Knopfwörter —
>   bleibt deutsch.
>
>   Was jemand als Lesezeichen haben kann, gilt weiter: `?sortiert=…` mit den
>   alten Schlüsseln (`sorting.OLD_SLUGS`), `?nur=unklar`, `?anlass=` (#57),
>   `/?rueckgaengig=…&art=…`. Im Code heißen diese alten Parameter englisch
>   (`old_sort`, `old_only`, …); der deutsche Name steht nur noch als Alias.
>   Der Browser liest den alten Speicherschlüssel `sortiert:…` einmal,
>   übersetzt den Wert und zieht ihn um. Auch ein Formular, das noch mit dem
>   alten Rücksprung (`/watchlist?nur=unklar`, `back=buch`) offen war, kommt
>   an.
> - **Kommandozeilen-Optionen** (`--datei`, `--nur-bekannte`, `--anzahl`,
>   `--fruehestens-nach`) sind Leseformat wie eine Adresse, stehen aber in
>   Cron-Einträgen, im Skill `buch-bewerten` und in `docs/betrieb.md`; sie
>   bleiben und tragen ein englisches `dest`.
> - **Schlüssel in Daten- und Config-Dateien** (`hinweis` in `owned.yaml`,
>   `sterne_ab` im Bewertungsschema, die Vokabular-Dateien mit `merkmale`,
>   `familien`, `beschreibung`, `muster`) bleiben deutsch, wie oben für
>   Config- und Profildateien festgehalten.
