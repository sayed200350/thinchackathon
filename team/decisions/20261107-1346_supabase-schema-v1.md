# Supabase Schema v1 als Contract
- Entschieden: Datenbank ist ein eigenes Supabase-Projekt (nicht Lovable Cloud). Das Schema ist gemeinsame Schnittstelle und liegt in `contract/db/schema.sql`, Regeln in `contract/db/README.md`.
- Tabellen: `decisions` (Engine-JSON, PK case_id + policy_version), `overrides` (Reviewer-Korrekturen, nur anhängen), `validation_results`, `business_metrics`; Views für das Dashboard (`v_compare`, `v_transition`, `v_rule_impact`, `v_change_check`, `v_error_rate`, `v_kpis`).
- Schreiber: Engine → decisions, Validator → validation_results (Service Role Key); App → overrides (anon Key, RLS: nur Insert, nur offene Claims); BWL → business_metrics (Table Editor). RLS auf allen Tabellen, Lesen für alle.
- Grund: Lovable-App kann direkt mit dem anon Key lesen und Korrekturen speichern; Engine-Ergebnisse und Validierung landen an einer Stelle, das Dashboard rechnet in SQL.
- Feldnamen folgen dem Engine-Contract von A (case_id, case_status, matched_rule, supporting_facts). `policy_clause` ist optional und offen.
- Offen: Verhältnis zur SQLite-Reviewer-API von A (`backend/`, `contract/api.md`). Backend und Datenbank gehören laut team/areas.md A; das Schema selbst ist gemeinsamer Contract.
- Informiert: A (team/inbox/A/20261107-1346_B_supabase-schema.md), einzige andere aktive Person. Zustimmung steht aus.
- Außerdem: `app/` ist Submodule `rafik-324/thinc-hack`, wird nur über Lovable geändert (team/areas.md, CLAUDE.md, Sync-Schritt `git submodule update --init`).
