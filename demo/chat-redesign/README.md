# Retakt client phone

The phone is the client app. The insurer workspace runs separately.

```sh
python3 -m backend --store sqlite --port 8765
python3 demo/chat-redesign/serve.py --port 8090 --backend http://127.0.0.1:8765 --intake-backend none
```

Open http://127.0.0.1:8090/mobile.html. `/app` also works directly without the phone frame.

- **New claim:** chat collects the six claim details, then opens the existing document, review and submission flow. Photos, PDFs and saved drafts use the same backend APIs as the original intake.
- **Call Rico:** the same green mascot as the insurer app starts a phone-specific copy of the existing ElevenLabs agent inside the phone. Microphone access starts only after pressing **Start call**. End, close and page exit release the call. Rico uses a general claim greeting, a brighter Charlie voice, and brief, kind replies. Mute/unmute is available during calls. Captured facts update on screen, including corrections; transcripts stay collapsed during a call and hidden at idle. After getting agreement, the agent calls `prepare_claim_in_phone`. The browser validates the fields, transfers them to the document step, and acknowledges the handoff. Choose **Continue to documents**, attach the required incident report and itemized repair quote for this vehicle-damage flow, review the details, then press **Submit claim**. Both browser and API block submission until the required document types are present. **Save and continue later** remains available for incomplete claims. A call alone does not file a claim or send SMS. The original agent and its older SMS integration are separate.
- **My claims:** automatically records this demo customer's drafts and submitted reports on this browser. **In progress** claims reopen with editable details and saved attachments. **Review and send** stays disabled until all six details and both required document types are present; the final **Send claim** action is on the review screen. **Save and continue later** returns to My claims. A successful submission moves the claim into **Submitted** immediately, where it is read-only. There is no private-link input, copy-link panel, or follow-up upload action in the phone flow. Existing receipt entries migrate into Submitted. The requested demo history adds three clearly labelled fictional submitted claims and one unfinished claim missing its itemized repair quote. The private capability remains internal to API calls.

`serve.py` serves the client pages and proxies API, asset and example-file requests to `--backend`. Point it at the same claim store as the insurer inbox. `--intake-backend none` sends claim and staff requests to `--backend`; the separate intake backend on port 8766 remains the default for the existing reviewer demo, and can be changed with `--intake-backend URL`. In the current local shared demo, port 8090 proxies the Supabase-backed service on port 8780, which uses the same claim database as the insurer. The new phone call handoff runs through the browser SDK, so it does not depend on a public post-call callback.

Text intake uses the existing Anthropic integration when `AI_PROVIDER=anthropic` and `AI_API_KEY` are present in the server's `.env`. Use `--env-file PATH` to select a different server-only settings file. Without a model configuration, the assistant collects the six details through guided questions and still supports the complete document and submission flow. Keys never enter client HTML or JavaScript.

The call loads the pinned `@elevenlabs/client@1.35.0` browser SDK from esm.sh on demand and uses its WebSocket transport. No frontend build is required. Both phone iframes delegate microphone, camera and audio playback to the client app.

The customer-facing label is **Insurance number**. The existing backend field remains `policy_number` for storage compatibility; the voice tools accept `insurance_number` and map it at the browser boundary. The chat shows compact captured facts and the latest question, with older messages collapsed.

Routes: `/mobile.html` (phone frame), `/app` (client), `/chat` (full intake), `/garage`, `/reviewer`, `/reviewer/evidence`.

Validation:

```sh
node demo/chat-redesign/tests/client-controls.cjs
python3 demo/chat-redesign/tests/test_demo_claims.py -q
# With jsdom installed (e.g. the insurer app’s development dependencies):
NODE_PATH=../thinc-hack/node_modules node demo/chat-redesign/tests/my-claims.cjs
node --check demo/chat-redesign/client.js
python3 -m py_compile demo/chat-redesign/serve.py
```

The control tests cover mute/unmute, collapsed transcripts, corrected names, the direct voice handoff, invalid dates, microphone denial, cancellation and receipt access. Backend completion tests verify that all submission routes reject missing documents while incomplete drafts save and resume. They mock microphone and ElevenLabs calls; they do not record audio, file a voice claim or send SMS. The browser walkthrough was checked with fictional details and sample PDFs against a separate temporary SQLite database, including submission, My claims, receipt reopening and follow-up documents.

`rico.svg` is generated with Blobatar 2.7.0 (MIT), using the insurer's `alain00` seed and green palette.

The connected ElevenLabs plugin created the phone agent and browser tools. The original agent checks passed: agreed details transfer with the correct fields, and cancellation does not transfer anything. The public IDs and test suite are recorded in `voice-agent.json`.

Phone drafts save in the background and flush before opening My claims. The browser index stores the private token and compact claim details, while attachment bytes stay in the backend draft. Save requests serialize before submission so revision checks cannot race the final send. Saved claims are available in this browser and origin; this demo does not add account sign-in or cross-device account history.

Reusable customer details live in `retakt.customer-profile.v1` in this browser: insured person's name, email, phone, address and insurance number. A new case shows **Are your details still current?** before those details enter the claim or a voice call. The customer can correct them or use different details. Only the reviewed email and insurance number fill the existing claim fields; name, phone and address are retained with the browser's claim summary. New descriptions, dates, locations, injury answers and documents are always collected afresh. Confirming a profile alone does not create an empty draft. Filing a claim also updates the reusable email and insurance number.

Rico receives only customer-reviewed reusable data through the SDK's `dynamicVariables.saved_customer_details`, with an empty default on the agent. The profile-reuse test verifies the insurance number and email and a fresh incident at handoff. No profile data is placed in a public URL. See [ElevenLabs dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables).

`GET /api/phone-demo/claims` loads the fictional history once into an isolated SQLite store, `backend/.local/phone-demo.sqlite3`. Calls for those four demo tokens stay in that store; regular claims retain the configured backend. The historical claims are read-only and the unfinished one accepts edits and uploads, with the same required-document validation before sending. Seeds are idempotent and never recreate a draft that has been sent. Use `--demo-db PATH` for an isolated walkthrough or test. The demo customer is fictional; an existing real customer profile takes precedence when filling the new-case review screen.
