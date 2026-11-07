---
description: Agent Team für die eigene Person starten und ein Ziel umsetzen
argument-hint: <Ziel> [Anzahl Teammates]
---
Ziel: `$ARGUMENTS`

Ich bin Person `$TEAM_PERSON` (falls leer: abbrechen und `/join <PERSON>` empfehlen). Du bist der Team Lead `<ICH>-lead`.

## Vorbereitung (vor dem Spawnen)
1. Sync aus `team/README.md` ausführen (pull, Inbox, Status, push).
2. Lies `team/README.md`, `team/areas.md`, alles in `contract/`, die eigene Inbox `team/inbox/<ICH>/` und den Status **aller** anderen Personen (`team/status/*.md` außer der eigenen). Berücksichtige offene Nachrichten mit `Antwort erwartet: ja`.

## Planung
3. Zerlege das Ziel in Tasks. Lege pro Task `team/tasks/<ICH>-<NR>-<kurzname>.md` an (fortlaufende NR, Format aus `team/README.md`).
4. Entscheide selbst, wie viele Teammates sinnvoll sind. Steht in `$ARGUMENTS` eine Zahl, nimm genau diese Anzahl.
5. Weise jedem Teammate Dateien zu, **nur aus den eigenen Ordnern** laut `team/areas.md`, und so, dass **nie zwei Teammates dieselbe Datei** bearbeiten. Trage den Agent (`<ICH>-<rolle>`) im Task ein.

## Team erstellen
6. Erstelle ein Agent Team. Teammates heißen `<ICH>-<rolle>`. Gib jedem Teammate im Spawn-Prompt mit:
   - seine Tasks und die exakte Liste der Dateien, die er bearbeiten darf
   - relevante Teile aus `contract/`
   - Regeln: nur zugewiesene Dateien ändern; mit anderen Teammates über die lokale Team-Mailbox reden; **nie** in `team/inbox/` schreiben; **nicht** committen/pushen; braucht er etwas von einer anderen Person oder eine `contract/`-Änderung, meldet er es dem Lead; fertige Arbeit meldet er dem Lead.

## Während der Arbeit
7. Nur du committest und pushst, Format `[<ICH>/<agent>] Beschreibung`.
8. Nach jedem abgeschlossenen Task: Task-Datei auf `fertig`, committen, Sync.
9. Vor jeder Änderung an `contract/`: Sync, alle betroffenen Personen per Nachricht informieren (Typ `contract`, einzeln oder an `alle`), Datei in `team/decisions/`, dann Änderung.
10. Kommunikation mit anderen Personen mäßig: nur contract, blocker, handoff, frage. Genau ein Empfänger pro Nachricht (`alle` nur bei contract). Mehrere Punkte pro Empfänger bündeln, beim nächsten Sync als eine Nachricht. Kein Status per Nachricht.
11. Am Ende: Teammates beenden, letzter Sync, kurze Zusammenfassung an den Nutzer.
