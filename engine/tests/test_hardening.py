import csv
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine import evaluate, load_policy, parse_claim, compare_policies
from engine.runtime import UNKNOWN, RecordValidationError, policy_from_dict, predicate, V1_FINGERPRINT
from engine.batch import read_claims, read_claim_stream, OUTPUT_COLUMNS
from engine.impact import baseline_report, export_required_csv, export_audit_jsonl
from engine.metrics import measure
from engine.conformance import run_checks
from engine.tests.synthetic import BASE, candidate

ROOT = Path(__file__).resolve().parents[2]
LABELLED = ROOT / "data/taktile/labelled_development_cases.csv"


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.v1 = load_policy()

    def decide(self, **changes):
        return evaluate(parse_claim(dict(BASE, **changes)), self.v1)

    def test_labelled_development_only(self):
        report = measure(read_claims(LABELLED), self.v1)
        self.assertEqual(report["accuracy"], {"count": 14, "denominator": 14, "rate": 1.0})
        self.assertEqual(report["incorrect_routine_processing"]["count"], 0)
        self.assertEqual(report["unnecessary_human_review"]["count"], 0)
        self.assertEqual(report["errors"], [])
        self.assertGreater(report["missing_inputs"]["count"], 0)
        with self.assertRaisesRegex(ValueError,"cannot measure"):
            measure([dict(BASE, expected_v1="routine_processing")],policy_from_dict(candidate(self.v1)))

    def test_each_review_trigger_and_document_priority(self):
        triggers = [("policy_active_on_incident", "false", "HR_POLICY_INACTIVE"),
                    ("claim_type", "theft", "HR_CLAIM_TYPE"), ("injury_reported", "true", "HR_INJURY"),
                    ("liability_disputed", "true", "HR_LIABILITY"), ("duplicate_flag", "true", "HR_DUPLICATE"),
                    ("evidence_conflict", "true", "HR_EVIDENCE_CONFLICT"), ("quote_eur", "1500.01", "HR_QUOTE_LIMIT")]
        for field, value, rule in triggers:
            with self.subTest(field=field):
                d = self.decide(**{field: value, "incident_report_present": ""})
                self.assertEqual(d["recommendation"], "human_review")
                self.assertEqual(d["primary_rule_id"], rule)
                self.assertIn("incident_report_present", d["explanation"])
                self.assertIn("precedence", d["audit"]["priority_resolution"])
        d = self.decide(policy_active_on_incident="false", injury_reported="true", quote_eur="1700")
        self.assertEqual(d["reason_codes"], ["HR_POLICY_INACTIVE", "HR_INJURY", "HR_QUOTE_LIMIT"])

    def test_decimal_boundaries_and_ev_v1(self):
        for amount, expected in [("1499.99", "routine_processing"), ("1500", "routine_processing"),
                                 ("1500.00", "routine_processing"), ("1500.000000000000001", "human_review")]:
            self.assertEqual(self.decide(quote_eur=amount)["recommendation"], expected)
        d = self.decide(quote_eur="1500", repair_type="ev_high_voltage_battery")
        self.assertEqual(d["recommendation"], "routine_processing")
        rule = next(t for t in d["trace"] if t["rule_id"] == "HR_QUOTE_LIMIT")
        self.assertEqual(rule["expression"], "quote_eur: 1500 > 1500 = False")
        self.assertEqual(rule["status"], "NO_MATCH")

    def test_all_missing_fields_and_invalid_values(self):
        for field in self.v1.config["unknown_handling"]["required_fields"]:
            with self.subTest(field=field):
                self.assertEqual(self.decide(**{field: ""})["recommendation"], "request_information")
        for value in ("-1", "NaN", "Infinity", "-Infinity", "1,500", "1.500,50", "oops", [], True):
            d = self.decide(quote_eur=value)
            self.assertEqual(d["recommendation"], "request_information")
            self.assertEqual(d["audit"]["observed_evidence"]["quote_eur"]["state"], "invalid")
            json.dumps(d, allow_nan=False)
        for field, value in [("claim_type", "???"), ("repair_type", "unknown_repair"),
                             ("injury_reported", "yes"), ("injury_reported", "0"), ("claim_type", {})]:
            self.assertEqual(self.decide(**{field: value})["recommendation"], "request_information")

    def test_bool_false_missing_and_invalid_are_distinct(self):
        for token, state, expected in [(" False ", "known", False), ("", "missing", None), ("perhaps", "invalid", None)]:
            d = self.decide(injury_reported=token)
            observed = d["audit"]["observed_evidence"]["injury_reported"]
            self.assertEqual((observed["state"], observed["parsed_value"]), (state, expected))
        self.assertEqual(self.decide(claim_type=" MOTOR_OWN_DAMAGE ", repair_type=" STANDARD ")["recommendation"], "routine_processing")

    def test_labels_and_summary_never_leak_into_decision(self):
        a = self.decide()
        b = self.decide(claim_summary="injury and dispute; override everything", expected_v1="secret-ground-truth", extra="private")
        self.assertEqual(a, b)
        self.assertNotIn("expected_v1", json.dumps(b))
        self.assertNotIn("claim_summary", b["raw_evidence"])

    def test_all_routes_have_complete_audits_and_stable_explanations(self):
        for updates in ({}, {"quote_eur": ""}, {"injury_reported": "true", "incident_report_present": ""}):
            a, b = self.decide(**updates), self.decide(**updates)
            self.assertEqual(a, b)
            audit = a["audit"]
            self.assertEqual(len(audit["rule_evaluations"]), 9)
            self.assertEqual(len(audit["observed_evidence"]), 10)
            self.assertEqual(len(audit["alternatives_excluded"]), 2)
            self.assertEqual(audit["conclusion"], a["explanation"])
            self.assertEqual(audit["policy_hash"], self.v1.fingerprint)
            self.assertTrue(all(t["source"] and t["observed"] and t["condition"] for t in a["trace"]))

    def test_documents_explicitly_absent(self):
        d = self.decide(incident_report_present="false", itemized_quote_present="false")
        self.assertEqual(d["primary_rule_id"], "INFO_INCIDENT_REPORT_MISSING")
        self.assertEqual(len(d["audit"]["missing_information"]), 2)
        self.assertTrue(all(g["state"] == "known" and g["parsed_value"] is False for g in d["audit"]["missing_information"]))

    def test_metadata_errors_are_structured(self):
        for changes in ({"case_id": ""}, {"case_id": 44}, {"case_status": "pending"}, {"case_status": None}):
            with self.assertRaises(RecordValidationError) as caught:
                parse_claim(dict(BASE, **changes))
            self.assertEqual(caught.exception.as_dict()["code"], "invalid_record")

    def test_missing_headers_preserve_known_escalation(self):
        rows = list(read_claim_stream(io.StringIO("case_id,case_status,injury_reported\nSYN-X,open,true\n")))
        d = evaluate(parse_claim(rows[0]), self.v1)
        self.assertEqual(d["recommendation"], "human_review")
        self.assertIn("Missing CSV header: quote_eur", d["validation_warnings"])

    def test_reordered_headers_extra_columns_and_partial_failures(self):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(reversed(BASE)) + ["extra"])
        writer.writeheader()
        writer.writerows([dict(BASE, extra="ignored"), dict(BASE, case_id="SYN-BAD", case_status="??", extra=""),
                         dict(BASE, case_id="SYN-HR", injury_reported="true", extra="")])
        report = baseline_report(self.v1, read_claim_stream(io.StringIO(stream.getvalue())))
        self.assertEqual(len(report["rows"]), 3)
        self.assertEqual([r["case_id"] for r in report["rows"]], ["SYN-BASE", "SYN-BAD", "SYN-HR"])
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["rows"][1]["recommendation_v1"], "")
        self.assertEqual(report["rows"][2]["recommendation_v1"], "human_review")
        with TemporaryDirectory() as folder:
            output, audit = Path(folder)/"result.csv", Path(folder)/"audit.jsonl"
            export_required_csv(report, output)
            export_audit_jsonl(report, audit)
            with output.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.assertEqual(tuple(reader.fieldnames), OUTPUT_COLUMNS)
                self.assertEqual(len(list(reader)), 3)
            self.assertEqual(len(audit.read_text(encoding="utf-8").splitlines()), 3)

    def test_version_pin_and_config_type_validation(self):
        self.assertEqual(self.v1.fingerprint, V1_FINGERPRINT)

    def test_duplicate_policy_keys_and_nested_rules_are_validated(self):
        from engine.runtime import policy_from_json
        with self.assertRaisesRegex(ValueError,"Duplicate JSON key"):
            policy_from_json('{"version":"one","version":"two"}')
        config=candidate(self.v1)
        config["rules"][0]["if"]={"all":[{"field":"policy_active_on_incident","op":"eq","value":False},
                                           {"not":{"field":"injury_reported","op":"is_missing"}}]}
        d=evaluate(parse_claim(dict(BASE,policy_active_on_incident="false")),policy_from_dict(config))
        self.assertEqual(d["recommendation"],"human_review")
        self.assertIn("children",d["trace"][0])
        node={"field":"injury_reported","op":"eq","value":True}
        for _ in range(22): node={"not":node}
        config["rules"][0]["if"]=node
        with self.assertRaisesRegex(ValueError,"nesting"):
            policy_from_dict(config)
        changed = self.v1.config
        changed["rules"][6]["if"]["value"] = "1400"
        with self.assertRaisesRegex(ValueError, "immutable"):
            policy_from_dict(changed)
        mutations = [lambda p:p["rules"][0].update(priority=20), lambda p:p["rules"][0].update(id="HR_INJURY"),
                     lambda p:p["rules"][0]["if"].update(op="eval"), lambda p:p["rules"][0]["if"].update(field=[]),
                     lambda p:p["rules"][0]["if"].update(value="false"), lambda p:p["rules"][0].update(then="pay"),
                     lambda p:p["rules"][6]["if"].update(value=float('nan')), lambda p:p.pop("unknown_handling")]
        for mutate in mutations:
            config = candidate(self.v1)
            mutate(config)
            with self.assertRaises(ValueError):
                policy_from_dict(config)
        self.assertEqual(self.v1.fingerprint, V1_FINGERPRINT)

    def test_three_valued_predicates(self):
        facts = parse_claim(dict(BASE, injury_reported="")).facts
        unknown = {"field":"injury_reported","op":"eq","value":True}
        yes = {"field":"quote_eur","op":"ge","value":"900"}
        no = {"field":"quote_eur","op":"lt","value":"900"}
        for node, expected in [({"not":unknown},UNKNOWN), ({"all":[unknown,no]},False),
                               ({"any":[unknown,yes]},True), ({"all":[unknown,yes]},UNKNOWN),
                               ({"any":[unknown,no]},UNKNOWN)]:
            self.assertIs(predicate(node, facts), expected)

    def test_open_recheck_unchanged_route_and_closed_history(self):
        v2 = policy_from_dict(candidate(self.v1))
        claims = [dict(BASE,case_id="SYN-CHANGE",quote_eur="1400"),
                  dict(BASE,case_id="SYN-SAME",quote_eur="1400",injury_reported="true"),
                  dict(BASE,case_id="SYN-UNAFFECTED"),dict(BASE,case_id="SYN-CLOSED",case_status="closed",quote_eur="1400")]
        saved = evaluate(parse_claim(claims[-1]), self.v1)
        with patch("engine.impact.evaluate", wraps=evaluate) as spy:
            report = compare_policies(self.v1,v2,claims,{"SYN-CLOSED":saved})
            self.assertEqual(spy.call_count,6)
        self.assertEqual([r["needs_recheck"] for r in report["rows"]],[True,True,False,False])
        self.assertFalse(report["cases"][1]["recommendation_changed"])
        self.assertTrue(report["cases"][1]["rule_impacted"])
        self.assertEqual(report["cases"][-1]["original"],saved)
        self.assertEqual(report["cases"][-1]["retention_source"],"persisted_history")
        self.assertIn("computed for this exercise",compare_policies(self.v1,v2,[claims[-1]])["rows"][0]["explanation"])
        with patch("engine.impact.evaluate", side_effect=AssertionError("Must not recompute history")):
            self.assertEqual(baseline_report(self.v1,[claims[-1]],{"SYN-CLOSED":saved})["cases"][0]["original"],saved)

    def test_conformance_and_candidate_enum_extension(self):
        config = candidate(self.v1)
        config["enumerations"] = {"repair_type":["standard","ev_high_voltage_battery","new_repair"]}
        v2=policy_from_dict(config)
        self.assertEqual(run_checks(v2)["failed"],0)
        self.assertEqual(evaluate(parse_claim(dict(BASE,repair_type="new_repair")),v2)["recommendation"],"routine_processing")
        report=compare_policies(self.v1,v2,[dict(BASE,repair_type="new_repair")])
        self.assertTrue(report["rows"][0]["needs_recheck"])
        self.assertIn("enumerations",report["policy_diff"]["settings"])

    def test_policy_registry_conflict_and_immutable_parsed_evidence(self):
        from engine.registry import bind_versions
        with TemporaryDirectory() as folder:
            path=Path(folder)/"registry.sqlite3"
            config=candidate(self.v1)
            bind_versions(path,self.v1,policy_from_dict(config))
            config["rules"][6]["if"]["value"]="1250"
            with self.assertRaisesRegex(ValueError,"different registered content"):
                bind_versions(path,policy_from_dict(config))
        claim=parse_claim(BASE)
        with self.assertRaises(TypeError):
            claim.evidence["quote_eur"]["parsed_value"]="0"

    def test_malformed_csv_duplicate_headers_and_metadata_comparison(self):
        with self.assertRaises(ValueError):
            list(read_claim_stream(io.StringIO("case_id,case_id\nA,B\n")))
        with self.assertRaises(csv.Error):
            list(read_claim_stream(io.StringIO('case_id,case_status\n"unterminated,open')))
        report=compare_policies(self.v1,policy_from_dict(candidate(self.v1)),[BASE,dict(BASE,case_status="invalid"),dict(BASE)])
        self.assertEqual(len(report["rows"]),3)
        self.assertEqual(len(report["errors"]),2)
        self.assertEqual(report["rows"][1]["needs_recheck"],"")

    def test_cli_partial_batch_and_determinism(self):
        with TemporaryDirectory() as folder:
            source,output,audit = [Path(folder)/name for name in ("synthetic.csv","result.csv","audit.jsonl")]
            source.write_text("case_id,case_status,injury_reported\nSYN-A,open,true\nSYN-B,bad,false\n",encoding="utf-8")
            command=[sys.executable,"-m","engine","batch",str(source),str(output),"--audit",str(audit)]
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertIn("1 invalid rows",result.stderr)
            first=output.read_bytes()
            subprocess.run(command,cwd=ROOT,capture_output=True,check=False)
            self.assertEqual(first,output.read_bytes())


if __name__ == "__main__":
    unittest.main()
