import io
import json
import os
import unittest
from unittest.mock import patch

from backend import chat_providers as providers


INTENTS = {"explain": "Explain a recorded route", "what_if": "Simulate changed facts"}
FACTS = {"route": "DEV-001 goes to routine processing.", "rule": "Rule v1.3 applies."}
HISTORY = [{"role": "user", "content": "Show DEV-001", "extra": "private metadata"}]


def completed(ids):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps({"statement_ids": ids})}]}]}


class ChatProviderTests(unittest.TestCase):
    def test_missing_credentials_require_no_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(providers, "_post") as post:
            self.assertIsNone(providers.classify_intent("Why?", HISTORY, INTENTS))
            self.assertIsNone(providers.compose_answer("Why?", HISTORY, FACTS))
            post.assert_not_called()

    def test_jev_choice_uses_defined_intents_and_limited_context(self):
        response = {"answers": {"intent": {"type": "choice", "choice": "what_if",
                    "confidence": 0.92, "probabilities": {"what_if": 0.96, "explain": 0.04}}}}
        with patch.dict(os.environ, {"JEV_API_KEY": "test-key", "JEV_MODEL": "test-model"}), \
                patch.object(providers, "_post", return_value=response) as post:
            result = providers.classify_intent("What about €1501?", HISTORY, INTENTS)
        self.assertEqual(result, "what_if")
        host, path, key, payload = post.call_args.args
        self.assertEqual((host, path, key), ("api.typesafe.ai", "/v1/systemone", "test-key"))
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["questions"]["intent"]["criteria"], INTENTS)
        self.assertEqual(payload["state"]["recent_turns"], [{"role": "user", "content": "Show DEV-001"}])

    def test_invalid_or_uncertain_jev_results_fall_back(self):
        for choice, confidence in [("explain", 0.3), ("explain", True), ("approve", 1),
                                   ("explain", float("nan")), (["explain"], 1)]:
            with self.subTest(choice=choice, confidence=confidence):
                response = {"answers": {"intent": {"type": "choice", "choice": choice, "confidence": confidence}}}
                with patch.dict(os.environ, {"JEV_API_KEY": "test-key"}), \
                        patch.object(providers, "_post", return_value=response):
                    self.assertIsNone(providers.classify_intent("Why?", [], INTENTS))

    def test_gpt_only_returns_known_evidence_ids(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}), \
                patch.object(providers, "_post", return_value=completed(["rule", "route"])) as post:
            self.assertEqual(providers.compose_answer("Why?", HISTORY, FACTS), ["rule", "route"])
        host, path, _, payload = post.call_args.args
        self.assertEqual((host, path, payload["model"]), ("api.openai.com", "/v1/responses", "test-model"))
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(json.loads(payload["input"])["available_statements"], FACTS)

    def test_incomplete_refused_and_untrusted_gpt_results_fall_back(self):
        refusal = completed(["route"])
        refusal["output"][0]["content"].append({"type": "refusal", "refusal": "Cannot respond."})
        replies = [refusal, dict(completed(["route"]), status="incomplete"),
                   completed(["made-up"]), completed([]), completed([{}]), completed(["rule", "rule"]),
                   {"status": "completed", "output": None}, {"error": {"message": "failure"}}]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            for reply in replies:
                with self.subTest(reply=reply), patch.object(providers, "_post", return_value=reply):
                    self.assertIsNone(providers.compose_answer("Why?", [], FACTS))

    def test_http_fallback_and_no_redirect_forwarding(self):
        with patch.object(providers.http.client, "HTTPSConnection") as connection:
            client = connection.return_value
            for status, data in [(307, b""), (401, b"unauthorized"), (200, b"not-json"),
                                 (200, b"[]"), (200, b"x" * (providers.MAX_RESPONSE_BYTES + 1))]:
                with self.subTest(status=status, length=len(data)):
                    client.getresponse.return_value.status = status
                    client.getresponse.return_value.read.side_effect = io.BytesIO(data).read
                    self.assertEqual(providers._post("example.invalid", "/model", "test-key", {}, 4), {})
            self.assertEqual(client.request.call_count, 5)
            client.getresponse.side_effect = TimeoutError()
            self.assertEqual(providers._post("example.invalid", "/model", "test-key", {}, 4), {})
            self.assertEqual(client.close.call_count, 6)
