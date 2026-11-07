# Ordnerbesitz

Jede Datei hat genau einen Besitzer. Nur der Besitzer schreibt.

## A — Sayed · Rules, CSV & Evaluation
- `engine/` — Entscheidungsengine (Policy v1, v2), CSV-Einlesen, Batch-Command
- `eval/` — Qualitätsreports, Auswertung gegen Labels
- `team/status/A.md`, `team/tasks/A-*.md`, `team/inbox/A/done/`

## B — Rafik · Reviewer-App, Business Case & Demo
- `app/` — Reviewer-App (Claim-Liste, Detailansicht, Korrekturen, Policy-Change-Preview)
- `business-case/` — Kostenrechner, Annahmen
- `demo/` — Demo-Skript, Pitch
- `team/status/B.md`, `team/tasks/B-*.md`, `team/inbox/B/done/`

## Gemeinsam (Änderung nur mit Nachricht an die andere Person)
- `contract/` — Ergebnis-Schema, Beispielresultat DEV-001, Batch-CSV-Spalten. Jede Änderung: Nachricht + Datei in `team/decisions/`.
- `data/` — Taktile-Material (CSVs, Policy). Nur lesen; neue Dateien (z. B. Policy v2) per Nachricht ankündigen.
- `team/README.md`, `team/areas.md`, `team/decisions/`
- `README.md`, `CLAUDE.md`, `.claude/`, `.gitignore`, `Usecase/`

## Schreibrechte in fremden Bereichen
- Nachrichten: A schreibt neue Dateien nach `team/inbox/B/`, B nach `team/inbox/A/`. Nur Anlegen, nie ändern oder verschieben.
