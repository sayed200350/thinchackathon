# Policy Replay

Taktile track · thinc! hack MUC · 7–8 November 2026

Policy Replay receives motor-insurance claims in a guided conversation. A claimant describes the incident, attaches evidence, checks their answers and receives a claim reference. Reviewers use a separate workspace to explore the fictional Taktile cases and replay policy decisions.

## Report a motor claim

Run `python3 -m backend` from the repository root with Python 3.9+ and open the [claim intake chat](http://127.0.0.1:8765/chat).

1. Start with a PDF or describe what happened. For the judges’ demo, download the [fictional accident report](http://127.0.0.1:8765/sample-accident-report.pdf) and import it on the opening screen.
2. Check the suggested answers against their filename and page. Correct one field, confirm the others, then answer the remaining questions. The claimant supplies the injury information.
3. Take a damage photo or choose an image on the phone. The document checklist shows which paperwork is still missing. A claimant can save a draft and reopen the private link on another device that can reach the same server.
4. Submit the claim. The receipt lists every received filename and the claim reference. Use the private link later to add an outstanding report or itemized quote.

The backend reads labelled fields from the first 12 text pages using Poppler’s `pdftotext`. For image-only PDFs it can try OCR on the first two pages using `pdftoppm` and Tesseract with English language data. On macOS, `brew install poppler tesseract` installs the readers. Claimants can attach a protected or unreadable file and enter the answers manually. Intake uses no model credentials. The local server listens on loopback. Cross-device links from a published app must point to its reachable HTTPS origin.

## Review the fictional demo cases

Open the [reviewer workspace](http://127.0.0.1:8765/reviewer).

1. Ask **“Why does DEV-002 need more information?”** The decision identifies the missing incident report under v1.2.
2. Ask **“What if we received the incident report?”** The simulator changes that one fact and returns routine processing under v1.3. Expand the evidence to read the policy clause.
3. Ask **“Show the recorded decision.”** The original still requests the incident report. **“Correct this decision”** opens a separate form where a reviewer can record a new route and reason.

For a live boundary test, ask about DEV-001, then try a €1,500 quote and a €1,501 quote. Only the second amount triggers human review.

To enable models for reviewer questions, set `JEV_API_KEY` and/or `OPENAI_API_KEY` in the server’s local `.env` and restart. Jev classifies the question. GPT selects verified statements for a claim explanation. The evidence panel identifies the source for each answer. [HTTP contract](contract/api.md)

## Hosted database for Lovable

The intake and reviewer API share the Thinc Supabase project. Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` (the publishable key) in the server’s ignored `.env`, then run `python3 -m backend --store supabase`. New claimant submissions and file contents go into private tables. The public demo queue contains fictional examples. [Database setup and staff access](contract/db/README.md)

For a rehearsal with a private SQLite copy, run `python3 -m backend --store sqlite`.

## Run the reviewer API

From the repository root, start the local service with Python 3.9 or newer:

```sh
python3 -m backend --ui-origin http://localhost:5173
```

Open [DEV-001](http://127.0.0.1:8765/api/claims/DEV-001) to read its original decision. Rafik can connect the reviewer screen using the [API contract and correction example](contract/api.md). The [engine guide](engine/README.md) covers the CSV command and [measured v1 results](eval/v1-development.json). Run all tests with `python3 -m unittest discover -v`.

## Start together

Read the [Taktile brief](Usecase/20261105_Taktile_thinc%21%20Hackathon%20Case%20Study.pdf) and unpack the [participant materials](Usecase/20261105_Taktile_thinc%21%20Hackathon%20Case%20Study%20Material.zip). The pack contains policy v1, 14 labelled development claims, and 12 unlabelled practice claims.

In the first 15 minutes, agree on one example result containing the case ID, open/closed status, recommendation, policy version, matched rule, and supporting facts. Use **DEV-001**. Its €650 parking scrape with complete paperwork goes to `routine_processing` under v1. Sayed can implement the engine and Rafik can build the screen against that example.

## Two-agent build plan

| Milestone | Sayed · Rules, CSV, evaluation & backend | Rafik · Reviewer app, business case & demo |
| --- | --- | --- |
| First working slice | Encode v1 in its specified order and read the official CSV format. Give Rafik a sample result, a command to reproduce it, and the API format for reading a decision and saving a reviewer correction. | Build the claim list and detail view. Show the decisive facts and clause. Build the correction form against Sayed’s API and display the original recommendation and audit history. |
| Before the Saturday 18:00 rule release | Persist reviewer corrections, reviewer identity, reason and policy version in the database alongside the original decision. Evaluate v1 against all 14 labels. Check the €1,500 boundary (DEV-010), a blank quote (DEV-013), and a known injury with a blank report field (DEV-014). | Connect the screen to Sayed’s API and verify that a saved correction survives refresh. Build a cost calculator with editable assumptions for claim volume, staff time, and costs of different errors. |
| When v2 arrives on Discord | Preserve v1 and implement the published change. Flag affected open claims. For closed claims, retain the v1 recommendation in v2 and set `needs_recheck` to `False`. | Independently work out which sample claims the new clause should affect. Compare with Sayed’s results and build **Preview policy change**, with old and new decisions, the changed clause, and the relevant fact. |
| Sunday handoff | Deliver the batch command and a quality report for each version. Include counts and denominators for correct routing, incorrect routine routing, and unnecessary human review. Break out changed cases. Own the final merge. | Use the measured error rates to show annual cost before and after, net benefit, payback, and the cost of applying v2. Own the demo and the judge’s live override. |

Work on separate branches, `codex/sayed-engine` and `codex/rafik-app`. At each handoff, share the pull request, one command or click path to try, and the expected result.

## Integration checks

- **Before 18:00:** Run DEV-001 from CSV to screen. Open DEV-002 and show why its missing incident report triggers `request_information`. Save a reviewer correction and reload it.
- **After v2:** Compare the engine with Rafik’s independent expectations. Check an affected open case and a closed case. Use the unlabelled practice CSV for a fresh-file run and labelled examples for accuracy measurements.
- **Before judging:** Rafik runs an unfamiliar CSV using Sayed’s instructions. Sayed acts as the judge and completes an override in Rafik’s UI without coaching.

The judges’ batch output must use these columns in this order:

```csv
case_id,recommendation_v1,recommendation_v2,needs_recheck,rule_v1,rule_v2,explanation
```

## Five-minute demo

1. **0:00–1:00 · Rafik** asks the chat why DEV-002 needs more information. Supply the missing incident report in a hypothetical, expand its clause and show the original decision.
2. **1:00–2:30 · Rafik and Sayed** preview the official policy change. Rafik opens an affected claim. Sayed explains why its route changed and shows a closed claim that retained its decision.
3. **2:30–3:30 · Judge** corrects a recommendation and enters a reason. Refresh the page and show the audit history.
4. **3:30–5:00 · Sayed and Rafik** show before-and-after quality, including changed cases. Rafik adjusts one cost assumption and closes on the effect on payback. Name the next test before rollout.

## Hackathon references

Case assignment is announced on Discord on Saturday at 13:30. The Taktile policy update is scheduled for 18:00 there. Jonathan, Senior Forward Deployed Engineer, is the on-site Taktile contact. The case uses hidden test claims. [Taktile brief on Drive](https://drive.google.com/file/d/1zUfKqMNmND-2Uz-qP3rJc4bHHLwuXHBW/view?usp=sharing) · [Participant pack on Drive](https://drive.google.com/file/d/1SUolqZMWaMn7FX2gravpVW67sAqIc3s5/view?usp=drive_link)

**NAP VC side challenge.** Across all three cases, the jury looks for an intuitive, polished user experience, an original idea built around the user, and a pitch that makes the value immediately clear.

**Other tracks.** Each case partner presents at the Saturday opening for about ten minutes.

- **Dash0.** [Challenge brief](Usecase/Dash0_Hackathon_Challenge.pdf) · [Perses](https://perses.dev) · [Alert thresholds](https://www.dash0.com/docs/dash0/monitoring/alerting/alerting-model#the-dollarthreshold-extension) · [Dashboard import](https://www.dash0.com/docs/api-reference/operations/post/api/import/dashboard) · [Check rule import](https://www.dash0.com/docs/api-reference/operations/post/api/import/check-rules) · [Starter repo](https://github.com/vimouzin/dash0-dashboard-migrator) · [Dash0 sign-in](https://accounts.dash0.com/sign-in) · [Datadog](https://www.datadoghq.com/) · [Datadog test assets](https://github.com/DataDog/integrations-core)
- **Reonic.** [Challenge brief](Usecase/Reonic_Hackathon_Challenge_final.pdf). The separately supplied project dataset is for the hackathon team’s local use.
