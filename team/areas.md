# Ordnerbesitz

Jede Datei hat genau einen Besitzer. Nur der Besitzer schreibt.

## A — Sayed · Rules, CSV, Evaluation & Backend
- `engine/` — Entscheidungsengine (Policy v1, v2), CSV-Einlesen, Batch-Command
- `eval/` — Qualitätsreports, Auswertung gegen Labels
- `backend/` — HTTP-API für Claims, Entscheidungen und Policy-Vorschau, Engine-Anbindung, Datenbank, Migrationen und Backend-Tests. Sayed speichert Reviewer-Korrekturen und die Audit-Historie.
- `contract/api.md` — Sayed gibt Rafik das API-Format zum Lesen einer Entscheidung und zum Speichern einer Korrektur.
- `team/status/A.md`, `team/tasks/A-*.md`, `team/inbox/A/done/`

## B — Rafik · Reviewer-App, Business Case & Demo
- `app/` — Reviewer-App (Claim-Liste, Detailansicht, Korrektur-Eingabe, Policy-Change-Preview)
- `business-case/` — Kostenrechner, Annahmen
- `demo/` — Demo-Skript, Pitch
- `team/status/B.md`, `team/tasks/B-*.md`, `team/inbox/B/done/`
- Rafiks App liest Entscheidungen und sendet Korrekturen über Sayeds API.

## Gemeinsam (Änderung nur mit Nachricht an alle betroffenen Personen)
- `contract/` (außer `contract/api.md`, siehe A) — Ergebnis-Schema, Beispielresultat DEV-001, Batch-CSV-Spalten. Jede Änderung: Nachricht + Datei in `team/decisions/`.
- `data/` — Taktile-Material (CSVs, Policy). Nur lesen; neue Dateien (z. B. Policy v2) per Nachricht ankündigen.
- `team/README.md`, `team/areas.md`, `team/decisions/`
- `README.md`, `CLAUDE.md`, `.claude/`, `.gitignore`, `Usecase/`

## Schreibrechte in fremden Bereichen
- Nachrichten: Jede Person legt neue Dateien in der Inbox des Empfängers an (`team/inbox/<EMPFÄNGER>/`). Nur Anlegen, nie ändern oder verschieben.
