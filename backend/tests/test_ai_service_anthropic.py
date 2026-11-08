"""Policy interpretation through Claude: request shape, schema translation and refusal handling."""
import json
import os
import unittest
from unittest import mock

from backend import ai_service

ENV = {"AI_PROVIDER": "anthropic", "AI_API_KEY": "sk-ant-test", "AI_MODEL": "claude-opus-5-5",
       "AI_BASE_URL": "https://api.anthropic.com/v1", "AI_TIMEOUT_SECONDS": "20"}
RESULT = {"summary": "s", "config_json": None, "ambiguities": [], "citations": []}


class AnthropicInterpreterTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_provider_selection_and_request(self):
        interpreter = ai_service.configured_interpreter()
        self.assertIsInstance(interpreter, ai_service.AnthropicInterpreter)
        self.assertGreaterEqual(interpreter.timeout, 90)
        url, headers, payload = interpreter.request_spec("{}")
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], "sk-ant-test")
        self.assertEqual(headers["anthropic-version"], "2026-10-21")
        self.assertNotIn("Authorization", headers)
        self.assertEqual(payload["model"], "claude-opus-5-5")
        self.assertEqual(payload["system"], ai_service.SYSTEM)
        schema = payload["output_config"]["format"]["schema"]
        self.assertEqual(schema["properties"]["config_json"], {"anyOf": [{"type": "string"}, {"type": "null"}]})
        self.assertNotIn("anyOf", ai_service.SCHEMA["properties"]["config_json"])  # shared schema untouched
        json.dumps(payload)

    def test_extract_reads_the_text_block_and_refuses_unfinished_answers(self):
        interpreter = ai_service.configured_interpreter()
        reply = {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""},
                                                        {"type": "text", "text": json.dumps(RESULT)}]}
        self.assertEqual(json.loads(interpreter.extract(reply)), RESULT)
        for stop in ("refusal", "max_tokens"):
            with self.assertRaises(ai_service.AIUnavailable):
                interpreter.extract(dict(reply, stop_reason=stop))
        with self.assertRaises(ValueError):
            interpreter.extract({"stop_reason": "end_turn", "content": []})

    def test_model_must_be_an_identifier(self):
        with mock.patch.dict(os.environ, {"AI_MODEL": "../evil"}):
            with self.assertRaises(ai_service.AIUnavailable):
                ai_service.configured_interpreter().request_spec("{}")


if __name__ == "__main__":
    unittest.main()
