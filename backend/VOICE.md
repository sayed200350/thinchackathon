# Browser voice claims with Vonage SMS

Open **Try the voice demo** on the claimant welcome screen, or open the [ElevenLabs browser call](https://elevenlabs.io/app/talk-to?agent_id=agent_7201m6vfb0xnec6ac5282430y7a3) on a mobile. The browser microphone handles the call. Use fictional details. The agent reads back six claim fields and asks permission to file. It separately asks whether the team may receive one private upload link on its demo phone. The person holding that phone can open the receipt and upload outstanding documents.

## Connect the demo

1. Register a Vonage API account. In the dashboard, verify the team phone as a test destination and get the API key and secret. Choose an SMS sender ID allowed for the destination country. The trial appends a demo label to the text. [Vonage trial accounts](https://api.support.vonage.com/hc/en-us/articles/212554438-What-are-the-limitations-of-a-trial-account) · [SMS sender IDs](https://developer.vonage.com/en/messages/guides/sms/sender-identity)
2. Give the claimant backend a public HTTPS origin. Route `/chat`, `/api/intakes/*` and `/api/voice/post-call` to it. Route `/sample-accident-report.pdf` for the demo PDF. Keep reviewer routes on their existing access path.
3. On the [ElevenLabs demo agent](https://elevenlabs.io/app/agents/agents/agent_7201m6vfb0xnec6ac5282430y7a3), configure a signed **post-call transcript** webhook using standard JSON. The endpoint is `https://YOUR-CLAIM-HOST/api/voice/post-call`. Enable retries and copy the HMAC secret to the backend. The [agent configuration](voice_agent.json) defines the readback, team-phone consent and data collection fields. [ElevenLabs post-call webhooks](https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks)
4. Set the following in the backend's ignored root `.env` or its hosting secret manager. The demo handset is fixed on the server. It should belong to the team and be verified in Vonage.

   ```dotenv
   ELEVENLABS_AGENT_ID=agent_7201m6vfb0xnec6ac5282430y7a3
   ELEVENLABS_WEBHOOK_SECRET=<webhook HMAC signing secret>
   CLAIM_PUBLIC_ORIGIN=https://YOUR-CLAIM-HOST
   VONAGE_API_KEY=<Vonage API key>
   VONAGE_API_SECRET=<Vonage API secret>
   VONAGE_SMS_FROM=<approved sender ID or international sending number>
   VOICE_DEMO_PHONE=<verified team mobile including + and country code>
   ```

5. Run `python3 -m backend --store supabase` with the existing Supabase and private-link settings. The server listens on localhost behind your public reverse proxy. Store the voice queue on a persistent private volume. Its default path is `backend/.local/voice-<project-host>.sqlite3`. Set `VOICE_QUEUE_PATH` to override it. With `--store sqlite` the default queue is next to the claims database.

## Rehearse on stage

Open the voice demo, allow microphone access and say “My parked car was hit in Mannheim on November 5, 2026. My policy is DEMO-42, my email is alex@example.org, and nobody was injured.” Confirm the readback. Give permission to text the **team demo phone** and end the call. On that phone, tap the SMS link, upload a sample incident report PDF, then show the same receipt with only the itemized repair quote outstanding. To give the judges a QR entry point, use your browser’s **Create QR code** action on the public claimant page.

For an offline rehearsal run `python3 -m unittest backend.tests.test_voice -v`. The tests simulate a signed browser call, capture the SMS locally and use its token to upload documents. For a live rehearsal, confirm the message on the verified handset.

## Delivery and recovery

- Unconfirmed or incomplete calls do not file a claim. A caller who confirms filing and declines SMS can still file. SMS requires explicit consent to this particular destination. A previous dial-in consent, spoken phone number, or client-supplied phone field cannot change the SMS recipient.
- The backend acknowledges a valid call after writing it to the queue. Each call can create one claim. Transient filing failures retry using the same claim ID and link. A Vonage HTTP 202 with a message UUID records acceptance. Confirm actual delivery on the handset or in the Vonage message logs. [Vonage Messages API](https://developer.vonage.com/en/api/messages)
- HTTP 429 queues a retry. An ambiguous send or other provider rejection moves the job to `review_sms`. An interruption during a send can leave it in `sending`. Check the provider logs before retrying. Upon completion the worker removes temporary answers, mobile and token.
- To inspect the private queue, query `SELECT conversation, reference, state, sms_provider, sms_sid FROM voice_claims`. The existing `sms_sid` column holds the Vonage UUID for new SMS jobs. Older dial-in jobs retain their prior history and queued claims can finish filing. Their links are never redirected to the team phone. If a Vonage send definitively failed, stop the worker, correct the cause, set only that row’s `state='queued', due=0`, and restart.
