Von: A
An: B
Typ: handoff
Betreff: Supabase ist live für Lovable

Projekt-URL: https://bdbvfcfmlhpfefdtrbkd.supabase.co · Publishable key im Projekt-Dashboard. Anbindung und Beispielabfrage in contract/db/README.md.
Queue: v_compare. Detail: claims (Rohfelder) + decisions (Belege, policy_clause). Speichern: overrides mit eindeutiger request_id; ursprüngliche Entscheidung bleibt erhalten.
Über die Data API bestätigt: 26 Claims und v1-Entscheidungen, 14 Labels, 24 offen, 2 geschlossen. Browser-Korrektur und erneutes Lesen im SQL-Test bestätigt, dann zurückgerollt.
SQLite bleibt lokal. Sayed lädt die Engine-Daten; nach v2 prüfen wir die Erwartungen gemeinsam. Bis dahin bleiben v2-Werte ausstehend.

Antwort erwartet: nein
