# Policy Replay — thinc! hack MUC (Taktile Track)

Hilft Kfz-Versicherungs-Reviewern bei einer Policy-Änderung zu sehen: **Welche offenen Claims brauchen einen zweiten Blick, und warum?** Deliverables: CSV-Entscheidungsengine (Policy v1 + v2), ein Backend (API, Korrekturen, Audit-Historie) und eine Reviewer-App, die dieselben Entscheidungen erklärt, plus Business Case und Demo. Details: `README.md`.

## Tech Stack
- Noch nicht festgelegt. Sayed (A) verantwortet Engine und Backend, Rafik (B) die App; die Schnittstellen sind in `contract/` (HTTP-API: `contract/api.md`, Besitzer A).
- Eingabedaten: `data/taktile/` (labelled_development_cases.csv, unlabelled_practice_cases.csv, policy_v1.docx).
- Jury-Output-Spalten: `contract/batch-output.md`.

## Befehle
- Lokale Reviewer-API: `python3 -m backend --ui-origin http://localhost:5173`. HTTP-Vertrag und Beispiele: `contract/api.md`.
- Engine und CSV: `python3 -m engine --help`. Auswertung: `python3 -m eval.quality data/taktile/labelled_development_cases.csv`.
- Alle Tests: `python3 -m unittest discover -v`.

## Zusammenarbeit (mehrere Personen, je ein Agent Team)
Verbindliche Regeln: **`team/README.md`**. Ordnerbesitz: `team/areas.md`. Identität: `TEAM_PERSON` (A oder B) in `.claude/settings.local.json`.

Kurzfassung:
- **Gateway:** Pro Person kommuniziert nur der Team Lead (`<PERSON>-lead`) nach außen über `team/inbox/`. Teammates nutzen die lokale Agent-Team-Mailbox, schreiben nie in `team/inbox/` und melden Bedarf an andere Personen ihrem Lead.
- **Nur der Lead committet und pusht.** Commit-Format `[<PERSON>/<agent>] ...`.
- Nie zwei Teammates an derselben Datei. Nur in eigenen Ordnern arbeiten.
- `app/` ist das Submodule `rafik-324/thinc-hack` (Lovable, gehört B): nur über Lovable ändern. Agents lesen `app/` nur, nie darin committen. Nach `git pull` immer `git submodule update --init`.
- Datenbank: eigenes Supabase-Projekt, Schema in `contract/db/` (gemeinsam). Keys nur in `.env` (Vorlage `.env.example`), nie committen.
- Nachrichten nur bei contract-Änderung, Blocker, Handoff oder Frage, gebündelt. Status gehört in `team/status/`.
- Jede Nachricht hat genau einen Empfänger. „An alle“ nur bei `contract/`-Änderungen (Kopie in die Inbox der anderen aktiven Person).
- Vor einer `contract/`-Änderung alle betroffenen Personen per Nachricht informieren + Datei in `team/decisions/`.
- Sync bei Session-Start, nach jedem Task, vor contract-Änderungen.

## Slash Commands
- `/join <PERSON>` — Identität setzen (A oder B laut `team/areas.md`; danach Claude Code neu starten)
- `/team <Ziel> [Anzahl]` — Agent Team für die eigene Person starten
- `/sync` — pull, Inbox lesen, Status aktualisieren, push
- `/msg <an> <typ> <inhalt>` — Nachricht an eine Person (A oder B) oder `alle` (nur bei contract); typ: contract | blocker | handoff | frage
