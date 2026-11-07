# Policy Replay — thinc! hack MUC (Taktile Track)

Hilft Kfz-Versicherungs-Reviewern bei einer Policy-Änderung zu sehen: **Welche offenen Claims brauchen einen zweiten Blick, und warum?** Deliverables: CSV-Entscheidungsengine (Policy v1 + v2) und eine Reviewer-App, die dieselben Entscheidungen erklärt, plus Business Case und Demo. Details: `README.md`.

## Tech Stack
- Noch nicht festgelegt. Engine (A) und App (B) wählen ihren Stack selbst; die Schnittstelle ist `contract/`.
- Eingabedaten: `data/taktile/` (labelled_development_cases.csv, unlabelled_practice_cases.csv, policy_v1.docx).
- Jury-Output-Spalten: `contract/batch-output.md`.

## Befehle
- Noch keine. Sobald es Build/Run/Test-Befehle gibt, hier ergänzen (Engine-Batch, App-Start, Tests).

## Zusammenarbeit (zwei Personen, je ein Agent Team)
Verbindliche Regeln: **`team/README.md`**. Ordnerbesitz: `team/areas.md`. Identität: `TEAM_PERSON` (A oder B) in `.claude/settings.local.json`.

Kurzfassung:
- **Gateway:** Nur der Team Lead (`<PERSON>-lead`) kommuniziert mit der anderen Person über `team/inbox/`. Teammates nutzen die lokale Agent-Team-Mailbox, schreiben nie in `team/inbox/` und melden Bedarf an die andere Person ihrem Lead.
- **Nur der Lead committet und pusht.** Commit-Format `[A/<agent>] ...` bzw. `[B/<agent>] ...`.
- Nie zwei Teammates an derselben Datei. Nur in eigenen Ordnern arbeiten.
- Nachrichten nur bei contract-Änderung, Blocker, Handoff oder Frage, gebündelt. Status gehört in `team/status/`.
- `contract/` nie ohne Nachricht + Datei in `team/decisions/` ändern.
- Sync bei Session-Start, nach jedem Task, vor contract-Änderungen.

## Slash Commands
- `/join A|B` — Identität setzen (danach Claude Code neu starten)
- `/team <Ziel> [Anzahl]` — Agent Team für die eigene Person starten
- `/sync` — pull, Inbox lesen, Status aktualisieren, push
- `/msg <typ> <inhalt>` — Nachricht an die andere Person (contract | blocker | handoff | frage)
