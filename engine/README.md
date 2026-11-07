# Hardened policy engine

Python 3.10+, standard library only. Run commands from the repository root. The policy remains deterministic; labels and narrative text never decide the route.

## Safe verification

The hardening task uses only the written policy, explicitly labelled development cases for regression, and newly constructed synthetic examples. The engine tests use those fixtures.

```powershell
python -m engine validate-v1
python -m unittest engine.tests.test_hardening backend.tests.test_reviewer -v
python -m engine test-policy engine/configs/policy_v1.json
```

Expected labelled result: 14/14 correct, zero incorrect routine referrals and zero unnecessary escalations, with denominator 14. The report includes the confusion matrix and handling of missing inputs. This is a small development sample, not evidence of production generalization. Candidate independent accuracy is **not measured** without legitimate labels.

## Run an assessment

```powershell
python -m engine decide engine/tests/fixtures/synthetic_claims.csv SYN-INJURY --policy engine/configs/policy_v1.json
python -m engine batch engine/tests/fixtures/synthetic_claims.csv outputs/hardening/synthetic-results.csv --audit outputs/hardening/synthetic-audit.jsonl
```

Batch with `--audit` retains invalid rows with diagnostics and returns a nonzero exit code. The compatibility batch without `--audit` atomically writes the original clause-level CSV when all records succeed.

Each detailed result includes all structured facts with `known`, `missing` or `invalid` state; every predicate's exact input, comparator and result (`MATCH`, `NO_MATCH`, `UNKNOWN`); unresolved facts/documents; priority resolution; alternatives excluded; source references; hashes; and a deterministic factual explanation. The compact CSV explanation contains decisive comparisons; the companion JSONL preserves the full audit.

CSV columns remain exactly:

```text
case_id,recommendation_v1,recommendation_v2,needs_recheck,rule_v1,rule_v2,explanation
```

Until a candidate is explicitly supplied, open v2 fields are blank. A closed fixture retains its computed v1 result with `False`, explicitly described as an exercise classification when there is no historical record.

## Policy changes

The original `engine/configs/policy_v1.json` is unchanged. Its canonical SHA-256 hash is pinned; altered content cannot reuse `v1`. Copy it to a separate file with a new version to encode a genuinely supplied amendment. Add `source` at policy/rule level to cite the actual amendment. Do not present synthetic fixtures as official v2.

```powershell
python -m engine compare --input engine/tests/fixtures/synthetic_claims.csv --v2 engine/tests/fixtures/v2_hypothetical_threshold.json --output outputs/hardening/synthetic-comparison.csv --audit outputs/hardening/synthetic-comparison.jsonl --report outputs/hardening/synthetic-impact.json
```

This command uses an explicitly hypothetical test fixture. For an actual change, substitute the genuinely supplied policy path. Comparison binds policy ID/version/hash in `engine/.local/policy-registry.sqlite3`; changed content must use another version. `--registry PATH` selects a separate registry for isolated tests. These bindings are append-only and do not activate policies.

Open cases are flagged when their recommendation changes or amended rule applicability/required evidence changes, even if the route stays unchanged. Closed cases never run through v2. `compare_policies(..., historical={case_id: persisted_decision})` and `baseline_report(..., historical=...)` verify identity, input fingerprint and original policy hash and reuse trusted closed records without evaluating them again. The browser supplies historical records from its database; standalone CSV fixtures have no stored history.

Supported rule operators: `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `in`, `is_known`, `is_missing`, with `all`/`any`/`not`. Human review outranks information requests; lower numeric priority wins within an outcome. IDs and priorities must be unique. Unknown handling and all required structured fields are validated. No arbitrary expression execution is allowed.

Readable claim types other than `motor_own_damage` trigger review. Blank/unreadable claim types request information unless another review trigger is known. Recognized v1 repair types are `standard` and `ev_high_voltage_battery`; neither alone triggers v1 review. An absent or unsupported repair type is an information gap. Future configs can declare `enumerations: {"repair_type": [...]}`. Unknown and invalid values remain distinct from Boolean `False`.

Boolean inputs accept JSON Booleans or case-insensitive, trimmed `true`/`false`; unsupported tokens are invalid. Quotes use finite nonnegative `Decimal` values. Ambiguous localized separators are not reinterpreted. Metadata requires a nonempty string ID and explicit `open`/`closed` status. Extra columns are ignored with a schema note; development labels are excluded from raw evidence, explanations and hashes.

## Partial failures

Missing structured CSV headers become unknown facts with schema notes. A known review trigger still wins. Invalid identity/status, duplicate IDs and structurally malformed records produce a row with blank recommendation/rule/recheck fields and an explicit `VALIDATION_ERROR`; valid rows continue in input order. The JSONL contains structured errors. Blank error outcomes are intentional, not a fourth handling recommendation. CLI exit code is `1` when any row fails.

Duplicate/ambiguous headers or malformed CSV quoting that prevents reliable row boundaries fail the whole file without replacing existing output. Success is `0`; input/policy/I/O/quality failure is `1`; invalid command syntax is `2`. No row is silently dropped. CSV replacement is atomic after parsing; companion audit/report writes are separate artifacts.

## Integration

`parse_claim`, `load_policy`, `evaluate`, `compare_policies`, and `export_required_csv` are available from `engine`. Evaluation performs no I/O or timestamp generation. `decide(claim)` returns the existing seven-field v1 contract. Use `assess_v1(claim)` for a full private v1 audit, granular rule IDs and employee explanations. `decision_summary(assessment)` produces the seven-field view from that same evaluation. Machine timestamps are added when persisting results.

See [hardening findings and examples](HARDENING_REPORT.md) and [browser instructions](../backend/README.md).
