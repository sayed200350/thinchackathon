import base64
import io
import json
from pathlib import Path
import unittest
import zipfile

from backend import workbench
from engine.docx_policy import PolicyDocumentError, policy_from_docx
from engine.runtime import policy_from_dict

ROOT = Path(__file__).resolve().parents[2]
POLICY_DOCX = ROOT / "data/taktile/policy_v1.docx"
BUNDLED = json.loads((ROOT / "engine/configs/policy_v1.json").read_text(encoding="utf-8"))


def edited(*replacements):
    """Copy of the real policy document with literal text replacements applied to its XML."""
    source = zipfile.ZipFile(POLICY_DOCX)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "word/document.xml":
                text = data.decode("utf-8")
                for old, new in replacements:
                    assert old in text, old
                    text = text.replace(old, new)
                data = text.encode("utf-8")
            target.writestr(item, data)
    return out.getvalue()


class DocxPolicyTests(unittest.TestCase):
    def test_supplied_word_policy_equals_bundled_v1(self):
        config, rules, _ = policy_from_docx(POLICY_DOCX.read_bytes())
        self.assertEqual(config, BUNDLED)
        self.assertEqual(len(rules), 9)
        policy_from_dict(config)  # passes the immutable-v1 check

    def test_edited_document_becomes_distinct_candidate_with_stable_rule_ids(self):
        data = edited(("v1", "v2"), ("1,500", "2,000"),
                      ("or quote_eur is", "or repair_type is ev_high_voltage_battery; or quote_eur is"))
        config, rules, _ = policy_from_docx(data, policy_id="fictional_motor_claims", filename="new policy.docx")
        self.assertEqual(config["version"], "v2")
        self.assertIn("new policy.docx", config["source"])
        by_id = {r["id"]: r for r in config["rules"]}
        self.assertEqual(by_id["HR_QUOTE_LIMIT"]["if"]["value"], "2000")
        self.assertEqual(by_id["HR_QUOTE_LIMIT"]["priority"], 70)
        ev = by_id["HR_REPAIR_TYPE_EQ_EV_HIGH_VOLTAGE_BATTERY"]
        self.assertEqual((ev["priority"], ev["then"]), (65, "human_review"))
        policy_from_dict(config)

    def test_end_to_end_run_uses_uploaded_word_policy(self):
        csv_text = (ROOT / "data/taktile/labelled_development_cases.csv").read_text(encoding="utf-8")
        base = workbench.convert_docx({"policy_docx": base64.b64encode(POLICY_DOCX.read_bytes()).decode(), "filename": "p.docx"})
        cand = workbench.convert_docx({"policy_docx": base64.b64encode(edited(("v1", "v2"), ("1,500", "2,000"))).decode(),
                                       "filename": "p2.docx", "expected_policy_id": "fictional_motor_claims"})
        result = workbench.run({"csv": csv_text, "baseline_text": base["policy_text"],
                                "candidate": "custom", "policy_text": cand["policy_text"]})
        self.assertEqual(result["errors"], [])
        changed = {row["case_id"] for row in result["rows"] if row["needs_recheck"]}
        self.assertEqual(changed, {"DEV-004"})  # the only open claim between EUR 1,500 and 2,000

    def test_unclear_wording_is_rejected_not_guessed(self):
        for old, new in [("quote_eur is greater than", "quote_eur is roughly near"),
                         ("claim_type is not motor_own_damage", "the vehicle looks suspicious"),
                         ("evidence_conflict is true", "evidence_confict is true"),
                         ("or itemized_quote_present is false", "and itemized_quote_present is false")]:
            with self.assertRaises(PolicyDocumentError, msg=new):
                policy_from_docx(edited((old, new)))

    def test_rejects_non_word_and_unsafe_files(self):
        with self.assertRaises(PolicyDocumentError):
            policy_from_docx(b"not a zip")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "b">]><w:document xmlns:w="x"/>')
        with self.assertRaises(PolicyDocumentError):
            policy_from_docx(out.getvalue())
        with self.assertRaises(ValueError):
            workbench.convert_docx({"policy_docx": "!!!not-base64!!!"})

    def test_changed_v1_content_is_still_locked(self):
        with self.assertRaises(ValueError):
            workbench.convert_docx({"policy_docx": base64.b64encode(edited(("1,500", "2,000"))).decode()})


if __name__ == "__main__":
    unittest.main()
