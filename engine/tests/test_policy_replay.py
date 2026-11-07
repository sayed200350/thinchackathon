import csv
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from engine import decide
from engine.batch import OUTPUT_COLUMNS, read_claims, replay_row, write_batch
from eval.quality import score


ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT = ROOT / "data/taktile/labelled_development_cases.csv"
PRACTICE = ROOT / "data/taktile/unlabelled_practice_cases.csv"
CLAIMS = {row["case_id"]: row for row in read_claims(DEVELOPMENT)}
BASE = CLAIMS["DEV-001"]


class PolicyTests(unittest.TestCase):
    def test_development_labels_and_shared_example(self):
        for case_id, claim in CLAIMS.items():
            with self.subTest(case_id=case_id):
                self.assertEqual(decide(claim)["recommendation"], claim["expected_v1"])
        fixture = json.loads((ROOT / "contract/example-result-DEV-001.json").read_text())
        self.assertEqual(decide(BASE), fixture)

    def test_strict_quote_boundary(self):
        for quote, expected in [("0", "routine_processing"), ("1499.99", "routine_processing"),
                                ("1500.00", "routine_processing"), ("1500.01", "human_review")]:
            with self.subTest(quote=quote):
                self.assertEqual(decide(dict(BASE, quote_eur=quote))["recommendation"], expected)

    def test_invalid_facts_do_not_default_to_false_or_zero(self):
        for field, raw in [("quote_eur", ""), ("quote_eur", "unreadable"), ("quote_eur", "NaN"),
                           ("quote_eur", "Infinity"), ("quote_eur", -1), ("claim_type", "unknown"),
                           ("injury_reported", "perhaps"), ("repair_type", None)]:
            with self.subTest(field=field, raw=raw):
                result = decide(dict(BASE, **{field: raw}))
                self.assertEqual(result["recommendation"], "request_information")
                self.assertIsNone(result["supporting_facts"][field])
        incomplete = dict(BASE)
        del incomplete["policy_active_on_incident"]
        self.assertEqual(decide(incomplete)["matched_rule"], "v1.missing")

    def test_known_review_reason_wins_over_absent_facts_and_documents(self):
        claim = dict(BASE, liability_disputed=True, incident_report_present=False, quote_eur=None)
        result = decide(claim)
        self.assertEqual(result["matched_rule"], "v1.1")
        self.assertEqual(result["supporting_facts"], {"liability_disputed": True})

    def test_document_absence_is_distinct_from_an_unknown(self):
        result = decide(dict(BASE, itemized_quote_present=False, injury_reported=None))
        self.assertEqual(result["matched_rule"], "v1.2")
        self.assertEqual(result["supporting_facts"], {"itemized_quote_present": False, "injury_reported": None})

    def test_summary_and_label_cannot_override_the_evidence(self):
        claim = dict(BASE, claim_summary="injuries reported", expected_v1="human_review")
        self.assertEqual(decide(claim), decide(BASE))

    def test_invalid_metadata_or_unreleased_version(self):
        for updates in [{"case_status": "pending"}, {"case_id": " "}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                decide(dict(BASE, **updates))
        with self.assertRaisesRegex(ValueError, "Unsupported policy version"):
            decide(BASE, "v2")

    def test_replay_preserves_closed_and_marks_only_changed_routes(self):
        candidate = dict(decide(BASE), policy_version="v2", matched_rule="test-only",
                         recommendation="human_review", explanation="Synthetic test condition.")
        callback = Mock(return_value=candidate)
        closed = replay_row(dict(BASE, case_status="closed"), callback)
        callback.assert_not_called()
        self.assertFalse(closed["needs_recheck"])
        self.assertEqual(closed["recommendation_v2"], closed["recommendation_v1"])
        self.assertEqual(closed["rule_v2"], closed["rule_v1"])
        self.assertTrue(replay_row(BASE, callback)["needs_recheck"])
        callback.return_value = dict(candidate, recommendation="routine_processing")
        self.assertFalse(replay_row(BASE, callback)["needs_recheck"])
        self.assertIsNone(replay_row(BASE)["needs_recheck"])


class BatchAndQualityTests(unittest.TestCase):
    def test_practice_batch_through_normal_entry_point(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "result.csv"
            run = subprocess.run([sys.executable, "-m", "engine", "batch", str(PRACTICE), str(output)],
                                 cwd=ROOT, text=True, capture_output=True, check=True)
            self.assertIn("await policy v2", run.stderr)
            with output.open(newline="") as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                self.assertEqual(tuple(reader.fieldnames), OUTPUT_COLUMNS)
            self.assertEqual([row["case_id"] for row in rows], [row["case_id"] for row in read_claims(PRACTICE)])
            self.assertEqual(len(rows), 12)
            for row in rows:
                if row["case_id"] in {"PRA-009", "PRA-010"}:
                    self.assertEqual(row["needs_recheck"], "False")
                    self.assertEqual(row["recommendation_v1"], row["recommendation_v2"])
                else:
                    self.assertEqual(row["recommendation_v2"], "")
                    self.assertEqual(row["needs_recheck"], "")

    def test_failed_or_retried_batches_keep_the_previous_file_intact(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "result.csv"
            broken = Path(folder) / "duplicate.csv"
            write_batch(PRACTICE, output)
            previous = output.read_bytes()
            broken.write_bytes(b"\xef\xbb\xbfcase_id,case_status\nX,open\nX,closed\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                write_batch(broken, output)
            self.assertEqual(output.read_bytes(), previous)
            with self.assertRaisesRegex(ValueError, "different"):
                write_batch(output, output)
            write_batch(PRACTICE, output)
            self.assertEqual(output.read_bytes(), previous)

    def test_quality_counts_both_expensive_error_types_and_rejects_unlabelled(self):
        with TemporaryDirectory() as folder:
            data = Path(folder) / "labels.csv"
            with data.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=BASE.keys())
                writer.writeheader()
                writer.writerow(dict(BASE, expected_v1="request_information"))
                writer.writerow(dict(CLAIMS["DEV-006"], expected_v1="routine_processing"))
            report = score(data)
            for metric in ["incorrect_routine_processing", "unnecessary_human_review"]:
                self.assertEqual(report[metric], {"count": 1, "denominator": 2, "rate": 0.5})
            self.assertEqual(report["accuracy"]["count"], 0)
            self.assertEqual(len(report["errors"]), 2)
        with self.assertRaisesRegex(ValueError, "expected_v1"):
            score(PRACTICE)
        stored = json.loads((ROOT / "eval/v1-development.json").read_text())
        self.assertEqual(score(DEVELOPMENT), stored)


if __name__ == "__main__":
    unittest.main()
