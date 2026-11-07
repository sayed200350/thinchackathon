# Team-Regeln (A + B)

Zwei Personen (A und B) arbeiten parallel, jede auf ihrem eigenen Rechner mit einem eigenen Claude Code Agent Team. Abstimmung läuft ausschließlich über Git. Kommunikation ist **mäßig**: nur wenn nötig, kurz und gebündelt.

Ordnerbesitz: siehe [areas.md](areas.md). Identität: `TEAM_PERSON` in `.claude/settings.local.json` (setzen mit `/join A` bzw. `/join B`).

## Gateway
- Pro Person kommuniziert **nur der Team Lead** mit der anderen Person. Teammates reden untereinander über die lokale Agent-Team-Mailbox und schreiben **nie** in `team/inbox/`. Braucht ein Teammate etwas von der anderen Person, meldet er es seinem Lead.
- **Nur der Lead committet und pusht.** Teammates melden fertige Arbeit an den Lead.
- Der Lead teilt die Dateien seiner Person so auf die Teammates auf, dass **nie zwei Teammates dieselbe Datei** bearbeiten.

## Mäßige Kommunikation
- Eine Nachricht an die andere Person gibt es nur bei:
  - Änderung in `contract/`
  - Blocker, der die andere Person braucht
  - Übergabe eines fertigen Teils, den die andere Person nutzt
  - Frage, die man nicht selbst klären kann
- **Kein Status per Nachricht.** Dafür ist `team/status/` da.
- Mehrere Punkte werden gebündelt und beim nächsten Sync als **eine** Nachricht verschickt.
- Nachrichten mit `Antwort erwartet: ja` werden beim nächsten Sync beantwortet.
- `contract/` wird **nie** ohne Nachricht an die andere Person geändert. Jede Änderung bekommt eine Datei in `team/decisions/`.

## Sync
- **Wann:** Start einer Session, nach jedem abgeschlossenen Task, vor jeder Änderung an `contract/`.
- **Ablauf:**
  1. `git pull --rebase --autostash`
  2. eigene Inbox `team/inbox/<ICH>/` lesen
  3. Erledigtes nach `team/inbox/<ICH>/done/` verschieben (`git mv`)
  4. eigene Statusdatei `team/status/<ICH>.md` aktualisieren
  5. committen, pushen

## Git
- Jede Person arbeitet nur in ihren eigenen Ordnern (siehe areas.md).
- Commit-Format: `[A/<agent>] Beschreibung` bzw. `[B/<agent>] Beschreibung`, z. B. `[A/A-engine] v1-Regeln implementiert`.
- Bei einem Konflikt in fremden Ordnern **nie** die Version der anderen Person überschreiben. Stattdessen eigene Änderung dort verwerfen und eine Nachricht schicken.
- Agent-Namen: `<PERSON>-lead` bzw. `<PERSON>-<rolle>` (z. B. `A-lead`, `B-ui`).

## Struktur

```
team/README.md            diese Regeln
team/areas.md             Ordnerbesitz von A und B
team/status/A.md          aktueller Stand von A, nur A schreibt
team/status/B.md          aktueller Stand von B, nur B schreibt
team/inbox/A/             Nachrichten an A, eine Datei pro Nachricht
team/inbox/A/done/        von A erledigte Nachrichten
team/inbox/B/             Nachrichten an B
team/inbox/B/done/        von B erledigte Nachrichten
team/tasks/               eine Datei pro Task, nur der Besitzer ändert sie
team/decisions/           eine Datei pro gemeinsamer Entscheidung, nie nachträglich ändern
contract/                 gemeinsame Schnittstellen (API, Datenformate, Typen)
```

## Formate

### Nachricht
Dateiname: `team/inbox/<EMPFÄNGER>/YYYYMMDD-HHMM_<absender>_<thema>.md`

```markdown
Von: A
An: B
Typ: contract | blocker | handoff | frage
Betreff: <eine Zeile>

<maximal 10 Zeilen, mit konkreten Dateipfaden>

Antwort erwartet: ja | nein
```

### Status (`team/status/<ICH>.md`, maximal 8 Zeilen)

```markdown
# Status A
- Arbeite an: ...
- Als Nächstes: ...
- Blocker: keine | ...
- Letzte Änderung an contract/: <datei, datum> | keine
- Stand: YYYY-MM-DD HH:MM
```

### Task (`team/tasks/<PERSON>-<NR>-<kurzname>.md`, z. B. `A-003-csv-reader.md`)

```markdown
# <Titel>
- Besitzer: A
- Agent: A-engine
- Status: offen | in Arbeit | fertig
- Dateien: engine/rules.py, engine/tests/test_rules.py
```

### Entscheidung (`team/decisions/YYYYMMDD-HHMM_<thema>.md`, nie nachträglich ändern)
Was wurde entschieden, warum, welche Dateien in `contract/` betroffen sind, wer zugestimmt hat. Revidieren = neue Datei anlegen.
