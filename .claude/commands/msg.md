---
description: Nachricht an die andere Person schicken (contract | blocker | handoff | frage)
argument-hint: <typ> <inhalt>
---
Eingabe: `$ARGUMENTS`. Erstes Wort = Typ, Rest = Inhalt. Ich bin `$TEAM_PERSON` (falls leer: abbrechen, `/join` empfehlen).

1. Ist der Inhalt eine reine Statusmeldung (woran ich arbeite, Fortschritt, nichts, was die andere Person tun oder wissen muss): **keine Nachricht**. Stattdessen `team/status/<ICH>.md` aktualisieren, committen, pushen und dem Nutzer sagen, dass das laut Regeln Status ist.
2. Typ muss `contract`, `blocker`, `handoff` oder `frage` sein. Sonst nachfragen.
3. Bei `contract`: zusätzlich eine Datei `team/decisions/YYYYMMDD-HHMM_<thema>.md` anlegen.
4. `git pull --rebase --autostash`. Gibt es schon eine ungesendete eigene Idee/Nachricht, bündeln.
5. Datei anlegen: `team/inbox/<ANDERE>/YYYYMMDD-HHMM_<ICH>_<thema>.md` (Zeit via `date '+%Y%m%d-%H%M'`, thema kurz, kebab-case), Format:
   ```
   Von: <ICH>
   An: <ANDERE>
   Typ: <typ>
   Betreff: <eine Zeile>

   <max. 10 Zeilen, mit konkreten Dateipfaden>

   Antwort erwartet: ja | nein
   ```
6. Committen mit `[<ICH>/<ICH>-lead] msg: <betreff>` und pushen.
