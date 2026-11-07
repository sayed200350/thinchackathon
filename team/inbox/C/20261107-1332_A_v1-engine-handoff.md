Von: A
An: C
Typ: handoff
Betreff: v1-Engine zur Backend-Anbindung

Import: from engine import decide; decide(claim, policy_version="v1") liefert das gemeinsame JSON aus einem CSV-/API-Dict.
Probe ab Repo-Root: python3 -m engine decide data/taktile/labelled_development_cases.csv DEV-001
Erwartung: routine_processing und v1.3, exakt wie contract/example-result-DEV-001.json.
Einzelheiten zu fehlenden Fakten, Eingaben und v2-Verfügbarkeit in engine/README.md.

Antwort erwartet: nein
