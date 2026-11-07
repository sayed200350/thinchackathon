# Hosted demo database

Policy Replay runs in the free **Thinc** organization, project `bdbvfcfmlhpfefdtrbkd`. Sayed owns the schema, engine imports and evaluation data. The [reviewer API](../api.md) reads this project and writes corrections using its publishable key. Rafik connects the Lovable UI to the same database.

- [Supabase project dashboard](https://supabase.com/dashboard/project/bdbvfcfmlhpfefdtrbkd)
- [Hosted Table Editor](https://supabase.com/dashboard/project/bdbvfcfmlhpfefdtrbkd/editor)
- **Project URL** · `https://bdbvfcfmlhpfefdtrbkd.supabase.co`
- **Browser key** · In the project overview, choose **Copy project URL and API keys → Copy Publishable key**. Use the existing `sb_publishable_…` key.

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

For claimant intake, run [claim_intake.sql](claim_intake.sql). It creates two private tables and a submit-only function for the app. Run the [intake smoke test](../../backend/supabase_intake_smoke.sql) to verify attachment bytes, private access, retry handling and rollback. The backend stores original document bytes alongside the submission.

Apply [intake_links.sql](intake_links.sql) after the intake schema to enable saved drafts and outstanding uploads. Run the [private-link smoke test](../../backend/supabase_intake_links_smoke.sql). A draft is associated with the hash of a claimant-generated secret. On submission the draft is cleared, and the link opens receipt information. Existing claim references and earlier submissions do not grant draft access.

1. Run [schema.sql](schema.sql), then [reviewer_corrections.sql](reviewer_corrections.sql) in the Supabase SQL Editor. The second script preserves existing audit entries, assigns revisions, and installs the atomic correction function.
2. From the repo root, run `python3 -m backend.supabase_seed > /tmp/policy-replay-seed.sql`. Run its contents in the SQL Editor. The seed inserts 26 official fictional claims, their 26 v1 engine decisions and the 14 supplied development labels. It checks existing snapshots and rolls back on conflicting data.
3. Run the [fixture and grants test](../../backend/supabase_smoke.sql) and [shared correction test](../../backend/supabase_correction_smoke.sql) in the SQL Editor. The latter inserts a temporary claim, exercises both write paths, checks idempotent retries and stale revisions, then rolls back its test records.
4. With a publishable key in your shell, verify frontend access through the Data API:

   ```sh
   curl -fsS -H "apikey: ${SUPABASE_ANON_KEY}" \
     'https://bdbvfcfmlhpfefdtrbkd.supabase.co/rest/v1/v_compare?case_id=eq.DEV-001&select=case_id,recommendation_v1,recommendation_v2,needs_recheck'
   ```

The hosted setup was checked on 7 November 2026. The browser-role test returned 26 decisions, 14 matching development labels and two closed cases. Readback through the Data API confirmed 24 open cases and zero saved overrides immediately after setup. No v2 expectations have been imported. Sayed maintains the validation labels after the official update, using independent expected outcomes reviewed with Rafik.

## Install private evidence storage

The evidence build adds quote version history, original photo dates, claimant explanations and translation choices. The browser continues to use the Python intake API. The publishable Supabase key alone grants no access to these private tables or submitted files.

1. Verify that [claim_intake.sql](claim_intake.sql) and [intake_links.sql](intake_links.sql) have been applied to the target database. For an existing Thinc installation, keep its seed data, submissions and private links. The evidence migration is a separate transaction.
2. Run the setup command from the repository root on the backend host, or with the same exported `CLAIM_EVIDENCE_SERVICE_KEY` the deployed server will use.

   ```sh
   python3 -m backend.evidence_setup --sql-output /tmp/thinc-evidence.sql
   ```

   With no exported credentials, the command creates or reuses two private files in ignored `backend/.local/`. The `claim_evidence_service_key` file is for the Python service. The `claim_reviewer_key` file is for authorized staff opening a submitted case. Alternatively supply `CLAIM_EVIDENCE_SERVICE_KEY` and `CLAIM_REVIEWER_KEY` as persistent server secrets of at least 32 characters each. The setup command reads exported environment variables. The HTTP service also reads its configured `.env`. Use the same evidence service credential in both processes. Keep the original credential available across restarts and across server instances.

3. Inspect the generated `/tmp/thinc-evidence.sql` and run that generated copy in the target project’s SQL Editor. Its source is [claim_evidence.sql](claim_evidence.sql). Generation replaces `__SERVICE_KEY_SHA256__` with the SHA-256 verifier. The SQL creates private evidence tables with row-level security, adjusts the allowable file sizes and positions, and installs the credential-checked `claim_evidence_io` function. It preserves original document rows. A repeated migration with a different verifier raises an error and rolls back.
4. In the target project’s SQL Editor, run [claim_evidence_checks.sql](claim_evidence_checks.sql). It temporarily uses a test verifier inside one transaction, checks that the browser role cannot read private tables or use the wrong credential, then submits, appends, retries, reopens, and retrieves both original byte sequences. The script rolls back all changes and prints a pass message.
5. On a **disposable PostgreSQL database** with the Supabase roles and all three intake migrations installed, run the parity test. The test connects using `CLAIM_TEST_PG_DSN`, impersonates `anon`, and exercises the real SQL function using the matching exported `CLAIM_EVIDENCE_SERVICE_KEY`. It creates a synthetic claim and two quote versions.

   ```sh
   python3 -m unittest backend.tests.test_evidence_postgres -v
   ```

6. Start the application against the intended project with `python3 -m backend --store supabase`. Verify with a fictional claim that the private receipt survives reopening, staff can download both PDF versions, and an incorrect reviewer key returns 403. Use only fictional data for the rehearsal.

On 7 November 2026, Thinc applied this migration and passed the rollback-only SQL check under the anonymous browser role. The test rows were rolled back.

For projects already running the evidence schema, apply [claim_image_sizes.sql](claim_image_sizes.sql) to enable larger photographed reports and quotes. Fresh installations include this limit. The enhanced claimant path accepts four initial attachments and preserves every original JPEG or PNG up to 12 MiB and each PDF up to 2 MiB. A claim can hold up to 40 files including later paperwork. Submitted links return receipt details and next-action guidance. Staff retrieve original attachments using a reference and the reviewer key. The project URL and publishable key may be used by the Lovable frontend. Keep the evidence service credential on the backend. [HTTP contract](../api.md)

## Install the insurer inbox

After the private evidence migration, apply [staff_corrections.sql](staff_corrections.sql), then [staff_inbox.sql](staff_inbox.sql). Both reuse the installed service verifier. The migrations add private, audited decisions and a paginated read function over existing submissions. Direct browser access to the underlying tables remains restricted. Enable the new HTTP backend alongside these migrations.

Start the dedicated staff gateway with `python3 -m backend.staff_public --port 8774 --upstream http://127.0.0.1:8766` and expose that port through HTTPS for the insurer's server. The claimant and garage gateways have their own allowlists. For the full request and response fields see the [insurer HTTP contract](../api.md#insurer-inbox-originals-and-corrections).

## Find a submitted claim and its documents

As an authorized project member, open the [Table Editor](https://supabase.com/dashboard/project/bdbvfcfmlhpfefdtrbkd/editor), select the `claim_intake_private` schema, and filter `submissions` by the claimant’s `reference`. Filter `documents` by the same reference to find the original filename, document category, position and file contents. Claimant details and attachments are accessible to database staff. The publishable key can submit a packet and receive its receipt.

With an authorized PostgreSQL connection in your environment, this example saves the first attachment on your computer. Supply its actual reference and use the filename shown in the table.

```sh
psql -XqAt -v ON_ERROR_STOP=1 -v ref='CLM-REPLACE-WITH-REFERENCE' <<'SQL' | xxd -r -p > attachment.pdf
select encode(content, 'hex') from claim_intake_private.documents
where reference = :'ref' and position = 1;
SQL
```
