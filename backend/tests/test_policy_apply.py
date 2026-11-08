"""POST /api/policies/{version}/apply: LLM interpretation guarded by citations, engine replay, DB writes."""
import copy
import json
import unittest
from pathlib import Path

from backend.policy_apply import Conflict, Rejected, apply_policy, decision_row
from backend.store import RequestError
from engine.batch import read_claims
from engine.docx_policy import _paragraphs
from engine.runtime import load_policy

ROOT = Path(__file__).resolve().parents[2]
V1_TEXT = "\n".join(_paragraphs((ROOT / "data/taktile/policy_v1.docx").read_bytes()))
V2_TEXT = """Change notice · policy v2
Effective time
For this exercise, policy v2 takes effect when the organizer releases this notice. It applies to all open claims from that point forward (after being processed by v1). Closed claims retain their historical v1 decision and should not be silently rewritten.
Two changes
1. The routine-processing repair quote limit falls from €1,500 to €1,200. A quote of exactly €1,200 remains within the limit; €1,201 requires human review.
2. Any claim with repair_type = ev_high_voltage_battery now requires human review, whatever the quote. This known review trigger takes priority over missing documents.
Everything else
All other v1 rules and their order remain in force."""


def v2_config():
    config = copy.deepcopy(load_policy().config)
    config["version"] = "v2"
    for rule in config["rules"]:
        if rule["id"] == "HR_QUOTE_LIMIT":
            rule["if"]["value"] = "1200"
            rule["reason"] = "The repair quote exceeds EUR 1200"
    config["rules"].append({"id": "HR_EV_BATTERY", "priority": 75, "then": "human_review",
                            "reason": "The repair is EV high-voltage battery work",
                            "if": {"field": "repair_type", "op": "eq", "value": "ev_high_voltage_battery"}})
    return config


GOOD = {
    "summary": "Quote limit lowered to EUR 1,200; EV battery work requires human review.",
    "config_json": json.dumps(v2_config()),
    "ambiguities": [],
    "citations": [
        {"target": "HR_QUOTE_LIMIT", "old_quote": "quote_eur is greater than €1,500",
         "new_quote": "The routine-processing repair quote limit falls from €1,500 to €1,200."},
        {"target": "HR_EV_BATTERY", "old_quote": "",
         "new_quote": "Any claim with repair_type = ev_high_voltage_battery now requires human review, whatever the quote."},
    ],
}


class FakeInterpreter:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def interpret(self, old_text, new_text, current, version):
        self.calls += 1
        assert old_text == V1_TEXT and new_text == V2_TEXT and version == "v2"
        return copy.deepcopy(self.value)


class FakeClient:
    """In-memory stand-in for the Supabase Data API with the constraints the SQL defines."""

    def __init__(self):
        claims = []
        for name in ("labelled_development_cases.csv", "unlabelled_practice_cases.csv"):
            for row in read_claims(ROOT / "data/taktile" / name):
                source = {k: v for k, v in row.items() if k != "expected_v1"}
                claims.append({"case_id": row["case_id"], "case_status": row["case_status"], "source_fields": source})
        self.tables = {
            "policies": [{"version": "v1", "name": "Policy v1", "content": V1_TEXT, "created_at": "2026-11-06T00:00:00"},
                         {"version": "v2", "name": "Policy v2", "content": V2_TEXT, "created_at": "2026-11-07T00:00:00"}],
            "policy_configs": [], "policy_runs": [], "claims": claims,
            "decisions": [{"case_id": c["case_id"], "policy_version": "v1"} for c in claims],
        }

    def select(self, resource, columns, order, **filters):
        rows = self.tables[resource]
        for key, value in filters.items():
            rows = [r for r in rows if str(r.get(key)) == value.removeprefix("eq.")]
        return [copy.deepcopy(r) for r in sorted(rows, key=lambda r: str(r.get(order)))]

    def insert(self, resource, rows, on_conflict=None):
        table = self.tables[resource]
        for row in rows:
            if resource == "policy_configs" and any(r["version"] == row["version"] for r in table):
                raise Conflict()
            if on_conflict:
                keys = on_conflict.split(",")
                table[:] = [r for r in table if any(r[k] != row[k] for k in keys)]
            table.append(dict(copy.deepcopy(row), created_at="2026-11-08T00:00:00"))


class PolicyApplyTest(unittest.TestCase):
    def test_v2_is_interpreted_once_and_every_open_claim_gets_its_own_v2_decision(self):
        client, ai = FakeClient(), FakeInterpreter(GOOD)
        result = apply_policy(client, "v2", ai)
        v2 = {r["case_id"]: r for r in client.tables["decisions"] if r["policy_version"] == "v2"}
        open_ids = {c["case_id"] for c in client.tables["claims"] if c["case_status"] == "open"}
        self.assertEqual(set(v2), open_ids)  # closed claims keep only their v1 decision
        self.assertNotIn("PRA-009", v2)
        self.assertNotIn("PRA-010", v2)
        # Independently derived from the change notice.
        for case_id in ("DEV-010", "DEV-011", "PRA-003", "PRA-004", "PRA-005", "PRA-006"):
            self.assertEqual(v2[case_id]["recommendation"], "human_review", case_id)
            self.assertEqual(v2[case_id]["matched_rule"], "v2.1")
        self.assertNotEqual(v2["PRA-002"]["recommendation"], "human_review")  # exactly €1,200 stays within the limit
        self.assertEqual(v2["DEV-001"]["recommendation"], "routine_processing")
        self.assertIn("EV high-voltage battery", v2["PRA-006"]["explanation"])
        self.assertEqual(v2["PRA-005"]["policy_clause"], GOOD["citations"][1]["new_quote"])
        self.assertEqual(len(client.tables["decisions"]), 26 + len(open_ids))  # v1 rows untouched
        self.assertEqual(len(client.tables["policy_configs"]), 1)
        self.assertEqual(client.tables["policy_configs"][0]["baseline_version"], "v1")
        self.assertEqual(result["open_evaluated"], len(open_ids))
        self.assertEqual(result["closed_retained"], 2)
        self.assertEqual(result["changed"], 6)
        self.assertTrue(result["config_created"])
        names = {r["case_id"]: r for r in result["rows"]}
        self.assertEqual(names["PRA-003"]["rule_v2_name"], "The repair quote exceeds EUR 1200")
        self.assertEqual(names["PRA-003"]["rule_v1_name"], "All checks passed")
        self.assertEqual(names["PRA-006"]["rule_v2_name"], "The repair is EV high-voltage battery work")

        again = apply_policy(client, "v2", ai)  # rerun: stored config, no second model call, no duplicates
        self.assertEqual(ai.calls, 1)
        self.assertFalse(again["config_created"])
        self.assertEqual(len([r for r in client.tables["decisions"] if r["policy_version"] == "v2"]), len(open_ids))
        self.assertEqual(len(client.tables["policy_runs"]), 2)

    def test_rerun_uses_current_claim_fields(self):
        client = FakeClient()
        apply_policy(client, "v2", FakeInterpreter(GOOD))
        claim = next(c for c in client.tables["claims"] if c["case_id"] == "DEV-001")
        claim["source_fields"]["quote_eur"] = "1250"
        apply_policy(client, "v2", FakeInterpreter(GOOD))
        row = next(r for r in client.tables["decisions"] if r["case_id"] == "DEV-001" and r["policy_version"] == "v2")
        self.assertEqual(row["recommendation"], "human_review")

    def test_unsupported_citation_or_ambiguity_writes_nothing(self):
        for broken in ({**GOOD, "ambiguities": ["Unclear whether €1,200 is inclusive."]},
                       {**GOOD, "citations": [dict(GOOD["citations"][0], new_quote="limit falls to €1,000"),
                                              GOOD["citations"][1]]},
                       {**GOOD, "citations": GOOD["citations"][:1]}):
            client = FakeClient()
            with self.assertRaises(Rejected) as caught:
                apply_policy(client, "v2", FakeInterpreter(broken))
            self.assertTrue(caught.exception.payload["problems"])
            self.assertEqual(client.tables["policy_configs"], [])
            self.assertEqual(client.tables["policy_runs"], [])
            self.assertFalse([r for r in client.tables["decisions"] if r["policy_version"] == "v2"])

    def test_model_renaming_the_version_label_does_not_block_apply(self):
        client = FakeClient()
        client.tables["policies"][1]["version"] = "Version 2"
        renamed = dict(GOOD, config_json=json.dumps(v2_config()))  # model answers with "v2"

        class Labelled(FakeInterpreter):
            def interpret(self, old_text, new_text, current, version):
                assert version == "Version 2"
                return copy.deepcopy(self.value)

        result = apply_policy(client, "Version 2", Labelled(renamed))
        self.assertEqual(result["changed"], 6)
        rows = [r for r in client.tables["decisions"] if r["policy_version"] == "Version 2"]
        self.assertEqual(len(rows), 24)
        self.assertEqual(client.tables["policy_configs"][0]["config"]["version"], "Version 2")

    def test_changed_text_for_an_applied_version_is_refused(self):
        client = FakeClient()
        apply_policy(client, "v2", FakeInterpreter(GOOD))
        client.tables["policies"][1]["content"] = V2_TEXT + "\n3. Something new."
        with self.assertRaises(RequestError) as caught:
            apply_policy(client, "v2", FakeInterpreter(GOOD))
        self.assertEqual(caught.exception.status, 409)

    def test_v1_unknown_and_empty_versions_are_refused(self):
        client = FakeClient()
        client.tables["policies"].append({"version": "v3", "name": "v3", "content": "", "created_at": "2026-11-08"})
        for version, status in (("v1", 400), ("v9", 404), ("v3", 400)):
            with self.assertRaises(RequestError) as caught:
                apply_policy(client, version, FakeInterpreter(GOOD))
            self.assertEqual(caught.exception.status, status, version)

    def test_decision_row_matches_seeded_v1_shape(self):
        client = FakeClient()
        apply_policy(client, "v2", FakeInterpreter(GOOD))
        row = next(r for r in client.tables["decisions"] if r["case_id"] == "DEV-002" and r["policy_version"] == "v2")
        self.assertEqual(set(row) - {"created_at"}, {"case_id", "policy_version", "case_status", "recommendation",
                                                      "matched_rule", "supporting_facts", "explanation", "policy_clause"})
        self.assertEqual(row["recommendation"], "request_information")
        self.assertTrue(row["policy_clause"].startswith("2. Otherwise, send to request_information"))


if __name__ == "__main__":
    unittest.main()
