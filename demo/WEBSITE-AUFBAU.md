# Aufbau der Reviewer-App (Retakt)

Stand: 2026-11-08. Code in `app/` (Lovable, TanStack Start + React + Tailwind/shadcn), Daten aus Supabase.

## Seiten

| Route | Name | Inhalt |
|---|---|---|
| `/` | Landing | Marketing-Seite „Retakt“: Hero mit animiertem Replay (v1 vs. v2), Abschnitt „Second look“, Impact-Rechner (Volumen, Minuten, Stundensatz). |
| `/queue` | Overview | Nur **offene** Claims. Filter-Buttons pro Entscheidung (All, fast_track, standard_review, …). Tabelle mit Claim, Entscheidung (+ „Overridden“), Regel, Betrag. Rechts die Detailansicht. KPI-Chip zeigt die Anzahl geschlossener Claims. |
| `/update` | Policy Update | Vergleich v1 gegen die gewählte Version: KPIs, Entscheidungen unter v1, Heatmap v1 × v2, „Changed claims per rule“ (echte Regeln 1–3 + Missing data), Liste geänderter Claims, „Is it correct?“, Manual Review vs. Retakt, Audit-Trail der Overrides. |
| `/history` | History | Alle **geschlossenen** Claims, schreibgeschützt, Badges grau. Rechts dieselbe Detailansicht, ohne Korrektur. |

## Rahmen (`components/app-shell.tsx`)

- **Seitenleiste:** Overview, Policy Update, History.
- **Kopfleiste:**
  - Umschalter Testdaten/Live
  - Auswahl „Policy Version“ und Button „Change policy“
- **Upload-Leiste** für neue Policies (`policy-upload-bar.tsx`) oben auf der Seite Policy Update.

## Bausteine

- `claim-detail-panel.tsx`: Detailansicht eines Claims mit Entscheidung, Begründung, Fakten, Feld-Editor (`claim-fields-editor.tsx`), Override-Formular und Override-Historie. Bei geschlossenen Claims ist alles gesperrt.
- `decision-badge.tsx`: farbiges Badge pro Entscheidung, `muted` für geschlossene Claims.

## Daten (`src/lib/`)

| Datei | Aufgabe |
|---|---|
| `policy-store.tsx` | Globaler Zustand: Datenquelle, Policy-Version, ausgewählter Claim, Overrides (nur in der Session, nicht in der DB). |
| `live-claims.ts` | Liest `claims` + `decisions` aus Supabase und baut daraus die Claims (v1 und gewählte Version). `useClaimSource()` liefert je nach Umschalter Live- oder Testdaten. |
| `policy-data.ts` | Typen und Testdaten. |
| `policies.ts` | Tabelle `policies`: Liste, Upload, „Apply“ über das Backend (`POST /api/policies/{v}/apply`), letzter Lauf aus `policy_runs`. |
| `policy-file.ts` | Liest hochgeladene Policies im Browser: .docx, .pdf (pdf.js), Text. |
| `db-impact.ts` | Fehlerquote und Automatisierungsgrad pro Version aus `decisions` + `validation_results`. |

## Ablauf Policy-Wechsel

1. Policy-Datei hochladen. Der Text landet in `policies`.
2. „Change policy“ bzw. „Apply“ ruft das Python-Backend auf (Standard `http://127.0.0.1:8765`, änderbar über `VITE_REVIEWER_API_URL`).
3. Das Backend bewertet alle offenen Claims neu, schreibt `decisions` für die neue Version und einen Eintrag in `policy_runs`.
4. Overview und Policy Update zeigen danach die Unterschiede. Geschlossene Claims behalten ihre v1-Entscheidung.

> Hinweis: Die Apply-Anbindung (Schritte 2–3) liegt in `app/` als lokale, noch nicht committete Änderung.
