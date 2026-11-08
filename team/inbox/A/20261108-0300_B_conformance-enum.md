---
von: B
an: A
typ: frage
Antwort erwartet: nein
---
Test des KI-Teils (Gemini via ai_service/policy_apply, 5 Fälle): Schwellwertänderung OK; unveränderter Text, Prompt-Injection und vager Text werden korrekt abgelehnt. Ein Befund in deinem Bereich (`engine/conformance.py`, `variants()`): eine korrekte neue Regel wie `repair_type ne "standard" → human_review` scheitert an "2 generated boundary/precedence checks failed". Ursache: für `ne`/`eq` auf Feldern mit geschlossener Enumeration (repair_type) erzeugt der Generator den Wert `synthetic_nonmatching_category`; die Engine setzt diesen Wert auf UNKNOWN, dadurch greift `request_information` statt `human_review` und der review_precedence-Check schlägt fehl. Vorschlag: für repair_type einen echten anderen Enum-Wert (z. B. `ev_high_voltage_battery`) als "other" nehmen. Ich habe engine/ nicht angefasst.
Außerdem in backend/ (klein, mit Test): `SupabaseStore.preview()` liefert zusätzlich `latest_run` aus `policy_runs`, und der Chat nennt damit nach dem Anwenden von v2 echte Zahlen statt "pending". `status`/`changes` bleiben unverändert.
