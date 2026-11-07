"""Print an atomic PostgreSQL seed for the official v1 hackathon datasets."""

import json
from pathlib import Path

from engine import ROUTES, decide
from engine.batch import read_claims
from engine.policy import FIELDS


DATA = Path(__file__).resolve().parents[1] / "data" / "taktile"
CLAUSES = {
    "v1.1": "1. Send to human_review if the policy was not active on the incident date; "
            "claim_type is not motor_own_damage; injury_reported, liability_disputed, "
            "duplicate_flag or evidence_conflict is true; or quote_eur is greater than €1,500.",
    "v1.2": "2. Otherwise, send to request_information if incident_report_present or "
            "itemized_quote_present is false.",
    "v1.3": "3. Otherwise, send to routine_processing. This means the case may enter the "
            "insurer’s normal downstream process. It does not mean payment is approved.",
    "v1.missing": "If an input field is absent or unreadable, do not invent a value. Request "
                  "information unless another known fact already requires human review. Some "
                  "development and evaluation cases have blank fields; treat a blank as an absent fact.",
}

# List only imported columns. Database-owned timestamps keep their defaults.
TABLES = {
    "claims": ("case_id", "case_status", "claim_summary", "source_fields"),
    "decisions": ("case_id", "policy_version", "case_status", "recommendation", "matched_rule",
                  "supporting_facts", "explanation", "policy_clause"),
    "validation_results": ("case_id", "policy_version", "expected", "expected_change", "source"),
}


def snapshots(data_dir: Path = DATA) -> dict:
    result = {table: [] for table in TABLES}
    seen = set()
    for filename, labelled in (("labelled_development_cases.csv", True),
                               ("unlabelled_practice_cases.csv", False)):
        for row in read_claims(data_dir / filename):
            decision = decide(row, "v1")
            case_id = decision["case_id"]
            if case_id in seen:
                raise ValueError(f"Duplicate case_id across input files: {case_id}.")
            seen.add(case_id)
            source = {key: row.get(key) for key in ("case_id", "case_status", "claim_summary", *FIELDS)}
            result["claims"].append({"case_id": case_id, "case_status": decision["case_status"],
                                     "claim_summary": source["claim_summary"], "source_fields": source})
            result["decisions"].append({**decision, "policy_clause": CLAUSES[decision["matched_rule"]]})
            if labelled:
                label = row.get("expected_v1")
                if label not in ROUTES:
                    raise ValueError(f"{case_id}: invalid development label.")
                result["validation_results"].append({"case_id": case_id, "policy_version": "v1",
                                                     "expected": label, "expected_change": None,
                                                     "source": "labelled"})
    return result


def dollar_quote(value: str, tag: str) -> str:
    while f"${tag}$" in value:
        tag += "_"
    delimiter = f"${tag}$"
    return delimiter + value + delimiter


def seed_sql(data_dir: Path = DATA) -> str:
    # A single DO statement is atomic in the dashboard and in ordinary psql.
    # Dollar-quote both nesting levels so CSV text remains data regardless of SQL settings.
    data = json.dumps(snapshots(data_dir), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    statements = [
        "DECLARE",
        f"    payload jsonb := {dollar_quote(data, 'seed_data')}::jsonb;",
        "    conflicting_id text;",
        "BEGIN",
        "    LOCK TABLE public.claims, public.decisions, public.validation_results "
        "IN SHARE ROW EXCLUSIVE MODE;",
    ]
    for table, columns in TABLES.items():
        fields = ", ".join(columns)
        source = f"jsonb_populate_recordset(NULL::public.{table}, payload->'{table}')"
        key = "case_id" if table == "claims" else "case_id, policy_version"
        existing = ", ".join("saved." + col for col in columns)
        incoming = ", ".join("seed." + col for col in columns)
        statements.append(f"""
    INSERT INTO public.{table} ({fields})
        SELECT {fields} FROM {source}
        ON CONFLICT ({key}) DO NOTHING;
    SELECT seed.case_id INTO conflicting_id FROM {source} AS seed
    WHERE NOT EXISTS (
        SELECT 1 FROM public.{table} AS saved
        WHERE saved.case_id = seed.case_id
          AND ROW({existing}) IS NOT DISTINCT FROM ROW({incoming})
    ) LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Existing {table} snapshot differs for case %. Seed rolled back.', conflicting_id;
    END IF;""")
    statements.append("END;")
    return "DO " + dollar_quote("\n".join(statements), "policy_seed") + ";"


if __name__ == "__main__":
    print(seed_sql())
