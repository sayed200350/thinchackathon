# Policy Replay

Taktile track · thinc! hack MUC · 7–8 November 2026

Policy Replay receives motor-insurance claims in a guided conversation. A claimant describes the incident, attaches evidence, checks their answers and receives a claim reference. Reviewers use a separate workspace to explore the fictional Taktile cases and replay policy decisions.

The deterministic engine routes claims to `routine_processing`, `request_information`, or `human_review`. Each result records the matched rule and supporting facts. Revised evidence creates a new decision in the same claim's history; reviewer corrections remain separate from the original machine decision.

## Quick start

Use **Python 3.10 or newer** and run commands from the repository root. The core engine, local API and policy workbench use the Python standard library; no frontend build or API key is needed for the local walkthrough.

```sh
python3 -m backend --store sqlite
```

| Open | Purpose |
| --- | --- |
| [Claim intake](http://127.0.0.1:8765/chat) | File a claim, attach evidence and save a private follow-up link. |
| [Fictional DEV-003 walkthrough](http://127.0.0.1:8765/chat?demo=DEV-003) | Rehearse the garage-quote demo below. |
| [Reviewer chat](http://127.0.0.1:8765/reviewer) | Explain recorded demo decisions and try changes to individual facts. |
| [Reviewer evidence](http://127.0.0.1:8765/reviewer/evidence) | Open a submitted reference with the reviewer key and inspect evidence history. |

Local claim data is stored in ignored `backend/.local/reviewer.sqlite3`. The explicit `--store sqlite` keeps this walkthrough local even when `.env` contains Supabase settings. Keep the terminal open; Ctrl+C stops the service.

For the separate policy workbench, run this in another terminal:

```sh
python3 -m backend.workbench_server --open
```

The [workbench](http://127.0.0.1:8767) starts empty and uses `backend/.local/workbench.sqlite3`. Upload a claim CSV and a Word or JSON policy to assess claims and preview a candidate policy. See the [workbench guide](backend/README.md).

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

## Configuration and frontend integration

Copy `.env.example` to `.env` when enabling optional integrations. Keep credentials on the server and out of version control. The claimant/reviewer service reads the root `.env` by default; `--env-file PATH` selects another file.

| Integration | Configuration |
| --- | --- |
| Shared Supabase storage | Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` (or `SUPABASE_ANON_KEY`), apply the documented migrations and provision the matching private evidence credential. Start with `python3 -m backend --store supabase`. |
| Separate reviewer frontend | Add `--ui-origin http://localhost:5173` to permit that browser origin. |
| Reviewer question models | Set `JEV_API_KEY` and/or `OPENAI_API_KEY`. Routing still comes from the policy engine. |
| Phone garage uploads | Install `backend/requirements-garage.txt` and configure the garage gateway as described above. |
| Voice and SMS | Follow [the voice setup guide](backend/VOICE.md) for ElevenLabs, Vonage and the public claimant origin. |
| Policy-owner review | Configure `POLICY_TWIN_OWNER_TOKEN` before starting the workbench. See [the workbench guide](backend/README.md#policy-owner-review) for the review flow. |

With `--store auto` (the API default), configured Supabase settings select hosted storage; otherwise the service uses SQLite. The public queue contains fictional cases. Submitted claims, original files and evidence history use private tables. See [database setup and staff access](contract/db/README.md) before using shared storage.

The [HTTP contract](contract/api.md) documents claim list/detail, reviewer corrections, intake, evidence and insurer access. For example, [DEV-001's API response](http://127.0.0.1:8765/api/claims/DEV-001) returns the fictional claim's recorded decision.

The separate frontend is a Git submodule in `app/`. Fetch it when working on that app:

```sh
git submodule update --init --recursive
```

The Python-served interfaces above work without initializing the submodule.

## Run the policy engine

Inspect a development claim or export decisions with a detailed audit:

```sh
python3 -m engine decide data/taktile/labelled_development_cases.csv DEV-001
python3 -m engine batch engine/tests/fixtures/synthetic_claims.csv outputs/local-results.csv --audit outputs/local-audit.jsonl
```

DEV-001's €650 parking scrape with complete paperwork goes to `routine_processing` under v1. Batch CSVs use these columns in this order:

```csv
case_id,recommendation_v1,recommendation_v2,needs_recheck,rule_v1,rule_v2,explanation
```

To rehearse a policy comparison with an explicitly hypothetical threshold change:

```sh
python3 -m engine compare \
  --input engine/tests/fixtures/synthetic_claims.csv \
  --v2 engine/tests/fixtures/v2_hypothetical_threshold.json \
  --output outputs/local-comparison.csv \
  --audit outputs/local-comparison.jsonl \
  --report outputs/local-impact.json
```

For an actual amendment, supply a separately versioned JSON policy citing its source. The CLI does not bundle an official v2 configuration. Open cases are flagged when the recommendation or relevant rule/evidence requirements change. Closed cases retain v1 results and `needs_recheck=False`; standalone CSV exercises have no persisted historical decision to reuse. Candidate previews do not activate a policy. See the [engine guide](engine/README.md) for version binding, validation and partial-failure behavior.

## Validation

```sh
python3 -m engine validate-v1
python3 -m engine test-policy engine/configs/policy_v1.json
python3 -m unittest discover -v
```

The [recorded v1 development report](eval/v1-development.json) has **14/14 correct routes**, **0/14 incorrect routine referrals**, and **0/14 unnecessary human reviews**. This is a small labelled development sample. The 12 unlabelled practice claims and hypothetical candidate cases do not provide an independent accuracy measurement.

Before a live demo, check the €1,500/€1,501 boundary, a missing incident report, a revised quote on the same reference, and a reviewer correction that survives refresh.

## Project layout

| Path | Contents |
| --- | --- |
| [`engine/`](engine/README.md) | Deterministic evaluation, policy configurations, explanations, audit exports and comparison CLI. |
| [`backend/`](backend/README.md) | Claimant and reviewer services, policy workbench, storage adapters and public gateways. |
| [`contract/`](contract/README.md) | Decision and HTTP contracts, SQL schema and migrations. |
| `data/taktile/` | Supplied policies, labelled development claims and unlabelled practice claims. |
| `eval/` | Recorded quality reports. |
| [`demo/landing/`](demo/landing/README.md) and [`demo/landing-react/`](demo/landing-react/README.md) | Landing-page demo and React integration assets. |
| `app/` | Separate reviewer frontend submodule. |
| [`video/`](video/README.md) | Remotion video project and preview/render instructions. |
| [`team/`](team/README.md) | Team responsibilities, decisions and handoff history. |

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
