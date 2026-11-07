---
description: Sync mit allen anderen Personen über Git (pull, Inbox, Status, push)
---
Führe den Sync-Ablauf aus `team/README.md` aus. Ich bin Person `$TEAM_PERSON` (Umgebungsvariable; prüfe mit `echo $TEAM_PERSON`, falls leer: abbrechen und `/join <PERSON>` empfehlen). Die anderen Personen sind alle übrigen Personen aus `team/areas.md`.

1. `git pull --rebase --autostash`. Bei Konflikten in fremden Ordnern nie die Version einer anderen Person überschreiben; eigene Änderung dort verwerfen und später eine Nachricht schicken. Danach `git submodule update --init` (`app/` ist Lovable-Submodule: nur lesen, nie darin committen).
2. Alle Dateien in `team/inbox/<ICH>/` (ohne `done/`) lesen.
3. Nachrichten, die vollständig erledigt sind bzw. nur Info waren, mit `git mv` nach `team/inbox/<ICH>/done/` verschieben. Nachrichten mit `Antwort erwartet: ja` erst verschieben, wenn eine Antwort geschickt ist (Antworten bündeln: pro Empfänger eine Nachricht, genau ein Empfänger pro Nachricht, Format aus `team/README.md`).
4. `team/status/<ICH>.md` aktualisieren (max. 8 Zeilen, Format aus `team/README.md`, aktueller Zeitstempel via `date '+%Y-%m-%d %H:%M'`).
5. Committen mit `[<ICH>/<ICH>-lead] sync` und pushen. Schlägt der Push fehl: erneut pull --rebase, dann push.

Danach kurz zusammenfassen:
- Neue Nachrichten (Absender, Typ, Betreff, was zu tun ist)
- Stand **aller** anderen Personen (je 1–2 Zeilen aus `team/status/<P>.md` für jede andere Person)
- Offene Antworten (Nachrichten mit `Antwort erwartet: ja`, die noch nicht beantwortet sind: an mich und von mir an andere)
