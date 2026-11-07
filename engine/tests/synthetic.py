"""New policy-derived fixtures; no evaluation data is used."""
BASE = dict(case_id="SYN-BASE", case_status="open", claim_summary="Synthetic narrative ignored by routing",
            policy_active_on_incident="true", claim_type="motor_own_damage", repair_type="standard",
            quote_eur="900", incident_report_present="true", itemized_quote_present="true",
            injury_reported="false", liability_disputed="false", duplicate_flag="false", evidence_conflict="false")


def candidate(policy, version="synthetic-test-v2"):
    config = policy.config
    config["version"] = version
    config["source"] = "Synthetic test-only amendment, not official v2"
    config["rules"][6]["if"]["value"] = "1300"
    config["rules"][6]["reason"] = "Synthetic threshold above 1300"
    return config
