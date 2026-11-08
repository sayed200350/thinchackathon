"""Apply an uploaded policy version to every claim in Supabase.

POST /api/policies/{version}/apply

1. Read the uploaded policy text (``policies.content``) and the baseline it amends.
2. Interpret the text once with the configured LLM into a deterministic engine configuration.
   The model output is untrusted: every changed or added rule needs a verbatim citation from the
   documents, the configuration must pass the engine's strict validation and generated safety
   checks. Otherwise nothing is written. The accepted configuration is stored immutably in
   ``policy_configs``; later runs of the same version reuse it without calling the model again.
3. Evaluate every current claim with the engine (closed claims keep their baseline decision),
   upsert one ``decisions`` row per open claim for this version and append a ``policy_runs`` row.

The service role key stays on the server; the browser only calls this endpoint.
"""
import base64
import hashlib
import http.client
import json
import os
import ssl
import sys
from urllib.parse import urlencode, urlsplit

from engine.conformance import BASE, run_checks
from engine.docx_policy import _paragraphs
from engine.impact import compare_policies
from decimal import Decimal

from engine.policy import FIELDS, _evidence_value
from engine.runtime import evaluate, fingerprint, load_policy, parse_claim, policy_from_dict

from .adaptation import ROOT, validate_interpretation
from .ai_service import AIUnavailable, configured_interpreter, validate_output
from .store import RequestError
from .supabase_seed import CLAUSES as V1_CLAUSES

PAGE_SIZE = 1000
ROUTE_STEP = {"human_review": "1", "request_information": "2", "routine_processing": "3"}
UNKNOWN_RULE, ROUTINE_RULE = "INFO_UNKNOWN_REQUIRED_FACT", "ROUTINE_ALL_CHECKS_PASSED"


def _service_key(key):
    if key.startswith("sb_secret_"):
        return True
    try:
        _, payload, _ = key.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return isinstance(claims, dict) and claims.get("role") == "service_role"
    except (ValueError, UnicodeError):
        return False


class ServiceClient:
    """Minimal Supabase Data API client with the service role (server side only)."""

    def __init__(self, url, key):
        location = urlsplit((url or "").strip())
        if location.scheme != "https" or not location.hostname or location.path not in ("", "/"):
            raise RequestError(503, "SUPABASE_URL must be an HTTPS project URL.")
        key = (key or "").strip()
        if not key or not _service_key(key) or any(c.isspace() for c in key):
            raise RequestError(503, "Policy apply needs SUPABASE_SERVICE_ROLE_KEY (secret key) in the server .env.")
        self.host, self.port, self._key = location.hostname, location.port, key
        self._tls = ssl.create_default_context()
        if (sys.platform == "darwin" and not self._tls.get_ca_certs() and os.path.isfile("/etc/ssl/cert.pem")
                and not (os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"))):
            self._tls.load_verify_locations(cafile="/etc/ssl/cert.pem")

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))

    def _call(self, method, resource, params=None, body=None, prefer=None):
        path = "/rest/v1/" + resource + ("?" + urlencode(params) if params else "")
        headers = {"apikey": self._key, "Authorization": "Bearer " + self._key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        connection = http.client.HTTPSConnection(self.host, self.port, timeout=20, context=self._tls)
        try:
            connection.request(method, path, headers=headers,
                               body=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"))
            response = connection.getresponse()
            raw = response.read(32 * 1024 * 1024)
            data = json.loads(raw) if raw else None
        except (ValueError, OSError, http.client.HTTPException) as error:
            raise RequestError(503, "Supabase is unavailable. Please retry.") from error
        finally:
            connection.close()
        if response.status == 409 or (isinstance(data, dict) and data.get("code") == "23505"):
            raise Conflict()
        if response.status == 404 and isinstance(data, dict) and data.get("code") == "42P01":
            raise RequestError(503, "Run contract/db/policy_runs.sql in the Supabase SQL editor first.")
        if response.status not in (200, 201, 204, 206):
            code = data.get("code") if isinstance(data, dict) else None
            if code in ("42P01", "PGRST205"):
                raise RequestError(503, "Run contract/db/policy_runs.sql in the Supabase SQL editor first.")
            raise RequestError(503, f"Supabase rejected the request ({response.status}{', ' + code if code else ''}).")
        return data

    def select(self, resource, columns, order, **filters):
        rows, offset = [], 0
        while True:
            page = self._call("GET", resource, dict(filters, select=columns, order=order + ".asc",
                                                    limit=PAGE_SIZE, offset=offset))
            if not isinstance(page, list):
                raise RequestError(503, "Supabase returned an invalid row set.")
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            offset += PAGE_SIZE

    def insert(self, resource, rows, on_conflict=None):
        params = {"on_conflict": on_conflict} if on_conflict else None
        prefer = "return=minimal" + (",resolution=merge-duplicates" if on_conflict else "")
        self._call("POST", resource, params, rows, prefer)


class Conflict(Exception):
    pass


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _baseline_clauses(baseline_version, configs):
    """Policy text per engine rule id of the baseline (used for rules the new text leaves unchanged)."""
    if baseline_version == "v1":
        clauses = {rule["id"]: V1_CLAUSES["v1.1" if rule["then"] == "human_review" else "v1.2"]
                   for rule in load_policy().config["rules"]}
        clauses.update({UNKNOWN_RULE: V1_CLAUSES["v1.missing"], ROUTINE_RULE: V1_CLAUSES["v1.3"]})
        return clauses
    return dict(configs[baseline_version]["interpretation"].get("clauses", {}))


def _safety(candidate):
    """Generated engine checks plus the invariant that a missing fact never routes routinely."""
    problems = []
    checks = run_checks(candidate)
    if checks["failed"]:
        problems.append(f"{checks['failed']} generated boundary/precedence checks failed.")
    for field in candidate.config["unknown_handling"]["required_fields"]:
        if evaluate(parse_claim(dict(BASE, **{field: None})), candidate, _detail=False)["recommendation"] == "routine_processing":
            problems.append(f"A missing {field} would be routed to routine processing.")
    return problems


APPLY_GUIDANCE = """
Implementation details are yours to choose and are NOT ambiguities: the identifier of a new rule
(use an uppercase ID with the prefix of its route, e.g. HR_ or INFO_) and its integer priority
(unique; place it with the other rules of the same route). Rules of the same route lead to the same
recommendation, so their relative order never changes an outcome. Route precedence (human_review
before request_information before routine_processing) is fixed by the engine. Report an ambiguity
only when the documents leave the resulting recommendation for some claim genuinely unclear.
Quote amounts exactly as written; a limit that a quote may equal but not exceed is operator gt."""
APPLY_TIMEOUT_SECONDS = 120


def apply_interpreter():
    """The configured model with apply-specific guidance and a longer timeout (reasoning models)."""
    base = configured_interpreter()

    class Interpreter(type(base)):
        def request_spec(self, content):
            url, auth, payload = super().request_spec(content)
            if "systemInstruction" in payload:
                payload["systemInstruction"]["parts"][0]["text"] += APPLY_GUIDANCE
            else:
                payload["messages"][0]["content"] += APPLY_GUIDANCE
            return url, auth, payload

    interpreter = Interpreter()
    interpreter.timeout = APPLY_TIMEOUT_SECONDS
    return interpreter


def interpret(policy_row, baseline, baseline_text, baseline_clauses, interpreter=None):
    """Return (config, interpretation) or raise RequestError(422) with the reasons."""
    version, text = policy_row["version"], policy_row["content"]
    try:
        value = validate_output((interpreter or apply_interpreter()).interpret(
            baseline_text, text, baseline.config, version))
    except AIUnavailable as error:
        raise RequestError(503, str(error)) from None
    except (ValueError, TypeError):
        raise RequestError(502, "The policy interpreter returned an invalid structured response. Nothing was written.") from None
    # The version label and policy family are ours, not the model's: a model that renames
    # "Version 2" to "v2" must not invalidate an otherwise correct interpretation.
    try:
        proposed = json.loads(value["config_json"]) if value["config_json"] else None
    except ValueError:
        proposed = None
    if isinstance(proposed, dict):
        proposed.update(version=version, policy_id=baseline.config["policy_id"])
        value["config_json"] = json.dumps(proposed)
    validation, candidate = validate_interpretation(value, baseline, version, baseline_text, text)
    problems = list(validation["errors"]) + list(value["ambiguities"])
    if candidate is not None and validation["valid"]:
        problems += _safety(candidate)
    if problems or candidate is None:
        raise Rejected({"error": "The policy text could not be turned into engine rules reliably. Nothing was written.",
                        "problems": problems, "summary": value["summary"], "citations": value["citations"]})
    clauses = dict(baseline_clauses)
    for citation in value["citations"]:
        if not citation["target"].startswith("setting:") and citation["new_quote"].strip():
            clauses[citation["target"]] = citation["new_quote"].strip()
    interpretation = {"summary": value["summary"], "citations": value["citations"],
                      "policy_diff": validation["policy_diff"], "clauses": clauses,
                      "model": os.environ.get("AI_MODEL", ""), "provider": os.environ.get("AI_PROVIDER", "")}
    return candidate.config, interpretation


class Rejected(Exception):
    def __init__(self, payload):
        super().__init__(payload["error"])
        self.payload = payload


def rule_names(policy):
    """Readable name per engine rule id (the rule's reason), used by the dashboard."""
    names = {rule["id"]: rule["reason"].rstrip(".") for rule in policy.config["rules"]}
    names.update({UNKNOWN_RULE: "Required facts missing or unreadable", ROUTINE_RULE: "All checks passed"})
    return names


def _step_rule(version, outcome, primary):
    if outcome == "request_information" and primary == UNKNOWN_RULE:
        return f"{version}.missing"
    return f"{version}.{ROUTE_STEP[outcome]}"


def decision_row(after, candidate, clauses):
    """One reviewer-facing decisions row, in the same shape as the seeded v1 rows."""
    outcome, primary = after["recommendation"], after["primary_rule_id"]
    rules = {rule["id"]: rule for rule in candidate.config["rules"]}
    matched = [t for t in after["trace"] if t["result"] is True and t["outcome"] == outcome]
    facts = after["normalized_facts"]
    missing = after["missing_or_invalid_fields"]
    if outcome == "human_review":
        reasons = [rules[t["rule_id"]]["reason"].rstrip(".") for t in matched]
        explanation = "Human review required because " + " and ".join(r[0].lower() + r[1:] for r in reasons) + "."
        fields = [f for t in matched for f in t["observed"]]
    elif outcome == "request_information":
        parts = ["missing " + FIELDS[f] for t in matched for f in t["observed"]]
        parts += ["missing or unreadable " + FIELDS[f] for f in missing]
        explanation = "Request information: " + ", ".join(parts) + "."
        fields = [f for t in matched for f in t["observed"]] + list(missing)
    else:
        explanation = (f"The €{facts['quote_eur']} own-damage claim has active cover, both required "
                       "documents and no review trigger, so it can enter routine processing.")
        fields = list(facts)
    support = {}
    for field in fields:
        value = facts.get(field)
        support[field] = _evidence_value(Decimal(value)) if field == "quote_eur" and value is not None else value
    return {"case_id": after["case_id"], "policy_version": candidate.version, "case_status": after["case_status"],
            "recommendation": outcome, "matched_rule": _step_rule(candidate.version, outcome, primary),
            "supporting_facts": support, "explanation": explanation + f" ({candidate.version}, rule {primary})",
            "policy_clause": clauses.get(primary) or clauses.get(ROUTINE_RULE)}


def apply_policy(client, version, interpreter=None):
    version = (version or "").strip()
    policies = {row["version"]: row for row in client.select("policies", "version,name,content,created_at", "created_at")}
    target = policies.get(version)
    if target is None:
        raise RequestError(404, f"Policy {version} has not been uploaded.")
    if version == "v1":
        raise RequestError(400, "v1 is the baseline every claim was decided with; upload a new version to apply.")
    if not (target.get("content") or "").strip():
        raise RequestError(400, f"Policy {version} has no text yet. Upload the file first.")
    configs = {row["version"]: row for row in client.select(
        "policy_configs", "version,baseline_version,config,config_hash,source_hash,interpretation,created_at", "created_at")}
    source_hash = text_hash(target["content"])
    stored = configs.get(version)
    if stored:
        if stored["source_hash"] != source_hash:
            raise RequestError(409, f"Policy {version} was already applied with a different text. Upload it as a new version.")
        baseline_version = stored["baseline_version"]
    else:
        # The newest already-applied version uploaded before this one, otherwise v1.
        earlier = [v for v in configs if policies.get(v) and policies[v]["created_at"] < target["created_at"]]
        baseline_version = max(earlier, key=lambda v: policies[v]["created_at"]) if earlier else "v1"
    baseline = load_policy() if baseline_version == "v1" else policy_from_dict(configs[baseline_version]["config"])
    created = False
    if stored:
        candidate = policy_from_dict(stored["config"])
        interpretation = stored["interpretation"]
    else:
        baseline_row = policies.get(baseline_version) or {}
        baseline_text = (baseline_row.get("content") or "").strip()
        if not baseline_text and baseline_version == "v1":
            baseline_text = "\n".join(_paragraphs((ROOT / "data/taktile/policy_v1.docx").read_bytes()))
        config, interpretation = interpret(target, baseline, baseline_text,
                                           _baseline_clauses(baseline_version, configs), interpreter)
        candidate = policy_from_dict(config)
        try:
            client.insert("policy_configs", [{
                "version": version, "policy_id": config["policy_id"], "baseline_version": baseline_version,
                "config": config, "config_hash": candidate.fingerprint, "source_hash": source_hash,
                "interpretation": interpretation}])
            created = True
        except Conflict:
            # A parallel click stored it first; always continue with the stored configuration.
            stored = next(r for r in client.select("policy_configs", "version,config,interpretation", "version",
                                                   version="eq." + version))
            candidate, interpretation = policy_from_dict(stored["config"]), stored["interpretation"]

    claims = client.select("claims", "case_id,case_status,source_fields", "case_id")
    rows = [dict(row["source_fields"] or {}, case_id=row["case_id"], case_status=row["case_status"]) for row in claims]
    report = compare_policies(baseline, candidate, rows)
    clauses = interpretation.get("clauses", {})
    decisions = [decision_row(case["candidate"], candidate, clauses)
                 for case in report["cases"] if "candidate" in case and not case.get("closed_retained")]
    if decisions:
        client.insert("decisions", decisions, on_conflict="case_id,policy_version")
    before_names, after_names = rule_names(baseline), rule_names(candidate)
    changed = sum(1 for case in report["cases"] if case.get("recommendation_changed") and not case.get("closed_retained"))
    run = {"version": version, "baseline_version": baseline_version, "config_hash": candidate.fingerprint,
           "claims_total": len(rows), "open_evaluated": len(decisions),
           "closed_retained": report["closed_retained"], "changed": changed,
           "needs_recheck": report["affected_open_cases"],
           "rows": [dict(row, rule_v1_name=before_names.get(row["rule_v1"], row["rule_v1"]),
                         rule_v2_name=after_names.get(row["rule_v2"], row["rule_v2"])) for row in report["rows"]]}
    client.insert("policy_runs", [run])
    return {**run, "config_created": created, "errors": report["errors"],
            "summary": interpretation.get("summary"), "citations": interpretation.get("citations", []),
            "policy_diff": interpretation.get("policy_diff"), "rules": candidate.config["rules"]}
