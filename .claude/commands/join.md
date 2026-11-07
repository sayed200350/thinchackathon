---
description: Legt fest, ob du Person A oder B bist (TEAM_PERSON)
argument-hint: A | B
---
Setze die Team-Identität auf `$ARGUMENTS`.

1. Prüfe, dass `$ARGUMENTS` genau `A` oder `B` ist (Großbuchstabe). Sonst abbrechen und nachfragen.
2. Lies `.claude/settings.local.json`, falls vorhanden. Setze im `"env"`-Block `"TEAM_PERSON": "$ARGUMENTS"`. Bestehende Einstellungen zusammenführen, nichts anderes überschreiben. Existiert die Datei nicht, lege sie an.
3. Prüfe, dass `.claude/settings.local.json` in `.gitignore` steht; falls nicht, ergänzen. Prüfe mit `git check-ignore .claude/settings.local.json`.
4. Sag dem Nutzer: Er ist jetzt Person $ARGUMENTS (Ordner laut `team/areas.md`), und **Claude Code muss neu gestartet werden**, damit `TEAM_PERSON` wirkt. Danach `/sync` und dann `/team <Ziel>`.
