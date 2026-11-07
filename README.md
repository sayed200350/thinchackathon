# Policy Replay

Taktile track · thinc! hack MUC · 7–8 November 2026

Policy Replay receives motor-insurance claims in a guided conversation. A claimant describes the incident, attaches evidence, checks their answers and receives a claim reference. Reviewers use a separate workspace to explore the fictional Taktile cases and replay policy decisions.

## Demo the €890 bumper claim

A garage sends a quote for €890. The chatbot reads the total and page, spots the missing breakdown, and gives the driver a request to copy to the garage. The driver submits once. Each new quote then updates the same claim, and the reviewer can show exactly which evidence changed its route.

On macOS, run these commands from the repository root to install the PDF reader and start a local rehearsal.

```sh
brew install poppler
python3 -m backend --store sqlite
```

1. Open the [fictional DEV-003 claim](http://127.0.0.1:8765/chat?demo=DEV-003), choose **Start sample claim**, and expand **Download sample garage quotes**. The fictional claim already has an incident report. The ordinary [claim intake](http://127.0.0.1:8765/chat) starts with the claimant’s own facts.
2. Attach **€890 total only** as an **Itemized repair quote**. Show the page citation and choose **Copy request for garage**. Select **Review claim → Submit claim**. The receipt names the garage as the next actor. Keep the private follow-up link.
3. Choose **Open reviewer evidence** on the receipt. Use the reference and the reviewer key supplied by the backend operator. For a default local rehearsal, the key is in the ignored file `backend/.local/claim_reviewer_key`. Show version 1 and the engine’s `request_information` decision under rule `v1.2`.
4. Open the private follow-up link, select **Add documents to this claim**, attach **€890 itemized**, and choose **Send additional documents**. Reopen the reference in the reviewer view. The amount stayed €890, the priced work now reconciles, and version 2 routes to `routine_processing` under `v1.3`. Both originals are available to the reviewer.
5. Hand the judge the **€1,800 itemized** and **Unreadable total** PDFs. Ask them to pick one and add it through the same private link. The €1,800 quote triggers `human_review` under `v1.1`. An unreadable total stays unknown and requests information under `v1.missing`. The earlier decisions remain in the history.

These routes are triage recommendations. The demo uses DEV-003’s fictional policy and incident facts. Ordinary submissions keep unavailable facts unknown. To rehearse a file without submitting a claim, use **Upload garage quote** in the [reviewer’s fictional replay](http://127.0.0.1:8765/reviewer/evidence).

## Let a judge send the revised quote from their phone

1. Configure a phone-accessible garage gateway using the steps below. File the fictional €890 total-only claim, then click **Request breakdown from garage** and **Enlarge QR code** on its receipt. Press Escape to return to the receipt.
2. Have a judge scan the QR code with their phone camera. Choose **Take a photo** to photograph a paper estimate, **Choose a file or gallery photo** for an existing image or PDF, or use a fictional example. The judge can preview and retake a photo before sending. Choose **Send quote**. The phone receives a confirmation.
3. The presenter’s receipt displays **Received from garage**. A photographed estimate goes to the claims team to read. With the example PDFs, the itemized €890 estimate takes the fictional case to routine processing and the €1,800 estimate takes it to human review. Open the saved claim in the reviewer to compare the original and revised estimates with their respective decisions.
4. Request a fresh link from the updated receipt for another judge. One link accepts one JPEG or PNG up to 12 MiB, or one PDF up to 2 MiB. Repeated scans after upload show the confirmation. A different quote arriving first closes the old link. Unused links expire after seven days.

### Start the phone gateway

From the repository root, install the QR and encryption dependencies in a virtual environment and run the garage gateway in the first terminal.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-garage.txt
.venv/bin/python -m backend.garage_public --port 8770 --upstream http://127.0.0.1:8766
```

In a second terminal, start a temporary HTTPS address pointed at **8770**, the garage-only port. On macOS, install the client once with `brew install cloudflared`.

```sh
cloudflared tunnel --url http://127.0.0.1:8770
```

In a third terminal, replace the example origin below with the HTTPS origin printed by the tunnel. Use `--store supabase` with the existing project configuration for shared storage.

```sh
.venv/bin/python -m backend --store sqlite --port 8766 --garage-public-origin https://YOUR-TUNNEL.trycloudflare.com
```

Open the [presenter chat](http://127.0.0.1:8766/chat?demo=DEV-003). Keep the Mac awake and all three processes running. When a temporary tunnel gets a new address, restart the API with that origin and generate a fresh QR from the receipt. For private Wi-Fi that allows communication between devices, start the gateway with `--bind 0.0.0.0` and configure the API origin as `http://<Mac-LAN-IP>:8770` instead of starting a tunnel. QR images are generated locally. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

## Other claimant journeys

- **Import a report.** From [claim intake](http://127.0.0.1:8765/chat) import the [sample accident report](http://127.0.0.1:8765/sample-accident-report.pdf). Check suggested answers against their filename and page. Choose **Ask a question** for filing help and return to the unfinished answer.
- **File with a German report.** Import the [German sample](http://127.0.0.1:8765/examples/photo-guide/accident-report-de.pdf). Edit and confirm the suggested English or choose **Continue with original German**. The reviewer can see the German text, page and claimant’s choice. The sample uses an offline phrasebook. For other supported German narratives, install the optional local model once with `python3 -m backend.claim_assistance --install-translation`. If a suggestion is unavailable, the claimant can supply English or use the original.
- **Start with a photo.** In the chatbot, choose **Take a photo** or **Choose a photo or PDF**. Preview the image, select damage photo, accident report or repair quote, then choose **Attach image and continue**. At **Documents**, attach up to four initial files and see examples of wide shots and close-ups. JPEG and PNG files can be up to 12 MiB each. PDFs can be up to 2 MiB each. If the camera date differs from the incident date, add an explanation. If the camera date is absent, supply a date or leave it unknown. The reviewer receives the original file and the separate dates.
- **Pause and follow up.** Choose **Save and continue later** to reopen answers and attachments with the private draft link. After submission the link shows the receipt and accepts missing paperwork or another quote. A link works on another device when both devices can reach the same HTTPS service.

The PDF importer reads labelled fields on the first 12 text pages. It can try English OCR on the first two pages of an image-only report when `pdftoppm` and Tesseract are installed (`brew install tesseract` adds Tesseract on macOS). Quote verification requires readable PDF text, a printed euro total, and reconciling priced work. The claimant can attach an unreadable document and continue. Claimant documents and translations are processed on the service host.

In the voice demo, a claimant speaks to ElevenLabs in their browser. With their permission, Vonage texts the private document-upload link to the team’s verified demo phone. [Set up the voice and SMS demo](backend/VOICE.md).

## Review the fictional demo cases

Open the [reviewer workspace](http://127.0.0.1:8765/reviewer).

1. Ask **“Why does DEV-002 need more information?”** The decision identifies the missing incident report under v1.2.
2. Ask **“What if we received the incident report?”** The simulator changes that one fact and returns routine processing under v1.3. Expand the evidence to read the policy clause.
3. Ask **“Show the recorded decision.”** The original still requests the incident report. **“Correct this decision”** opens a separate form where a reviewer can record a new route and reason.

For a live boundary test, ask about DEV-001, then try a €1,500 quote and a €1,501 quote. Only the second amount triggers human review.

To enable models for reviewer questions, set `JEV_API_KEY` and/or `OPENAI_API_KEY` in the server’s local `.env` and restart. Jev classifies the question. GPT selects verified statements for a claim explanation. The evidence panel identifies the source for each answer. [HTTP contract](contract/api.md)

## Hosted database for Lovable

The original intake and reviewer API use the Thinc Supabase project. Thinc has the evidence migration and passed its rollback-only database check. To run the hosted path, provision the matching evidence service credential on the API server. Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` (also accepted as `SUPABASE_ANON_KEY`), then run `python3 -m backend --store supabase`. The public queue contains fictional cases. Real submissions, original files and evidence history use private tables. [Database setup and staff access](contract/db/README.md)

For a rehearsal with a private SQLite copy, run `python3 -m backend --store sqlite`.

## Run the reviewer API

Mo’s engine evaluates the submitted claim and each revised garage quote under policy v1. The insurer can open the claim by its existing reference to inspect which rules matched, what evidence was missing, and why the recommendation changed.

To try a policy change locally, run `python3 -m backend --open` and open the [policy workbench](http://127.0.0.1:8767). Upload the supplied Word policy and the [synthetic claims](engine/tests/fixtures/synthetic_claims.csv) to compare decisions and download their explanations. The workbench starts empty and uses a separate SQLite database. [Workbench guide](backend/README.md)

From the repository root, start the local service with Python 3.10 or newer:

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

## Five minutes with the judges

| Time | Presenter | What the judges see |
| --- | --- | --- |
| 0:00–1:30 | Rafik as the driver | Upload the €890 total-only quote, copy the garage request and submit. |
| 1:30–2:30 | Sayed as the reviewer | Open the submitted reference, show the original PDF and explain why v1.2 requests the breakdown. |
| 2:30–3:30 | Rafik | Reopen the same private receipt and send the €890 itemized version. Sayed shows the new v1.3 decision and the earlier version. |
| 3:30–5:00 | Judge | Choose a high-value or unreadable quote. Predict the route, replay it and inspect the precise change and version history. |

## Hackathon references

Case assignment is announced on Discord on Saturday at 13:30. The Taktile policy update is scheduled for 18:00 there. Jonathan, Senior Forward Deployed Engineer, is the on-site Taktile contact. The case uses hidden test claims. [Taktile brief on Drive](https://drive.google.com/file/d/1zUfKqMNmND-2Uz-qP3rJc4bHHLwuXHBW/view?usp=sharing) · [Participant pack on Drive](https://drive.google.com/file/d/1SUolqZMWaMn7FX2gravpVW67sAqIc3s5/view?usp=drive_link)

**NAP VC side challenge.** Across all three cases, the jury looks for an intuitive, polished user experience, an original idea built around the user, and a pitch that makes the value immediately clear.

**Other tracks.** Each case partner presents at the Saturday opening for about ten minutes.

- **Dash0.** [Challenge brief](Usecase/Dash0_Hackathon_Challenge.pdf) · [Perses](https://perses.dev) · [Alert thresholds](https://www.dash0.com/docs/dash0/monitoring/alerting/alerting-model#the-dollarthreshold-extension) · [Dashboard import](https://www.dash0.com/docs/api-reference/operations/post/api/import/dashboard) · [Check rule import](https://www.dash0.com/docs/api-reference/operations/post/api/import/check-rules) · [Starter repo](https://github.com/vimouzin/dash0-dashboard-migrator) · [Dash0 sign-in](https://accounts.dash0.com/sign-in) · [Datadog](https://www.datadoghq.com/) · [Datadog test assets](https://github.com/DataDog/integrations-core)
- **Reonic.** [Challenge brief](Usecase/Reonic_Hackathon_Challenge_final.pdf). The separately supplied project dataset is for the hackathon team’s local use.
