# Settings-Seite: AI-Key zur Laufzeit ändern

- Datum: 2026-11-08, von B
- Neu: `backend/settings_api.py`, Route `GET|POST /api/settings/ai` in `backend/__main__.py`, Tests `backend/tests/test_settings_api.py`, Abschnitt in `contract/api.md`.
- Der Key wird beim Provider geprüft (Modellliste, kein Generierungs-Quota), danach in `os.environ` gesetzt (Policy-Apply und Chat lesen `AI_API_KEY` pro Aufruf) und in `.env` geschrieben.
- Sicherheit: Der Server lauscht nur auf 127.0.0.1. JSON-POSTs brauchen den CORS-Preflight, den nur `--ui-origin` besteht. GET liefert nie den Key, nur die letzten vier Zeichen.
- App: Seite `/settings` mit Reiter „API key“, Zahnrad unten in der Sidebar.
