---
von: B
an: A
typ: handoff
---
Ich habe in deinem Backend Anthropic als dritten AI-Provider ergänzt (Rafik wollte Anthropic-Keys auf der Settings-Seite). `AI_PROVIDER=anthropic` funktioniert jetzt für Policy-Interpretation (`AnthropicInterpreter` in `ai_service.py`, Structured Output, Timeout mindestens 90 s) und den Reviewer-Chat (`_claude_json` in `chat_providers.py`, `provider_name` meldet "Claude"). `POST /api/settings/ai` erkennt den Provider am Key (`sk-ant-` → anthropic, `AIza`/`AQ.` → gemini) und setzt `AI_PROVIDER`/`AI_BASE_URL`/`AI_MODEL` mit. Doku-Satz in `contract/api.md` ergänzt. Tests: `backend/tests/test_ai_service_anthropic.py`, neue Fälle in `test_settings_api.py` und `test_chat_providers.py`; ein alter Test (`test_disabled_provider_is_refused`) nutzt jetzt einen Key ohne bekanntes Format, weil ein Gemini-Key AI jetzt einschaltet. Ein echter Anthropic-Aufruf ist mangels Key ungetestet. Bitte kurz drüberschauen, ob das für dich passt.
