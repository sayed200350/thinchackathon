# Policy-Versionen in Supabase speichern und vergleichen
- Entschieden (Vorschlag von B, Zustimmung von A steht aus): Neue Tabelle `policies` (eine unveränderliche Zeile pro Version, Text + Klauseln als jsonb) und Funktion `policy_diff(p_from, p_to)` für den klauselweisen Vergleich. Datei: `contract/db/policies.sql`, idempotent, seedet v1 aus `data/taktile/policy_v1.docx`.
- Grund: Die Reviewer-App bekommt eine Update-Seite. Der Policy Owner lädt die neue Policy hoch, sie wird gespeichert und mit der alten verglichen (Brief, Deliverable 2: „a way to update the rules and see what the change affects“). Die Policy kommt als Text/Dokument (Discord, Samstag 18:00).
- Klauseln: `id` stabil (`rule-N`, Abschnitts-Slug, `-2`, `-3` bei mehreren Absätzen), erzeugt mit `contract/db/policy-parser.mjs`. Die App nutzt denselben Parser, damit v1-Seed und Uploads vergleichbar sind.
- RLS: Lesen für alle, Insert für anon (nur Spalten policy_version, title, source_filename, raw_text, clauses, uploaded_by), kein Update/Delete. Versionsname `^v[0-9]+$`.
- Nicht enthalten: Die Engine bleibt bei v1. Welche Claims sich durch die neue Policy ändern, berechnet erst eine v2-Implementierung von A (`decisions` mit policy_version v2). Die Tabelle `policies` löst keine Engine-Läufe aus.
- Bestehende Tabellen, Views und Funktionen bleiben unverändert.
- Informiert: A (team/inbox/A/*_B_policy-versions.md).
