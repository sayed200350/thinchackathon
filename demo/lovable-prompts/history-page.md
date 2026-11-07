# Lovable-Prompt: History-Seite (Audit-Trail)

Voraussetzung: `claim_field_changes` existiert (ist angewendet). Für Policy-Versionen zusätzlich `contract/db/policies.sql` im Supabase SQL Editor ausführen.

```
Build the /history page (currently an empty placeholder) as the audit trail of the app. Use the connected Supabase client with the anon key. Do NOT create tables or migrations; only read.

Page title "History", subtitle "Every policy version, correction and data edit, newest first."

Top: a filter bar. Segmented control [All | Corrections | Field edits | Policy versions], a search box for case_id, and a text "N events".

Body: ONE chronological timeline (newest first), merged client-side from three sources, each event as a compact row (same Card/Badge style as the rest of the app, dense, mono timestamps, no large icons):

1) Corrections — table `overrides` (id, case_id, policy_version, original_recommendation, corrected_recommendation, reason, reviewer, created_at, revision).
   Row: badge "Correction", case_id (link to /queue?claim={case_id}), original recommendation badge → corrected recommendation badge, "by {reviewer} · {policy_version}", the reason as a muted second line.
2) Field edits — table `claim_field_changes` (case_id, field, old_value, new_value, editor, created_at).
   Row: badge "Data edit", case_id link, "{field}: {old_value} → {new_value}" (jsonb values rendered as plain text, null as "empty"), "by {editor}".
3) Policy versions — table `policies` (policy_version, title, source_filename, uploaded_by, created_at, clauses). Select only these columns, NOT raw_text.
   Row: badge "Policy {policy_version}", title, source_filename, "by {uploaded_by}", "{clauses.length} clauses", and a button "Compare with previous" that links to /update. If the table does not exist or the query fails, silently skip this source (do not break the page).

Recommendation badges reuse the existing DecisionBadge and the app's decision labels. Timestamps: local, format "07 Nov 2026, 14:32", relative time ("3 min ago") as a tooltip.
Loading: skeleton rows. Empty state: "No events yet. Corrections, data edits and new policy versions appear here." Error per source: small muted notice at the top ("Could not load policy versions"), the other sources still render.
Refetch when the tab regains focus. Limit each source to the latest 200 rows.

Do not change other pages, routes or the theme.
```
