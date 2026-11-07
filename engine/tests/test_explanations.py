"""Decision/explanation consistency. Uses only the labelled development file and policy-derived synthetic claims."""
import copy
import base64
import csv
import json
from pathlib import Path
import unittest

from backend import workbench
from engine import assess_v1, evaluate, load_policy, parse_claim
from engine.batch import OUTPUT_COLUMNS
from engine.runtime import policy_from_dict
from engine.tests.synthetic import BASE, candidate

ROOT = Path(__file__).resolve().parents[2]
LABELLED = ROOT / "data/taktile/labelled_development_cases.csv"


def case(**changes):
    return {**BASE, "case_id": "SYN-X", **changes}


def detail_of(decision):
    return decision["audit"]["detail"]


class ExplanationTests(unittest.TestCase):
    def test_uploaded_word_policy_and_csv_have_short_employee_reasons(self):
        uploaded = workbench.convert_docx({
            "policy_docx": base64.b64encode((ROOT / "data/taktile/policy_v1.docx").read_bytes()).decode(),
            "filename": "policy_v1.docx"})
        result = workbench.run({"csv": LABELLED.read_text(encoding="utf-8-sig"),
                                "baseline_text": uploaded["policy_text"]})
        self.assertEqual(result["errors"], [])
        for decision, exported in zip(result["decisions"], result["rows"]):
            employee = detail_of(decision)["employee"]
            self.assertLessEqual(len(employee["why"].split()), 40)
            self.assertIn(employee["why"], exported["explanation"])
            self.assertIn(employee["next_step"], exported["explanation"])
            self.assertIn("Policy v1", employee["policy_basis"])
            for field in BASE:
                if "_" in field:
                    self.assertNotIn(field, decision["concise_explanation"])
            self.assertNotIn(decision["primary_rule_id"], decision["concise_explanation"])

    def test_employee_amounts_follow_policy_and_include_exact_boundary(self):
        v2 = policy_from_dict(candidate(load_policy()))
        employee = detail_of(evaluate(parse_claim(case(quote_eur="1400")), v2))["employee"]
        self.assertEqual(employee["why"], "The repair quote is €1,400, above the policy's €1,300 limit.")
        boundary = detail_of(assess_v1(case(quote_eur="1500")))["employee"]
        self.assertIn("€1,500, within", boundary["why"])

    def test_employee_unknown_quote_and_absent_document_are_distinct(self):
        missing = detail_of(assess_v1(case(quote_eur="")))["employee"]
        absent = detail_of(assess_v1(case(incident_report_present="false")))["employee"]
        self.assertIn("missing or unreadable: repair quote", missing["why"])
        self.assertNotIn("€0", missing["why"])
        self.assertEqual(absent["why"], "The incident report is absent.")
        self.assertIn("incident report", absent["next_step"])

    def test_employee_review_reason_does_not_blame_missing_information(self):
        for report in ("", "false"):
            employee = detail_of(assess_v1(case(injury_reported="true", incident_report_present=report)))["employee"]
            self.assertEqual(employee["why"], "An injury was reported.")
            self.assertIn("claims reviewer", employee["next_step"])
            self.assertIn("incident report", " ".join(employee["notes"]))
            self.assertIn("Human review is still required", " ".join(employee["notes"]))

    def test_employee_multiple_reasons_and_closed_next_step(self):
        employee = detail_of(assess_v1(case(injury_reported="true", quote_eur="1800")))["employee"]
        self.assertIn("An injury was reported.", employee["why"])
        self.assertIn("€1,800", employee["why"])
        closed = assess_v1(case(case_status="closed", injury_reported="true"))
        self.assertIn("This claim is closed", closed["concise_explanation"])
        self.assertNotIn("Send the claim", closed["concise_explanation"])

    def assert_consistent(self, decision):
        detail = detail_of(decision)
        self.assertEqual(detail["recommendation"], decision["recommendation"])
        self.assertEqual(detail["policy_version"], decision["policy_version"])
        self.assertEqual(detail["decisive_rule_ids"], [decision["primary_rule_id"]])
        self.assertEqual(detail["unknown_fields"], decision["missing_or_invalid_fields"])
        matched = {r["rule_id"] for r in detail["rules"] if r["status"] == "MATCH"}
        self.assertEqual(matched, set(decision["reason_codes"]))
        return detail

    # --- 1. the 14 labelled development cases are unchanged and each explanation agrees with the engine ---------
    def test_labelled_cases_correct_and_explanations_agree(self):
        with LABELLED.open(encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 14)
        for row in rows:
            decision = assess_v1(row)
            self.assertEqual(decision["recommendation"], row["expected_v1"], row["case_id"])
            self.assert_consistent(decision)

    # --- section 4 scenarios ---------------------------------------------------------------------------------
    def test_routine_states_no_match_and_not_payment(self):
        d = assess_v1(case(quote_eur="650"))
        detail = self.assert_consistent(d)
        self.assertEqual(d["recommendation"], "routine_processing")
        self.assertIn("none triggered", detail["summary"])
        self.assertIn("not approval to pay", detail["summary"])
        self.assertIn("not approval to pay", detail["meaning"])

    def test_missing_incident_report_is_named(self):
        d = assess_v1(case(incident_report_present="false"))
        detail = self.assert_consistent(d)
        self.assertEqual(d["recommendation"], "request_information")
        self.assertIn("incident report", detail["summary"])
        self.assertEqual(detail["decisive_rule_ids"], ["INFO_INCIDENT_REPORT_MISSING"])
        routine = next(w for w in detail["why_not"] if w["route"] == "routine_processing")
        self.assertIn("INFO_INCIDENT_REPORT_MISSING", routine["text"])

    def test_threshold_shows_actual_comparison(self):
        d = assess_v1(case(quote_eur="1800"))
        detail = self.assert_consistent(d)
        self.assertEqual(d["recommendation"], "human_review")
        self.assertIn("€1,800 > €1,500", detail["summary"])

    def test_known_trigger_outranks_missing_information_but_discloses_it(self):
        d = assess_v1(case(injury_reported="true", incident_report_present="", quote_eur="350"))
        detail = self.assert_consistent(d)
        self.assertEqual(d["recommendation"], "human_review")
        self.assertEqual(detail["decisive_rule_ids"], ["HR_INJURY"])
        self.assertIn("outranks", detail["summary"])
        self.assertIn("incident report", detail["summary"])
        self.assertIn("incident_report_present", detail["unknown_fields"])
        self.assertTrue(any(f["status"] == "Missing / Unknown" and f.get("field") == "incident_report_present" for f in detail["factors"]))

    def test_unknown_quote_is_never_zero_or_safe(self):
        d = assess_v1(case(quote_eur=""))
        detail = self.assert_consistent(d)
        self.assertEqual(d["recommendation"], "request_information")
        self.assertEqual(detail["unknown_fields"], ["quote_eur"])
        quote_rule = next(r for r in detail["rules"] if r["rule_id"] == "HR_QUOTE_LIMIT")
        self.assertEqual((quote_rule["status"], quote_rule["result"]), ("UNKNOWN", "unknown"))
        self.assertEqual(quote_rule["role"], "unresolved")
        self.assertIsNone(quote_rule["conditions"][0]["actual"])
        text = json.dumps(detail, ensure_ascii=False)
        self.assertNotIn("€0", text)
        self.assertIn("Unknown — information needed", text)
        self.assertFalse(any(f["status"] == "Satisfied / Not triggered" and f.get("rule_id") == "HR_QUOTE_LIMIT" for f in detail["factors"]))

    def test_exact_boundary_does_not_escalate(self):
        d = assess_v1(case(quote_eur="1500"))
        detail = self.assert_consistent(d)
        self.assertEqual(d["recommendation"], "routine_processing")
        factor = next(f for f in detail["factors"] if f.get("rule_id") == "HR_QUOTE_LIMIT")
        self.assertEqual(factor["facts"][0]["comparison"], "€1,500 > €1,500 is false")

    def test_ev_repair_is_not_an_escalation_under_v1(self):
        d = assess_v1(case(repair_type="ev_high_voltage_battery", quote_eur="900"))
        detail = self.assert_consistent(d)
        self.assertEqual(d["recommendation"], "routine_processing")
        self.assertFalse(any(c["field"] == "repair_type" for r in detail["rules"] for c in r["conditions"]))
        self.assertNotIn("battery", json.dumps(detail).lower().replace("ev_high_voltage_battery", ""))

    def test_multiple_triggers_are_all_shown(self):
        d = assess_v1(case(injury_reported="true", quote_eur="1800"))
        detail = self.assert_consistent(d)
        self.assertEqual(detail["decisive_rule_ids"], ["HR_INJURY"])
        self.assertEqual(detail["corroborating_rule_ids"], ["HR_QUOTE_LIMIT"])
        self.assertIn("injury", detail["summary"])
        self.assertIn("€1,800 > €1,500", detail["summary"])

    # --- counterfactuals -------------------------------------------------------------------------------------
    def test_counterfactuals_are_verified_by_the_engine_and_name_remaining_blockers(self):
        single = detail_of(assess_v1(case(quote_eur="1800")))["counterfactuals"]
        self.assertEqual(single[0]["resulting_recommendation"], "routine_processing")
        self.assertTrue(single[0]["verified"] and single[0]["hypothetical_only"])
        both = detail_of(assess_v1(case(injury_reported="true", quote_eur="1800")))["counterfactuals"]
        self.assertEqual(both[0]["resulting_recommendation"], "human_review")
        self.assertEqual(both[0]["remaining_blockers"], ["HR_INJURY"])
        self.assertIn("only the condition", both[0]["text"])
        # known facts such as an injury are never offered as something to change
        self.assertEqual(detail_of(assess_v1(case(injury_reported="true")))["counterfactuals"], [])

    def test_counterfactual_never_edits_real_evidence(self):
        raw = case(quote_eur="1800")
        claim = parse_claim(raw)
        before = assess_v1(raw)["raw_evidence"], dict(claim.facts)
        evaluate(claim, load_policy())
        self.assertEqual((assess_v1(raw)["raw_evidence"], dict(claim.facts)), before)

    # --- versions and modes ----------------------------------------------------------------------------------
    def test_threshold_text_and_version_come_from_the_policy_used(self):
        v2 = policy_from_dict(candidate(load_policy()))  # synthetic candidate: limit lowered to 1300
        claim = parse_claim(case(quote_eur="1400"))
        d1, d2 = evaluate(claim, load_policy()), evaluate(claim, v2)
        self.assertEqual((d1["policy_version"], d2["policy_version"]), ("v1", "synthetic-test-v2"))
        v1_factor = next(f for f in detail_of(d1)["factors"] if f.get("rule_id") == "HR_QUOTE_LIMIT")
        self.assertEqual(v1_factor["facts"][0]["comparison"], "€1,400 > €1,500 is false")
        self.assertEqual(d1["recommendation"], "routine_processing")
        self.assertEqual(d2["recommendation"], "human_review")
        self.assertIn("€1,400 > €1,300", detail_of(d2)["summary"])
        self.assertEqual(detail_of(d2)["policy_version"], "synthetic-test-v2")
        # loading a later policy does not change what v1 said about the same claim
        again = evaluate(claim, load_policy())
        self.assertEqual(detail_of(again), detail_of(d1))

    def test_manual_and_batch_modes_give_the_same_explanation(self):
        rows = [case(case_id="A1", quote_eur="1800"), case(case_id="A2", incident_report_present=""),
                case(case_id="A3", injury_reported="true", quote_eur="1800")]
        run = workbench.run({"claims": rows})
        for row, decision in zip(rows, run["decisions"]):
            self.assertEqual(detail_of(decision), detail_of(assess_v1(row)))
        self.assertEqual(run["rows"][0]["recommendation_v1"], "human_review")

    # --- output contract and boundaries ----------------------------------------------------------------------
    def test_required_csv_columns_are_unchanged(self):
        self.assertEqual(list(OUTPUT_COLUMNS), ["case_id", "recommendation_v1", "recommendation_v2", "needs_recheck", "rule_v1", "rule_v2", "explanation"])

    def test_explanation_layer_contains_no_policy_constants(self):
        for name in ("engine/explain.py", "backend/web/explain.js"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for constant in ("1500", "1,500", "motor_own_damage", "HR_QUOTE_LIMIT", "ev_high_voltage_battery"):
                self.assertNotIn(constant, text, f"{name} must read policy content from configuration: {constant}")

    def test_comparison_view_lists_the_changed_rule(self):
        config = candidate(load_policy())
        result = workbench.run({"claims": [case(case_id="C1", quote_eur="1400")], "candidate": "custom", "policy": config})
        comparison = result["comparison"]["cases"][0]
        self.assertEqual(comparison["impacted_rule_ids"], ["HR_QUOTE_LIMIT"])
        changed = comparison["version_differences"]["changed_rules"][0]
        self.assertEqual((changed["before"]["if"]["value"], changed["after"]["if"]["value"]), ("1500", "1300"))
        self.assertEqual(detail_of(comparison["candidate"])["policy_version"], "synthetic-test-v2")


if __name__ == "__main__":
    unittest.main()
