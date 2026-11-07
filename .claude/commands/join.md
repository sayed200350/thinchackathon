---
description: Legt fest, welche Person du bist (TEAM_PERSON, z. B. A oder B)
argument-hint: <PERSON>
---
Setze die Team-Identität auf `$ARGUMENTS`.

1. Lies `team/areas.md`. Gültig ist jede Person, die dort als Abschnitt `## <PERSON> — …` steht. Ist `$ARGUMENTS` keine davon (Großbuchstabe), abbrechen und die gültigen Personen nennen.
2. Lies `.claude/settings.local.json`, falls vorhanden. Setze im `"env"`-Block `"TEAM_PERSON": "$ARGUMENTS"`. Bestehende Einstellungen zusammenführen, nichts anderes überschreiben. Existiert die Datei nicht, lege sie an.
3. Prüfe, dass `.claude/settings.local.json` in `.gitignore` steht; falls nicht, ergänzen. Prüfe mit `git check-ignore .claude/settings.local.json`.
4. Prüfe, dass `team/status/$ARGUMENTS.md` und `team/inbox/$ARGUMENTS/done/` existieren; falls nicht, Hinweis geben (nicht selbst anlegen, das ist Teil des Team-Setups).
5. Sag dem Nutzer: Er ist jetzt Person $ARGUMENTS (Ordner laut `team/areas.md`), und **Claude Code muss neu gestartet werden**, damit `TEAM_PERSON` wirkt. Danach `/sync` und dann `/team <Ziel>`.
