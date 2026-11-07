from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPConnection
import csv
import json
from pathlib import Path
import selectors
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


from backend.store import initialize


ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://localhost:5173"
CLAIM = "/api/claims/DEV-001"
CORRECTION = {"recommendation": "human_review", "reviewer": "Demo reviewer",
              "reason": "Workshop called with conflicting evidence after intake.",
              "policy_version": "v1", "expected_revision": 0, "request_id": "demo-review-1"}


@contextmanager
def running_api(database):
    process = subprocess.Popen(
        [sys.executable, "-m", "backend", "--db", str(database), "--port", "0", "--ui-origin", ORIGIN],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=15):
                raise RuntimeError("The API did not start in time.")
        banner = process.stdout.readline().strip()
        if not banner:
            raise RuntimeError(process.stderr.readline())
        yield int(banner.rsplit(":", 1)[1])
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def call(port, method, path, body=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        payload = None if body is None else json.dumps(body).encode()
        connection.request(method, path, body=payload, headers={"Content-Type": "application/json", "Origin": ORIGIN})
        response = connection.getresponse()
        data = response.read()
        return response.status, json.loads(data) if data else None, response.getheaders()
    finally:
        connection.close()


class ReviewerAPITests(unittest.TestCase):
    def test_handoff_over_http_and_after_full_process_restart(self):
        fixture = json.loads((ROOT / "contract/example-result-DEV-001.json").read_text())
        with TemporaryDirectory() as folder:
            database = Path(folder) / "claims.sqlite3"
            with running_api(database) as port:
                status, original, headers = call(port, "GET", CLAIM)
                self.assertEqual(status, 200)
                self.assertEqual(dict(headers)["Access-Control-Allow-Origin"], ORIGIN)
                self.assertEqual(original["decision"], fixture)
                self.assertNotIn("expected_v1", original["claim"])
                status, corrected, _ = call(port, "POST", CLAIM + "/corrections", CORRECTION)
                self.assertEqual(status, 201)
                self.assertEqual(corrected["effective_recommendation"], "human_review")
                status, retried, _ = call(port, "POST", CLAIM + "/corrections", CORRECTION)
                self.assertEqual((status, retried), (200, corrected))
            with running_api(database) as port:
                status, reloaded, _ = call(port, "GET", CLAIM)
                self.assertEqual((status, reloaded), (200, corrected))
                self.assertEqual(reloaded["decision"], original["decision"])
                self.assertEqual(reloaded["revision"], 1)
                entry, = reloaded["history"]
                for field in ("reviewer", "reason", "policy_version", "request_id", "recommendation"):
                    self.assertEqual(entry[field], CORRECTION[field])
                self.assertEqual(entry["previous_recommendation"], "routine_processing")
                self.assertTrue(entry["created_at"].endswith("Z"))
                _, queue, _ = call(port, "GET", "/api/claims")
                self.assertEqual(len(queue["claims"]), 26)
                first = next(c for c in queue["claims"] if c["case_id"] == "DEV-001")
                self.assertEqual((first["recommendation"], first["effective_recommendation"]),
                                 ("routine_processing", "human_review"))

    def test_changed_seed_cannot_silently_reopen_or_reuse_a_saved_claim(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / "db"
            seed = Path(folder) / "claims.csv"
            with (ROOT / "data/taktile/labelled_development_cases.csv").open() as source:
                row = next(csv.DictReader(source))
            for status in ("open", "closed"):
                with seed.open("w", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=row.keys())
                    writer.writeheader()
                    writer.writerow(dict(row, case_status=status))
                if status == "open":
                    initialize(database, [seed])
                else:
                    with self.assertRaisesRegex(ValueError, "DEV-001.*saved snapshot"):
                        initialize(database, [seed])

    def test_concurrent_updates_closed_claims_and_invalid_corrections(self):
        with TemporaryDirectory() as folder, running_api(Path(folder) / "db") as port:
            path = CLAIM + "/corrections"
            requests = [dict(CORRECTION, request_id=f"review-{i}") for i in (1, 2)]
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda b: call(port, "POST", path, b), requests))
            self.assertEqual(sorted(r[0] for r in responses), [201, 409])
            winner = next(r[1]["history"][0]["request_id"] for r in responses if r[0] == 201)
            self.assertEqual(call(port, "POST", path, dict(CORRECTION, request_id=winner, reason="Different."))[0], 409)
            for changes, status in [({"reason": " "}, 400), ({"expected_revision": True}, 400),
                                    ({"policy_version": "v2"}, 409), ({"recommendation": "invalid"}, 400)]:
                self.assertEqual(call(port, "POST", path, dict(CORRECTION, **changes))[0], status)
            self.assertEqual(call(port, "POST", "/api/claims/PRA-009/corrections", CORRECTION)[0], 409)
            self.assertEqual(call(port, "GET", "/api/claims/missing")[0], 404)
            self.assertEqual(call(port, "GET", CLAIM)[1]["revision"], 1)
            status, preview, _ = call(port, "GET", "/api/policy-preview")
            self.assertEqual((status, preview["status"], preview["changes"]), (200, "awaiting_v2", None))
            self.assertEqual((preview["open_claims"], preview["closed_claims"]), (24, 2))


if __name__ == "__main__":
    unittest.main()
