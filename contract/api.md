# Reviewer API

**Owner: Sayed (A). Consumer: Rafik (B).** Start from the repository root with Python 3.9+:

```sh
python3 -m backend --ui-origin http://localhost:5173
```

The service listens at `http://127.0.0.1:8765`. Use your frontend’s origin for browser requests, or proxy `/api` from the frontend. With `SUPABASE_URL` and either `SUPABASE_PUBLISHABLE_KEY` or `SUPABASE_ANON_KEY` in the server environment or repo `.env`, every route uses the hosted project. Use `--store supabase` to require that configuration. An unavailable hosted database returns HTTP 503. See the [required migration](db/README.md).

For an offline rehearsal, pass `--store sqlite`. The offline store seeds `backend/.local/reviewer.sqlite3` from the development and practice CSVs. Passing `--db PATH` or `--claims FILE [FILE ...]` also selects SQLite. Startup without any Supabase configuration defaults to SQLite. Each database keeps its own records.

| Method and path | Response |
| --- | --- |
| `GET /chat` or `GET /` | Claimant intake conversation with attachment upload, review and receipt. |
| `POST /api/intakes` | Submit a confirmed claimant packet and its files in one transaction. Returns a receipt, including on an identical retry. |
| `GET /chat?demo=DEV-003` | Opt-in fictional claimant walkthrough with a pre-existing incident report. |
| `GET /sample-accident-report.pdf` | English sample report. Use `/examples/photo-guide/accident-report-de.pdf` for the German report and `/examples/quotes/{name}.pdf` for the four [judge fixtures](../backend/fixtures/quotes). |
| `POST /api/intakes/import-pdf` | Parse a PDF without saving a claim. Send `name` and `content_base64`. Returns `document_kind`, `suggestions`, `notice`, and an optional German narrative `translation`. Each suggestion carries `field`, `value` and one-based `page`. |
| `POST /api/intakes/save-draft` | Send `token`, `draft` and `expected_revision`. Returns `status: "draft"` and the saved `revision`. |
| `POST /api/intakes/resume` | Send `token` to retrieve that draft or its submitted receipt. |
| `POST /api/intakes/submit` | Submit with a private link using `token`, `expected_revision` and `payload` (the complete intake object below). |
| `POST /api/intakes/add-documents` | Send `token`, a fresh UUIDv4 `request_id` and `documents` for the outstanding paperwork. Returns the updated receipt. Reuse the same ID and body when retrying. |
| `POST /api/evidence/quote` | Stateless assessment of one garage quote. Send `{"document": ...}` with the attachment object below. |
| `POST /api/evidence/replay` | Stateless fictional DEV-003 replay with the same input. Returns `assessment`, `original` and `decision`. |
| `GET /reviewer/evidence` | Fictional replay UI and staff access form. The fictional receipt links here with `?reference=CLM-…`. Staff supply a reviewer key to open a submitted case. |
| `POST /api/evidence/reviewer` | Staff only. Send `reference` and `reviewer_key` to retrieve the submitted case’s decision and evidence history. |
| `POST /api/evidence/document` | Staff only. Add a zero-based integer `position` to the staff request to receive the original `name` and `content_base64`. |
| `GET /reviewer` | Reviewer workspace for the fictional demo queue. |
| `POST /api/chat` | A reviewer question about an existing demo case. Returns the selected claim, answer, evidence, suggested follow-ups and the providers actually used. |
| `GET /api/claims` | `{"claims":[...]}`. Rows have `case_id`, `case_status`, the original `recommendation`, the current `effective_recommendation`, and integer `revision`. |
| `GET /api/claims/{case_id}` | `claim` (source CSV fields, excluding development labels), `decision` (immutable [engine result](example-result-DEV-001.json)), `effective_recommendation`, `revision`, and `history` (oldest first). |
| `POST /api/claims/{case_id}/corrections` | Append a correction. Returns the updated detail object, HTTP 201 on creation and 200 on an identical retry. |
| `GET /api/policy-preview` | Until the official update, returns `status: "awaiting_v2"`, `from_version: "v1"`, `to_version: "v2"`, open/closed claim counts, and `changes: null`. |

## Connect claimant intake in Lovable

Collect answers and attachments in memory until the claimant chooses to save or submit. A PDF import returns suggestions for confirmation. Generate a 32-byte random `token` with `crypto.getRandomValues()` and encode it as 64 lowercase hexadecimal characters. The private link uses `/chat#claim=TOKEN`. Keep the token in the fragment and in POST bodies. Anyone holding the link can reopen the draft including its attachments. After submission it opens the receipt and permits additional paperwork.

A draft contains `values` (partial form answers), `documents`, `step` (integer 0–16), and `sources` (field to `{"name": "report.pdf", "page": 1}`). Start with `expected_revision: 0`, then use the returned revision. HTTP 409 means the draft changed or the submission conflicts with a prior request. Reopen the saved version before editing again.

On submission, send the following payload to `POST /api/intakes/submit` with its token and revision. Generate `request_id` with `crypto.randomUUID()`. Keep the confirmed request body for retries. The existing endpoint `POST /api/intakes` still accepts this payload directly for clients that only need an initial receipt.

| Field | Accepted value |
| --- | --- |
| `description`, `location`, `policy_number` | Incident description (10–2,000 characters), location (1–160) and policy reference (1–80). |
| `incident_date`, `email`, `injury_status` | A valid YYYY-MM-DD date up to today in Europe/Berlin, a contact email, and `yes`, `no` or `unknown`. |
| `documents` | An array of up to four objects for `evidence_version: 1`, or three for legacy requests. Use `[]` to submit without files. Each object has `kind`, `name` and `content_base64` (standard base64 with no data-URL prefix). |
| `kind` | `incident_report`, `itemized_quote` or `damage_photo`. Files must be PDF, PNG or JPEG with a matching filename extension. The limit is 2 MiB per file, or 12 MiB for an enhanced JPEG or PNG damage photo. |

Both submission formats return `reference`, `document_count` and `missing_documents`. Linked submissions also return `status: "submitted"` and `documents` containing the received filenames and kinds. The legacy link accepts one outstanding report or estimate of each kind. An invalid packet returns 400, a changed retry returns 409, and an oversized request returns 413.

### Evidence-aware intake

Set top-level `"evidence_version": 1` on **save-draft, resume, submit and add-documents**, including receipt refreshes. This version uses a maximum of four initial documents and 40 documents over the life of a claim. With additional paperwork, send at most one revised quote and one outstanding incident report per request. A revised quote appends a new version even when the previous quote was verified. Old submitted links continue to use the original receipt and outstanding-paperwork rules.

`draft.notes` and `payload.notes` are optional objects. On **add-documents**, send `notes` at the top level. Their positions refer to zero-based indexes in the request’s own `documents` array. This example attaches a photo at position 0 and a report at position 1.

```json
{
  "photos": [{
    "position": 0, "view": "wide", "exif_date": null,
    "manual_date": "2025-10-19", "explanation": "I photographed the damage the following morning."
  }],
  "translations": [{
    "position": 1, "original": "Mein Fahrzeug war geparkt.", "english": "My vehicle was parked.",
    "page": 1, "source": "phrasebook", "confirmed": true, "use_original": false
  }]
}
```

- Photo views are `wide`, `close_up` or an empty string. The service derives the camera date from the original bytes. The manual date and explanation are claimant input. Keep incident date in `payload.incident_date`.
- Importing a supported German incident narrative returns `translation` with the text pair, page, `source` (`local_model`, `phrasebook` or `manual`), and both choice flags initially false. Confirm edited English with `confirmed: true`, or keep German with `use_original: true`. Exactly one choice must be set for a translation to be submitted. The incoming evidence notes are for the specific attached document.
- `demo_case: "DEV-003"` belongs inside `draft` or `payload` only when the user starts the fictional walkthrough. Ordinary submissions leave the field out, and missing insurance facts remain unknown.
- The service assesses uploaded quote bytes on submission and follow-up. `POST /api/evidence/quote` previews the same result. It returns `name`, `status` (`verified` or `needs_clarification`), `amount_eur`, `itemized`, `page`, `reason`, `total_text`, `lines` (description, amount and page) and `garage_request`. Absent evidence can produce nulls. A verified result means recognized priced work and any listed tax reconcile to a single printed euro total.
- A submitted receipt’s `evidence.quotes` contains each version’s summary, position and filing guidance. `evidence.next_action` has `owner` (`claimant`, `garage` or `claims_team`) and `message`. Only an explicit fictional demo also includes `demo_case` and `decision` in this receipt. Use the staff endpoints for original bytes, private notes, and the full history.

### Garage quote handoff

| Endpoint | Request | Successful response |
| --- | --- | --- |
| `POST /api/intakes/garage-link` | `{"token":"<claimant token>"}` for a submitted evidence-enabled claim | `url`, locally generated `qr_svg`, and UTC `expires_at` |
| `POST /api/garage/status` | `{"token":"<garage token>"}` | `{"status":"open","demo":false}`, or just `status` with `received` or `closed` |
| `POST /api/garage/upload` | `token` and one `document` with `kind:"itemized_quote"`, a PDF `name`, and `content_base64` | `{"status":"received"}` |

The garage token travels in the fragment of `/garage#upload=…` and in the body of those two garage operations. An open fictional DEV-003 link includes `demo:true`. The phone receives no claim reference, contact data, previous filenames, policy result, or receipt access. Use a single PDF of up to 2 MiB. A malformed or expired capability returns 403. A stale revision or a different second file returns 409. Retrying the original file on a used link returns the same confirmation. Reminting a link for a given quote version still grants one upload in total. The receipt and staff history mark quotes that arrived through this route with `source:"garage"`.

Configure `GARAGE_PUBLIC_ORIGIN` or `--garage-public-origin` on the claimant API to enable issuance. Use the URL of the restricted garage gateway. An absent or unusable sharing address returns 503. The backend uses a separate persisted `claim_garage_key` in its existing private key directory. All replicas must use the same server-only `CLAIM_GARAGE_KEY` or persisted key. Rotating it invalidates existing links. The current Thinc evidence schema supports this operation.

### Staff evidence and credentials

In **Open submitted claim**, staff enter the public claim reference and their reviewer key. Send both in JSON over HTTPS when hosted. The staff response includes `reference`, `incident_date`, the filenames in `documents`, and `evidence` with the latest decision, append-only quote versions, decision history, and both sets of notes. `history[].decision.matched_rule` gives the clause for that version. `quotes[].position` identifies its original file. File positions are zero-based in all HTTP responses. Missing or incorrect staff credentials return 403. A reference without an enhanced record returns 404.

The server’s `CLAIM_REVIEWER_KEY` authenticates staff. The separate `CLAIM_EVIDENCE_SERVICE_KEY` authenticates the Python service to the Supabase evidence function. Keep both out of Lovable environment variables prefixed with `VITE_`, public source, URLs and claimant messages. Staff can enter the reviewer key in the protected lookup form. Configure the evidence service key only on the backend. The [database setup](db/README.md) covers local credential files, provisioning and migration.

## Connect the reviewer chat

Send the latest question and copy the last response’s `case_id` into the next request. A new claim ID in the question switches the conversation to that claim. Include recent completed turns as `{"role":"user"|"assistant","content":"..."}`. The service accepts a maximum of 16 history entries and 2,000 characters in the new message.

```sh
curl -sS http://127.0.0.1:8765/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Why does DEV-002 need more information?","case_id":null,"history":[]}'
curl -sS http://127.0.0.1:8765/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What if we received the incident report?","case_id":"DEV-002"}'
```

Render `answer` and each `evidence` entry (`label`, `value`) as text. Each suggestion is another question the user can send. If present, `action.type = "review_correction"` supplies `case_id`, `policy_version`, `revision` and `current_recommendation` for the confirmation form below. Sending a chat message never appends a correction.

`model_usage.intent` reports `Jev` or `local`. `model_usage.answer` reports `GPT` when it selects supporting statements and `policy engine` for local responses. Jev receives the question, recent conversation text and the available intents. GPT receives the question, recent conversation text and the verified candidate statements on explanatory turns. The model keys belong on the server. The engine reads recorded claim facts and computes every scenario result locally.

In Supabase mode the chat, correction form and claim detail all read the shared audit history. Two backends can point to the same project. The Python service must be deployed to an HTTPS endpoint for a published Lovable app to call it. Conversation text and hypothetical results remain in the browser session.

## Save and verify a reviewer correction

Read DEV-001. On a fresh demo database its original recommendation is `routine_processing` and its revision is 0.

```sh
curl -sS http://127.0.0.1:8765/api/claims/DEV-001
curl -sS http://127.0.0.1:8765/api/claims/DEV-001/corrections \
  -H 'Content-Type: application/json' \
  -d '{"recommendation":"human_review","reason":"Workshop called with conflicting evidence after intake.","reviewer":"Demo reviewer","policy_version":"v1","expected_revision":0,"request_id":"demo-review-1"}'
curl -sS http://127.0.0.1:8765/api/claims/DEV-001
```

The fields in `claim` are raw CSV strings, including `"False"`. The fields in `decision.supporting_facts` carry normalized values, including JSON booleans and `null` for unknown facts.

The reload returns the original recommendation in `decision.recommendation`, `human_review` in `effective_recommendation`, and revision 1. The history entry includes `revision`, `request_id`, `reviewer`, `reason`, `policy_version`, `previous_recommendation`, `recommendation`, and `created_at` (UTC). The same result survives a process restart. Reviewer identity is entered by the demo user.

The frontend should generate one request ID per save (for example, `crypto.randomUUID()`) and reuse it if that request is retried. Send the `revision` and `decision.policy_version` you last read. A 409 means the claim is closed, the decision changed, or a request ID was reused for different content. Reload the claim before asking the reviewer to act again. A 400 indicates invalid input, a 404 an unknown claim or path, and a 415 an incorrect content type. Error bodies use `{"error":"..."}`.

Run the real HTTP restart and concurrent-review tests with `python3 -m unittest backend.tests.test_reviewer -v`.
