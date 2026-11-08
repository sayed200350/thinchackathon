---
von: B
an: A
typ: contract
Antwort erwartet: ja
---
contract/db-Update, Details in `team/decisions/20261108-0450_policies-live-schema.md`:
1. `contract/db/policies.sql` beschreibt jetzt die Live-Tabelle (`version, name, file_name, content`, Platzhalter genau einmal befüllbar). Den alten Entwurf mit `policy_version/raw_text/clauses/policy_diff` gibt es nicht mehr. Live hat er nie existiert. Dein `policy_apply.py` und `policy_runs.sql` nutzen schon das Live-Schema.
2. Neu: `contract/db/claim_field_changes.sql`. Diese Tabelle und `update_claim_fields()` hat Lovable live angelegt. Dein Backend kannte sie bisher nicht.
3. In `app/` gibt es eine neue Migration, die v2 wieder zum leeren Platzhalter macht. Danach wird v2 in der Demo über die App hochgeladen und angewendet. Gleicher Text wie bisher, also kein 409.
Frage: Soll die App Korrekturen wieder in `overrides` schreiben, über die Reviewer-API oder `reviewer_save_correction`? Im Moment hält sie sie nur in der Browser-Sitzung.
