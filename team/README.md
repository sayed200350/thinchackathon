# Team-Regeln (A + B)

Mehrere Personen (aktuell A, B und C, siehe areas.md) arbeiten parallel, jede auf ihrem eigenen Rechner mit einem eigenen Claude Code Agent Team. Abstimmung läuft ausschließlich über Git. Kommunikation ist **mäßig**: nur wenn nötig, kurz und gebündelt.

Ordnerbesitz: siehe [areas.md](areas.md). Identität: `TEAM_PERSON` in `.claude/settings.local.json` (setzen mit `/join <PERSON>`, z. B. `/join C`).

## Gateway
- Pro Person kommuniziert **nur der Team Lead** nach außen, also mit den anderen Personen. Teammates reden untereinander über die lokale Agent-Team-Mailbox und schreiben **nie** in `team/inbox/`. Braucht ein Teammate etwas von einer anderen Person, meldet er es seinem Lead.
- **Nur der Lead committet und pusht.** Teammates melden fertige Arbeit an den Lead.
- Der Lead teilt die Dateien seiner Person so auf die Teammates auf, dass **nie zwei Teammates dieselbe Datei** bearbeiten.

## Mäßige Kommunikation
- Jede Nachricht hat **genau einen Empfänger**.
- Eine Nachricht **an alle** ist nur bei Änderungen in `contract/` erlaubt. Sie landet als Kopie (gleicher Inhalt, gleicher Dateiname) in jeder Inbox außer der eigenen; `An:` lautet dann `alle`.
- Eine Nachricht an eine andere Person gibt es nur bei:
  - Änderung in `contract/`
  - Blocker, der eine andere Person braucht
  - Übergabe eines fertigen Teils, den eine andere Person nutzt
  - Frage, die man nicht selbst klären kann
- **Kein Status per Nachricht.** Dafür ist `team/status/` da.
- Mehrere Punkte werden gebündelt und beim nächsten Sync als **eine** Nachricht verschickt.
- Nachrichten mit `Antwort erwartet: ja` werden beim nächsten Sync beantwortet.
- **Vor** einer Änderung an `contract/` werden **alle betroffenen Personen** per Nachricht informiert (einzeln oder per Nachricht an alle). Jede Änderung bekommt eine Datei in `team/decisions/`.

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
- Commit-Format: `[<PERSON>/<agent>] Beschreibung`, z. B. `[A/A-engine] v1-Regeln implementiert`.
- Bei einem Konflikt in fremden Ordnern **nie** die Version einer anderen Person überschreiben. Stattdessen eigene Änderung dort verwerfen und eine Nachricht schicken.
- Agent-Namen: `<PERSON>-lead` bzw. `<PERSON>-<rolle>` (z. B. `A-lead`, `B-ui`, `C-api`).

## Struktur

```
team/README.md            diese Regeln
team/areas.md             Ordnerbesitz von A und B
team/status/A.md          aktueller Stand von A, nur A schreibt
team/status/B.md          aktueller Stand von B, nur B schreibt
team/status/C.md          aktueller Stand von C, nur C schreibt
team/inbox/A/             Nachrichten an A, eine Datei pro Nachricht
team/inbox/A/done/        von A erledigte Nachrichten
team/inbox/B/             Nachrichten an B
team/inbox/B/done/        von B erledigte Nachrichten
team/inbox/C/             Nachrichten an C
team/inbox/C/done/        von C erledigte Nachrichten
team/tasks/               eine Datei pro Task, nur der Besitzer ändert sie
team/decisions/           eine Datei pro gemeinsamer Entscheidung, nie nachträglich ändern
contract/                 gemeinsame Schnittstellen (API, Datenformate, Typen)
```

## Formate

### Nachricht
Dateiname: `team/inbox/<EMPFÄNGER>/YYYYMMDD-HHMM_<absender>_<thema>.md`

```markdown
Von: A
An: B            (oder: alle — nur bei Typ contract)
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
Was wurde entschieden, warum, welche Dateien in `contract/` betroffen sind, wer informiert wurde bzw. zugestimmt hat. Revidieren = neue Datei anlegen.
