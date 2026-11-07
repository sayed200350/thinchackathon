# Datenbank-Contract (Supabase)

Eigenes Supabase-Projekt (**nicht** Lovable Cloud). Schema: [`schema.sql`](schema.sql), idempotent, im Supabase SQL Editor ausführen.
Gemeinsame Schnittstelle: Änderungen nur mit Nachricht an alle Betroffenen + Datei in `team/decisions/`.
Feldnamen folgen dem Engine-Contract ([`../decision-result.md`](../decision-result.md), [`../example-result-DEV-001.json`](../example-result-DEV-001.json)).

## Wer schreibt was

| Tabelle | Schreiber | Key | Inhalt |
| --- | --- | --- | --- |
| `decisions` | Engine (`engine/`, A) | Service Role | ein Engine-JSON pro `(case_id, policy_version)`, Upsert |
| `validation_results` | Validator (`eval/`, A) | Service Role | erwartete Empfehlung + erwartete Änderung, `source` = `labelled` \| `edge_case` |
| `overrides` | Reviewer-App (`app/`, B, Lovable) | anon | nur Insert, nur für offene Claims (RLS); nie Update/Delete |
| `business_metrics` | BWL (B) | Supabase Table Editor | Kennzahlen für den Business Case |

Views (nur lesen, anon): `v_compare` (v1 gegen v2 pro Fall, `needs_recheck`, letzte Korrektur), `v_transition`, `v_rule_impact`, `v_change_check` (Vier-Felder: erwartete gegen tatsächliche Änderung), `v_error_rate`, `v_kpis` (inkl. `closed_changed`, Ziel 0).

## Keys

- `SUPABASE_URL`: alle.
- `SUPABASE_ANON_KEY`: nur die Lovable-App. Darf im Browser liegen; RLS erlaubt nur Lesen + Insert in `overrides`.
- `SUPABASE_SERVICE_ROLE_KEY`: nur Engine und Validator (lokal/Server). Umgeht RLS. **Nie** ins Frontend, nie committen.
- Lokal in `.env` (gitignored), Vorlage: `/.env.example`.

## Regeln

- `decisions` ist die unveränderte Engine-Entscheidung. Korrekturen landen ausschließlich in `overrides` (Audit-Historie, nur anhängen).
- Geschlossene Claims: v2 übernimmt die v1-Empfehlung, `needs_recheck` = false, keine Korrekturen.
- `supporting_facts` sind die entscheidenden Fakten (bei `v1.1` die Auslöser, bei `v1.2`/`v1.missing` die fehlenden Angaben, bei `v1.3` alle geprüften Felder); `null` = unbekannt.
- `policy_clause` ist optional, bis A festlegt, woher der Klauseltext kommt.
