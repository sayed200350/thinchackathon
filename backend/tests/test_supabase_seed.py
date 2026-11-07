import unittest
from zipfile import ZipFile
from xml.etree import ElementTree

from backend.supabase_seed import CLAUSES, DATA, dollar_quote, snapshots
from engine import decide
from engine.batch import read_claims


class SupabaseSeedTests(unittest.TestCase):
    def test_seed_matches_engine_and_separates_labels_from_source_facts(self):
        imported = snapshots()
        labels = {row["case_id"]: row["expected_v1"]
                  for row in read_claims(DATA / "labelled_development_cases.csv")}
        self.assertEqual(len(imported["claims"]), 26)
        originals = {row["case_id"]: row for row in imported["decisions"]}
        self.assertEqual(len(originals), 26)
        self.assertEqual({row["case_id"]: row["expected"] for row in imported["validation_results"]}, labels)
        for row in imported["claims"]:
            raw = row["source_fields"]
            self.assertNotIn("expected_v1", raw)
            decision = decide(raw)
            self.assertEqual(originals[row["case_id"]], {
                **decision, "policy_clause": CLAUSES[decision["matched_rule"]]})

    def test_clause_text_comes_from_official_policy(self):
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with ZipFile(DATA / "policy_v1.docx") as policy:
            doc = ElementTree.fromstring(policy.read("word/document.xml"))
        paragraphs = {"".join(t.text or "" for t in p.findall(".//w:t", ns))
                      for p in doc.findall(".//w:p", ns)}
        self.assertTrue(set(CLAUSES.values()) <= paragraphs)

    def test_delimiter_stays_outside_input_text(self):
        text = "quoted ' and $seed_data$ and $seed_data_$"
        self.assertEqual(dollar_quote(text, "seed_data"), f"$seed_data__${text}$seed_data__$")


if __name__ == "__main__":
    unittest.main()
