# Ordnerbesitz

Jede Datei hat genau einen Besitzer. Nur der Besitzer schreibt.

## A — Sayed · Rules, CSV & Evaluation
- `engine/` — Entscheidungsengine (Policy v1, v2), CSV-Einlesen, Batch-Command
- `eval/` — Qualitätsreports, Auswertung gegen Labels
- `team/status/A.md`, `team/tasks/A-*.md`, `team/inbox/A/done/`

## B — Rafik · Reviewer-App, Business Case & Demo
- `app/` — Reviewer-App (Claim-Liste, Detailansicht, Korrektur-Eingabe, Policy-Change-Preview)
- `business-case/` — Kostenrechner, Annahmen
- `demo/` — Demo-Skript, Pitch
- `team/status/B.md`, `team/tasks/B-*.md`, `team/inbox/B/done/`
- Nicht mehr B: Speichern von Reviewer-Korrekturen und Audit-Historie (jetzt C). `app/` ist nur Frontend und spricht die API aus `contract/api.md`.

## C — Mo · Backend
- `backend/` — API-Server (Claims, Entscheidungen, Policy-Change-Preview), Speicherung von Reviewer-Korrekturen und Audit-Historie, Engine-Anbindung (ruft `engine/` von A als Bibliothek bzw. Batch-Command auf)
- `backend/db/` — Datenbank, Schema, Migrationen
- `backend/tests/` — Backend-Tests
- `contract/api.md` — HTTP-API-Spezifikation (Besitzer C; Änderungen weiter nur mit Nachricht an alle Betroffenen + Datei in `team/decisions/`)
- `team/status/C.md`, `team/tasks/C-*.md`, `team/inbox/C/done/`

## Gemeinsam (Änderung nur mit Nachricht an alle betroffenen Personen)
- `contract/` (außer `contract/api.md`, siehe C) — Ergebnis-Schema, Beispielresultat DEV-001, Batch-CSV-Spalten. Jede Änderung: Nachricht + Datei in `team/decisions/`.
- `data/` — Taktile-Material (CSVs, Policy). Nur lesen; neue Dateien (z. B. Policy v2) per Nachricht ankündigen.
- `team/README.md`, `team/areas.md`, `team/decisions/`
- `README.md`, `CLAUDE.md`, `.claude/`, `.gitignore`, `Usecase/`

## Schreibrechte in fremden Bereichen
- Nachrichten: Jede Person legt neue Dateien in der Inbox des Empfängers an (`team/inbox/<EMPFÄNGER>/`). Nur Anlegen, nie ändern oder verschieben.
