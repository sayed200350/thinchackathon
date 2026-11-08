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


GEMINI_ENV = {"AI_PROVIDER": "gemini", "AI_API_KEY": "k", "AI_MODEL": "gemini-test",
              "AI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta"}


def gemini_reply(value):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]}


CLAUDE_ENV = {"AI_PROVIDER": "anthropic", "AI_API_KEY": "k", "AI_MODEL": "claude-opus-5-5",
              "AI_BASE_URL": "https://api.anthropic.com/v1"}


def claude_reply(value, stop="end_turn"):
    return {"stop_reason": stop, "content": [{"type": "thinking", "thinking": ""},
                                              {"type": "text", "text": json.dumps(value)}]}


class ClaudeTests(unittest.TestCase):
    def test_intent_and_answer_use_claude_with_the_ai_key(self):
        with patch.dict(os.environ, CLAUDE_ENV, clear=True), \
                patch.object(providers, "_post", return_value=claude_reply({"intent": "what_if"})) as post:
            self.assertEqual(providers.classify_intent("What about 1501?", HISTORY, INTENTS), "what_if")
            self.assertEqual(providers.provider_name("intent"), "Claude")
        host, path, key, payload, _timeout = post.call_args.args
        self.assertEqual((host, path, key), ("api.anthropic.com", "/v1/messages", "k"))
        self.assertEqual(post.call_args.kwargs, {"auth_header": "x-api-key",
                                                 "extra_headers": {"anthropic-version": "2026-10-21"}})
        self.assertEqual(payload["model"], "claude-opus-5-5")
        self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")
        with patch.dict(os.environ, CLAUDE_ENV, clear=True), \
                patch.object(providers, "_post", return_value=claude_reply({"statement_ids": ["rule", "route"]})):
            self.assertEqual(providers.compose_answer("Why?", HISTORY, FACTS), ["rule", "route"])

    def test_refused_or_invalid_claude_output_falls_back(self):
        for reply in (claude_reply({"intent": "what_if"}, stop="refusal"), claude_reply({"intent": "approve"}),
                      claude_reply({"intent": "what_if"}, stop="max_tokens"), {}):
            with patch.dict(os.environ, CLAUDE_ENV, clear=True), patch.object(providers, "_post", return_value=reply):
                self.assertIsNone(providers.classify_intent("Why?", [], INTENTS))


class GeminiTests(unittest.TestCase):
    def test_intent_and_answer_use_gemini_when_only_ai_settings_exist(self):
        with patch.dict(os.environ, GEMINI_ENV, clear=True), \
                patch.object(providers, "_post", return_value=gemini_reply({"intent": "what_if"})) as post:
            self.assertEqual(providers.classify_intent("What about 1501?", HISTORY, INTENTS), "what_if")
        host, path, key, payload, _timeout = post.call_args.args
        self.assertEqual((host, path, key), ("generativelanguage.googleapis.com", "/v1beta/models/gemini-test:generateContent", "k"))
        self.assertEqual(post.call_args.kwargs, {"auth_header": "x-goog-api-key"})
        self.assertNotIn("k", payload["contents"][0]["parts"][0]["text"].split())
        with patch.dict(os.environ, GEMINI_ENV, clear=True), \
                patch.object(providers, "_post", return_value=gemini_reply({"statement_ids": ["rule", "route"]})):
            self.assertEqual(providers.compose_answer("Why?", HISTORY, FACTS), ["rule", "route"])
            self.assertEqual(providers.provider_name("intent"), "Gemini")

    def test_invalid_gemini_output_falls_back(self):
        bad = [gemini_reply({"intent": "approve"}), gemini_reply({"intent": "what_if", "x": 1}), {},
               {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}]
        for reply in bad:
            with patch.dict(os.environ, GEMINI_ENV, clear=True), patch.object(providers, "_post", return_value=reply):
                self.assertIsNone(providers.classify_intent("Why?", [], INTENTS))
        for ids in (["nope"], [], ["rule", "rule"]):
            with patch.dict(os.environ, GEMINI_ENV, clear=True), \
                    patch.object(providers, "_post", return_value=gemini_reply({"statement_ids": ids})):
                self.assertIsNone(providers.compose_answer("Why?", [], FACTS))

    def test_unsafe_or_missing_gemini_settings_make_no_request(self):
        for change in ({"AI_PROVIDER": "disabled"}, {"AI_API_KEY": ""}, {"AI_BASE_URL": "http://x.example/v1"},
                       {"AI_MODEL": "a/b"}, {"AI_BASE_URL": "https://u:p@x.example"}):
            with patch.dict(os.environ, {**GEMINI_ENV, **change}, clear=True), patch.object(providers, "_post") as post:
                self.assertIsNone(providers.classify_intent("Why?", [], INTENTS))
                post.assert_not_called()


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
