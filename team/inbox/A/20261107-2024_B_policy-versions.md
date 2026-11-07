Von: B
An: A
Typ: contract
Betreff: Neue Tabelle policies + policy_diff() für die Update-Seite (nur additiv)

Neu: contract/db/policies.sql (Tabelle policies, Funktion policy_diff, Seed v1 aus policy_v1.docx) und contract/db/policy-parser.mjs (Referenz-Parser Text -> Klauseln). Decision: team/decisions/*_policy-versions.md. Bestehende Tabellen/Views unverändert.
Die Lovable-App bekommt eine Seite /update: neue Policy hochladen, in policies speichern (anon Insert, keine Updates), Klauselvergleich v1 gegen v2 über policy_diff().
Bitte: (1) Zustimmung oder Einwände zum Schema, ggf. selbst im SQL Editor ausführen. (2) Kannst du die Klausel-IDs (rule-1, ...) für decisions.policy_clause und rule_v2 nutzen, damit „Changed because“ auf dieselbe Klausel zeigt? (3) Ab 18:00 legst du v2-Entscheidungen in decisions ab, dann zeigt die App die betroffenen Claims. Bis dahin vergleicht die Seite nur Texte.

Antwort erwartet: ja
