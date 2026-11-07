# Entscheidungsergebnis (Entwurf v0)

Ein Ergebnis pro Fall und Policy-Version, JSON:

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `case_id` | string | z. B. `DEV-001` |
| `case_status` | `open` \| `closed` | aus der Eingabe-CSV |
| `policy_version` | string | `v1`, `v2`, … |
| `recommendation` | string | z. B. `routine_processing`, `request_information`, … (Werte laut Policy) |
| `matched_rule` | string | ID/Name der entscheidenden Regel bzw. Klausel |
| `supporting_facts` | object | die entscheidenden Felder aus der CSV mit Werten |
| `explanation` | string | ein Satz für Reviewer |

Entwurf, A darf bei der Implementierung präzisieren (dann Nachricht + Decision).
