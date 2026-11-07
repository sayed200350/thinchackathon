# Gemeinsame Datenquelle für die Reviewer-API

Der Reviewer-Server nutzt das konfigurierte Supabase-Projekt für die Queue, Claims, Korrekturen und Policy-Vorschau. SQLite ist als expliziter Offline-Modus verfügbar. Korrekturen prüfen die Revision im selben Datenbankvorgang wie das Speichern. Bestehende Korrekturen bleiben erhalten. Rafik wurde vorab über die Ergänzung zum Datenbankvertrag informiert.
