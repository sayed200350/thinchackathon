# Hosted demo database

Policy Replay runs in the free **Thinc** organization, project `bdbvfcfmlhpfefdtrbkd`. Sayed owns the schema, engine imports and evaluation data. The [reviewer API](../api.md) reads this project and writes corrections using its publishable key. Rafik connects the Lovable UI to the same database.

- [Supabase project dashboard](https://supabase.com/dashboard/project/bdbvfcfmlhpfefdtrbkd)
- [Hosted Table Editor](https://supabase.com/dashboard/project/bdbvfcfmlhpfefdtrbkd/editor)
- **Project URL:** `https://bdbvfcfmlhpfefdtrbkd.supabase.co`
- **Browser key:** In the project overview, choose **Copy project URL and API keys → Copy Publishable key**. Use the existing `sb_publishable_…` key.

## Connect Lovable

Set `VITE_SUPABASE_URL` to the project URL and `VITE_SUPABASE_PUBLISHABLE_KEY` to the publishable key (or use the names already consumed by the frontend’s Supabase client). Only the publishable key belongs in the browser. Sayed’s ignored local `.env` stores these values under the shared repo names `SUPABASE_URL` and `SUPABASE_ANON_KEY`.

| Screen | Read or write |
| --- | --- |
| Claims queue | Read `v_compare`, ordered by `case_id`. Until v2 arrives, the v2 decision and open-case recheck flag are null. Closed cases retain a false recheck flag. |
| Case detail | Read `claims` by case ID for the summary and raw CSV fields. Read `decisions` by case ID and policy version for the normalized evidence, recommendation, rule ID, original policy clause and explanation. |
| Reviewer correction | Call the [reviewer API](../api.md) with the last seen revision. Its Supabase function `reviewer_save_correction` checks the revision and saves the audit entry in one transaction. Existing Lovable inserts into `overrides` also receive a revision. Direct inserts only use the seven writable columns below and can use `request_id` to identify a retry. |
| Audit history | Read `overrides` by case ID, ordered by `created_at` and `id`. Reload `decisions` to show the original alongside the reviewer’s correction. |
| Evaluation and business case | Read `v_error_rate`, `v_kpis`, `v_rule_impact`, `v_transition` and `v_change_check`. The team can enter business assumptions in `business_metrics` through the dashboard. |

The browser roles can read the fictional demo data and append reviewer actions. The writable columns are `case_id`, `policy_version`, `original_recommendation`, `corrected_recommendation`, `reason`, `reviewer` and `request_id`. Row-level security checks the original decision, the open status and the target route. The database supplies the audit ID, timestamp and revision. Reviewer names in this hackathon demo are self-reported.

## Reproduce the setup

1. Run [schema.sql](schema.sql), then [reviewer_corrections.sql](reviewer_corrections.sql) in the Supabase SQL Editor. The second script preserves existing audit entries, assigns revisions, and installs the atomic correction function.
2. From the repo root, run `python3 -m backend.supabase_seed > /tmp/policy-replay-seed.sql`. Run its contents in the SQL Editor. The seed inserts 26 official fictional claims, their 26 v1 engine decisions and the 14 supplied development labels. It checks existing snapshots and rolls back on conflicting data.
3. Run the [fixture and grants test](../../backend/supabase_smoke.sql) and [shared correction test](../../backend/supabase_correction_smoke.sql) in the SQL Editor. The latter inserts a temporary claim, exercises both write paths, checks idempotent retries and stale revisions, then rolls back its test records.
4. With a publishable key in your shell, verify frontend access through the Data API:

   ```sh
   curl -fsS -H "apikey: ${SUPABASE_ANON_KEY}" \
     'https://bdbvfcfmlhpfefdtrbkd.supabase.co/rest/v1/v_compare?case_id=eq.DEV-001&select=case_id,recommendation_v1,recommendation_v2,needs_recheck'
   ```

The hosted setup was checked on 7 November 2026. The browser-role test returned 26 decisions, 14 matching development labels and two closed cases. Readback through the Data API confirmed 24 open cases and zero saved overrides immediately after setup. No v2 expectations have been imported. Sayed maintains the validation labels after the official update, using independent expected outcomes reviewed with Rafik.
