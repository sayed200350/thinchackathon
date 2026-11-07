---
description: Sync mit der anderen Person über Git (pull, Inbox, Status, push)
---
Führe den Sync-Ablauf aus `team/README.md` aus. Ich bin Person `$TEAM_PERSON` (Umgebungsvariable; prüfe mit `echo $TEAM_PERSON`, falls leer: abbrechen und `/join A` bzw. `/join B` empfehlen). Die andere Person ist der jeweils andere Buchstabe.

1. `git pull --rebase --autostash`. Bei Konflikten in fremden Ordnern nie die Version der anderen Person überschreiben; eigene Änderung dort verwerfen und später eine Nachricht schicken.
2. Alle Dateien in `team/inbox/<ICH>/` (ohne `done/`) lesen.
3. Nachrichten, die vollständig erledigt sind bzw. nur Info waren, mit `git mv` nach `team/inbox/<ICH>/done/` verschieben. Nachrichten mit `Antwort erwartet: ja` erst verschieben, wenn eine Antwort geschickt ist (Antworten bündeln: eine Nachricht an die andere Person, Format aus `team/README.md`).
4. `team/status/<ICH>.md` aktualisieren (max. 8 Zeilen, Format aus `team/README.md`, aktueller Zeitstempel via `date '+%Y-%m-%d %H:%M'`).
5. Committen mit `[<ICH>/<ICH>-lead] sync` und pushen. Schlägt der Push fehl: erneut pull --rebase, dann push.

Danach kurz zusammenfassen:
- Neue Nachrichten (Absender, Typ, Betreff, was zu tun ist)
- Stand der anderen Person (aus `team/status/<ANDERE>.md`)
- Offene Antworten (Nachrichten mit `Antwort erwartet: ja`, die noch nicht beantwortet sind, in beide Richtungen)
