"""Settings page: the AI key is verified with the provider, applied live and written to .env."""
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from backend import settings_api
from backend.store import RequestError

GOOD = "AQ.new-key-0123456789abcdef"
ENV = {"AI_PROVIDER": "gemini", "AI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
       "AI_MODEL": "gemini-3.5-flash", "AI_API_KEY": "AQ.old-key-0000000000000000"}


def provider(status=200):
    calls = []

    def opener(request, timeout):
        calls.append(request)
        if status != 200:
            raise HTTPError(request.full_url, status, "x", {}, io.BytesIO(b"{}"))
        return io.BytesIO(b"{}")
    return opener, calls


class SettingsApiTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.env = Path(folder.name) / ".env"
        self.env.write_text("SUPABASE_URL=https://x.supabase.co\nAI_API_KEY=AQ.old-key-0000000000000000\n"
                            "# comment\nAI_MODEL=gemini-3.5-flash\n", encoding="utf-8")

    def test_get_never_returns_the_key(self):
        status, body = settings_api.handle("GET", None, self.env)
        self.assertEqual(status, 200)
        self.assertEqual(body["key_hint"], "…0000")
        self.assertNotIn("AQ.old-key", str(body))
        self.assertEqual(body["model"], "gemini-3.5-flash")

    def test_accepted_key_is_live_and_persisted_without_touching_other_lines(self):
        opener, calls = provider(200)
        result = settings_api.update_ai_key({"api_key": f"  {GOOD} "}, self.env, opener)
        self.assertEqual(os.environ["AI_API_KEY"], GOOD)
        self.assertTrue(result["saved"])
        self.assertIsNone(result["warning"])
        self.assertNotIn(GOOD, str(result))
        lines = self.env.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["SUPABASE_URL=https://x.supabase.co", f"AI_API_KEY={GOOD}",
                                 "# comment", "AI_MODEL=gemini-3.5-flash"])
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertEqual(calls[0].full_url, ENV["AI_BASE_URL"] + "/models")
        self.assertEqual(calls[0].get_header("X-goog-api-key"), GOOD)

    def test_rejected_key_changes_nothing(self):
        before = self.env.read_text(encoding="utf-8")
        for status, code in ((400, 422), (403, 422), (500, 502)):
            with self.assertRaises(RequestError) as caught:
                settings_api.update_ai_key({"api_key": GOOD}, self.env, provider(status)[0])
            self.assertEqual(caught.exception.status, code)
        self.assertEqual(os.environ["AI_API_KEY"], ENV["AI_API_KEY"])
        self.assertEqual(self.env.read_text(encoding="utf-8"), before)

    def test_quota_exhausted_key_is_saved_with_a_warning(self):
        result = settings_api.update_ai_key({"api_key": GOOD}, self.env, provider(429)[0])
        self.assertIn("quota", result["warning"])
        self.assertEqual(os.environ["AI_API_KEY"], GOOD)

    def test_malformed_requests_are_refused_before_any_provider_call(self):
        opener, calls = provider(200)
        for body in ({}, {"api_key": 5}, {"api_key": "short"}, {"api_key": "bad key with spaces 12345"},
                     {"api_key": GOOD, "model": "x"}, {"api_key": GOOD + "\nAI_PROVIDER=evil"}):
            with self.assertRaises(RequestError):
                settings_api.update_ai_key(body, self.env, opener)
        self.assertEqual(calls, [])

    def test_missing_env_line_is_appended(self):
        self.env.write_text("SUPABASE_URL=https://x.supabase.co", encoding="utf-8")
        settings_api.update_ai_key({"api_key": GOOD}, self.env, provider(200)[0])
        self.assertEqual(self.env.read_text(encoding="utf-8"),
                         f"SUPABASE_URL=https://x.supabase.co\nAI_API_KEY={GOOD}\n")

    def test_disabled_provider_is_refused(self):
        with mock.patch.dict(os.environ, {"AI_PROVIDER": "disabled"}):
            with self.assertRaises(RequestError) as caught:
                settings_api.update_ai_key({"api_key": GOOD}, self.env, provider(200)[0])
        self.assertEqual(caught.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
