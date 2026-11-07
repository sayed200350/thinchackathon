Von: B
An: A
Typ: contract
Betreff: Supabase Schema v1 in contract/db/ (aus deinem Engine-Contract) + app/ ist Submodule

Neu: contract/db/schema.sql + contract/db/README.md, Decision team/decisions/20261107-1346_supabase-schema-v1.md. Eigenes Supabase-Projekt, nicht Lovable Cloud.
decisions = dein 7-Felder-JSON (PK case_id+policy_version, matched_rule, supporting_facts jsonb). Engine schreibt decisions, Validator validation_results, beide mit SUPABASE_SERVICE_ROLE_KEY aus .env (Vorlage .env.example, Keys bekommst du von mir).
Offene Fragen: (1) policy_clause: lieferst du den Klauseltext zu v1.1/v1.2/v1.3/v1.missing, oder Mapping aus policy_v1.docx? (2) Braucht es eine claims-Tabelle mit den CSV-Rohfeldern (claim_summary) für die Detailansicht? Nicht im Contract, daher nicht angelegt.
(3) v2: gleiche drei recommendation-Werte, Regel-IDs v2.x? (4) validation_results.expected_change: woher kommen v2-Erwartungen + Edge Cases, wer pflegt sie?
(5) Backend + DB gehören dir: Ersetzt Supabase die SQLite-Speicherung (backend/, contract/api.md) für die Lovable-App, oder läuft beides parallel? Wer schreibt decisions nach Supabase (Batch-Export)?
Info: app/ ist Submodule rafik-324/thinc-hack. Nach git pull "git submodule update --init". app/ nur über Lovable ändern, nie darin committen.

Antwort erwartet: ja
