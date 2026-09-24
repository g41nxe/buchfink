# Buchfink

Einstieg: [README.md](README.md) sagt, was das Werkzeug tut, [CONTEXT.md](CONTEXT.md)
liefert die Begriffe, [docs/rundgang.md](docs/rundgang.md) erklärt die Arbeitsweise,
ohne den Code zu lesen.

## Sprachregelung (ADR 22)

- **Bezeichner sind englisch**: Klassen, Funktionen, Tabellen, Routen, Dateinamen,
  Testnamen.
- **Alle Prosa ist deutsch**: Kommentare, Docstrings, Commit-Nachrichten, `docs/`,
  README, Oberfläche, Tagesbericht, Issues, diese Datei.
- **Das Glossar in `CONTEXT.md` ist die Brücke**: jeder englische Begriff trägt
  genau ein deutsches Wort. Im Code der englische Name, im Text das deutsche Wort.
  Wer im Kommentar das Codeobjekt meint, schreibt es in Backticks (`Digest`); wer
  die Sache meint, die bei der Leserin ankommt, schreibt Tagesbericht.
- Wer ein neues Wort einführt, trägt es ins Glossar ein — sonst gibt es zwei.

## Entwicklung

- `uv run pytest && uv run ruff check .` — Smoke-Tests gegen die echten Quellen
  sind mit `@pytest.mark.live` markiert und laufen nicht mit.
- Oberfläche: `uv run python -m ebook_watchlist.web` (Port 8437). Die statischen
  Dateien vorher einmal mit `uv run python -m ebook_watchlist.web.build` bauen.
- Projekteigene Skills liegen in `.agents/skills/` (`buch-bewerten` ruft
  `ebw judge` auf; der Code urteilt, der Skill liest vor).

## Agent skills

### Issue tracker

Issues leben in GitHub Issues von `g41nxe/ebook-watchlist` (über die `gh`-CLI);
fremde Pull Requests sind keine Triage-Oberfläche. Siehe `docs/agents/issue-tracker.md`.

### Triage labels

Die fünf kanonischen Labels werden unverändert benutzt (`needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`). Siehe `docs/agents/triage-labels.md`.

### Domain docs

Einzel-Kontext: eine `CONTEXT.md` und ein `docs/adr/` im Wurzelverzeichnis.
Siehe `docs/agents/domain.md`.
