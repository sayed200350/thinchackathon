# Session-Kontext für B (Rafik) — Stand 2026-11-08

Zweck: Eine neue Claude-Session soll sofort wissen, wo das Projekt steht. Ergänzt `CLAUDE.md`, `team/README.md`, `team/areas.md`. Bei Widerspruch gelten die Dateien im Repo; prüfe Angaben hier gegen den Code, bevor du dich darauf verlässt.

## 1. Projekt in einem Absatz
**Policy Replay / Retakt** (Taktile-Track, thinc! hack MUC, 7.–8. Nov 2026). Kfz-Schadenfälle werden von einer deterministischen Regel-Engine in `routine_processing`, `request_information` oder `human_review` eingeordnet. Ändert sich die Policy (v1 → v2), sollen Reviewer sehen, **welche offenen Claims einen zweiten Blick brauchen und warum**. Geschlossene Claims behalten ihre v1-Entscheidung (`needs_recheck = False`). Persona für Pitch/Demo: Lena, Schadenprüferin. Bewertung: Entscheidungsqualität 30 %, Umgang mit Unsicherheit/Änderung 15 %, **Reviewer-Erlebnis 20 %**, Messung 10 %, **Business Case 25 %** (die letzten beiden fetten Punkte sind Rafiks Teil, zusammen 45 %). Jury testet live **eine Korrektur** (Korrektur, Begründung, Reviewer und Policy-Version müssen gespeichert sein) und lässt die Batch-CSV auf versteckten Fällen laufen.

## 2. Rollen und Regeln (Kurzfassung, Details in `team/`)
- **A = Sayed**: `engine/`, `eval/`, `backend/`, `contract/api.md`. **B = Rafik (ich)**: `app/` (Lovable), `business-case/`, `demo/`. **C (Mo) ist aus der Aufteilung raus**; Mos gehärtete Engine ist in `engine/` gemergt.
- `TEAM_PERSON=B` (`.claude/settings.local.json`). Nur der Lead committet/pusht, Format `[B/B-lead] …`, Trailer laut Session-Reminder. Nachrichten nur per `team/inbox/<EMPFÄNGER>/`, ein Empfänger pro Nachricht; Änderungen in `contract/` brauchen Nachricht + Datei in `team/decisions/`.
- Sync: `git pull --rebase --autostash`, dann `git submodule update --init`, Inbox lesen, `team/status/B.md` aktualisieren (steht noch auf dem Stand von 13:48), pushen.
- **`app/` ist das Submodule `rafik-324/thinc-hack` (Lovable).** Änderungen nur über Lovable-Prompts. Ausnahmen: Landing (`src/routes/index.tsx`, `src/components/ascii-columns.tsx`) darf Claude ändern; sonst nur, wenn Rafik es ausdrücklich verlangt, und dann in `app/` erst nach seiner Bestätigung committen/pushen (siehe Memory `app-only-landing`). Vor einem Push von `app/` fetchen. Im Hauptrepo wird nur der **Submodule-Zeiger** committet; die lokale Änderung an `ascii-columns.tsx` im Submodul bleibt lokal.
- Rafik schreibt per Spracheingabe (verhört sich manchmal), meist Deutsch. Er will kurze, ehrliche Antworten, und dass Dinge **auf localhost laufen**.

## 3. Repo-Karte
| Pfad | Inhalt |
| --- | --- |
| `data/taktile/` | `labelled_development_cases.csv` (14), `unlabelled_practice_cases.csv` (12), `policy_v1.docx` |
| `Usecase/` | Taktile-Brief (PDF), Material-ZIP |
| `engine/` | Hardened Engine (A/Mo): `python3 -m engine decide|batch|compare|validate-v1`, `engine/configs/policy_v1.json`, `docx_policy.py` (Word → Regeln), Registry, Audit-JSONL. **v2 noch nicht offiziell eingebaut** |
| `eval/` | Qualitätsreports (`v1-development.json`: 14/14, 0 falsche Routine, 0 unnötige Eskalation) |
| `backend/` | Reviewer-/Claimant-API (Port 8765), HTML-Seiten, Workbench (`backend/web/`, Port 8767) |
| `contract/` | `decision-result.md`, `example-result-DEV-001.json`, `batch-output.md`, `api.md`, `db/*.sql` |
| `app/` | Lovable-App (Submodule), Vite + TanStack Start + Supabase |
| `demo/chat-redesign/` | Mein Mobile-Redesign (siehe 6) |
| `demo/lovable-prompts/` | Fertige Lovable-Prompts (History-Seite; Update-Seite ist teilweise überholt, siehe 5) |
| `demo/design-system.md` | Taktile-Designwerte; `demo/landing*` ASCII-Landing |
| `business-case/` | **leer** |

Jury-CSV-Spalten (exakt): `case_id,recommendation_v1,recommendation_v2,needs_recheck,rule_v1,rule_v2,explanation`.

## 4. Policy v1 (aus `policy_v1.docx`)
Reihenfolge: (1) `human_review`, wenn Police zum Schadentag nicht aktiv, `claim_type` ≠ `motor_own_damage`, `injury_reported`/`liability_disputed`/`duplicate_flag`/`evidence_conflict` true oder `quote_eur` > 1500. (2) sonst `request_information`, wenn `incident_report_present` oder `itemized_quote_present` false. (3) sonst `routine_processing`. Leere Felder = fehlende Fakten, nie erfinden (`v1.missing`). Regel-IDs der Engine: `v1.1`, `v1.2`, `v1.3`, `v1.missing`. DEV-001 = Parkschaden 650 € → routine (Referenzfall).

## 5. Supabase (eigenes Projekt, **nicht** Lovable Cloud)
- Projekt-Ref `bdbvfcfmlhpfefdtrbkd`, URL `https://bdbvfcfmlhpfefdtrbkd.supabase.co`. Browser nutzt nur den publishable/anon Key (`app/.env`, gitignored). Service-Role-Key nie ins Frontend/Repo.
- Live-Tabellen: `claims` (case_id, case_status, claim_summary, source_fields jsonb), `decisions` (PK case_id + policy_version; recommendation, matched_rule, supporting_facts, explanation, policy_clause), `overrides` (Audit, nur offene Claims, mit revision), `validation_results`, `business_metrics`, `claim_field_changes` (Lovable-Migration, Feld-Edits; 2 Testzeilen von „Test“ auf DEV-001 `quote_eur` 650↔651 sind drin, vor der Demo löschen), `policies`. Views: `v_compare`, `v_transition`, `v_rule_impact`, `v_change_check`, `v_error_rate`, `v_kpis`. Funktionen: `reviewer_save_correction`, `update_claim_fields`, Intake-/Evidence-Funktionen (A).
- **⚠ `policies` gibt es doppelt, und die Live-Tabelle ist die von Lovable**: `id uuid, version text UNIQUE, name, file_name, content text, created_at`, Platzhalter-Zeilen `v1`/`v2` (leer, einmalig befüllbar, danach unveränderlich). Meine `contract/db/policies.sql` (Spalten `policy_version`, `clauses` jsonb, `policy_diff()`) passt **nicht** dazu und **darf nicht ausgeführt werden**, ohne vorher zu entscheiden. Die zugehörige Decision `team/decisions/20261107-2024_policy-versions.md` und die Nachricht an A sind damit teilweise überholt. Offene Entscheidung: `policies.sql` anpassen (Klauseldiff auf `content` aufbauen) oder verwerfen/zurückziehen und A informieren.
- Die App liest jetzt echte Daten (`src/lib/live-claims.ts`, `policies.ts`, `db-impact.ts`, `claim-fields-editor.tsx`); Reste von Mock-Daten stehen noch in `policy-data.ts`.

## 6. App (Lovable) — Stand
Routen: `/` (ASCII-Landing), `/queue` (Claims), `/update` (ehemals Policy-Impact; Upload der Policy-Datei, Vergleich), `/history`. Name in der UI: **Retakt**. Design: dunkel, Punktraster, Glas-Karten, Pill-Topbar, Mono für Zahlen. Lokal: `cd app && npm run dev -- --host 127.0.0.1 --port 8081`. Bei Pull: `git -C app pull --ff-only --autostash` (Lovable pusht laufend; Zeiger im Hauptrepo nachziehen).

## 7. Backend-Seiten und mein Mobile-Redesign
Backend (A), Port 8765: `/` und `/chat` Schadenaufnahme (`intake.html`; Demo `/chat?demo=DEV-003`), `/reviewer` Reviewer-Chat (`chat.html`, `POST /api/chat`), `/reviewer/evidence` Quote-Evidence (`quote_review.html`, braucht Prüfschlüssel), `/garage` Werkstatt-Upload per Einmal-Link/QR. Start offline: `python3 -m backend --store sqlite --db /tmp/retakt-demo.sqlite3` (ohne `.env`, KI-Antworten laufen dann lokal/regelbasiert). A hat zusätzlich die Insurer-Workbench (`python3 -m backend.workbench_server --open`, Port 8767, Desktop).

**Mein Redesign** `demo/chat-redesign/` (Originale in `backend/` bleiben unberührt): `index.html` (Reviewer-Chat), `intake.html`, `garage.html`, `evidence.html`, gemeinsames `retakt.css`, `serve.py` (Proxy: liefert die Seiten unter denselben Adressen, leitet `/api/*` usw. ans Backend), `mobile.html` (Handy-Rahmen 390×844 mit Umschalter Report claim / Garage / Reviewer chat / Evidence und ASCII-Hintergrund). Start:
```sh
python3 -m backend --store sqlite --db /tmp/retakt-demo.sqlite3
python3 demo/chat-redesign/serve.py --port 8090
open http://127.0.0.1:8090/mobile.html
```
Wichtig: Die `<script>`-Blöcke der Seiten sind **byte-identisch** mit den Originalen (nur Markup/CSS neu). Ich konnte sie nie im Browser sehen (kein Chrome-Pfad für Screenshots); alles ist nur per Syntax-, ID-, Klassen- und `curl`-Prüfung verifiziert. In `intake.html` ist der Text unter der Überschrift per CSS ausgeblendet, weil das Skript im Demo-Modus hineinschreibt. ASCII-Hintergrund: Zeichenhelligkeit mittel (max 38 %, Wörter 15 %); eine Variante mit ASCII-Händen (Erschaffung Adams) wurde getestet und von Rafik verworfen. Übernahme ins Backend wäre Absprache mit A (`index.html` → `chat.html`, `evidence.html` → `quote_review.html`, `/retakt.css` ausliefern).

## 8. Offen / nächste Schritte (Priorität von oben)
1. **v2-Policy**: liegt als PDF in `~/Downloads/20261105_Taktile_thinc! Hackathon policyv2.pdf` (Dateiname mit Leerzeichen und `!` quoten). A baut v2 in die Engine, Rafik formuliert **unabhängig** Erwartungen (welche Fälle ändern sich) → `validation_results` (`expected_change`), Abgleich über `v_change_check`. Upload der App kann nur `.docx`/Text; PDF-Unterstützung prüfen.
2. **Business Case** (25 %): `business-case/` ist leer. Editierbares Modell: Triagekosten heute vs. mit System, Fehlerkosten (falsche Routine ≫ unnötige Eskalation) mit den gemessenen Fehlerraten v1/v2, Kosten einer Policy-Änderung heute vs. mit System, Netto-Nutzen, Payback. Annahmen offen legen, realistisch für mittelgroße europäische Kfz-Versicherer. Daten für die App: `business_metrics`.
3. **Demo-Skript** (5 Min, Ablauf in `README.md`): leichter Fall (DEV-001), unvollständiger (DEV-002), betroffener Fall nach v2, geschlossener Fall bleibt, **Juror korrigiert live**, Reload zeigt Audit, Vorher/Nachher-Qualität, Kosten-Annahme live ändern. A hat zusätzlich den €890-Werkstatt-Ablauf (`README.md#demo-the-890-bumper-claim`). Noch nichts geschrieben; `demo/` hat Entwürfe der Landing.
4. `team/status/B.md` aktualisieren; Nachrichten in `team/inbox/B/` (A: Supabase, Chat, Intake, Evidence, Garage, Bilder, Staff-Inbox; alle reine Info, nicht abgelegt) nach `done/` verschieben.
5. Entscheidung zur doppelten `policies`-Definition (siehe 5) und Antwort von A auf `20261107-2024_B_policy-versions.md` abwarten.
6. Vor der Demo: Testzeilen in `claim_field_changes` löschen, Overrides leer lassen, Ports prüfen (8081 App, 8765 Backend, 8090 Redesign-Proxy, 8767 Workbench).

## 9. Fallen
- Lovable pusht parallel: vor `git push` im Hauptrepo `git pull --rebase`; nie History in `app/` umschreiben.
- GitHub blockt die private E-Mail für `app/`-Pushes (noreply-Adresse laut Memory).
- Ältere Notizen im Repo (z. B. `team/README.md`) erwähnen noch Person C; maßgeblich ist `team/areas.md` in der aktuellen Fassung von A.
- Ein Hintergrundprozess `Python -m backend …` lässt sich nicht mit `pkill -f "python3 -m backend"` beenden (Prozessname `Python`); per Port (`lsof -ti tcp:8765`) beenden.
- Jury-Daten sind fiktiv; die Policy ist ausdrücklich erfunden.
