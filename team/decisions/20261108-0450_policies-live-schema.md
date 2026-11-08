# contract/db an den Live-Stand angleichen: `policies` und `claim_field_changes`

**Von:** B (Rafik) · **Betrifft:** A (contract/db/, backend/) · **Status:** von B freigegeben, Rückmeldung von A offen

- **`contract/db/policies.sql` ersetzt den alten Entwurf.**
  - Der Entwurf aus `20261107-2024_policy-versions.md` (`policy_version`, `title`, `raw_text`, `clauses`, `policy_diff`) wurde nie eingespielt.
  - Live läuft Lovables Tabelle: `id, version, name, file_name, content, created_at`. Leere Platzhalter v1/v2 dürfen genau einmal befüllt werden (Policy „fill policy placeholder“).
  - `backend/policy_apply.py` und `policy_runs.sql` (FK auf `policies.version`) nutzen schon dieses Schema.
  - `policy-parser.mjs` bleibt als Referenz liegen, wird aber nicht mehr gebraucht.
- **Neu: `contract/db/claim_field_changes.sql`.** Lovable hat die Tabelle und die Funktion `update_claim_fields()` angelegt: Feldänderungen an `claims.source_fields`, mit einem Log-Eintrag pro Feld. Die Engine läuft dabei nicht neu.
- **Neue Migration in `app/`:** `20261108040000_reset-policy-v2-placeholder.sql` leert `content` und `file_name` von v2, damit v2 in der Demo über die App hochgeladen werden kann. Hat v2 schon eine `policy_configs`-Zeile, akzeptiert Apply nur denselben Text, sonst kommt 409.
- **Offen, Frage an A:** Soll die App Korrekturen wieder in `overrides` schreiben, über die Reviewer-API oder `reviewer_save_correction`? Im Moment hält die App sie nur in der Browser-Sitzung.
