# Betrieb: `ebw serve` starten

Buchfink besteht aus zwei Prozessen: der **Oberfläche** und dem
**Hintergrunddienst** (ADR 40). Die Oberfläche zeigt an und stellt Aufträge ein;
der Dienst arbeitet sie ab — den Lauf, den engen Lauf, den Steckbrief — und
**holt nach**: alle 15 Minuten prüft er, ob der letzte *fertige* Lauf älter ist
als die Kadenz („Lauf alle N Stunden“ auf der Übersicht, Voreinstellung 24). Dann stößt er
einen an. Einen festen Termin gibt es nicht, und damit nichts, was ein
zugeklappter Rechner verpassen könnte.

```bash
ebw serve        # Oberfläche und Dienst zusammen, beide enden gemeinsam
ebw web          # nur die Oberfläche
ebw worker       # nur der Dienst
```

`ebw` gibt es nach `uv sync` in `.venv`; `python -m ebook_watchlist` ist
derselbe Befehl. Läuft die Oberfläche ohne Dienst, sagt sie es: die Knöpfe
melden „Kein Hintergrunddienst“, statt still in eine Schlange zu legen, die
niemand abarbeitet.

Die Schlange liegt in `data/jobs.db`, getrennt von der Hauptdatenbank. Der Dienst
schreibt nach `data/worker.log` (unter `ebw serve`) oder auf die Konsole; jeder
Lauf, den er anstößt, ist ein eigener Prozess mit seiner Ausgabe in
`data/run-ui.log`. Eine Dateisperre serialisiert Läufe weiterhin: ein zweiter
Start beendet sich sofort wieder, egal woher er kommt.

Ein äußerer Zeitplaner ist nicht mehr nötig, aber möglich: `ebw run
--wenn-faellig` läuft nur, wenn die Kadenz es erlaubt, und lässt sich deshalb
gefahrlos stündlich rufen. Ein Umzug auf einen anderen Rechner ist *Repository kopieren,
`uv sync`, `data/` mitnehmen*.

## Container

Der Weg auf einem Rechner, auf dem schon andere Dienste in Containern laufen.
Das Bild startet `ebw serve`, also Oberfläche und Dienst in einem Container.
Getrennt geht es auch — zwei Container aus demselben Bild, `ebw web` und `ebw
worker`, auf demselben Volume —, denn seit ADR 40 verfolgt niemand mehr eine
Prozessnummer über Container hinweg.

```bash
cp .env.example .env          # Zeitzone, optional der API-Schluessel
docker volume create buchfink-data
docker compose up -d
```

Erreichbar unter **`http://buchfink.localhost/`**. Browser lösen `*.localhost`
selbst auf, ohne hosts-Eintrag; das Betriebssystem tut das übrigens *nicht*,
weshalb `ping buchfink.localhost` scheitert, während der Browser funktioniert.

Was dabei zu wissen ist:

- **Die Daten liegen im Volume `buchfink-data`**, nicht in `data/`. Die
  Datenbank fährt SQLite im WAL-Modus; über einen Bind-Mount von `D:\` liefe
  sie durch die Virtualisierungsschicht von Docker Desktop, wo die Sperren
  dokumentiert unzuverlässig sind. Das Volume ist bewusst `external`, damit ein
  versehentliches `docker compose down -v` die Datenbank nicht mitnimmt.
- **Die YAML-Dateien kommen weiterhin aus `data/`**, schreibgeschützt
  eingebunden — du bearbeitest sie mit deinem Editor. `settings.yaml` ist dabei
  keine Saatgutdatei, sondern wird bei jeder Anfrage gelesen; `seed.yaml`
  dagegen gilt nur beim Import (ADR 32, `CONTEXT.md`).
- **Der Lauf taktet sich selbst**: der Dienst prüft alle 15 Minuten, ob einer
  fällig ist, und stößt ihn dann an. Nach einer Pause des Containers ist das beim
  ersten Prüfen so; ein Neustart kostet keinen Lauf, solange der letzte jünger
  als die Kadenz ist. Ohne das kostete jedes `docker compose up` einen vollen
  Lauf gegen die echten Quellen — ein Nachmittag mit fünf Neubauten steht bis
  heute in der Preisgeschichte jedes Buchs.

  Die Grenze gilt der **Maschine**: der Knopf „Jetzt prüfen" und ein getipptes
  `ebw run` laufen sofort, immer. Enge Läufe zählen nicht mit — sie fragen eine
  Adresse ab und machen keinen Rundgang. Ein abgebrochener Lauf zählt auch nicht:
  er ist beim nächsten Prüfen wieder fällig.
- **Das Bewertungstor braucht eine Anmeldung**, sonst erscheinen alle Funde
  unbewertet — kein Fehler, nur kein Tor. Zwei Wege, in dieser Reihenfolge:
  `ANTHROPIC_API_KEY` aus der Console (getrennt abgerechnet), sonst die im Bild
  mitgebaute `claude`-CLI. Die braucht einen langlebigen Token, den du auf
  deinem Rechner mit `claude setup-token` erzeugst und als
  `CLAUDE_CODE_OAUTH_TOKEN` in die `.env` schreibst; er hängt am Abonnement und
  kostet kein zusätzliches Guthaben. Die CLI-Fassung steht als
  `CLAUDE_CODE_VERSION` fest im [`Dockerfile`](../Dockerfile) und aktualisiert
  sich nicht selbst — ein Bild soll sich nicht unter der Hand ändern.
  Sie kostet allerdings 320 MB im Bild und rund 34 Sekunden je Aufruf; wer
  einen Rückstand zügig abarbeiten will, nimmt den Schlüssel.

Eine vorhandene Datenbank kommt so ins Volume (vorher den Lauf beenden, damit
niemand schreibt):

```bash
docker compose down
docker run --rm -v buchfink-data:/ziel -v "$PWD/data:/quelle:ro" alpine \
  sh -c 'cp -a /quelle/. /ziel/ && rm -f /ziel/run.lock /ziel/*.log /ziel/secrets.env'
```

Und wieder heraus — als konsistente Sicherung, nicht als Dateikopie, weil eine
laufende SQLite-Datenbank aus drei Dateien besteht und eine Kopie davon
irgendein Zwischenzustand wäre:

```bash
docker compose exec buchfink /app/.venv/bin/python scripts/sicherung.py
```

Das schreibt `snapshots-JJJJ-MM-TT.db` nach `data-sicherung/`, prüft die Kopie
und nennt die Zahl der Bücher darin — eine Sicherung, die niemand aufmacht, ist
eine Behauptung. Das Skript liegt bewusst in einer Datei statt in einem
`python -c`-Einzeiler: dessen Anführungszeichen zerfallen in jeder Shell
anders.

> **Git Bash unter Windows** übersetzt `/app/...` in einen Windows-Pfad, und
> `docker compose exec` scheitert dann mit „no such file or directory".
> Entweder `MSYS_NO_PATHCONV=1` davorsetzen oder PowerShell nehmen.

### Anschluss an einen vorhandenen Traefik

Buchfink hängt sich an ein Netz namens `proxy`, das **keinem Projekt gehört**
und einmalig außerhalb aller Compose-Dateien angelegt wird:

```bash
docker network create proxy
```

Das ist der übliche Aufbau, wenn mehrere Projekte sich einen Proxy teilen, und
er hat einen Zweck über die Ordnung hinaus: keine Compose-Datei muss den Namen
einer anderen kennen. Die Anmeldung beim Proxy besteht aus zwei Teilen —
Mitgliedschaft im Netz und `traefik.enable=true` —, und beides zusammen ist
zugleich die Absicherung. Versehentlich passiert es nicht.

Traefik selbst braucht dafür:

```yaml
- --providers.docker=true
- --providers.docker.exposedbydefault=false
- --providers.docker.network=proxy
- --entrypoints.web.address=:80
```

Ausdrücklich **keine** `--providers.docker.constraints`-Zeile mit einem
Projektnamen. Eine solche zwingt jeden, der mitfahren will, den Namen eines
fremden Projekts zu tragen — und dann kennen sich die Projekte doch wieder.

## Windows — eine Aufgabe zur Anmeldung

`ebw serve` läuft unter `pythonw.exe` aus der bereits gebauten Umgebung — ohne
`uv`, weil das zur Laufzeit nichts beiträgt, und ohne Konsolenfenster, das sonst
dauerhaft offen stünde und beim versehentlichen Zuklicken den Server mitnähme.
Eine Aufgabe für den täglichen Lauf braucht es nicht mehr: der Dienst holt nach,
sobald der Rechner wieder wach ist.

```powershell
$repo = 'D:\Pfad\zum\repo'
$ich  = "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName 'Buchfink' -Force `
  -Action (New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" `
      -Argument '-m ebook_watchlist serve' -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $ich) `
  -Principal (New-ScheduledTaskPrincipal -UserId $ich -LogonType Interactive) `
  -Settings (New-ScheduledTaskSettingsSet -RestartCount 3 `
      -RestartInterval (New-TimeSpan -Minutes 5) `
      -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew)
```

Wer von früher die Aufgaben „Buchfink Lauf“ und „Buchfink Oberflaeche“ hat,
entfernt sie (`Unregister-ScheduledTask -TaskName 'Buchfink Lauf'`, ebenso die
Oberfläche) — die Oberfläche startete nur `ebook_watchlist.web`, also ohne Dienst.

Vier Einstellungen, die alle einen Grund haben:

- **`-User $ich` am Auslöser.** Ein Anmelde-Auslöser ohne Benutzerangabe gilt
  für *alle* Benutzer und braucht deshalb Administratorrechte. Mit
  Benutzerbindung registriert sich die Aufgabe ohne Erhöhung.
- **`LogonType Interactive`.** Die Aufgabe läuft mit deinem Token, wenn du
  angemeldet bist — kein gespeichertes Kennwort. Der Preis: nach einem
  Neustart läuft Buchfink erst ab der Anmeldung, nicht ab dem Einschalten.
- **`ExecutionTimeLimit` auf null**, also unbegrenzt. Die Vorgabe wäre drei
  Tage, und danach hätte die Aufgabenplanung den Server kommentarlos beendet.
- **`RestartCount`/`RestartInterval`.** Stirbt der Prozess, startet die
  Aufgabenplanung ihn dreimal im Abstand von fünf Minuten neu.

Danach ist die Oberfläche unter `http://localhost:8437/` erreichbar, im
selben Netz auch vom Telefon.

**Beenden und nachsehen:**

```powershell
Stop-ScheduledTask  -TaskName 'Buchfink'   # anhalten, der Dienst endet mit
Start-ScheduledTask -TaskName 'Buchfink'   # wieder starten
Get-ScheduledTask -TaskName 'Buchfink*' | Get-ScheduledTaskInfo
```

Im Task-Manager stehen mehrere `pythonw.exe`, und das ist richtig so: die
`pythonw.exe` im `.venv` ist ein Trampolin, das den eigentlichen Interpreter
startet, und der Dienst ist ein zweiter Prozess. Wer den Elternprozess
abschießt, nimmt die Kinder mit — deshalb hält man die Aufgabe an, statt
Prozesse zu suchen.

Die Ausgabe der Oberfläche landet in `data/web.log`, die des Dienstes in
`data/worker.log`. Ohne Konsole hat `pythonw.exe` keine gültigen
Ausgabe-Handles; Buchfink erkennt das beim Start und schreibt stattdessen in
diese Datei ([`web/__main__.py`](../src/ebook_watchlist/web/__main__.py)). Ohne
diese Vorkehrung beendete schon die erste Startzeile den Prozess mit
Rückgabewert 1 — ohne Spur, weil die Fehlermeldung denselben kaputten Weg
genommen hätte.

## Linux / Raspberry Pi — systemd

Ein Benutzerdienst unter `~/.config/systemd/user/buchfink.service`:

```ini
[Unit]
Description=Buchfink

[Service]
Type=simple
WorkingDirectory=%h/ebook-watchlist
ExecStart=%h/ebook-watchlist/.venv/bin/ebw serve
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now buchfink.service
```

Wer Oberfläche und Dienst getrennt haben will, legt zwei solche Dateien an, mit
`ebw web` und `ebw worker`. Unter systemd braucht es die Vorkehrung aus
`web/__main__.py` nicht: das Journal nimmt die Ausgabe entgegen. Ein Timer für
den täglichen Lauf ist überflüssig; wer trotzdem einen will, ruft
[`scripts/run-daily.sh`](../scripts/run-daily.sh) — der Lauf achtet selbst auf
die Kadenz.
