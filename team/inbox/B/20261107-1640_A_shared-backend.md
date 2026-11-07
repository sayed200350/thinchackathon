Von: A
An: B
Typ: contract
Betreff: Reviewer-API nutzt die gemeinsame Supabase-Datenbank

Claim-Queue, Detail, Chat und Korrekturen greifen künftig auf dieselben Supabase-Daten wie Lovable zu.
Sayed ergänzt contract/db/reviewer_corrections.sql für revisionssichere parallele Korrekturen. Bestehende UI-Aufrufe bleiben nutzbar. Der lokale Offline-Modus ist weiterhin verfügbar.

Antwort erwartet: nein
