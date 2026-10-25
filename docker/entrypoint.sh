#!/bin/sh
# Oberflaeche und Hintergrunddienst in einem Container (ADR 40).
#
# Der Dienst holt selbst nach, was faellig ist: alle 15 Minuten prueft er, ob
# der letzte fertige Lauf aelter als die Kadenz ist (`run_every_hours`). Eine
# Schleife mit `sleep`, wie sie hier bis ADR 40 stand, braucht es nicht mehr;
# nach einer Pause des Containers ist ein Lauf beim ersten Pruefen faellig.
#
# Wer Oberflaeche und Dienst getrennt fahren will, startet zwei Container aus
# demselben Bild mit `ebw web` und `ebw worker` auf demselben Volume.
set -e

# `exec`, damit `ebw serve` die Signale von `docker stop` selbst bekommt und
# den Dienst mit sich beendet. Der Lauf, den der Dienst gerade begleitet, ist
# ein eigener Prozess; tini sammelt ihn ein (`init: true` in der Compose-Datei).
exec /app/.venv/bin/ebw serve
