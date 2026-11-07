# Person C (Backend) und Besitz von contract/api.md

- Entschieden: Neue Person C besitzt `backend/` (API-Server, `backend/db/` inkl. Migrationen, `backend/tests/`) und `contract/api.md` (HTTP-API).
- Von A wandert nichts ab: `engine/` und `eval/` bleiben A; C ruft die Engine als Bibliothek bzw. per Batch-Command auf.
- Von B wandert kein Ordner ab, aber Verantwortung: Speichern von Reviewer-Korrekturen und Audit-Historie macht C. `app/` (B) ist nur Frontend gegen `contract/api.md`.
- Übrige `contract/`-Dateien bleiben gemeinsam. Regeln für mehr als zwei Personen siehe `team/README.md` (ein Empfänger pro Nachricht, „alle“ nur bei contract).
- Grund: dritte Person im Team für das Backend.
- Informiert: B und C per Nachricht an alle. Entschieden von A.
