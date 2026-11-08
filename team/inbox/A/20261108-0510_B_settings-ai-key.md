---
von: B
an: A
typ: contract
---
Neuer Endpunkt in deinem Backend: `GET|POST /api/settings/ai` (`backend/settings_api.py`, eine Route in `__main__.py`, Doku in `contract/api.md`). Damit kann man in der App unter Settings den `AI_API_KEY` ändern. Er wird beim Provider geprüft, ist sofort aktiv und landet in `.env`. `ai_service.py` und `chat_providers.py` sind unverändert, sie lesen den Key ohnehin pro Aufruf aus der Umgebung. Details: team/decisions/20261108-0510_settings-ai-key.md.
