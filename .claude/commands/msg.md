---
description: Nachricht an eine Person oder an alle schicken (contract | blocker | handoff | frage)
argument-hint: <an> <typ> <inhalt>
---
Eingabe: `$ARGUMENTS`. Erstes Wort = Empfänger `<an>`, zweites Wort = Typ, Rest = Inhalt. Ich bin `$TEAM_PERSON` (falls leer: abbrechen, `/join` empfehlen).

1. `<an>` muss eine Person aus `team/areas.md` außer mir sein, oder `alle`. Sonst nachfragen.
2. Typ muss `contract`, `blocker`, `handoff` oder `frage` sein. Sonst nachfragen. `alle` ist **nur** bei Typ `contract` erlaubt; sonst abbrechen und einen einzelnen Empfänger erfragen.
3. Ist der Inhalt eine reine Statusmeldung (woran ich arbeite, Fortschritt, nichts, was jemand tun oder wissen muss): **keine Nachricht**. Stattdessen `team/status/<ICH>.md` aktualisieren, committen, pushen und dem Nutzer sagen, dass das laut Regeln Status ist.
4. `git pull --rebase --autostash`.
5. Bei Typ `contract`: Prüfe, welche Personen betroffen sind; sie alle müssen informiert werden (einzelne Nachrichten oder `alle`). Lege zusätzlich `team/decisions/YYYYMMDD-HHMM_<thema>.md` an.
6. Datei anlegen: `team/inbox/<an>/YYYYMMDD-HHMM_<ICH>_<thema>.md` (Zeit via `date '+%Y%m%d-%H%M'`, thema kurz, kebab-case). Bei `alle`: dieselbe Datei als Kopie in die Inbox jeder anderen aktiven Person aus `team/areas.md`. Format:
   ```
   Von: <ICH>
   An: <an>
   Typ: <typ>
   Betreff: <eine Zeile>

   <max. 10 Zeilen, mit konkreten Dateipfaden>

   Antwort erwartet: ja | nein
   ```
7. Committen mit `[<ICH>/<ICH>-lead] msg an <an>: <betreff>` und pushen.
