# Reviewer API

**Owner: Sayed (A). Consumer: Rafik (B).** Start from the repository root with Python 3.9+:

```sh
python3 -m backend --ui-origin http://localhost:5173
```

The local service listens at `http://127.0.0.1:8765`. Use your frontend’s actual origin for browser requests, or proxy `/api` from the frontend. The default SQLite database is `backend/.local/reviewer.sqlite3`. Startup seeds 26 fictional claims from the development and practice CSVs. Restarting with the same database preserves original decisions and reviewer history. Pass `--db PATH` for a separate demo database and `--claims FILE [FILE ...]` for other input files. An existing case ID with different source facts is reported at startup.

| Method and path | Response |
| --- | --- |
| `GET /api/claims` | `{"claims":[...]}`. Rows have `case_id`, `case_status`, the original `recommendation`, the current `effective_recommendation`, and integer `revision`. |
| `GET /api/claims/{case_id}` | `claim` (source CSV fields, excluding development labels), `decision` (immutable [engine result](example-result-DEV-001.json)), `effective_recommendation`, `revision`, and `history` (oldest first). |
| `POST /api/claims/{case_id}/corrections` | Append a correction. Returns the updated detail object, HTTP 201 on creation and 200 on an identical retry. |
| `GET /api/policy-preview` | Until the official update, returns `status: "awaiting_v2"`, `from_version: "v1"`, `to_version: "v2"`, open/closed claim counts, and `changes: null`. |

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
