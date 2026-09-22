# Betrieb: den Lauf täglich anstoßen, die Oberfläche dauerhaft halten

Es gibt keinen eigenen Zeitplaner — der Lauf wird von außen angestoßen, einmal
am Tag reicht. Wie oft er dann *wirklich* läuft, entscheidet er selbst: die
Kadenz steht als `run_every_hours` im Profil, und das Journal weiß, wann
zuletzt gelaufen wurde. Ein Wirt, der zu dicht taktet, kostet deshalb nichts.
Eine Dateisperre
serialisiert parallele Läufe: ein zweiter Start beendet sich sofort wieder.
Ein Umzug auf einen anderen Rechner ist *Repository kopieren, `uv sync`,
`data/` mitnehmen*.

Zwei Dinge wollen eingerichtet werden, und sie sind unabhängig voneinander:
der **tägliche Lauf** und die **Oberfläche**, die dauerhaft erreichbar sein
soll. Ohne den Lauf zeigt die Oberfläche nie etwas Neues; ohne die Oberfläche
läuft das Werkzeug trotzdem.

Drei Wege stehen hier, und man nimmt genau einen: **Container** (fasst beides
zusammen), **Windows-Aufgabenplanung** oder **systemd**. Wer den Container
fährt, legt keine Aufgaben an — sonst streiten zwei Server um Port 8437.

## Container

Der Weg auf einem Rechner, auf dem schon andere Dienste in Containern laufen.
Ein Container, nicht zwei: der Webprozess startet den Lauf als Kindprozess und
verfolgt ihn über dessen pid, und der enge Lauf läuft als Thread in ihm.
Getrennte Container hätten getrennte pid-Namensräume, und die Lauf-Liste zeigte
„läuft" für längst beendete Läufe.

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
- **Der Lauf taktet sich selbst**: das Einstiegsskript stößt beim Start einen
  Lauf an und dann alle 24 Stunden. Keine feste Uhrzeit — ein Lauf vergleicht
  gegen die letzte Aufzeichnung, nie gegen „gestern".
- **Die Kadenz steht in den Einstellungen, nicht im Wirt.** Ein Lauf mit `--trigger cron`
  schaut selbst ins Journal und tut nichts, wenn der letzte keine
  `run_every_hours` Stunden her ist (Voreinstellung **20**); er sagt es und
  endet mit 0, denn zu eifrig ist kein Fehler. Der Wirt darf deshalb dumm sein
  und einfach täglich rufen. Ohne das kostete jedes `docker compose up` einen
  vollen Lauf gegen die echten Quellen — ein Nachmittag mit fünf Neubauten
  steht bis heute in der Preisgeschichte jedes Buchs.

  Zwanzig statt vierundzwanzig, weil der tägliche Ruf um die Dauer jedes Laufs
  nach hinten rutscht und sonst irgendwann ein Tag ausfiele.

  Die Grenze gilt der **Maschine**: der Knopf „Lauf jetzt starten" und ein
  getipptes `ebw` laufen sofort, immer. Von Hand erzwingen lässt sich ein Lauf
  mit `--fruehestens-nach 0`, verstellen mit `--fruehestens-nach N`. Enge
  Läufe zählen ohnehin nicht mit — sie fragen eine Adresse ab und machen
  keinen Rundgang.
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

## Windows — Aufgabenplanung

### Der tägliche Lauf

[`scripts/run-daily.cmd`](../scripts/run-daily.cmd) wechselt ins Repository,
startet den Lauf und hängt die Ausgabe an `data/run.log` an. Die Aufgabe
zeigt einfach auf diese Datei — die ganze Kommandozeile bei `schtasks` zu
hinterlegen heißt sonst, sich mit den Anführungszeichen-Regeln von `cmd` zu
prügeln:

```powershell
$repo = 'D:\Pfad\zum\repo'
$ich  = "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName 'Buchfink Lauf' -Force `
  -Action (New-ScheduledTaskAction -Execute "$repo\scripts\run-daily.cmd" -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -Daily -At '06:00') `
  -Principal (New-ScheduledTaskPrincipal -UserId $ich -LogonType Interactive) `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable `
      -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew)
```

`StartWhenAvailable` holt einen verpassten Lauf nach — dieselbe Rolle wie
`Persistent=true` beim systemd-Timer. Das Zeitlimit von zwei Stunden ist
keine Schätzung der Dauer, sondern eine Notbremse: ein hängender Lauf hält
sonst die Sperre und blockiert damit auch den von morgen.

### Die Oberfläche

Sie läuft unter `pythonw.exe` aus der bereits gebauten Umgebung — ohne `uv`,
weil das zur Laufzeit nichts beiträgt, und ohne Konsolenfenster, das sonst
dauerhaft offen stünde und beim versehentlichen Zuklicken den Server mitnähme.

```powershell
$repo = 'D:\Pfad\zum\repo'
$ich  = "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName 'Buchfink Oberflaeche' -Force `
  -Action (New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" `
      -Argument '-m ebook_watchlist.web' -WorkingDirectory $repo) `
  -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $ich) `
  -Principal (New-ScheduledTaskPrincipal -UserId $ich -LogonType Interactive) `
  -Settings (New-ScheduledTaskSettingsSet -RestartCount 3 `
      -RestartInterval (New-TimeSpan -Minutes 5) `
      -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew)
```

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
Stop-ScheduledTask  -TaskName 'Buchfink Oberflaeche'   # anhalten
Start-ScheduledTask -TaskName 'Buchfink Oberflaeche'   # wieder starten
Get-ScheduledTask -TaskName 'Buchfink*' | Get-ScheduledTaskInfo
```

Im Task-Manager stehen **zwei** `pythonw.exe`, und das ist richtig so: die
`pythonw.exe` im `.venv` ist ein Trampolin, das den eigentlichen Interpreter
startet. Wer den Elternprozess abschießt, nimmt das Kind mit — deshalb hält
man die Aufgabe an, statt Prozesse zu suchen.

Die Ausgabe der Oberfläche landet in `data/web.log`. Ohne Konsole hat
`pythonw.exe` keine gültigen Ausgabe-Handles; die Oberfläche erkennt das beim
Start und schreibt stattdessen in diese Datei
([`web/__main__.py`](../src/ebook_watchlist/web/__main__.py)). Ohne diese
Vorkehrung beendete schon die erste Startzeile den Prozess mit Rückgabewert 1
— ohne Spur, weil die Fehlermeldung denselben kaputten Weg genommen hätte.

## Linux / Raspberry Pi — systemd-Timer

[`scripts/run-daily.sh`](../scripts/run-daily.sh) übernimmt dieselbe Rolle.
Zwei Dateien unter `~/.config/systemd/user/`:

```ini
# ebook-watchlist.service
[Unit]
Description=Buchfink

[Service]
Type=oneshot
WorkingDirectory=%h/ebook-watchlist
ExecStart=%h/ebook-watchlist/scripts/run-daily.sh
```

```ini
# ebook-watchlist.timer
[Unit]
Description=Taeglicher Buchfink-Lauf

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now ebook-watchlist.timer
```

`Persistent=true` holt einen verpassten Lauf nach dem Einschalten nach. Nötig
ist das nicht, weil ein Lauf immer gegen die letzte Aufzeichnung vergleicht,
nie gegen „gestern". Alle Zeiten sind Ortszeit; bei der Zeitumstellung kann
ein Lauf ausfallen oder doppelt laufen. Beides ist unkritisch.

Für die Oberfläche gilt dort dasselbe Muster als eigener Dienst — `Type=simple`,
`ExecStart=%h/ebook-watchlist/.venv/bin/python -m ebook_watchlist.web`,
`Restart=on-failure`, `WantedBy=default.target`. Unter systemd braucht es die
Vorkehrung aus `web/__main__.py` nicht: das Journal nimmt die Ausgabe entgegen.
