# Contract (gemeinsam, A + B)

Gemeinsame Schnittstellen zwischen Engine (A) und App (B). **Nie ohne Nachricht an die andere Person ändern**; jede Änderung bekommt eine Datei in `team/decisions/`.

- `decision-result.md` — Format eines Einzelergebnisses (Engine → App)
- `example-result-DEV-001.json` — vereinbartes Beispielergebnis
- `batch-output.md` — Spalten der Batch-CSV für die Jury

Eingabeformat: die offiziellen Taktile-CSVs in `data/taktile/` (Spalten siehe Header von `labelled_development_cases.csv`; die Spalte `expected_v1` gibt es nur in den gelabelten Fällen).
