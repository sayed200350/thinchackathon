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
| `GET /reviewer` | Reviewer workspace for the fictional demo queue. |
| `POST /api/chat` | A reviewer question about an existing demo case. Returns the selected claim, answer, evidence, suggested follow-ups and the providers actually used. |
| `GET /api/claims` | `{"claims":[...]}`. Rows have `case_id`, `case_status`, the original `recommendation`, the current `effective_recommendation`, and integer `revision`. |
| `GET /api/claims/{case_id}` | `claim` (source CSV fields, excluding development labels), `decision` (immutable [engine result](example-result-DEV-001.json)), `effective_recommendation`, `revision`, and `history` (oldest first). |
| `POST /api/claims/{case_id}/corrections` | Append a correction. Returns the updated detail object, HTTP 201 on creation and 200 on an identical retry. |
| `GET /api/policy-preview` | Until the official update, returns `status: "awaiting_v2"`, `from_version: "v1"`, `to_version: "v2"`, open/closed claim counts, and `changes: null`. |

## Connect claimant intake in Lovable

Collect answers and attachments in memory. On **Submit claim**, send a JSON object to `POST /api/intakes`. Generate `request_id` with `crypto.randomUUID()`. Keep the exact confirmed body when retrying after an interrupted response.

| Field | Accepted value |
| --- | --- |
| `description`, `location`, `policy_number` | Incident description (10–2,000 characters), location (1–160) and policy reference (1–80). |
| `incident_date`, `email`, `injury_status` | A valid YYYY-MM-DD date up to today in Europe/Berlin, a contact email, and `yes`, `no` or `unknown`. |
| `documents` | An array of up to three objects. Use `[]` to submit without files. Each object has `kind`, `name` and `content_base64` (standard base64 with no data-URL prefix). |
| `kind` | `incident_report`, `itemized_quote` or `damage_photo`. Each file must be PDF, PNG or JPEG, up to 2 MiB, with a matching filename extension. |

HTTP 200 returns `reference`, `document_count` and `missing_documents`. The latter lists any outstanding incident report or itemized quote. An invalid packet returns 400, a changed retry under an existing ID returns 409, and an oversized request returns 413. Each succeeded receipt refers to one complete saved packet. Private submissions have no public read endpoint. [Staff access](db/README.md)

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
