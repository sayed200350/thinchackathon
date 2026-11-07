# Policy engine hardening report

## Findings and fixes

| Root cause | Policy or audit failure | Implemented fix |
| --- | --- | --- |
| Missing and invalid values shared a null representation with generic warnings | A reviewer could not distinguish absent evidence from malformed evidence or explicit False | Each fact records raw value, parsed value, `known`/`missing`/`invalid` state and a validation issue; predicates retain three-valued logic |
| Arbitrary repair categories were treated as complete evidence | Unsupported structured categories could reach routine processing | Validate the two v1 repair categories; unsupported/absent values request information unless review wins; future enumerations are declarative |
| Boolean aliases such as `yes`/`0` were silently accepted | Unspecified tokens could establish a false/no-trigger condition | Accept only actual Boolean values and trimmed case-insensitive true/false strings |
| Entire raw rows were copied into decisions | `expected_v1`, narrative and extra fields leaked into audit evidence | Explicit structured-field allowlist; labels and narrative do not affect or appear in decision evidence |
| Legacy explanation discarded information gaps when escalation won | Known injury plus missing report lost relevant uncertainty | One evidence-driven audit/explanation implementation shared by `evaluate`, legacy `decide`, API and batch |
| Traces contained only IDs and Boolean/null results | Missing exact comparisons, source references and alternatives | Full predicate trees, observed input states, comparators/thresholds, MATCH/NO_MATCH/UNKNOWN, priority resolution and excluded routes |
| Strict schema errors stopped classifiable rows; metadata errors stopped entire batches | Missing headers obscured known review triggers and valid later rows | Schema notes + conservative evaluation; explicit record errors with one output row per recoverable input row; nonzero CLI exit on partial failure |
| Closed replay recomputed v1 and called it historical | Stored immutable decisions were not actually reused | Trusted history with identity/input/policy-hash verification; no reevaluation for stored closed cases; fixture-only results clearly marked computed |
| A new hash did not stop reusing a version name | Policy identity could silently refer to different content | Unchanged v1 config pinned by hash; append-only CLI and server version registries reject content conflicts |
| No authenticated owner policy-review event | Candidate previews lacked approval control | Credential-gated owner review, conformance checks, immutable version binding, append-only actor/reason/time/hash event; no automatic activation |
| Startup/tests loaded non-development datasets and old caches | Incompatible with this hardening task's data-access restriction | Six new synthetic startup fixtures, fresh database, and replacement regression suites restricted to synthetic and labelled development data |

The core v1 review ordering and strict `>1500` boundary already matched the written policy. No business rules were inferred from labels. No case-specific routing shortcuts were introduced. The EV repair category remains routine-eligible under v1 when all other conditions permit it.

## Architecture and traceability

- `engine/configs/policy_v1.json`: original bytes retained; canonical hash `5421f441d3f296fb6951661922d106b77078c59b54b4a2815b42218c7e1fa38a` pinned in the loader.
- `engine/runtime.py`, `engine/policy.py`: normalization, metadata validation, typed policy validation, three-valued predicates, immutable parsed evidence, pure evaluator and legacy API adapter.
- `engine/audit.py`: factual predicate trees, written-policy attribution, uncertainty, precedence and deterministic explanations. Full results contain no labels or narrative evidence.
- `engine/batch.py`, `engine/impact.py`, `engine/__main__.py`: shared CSV parser, partial-row errors, detailed replay/diffs, trusted closed history, exact CSV and JSONL export.
- `engine/metrics.py`: labelled accuracy/confusion/error rates, mismatch causes, and missing-input handling. All rates explicitly use total labelled cases as denominator.
- `engine/registry.py`, `backend/policies.py`: immutable version bindings; server-side owner review and approval events.
- `backend/store.py`: timestamped original machine record plus separate append-only reviewer corrections. The default fresh database contains synthetic data only.
- `backend/workbench.py`, `backend/web/`: browser evidence inspection, full JSON/JSONL downloads, partial-error visibility, stored-history replay and owner-review form.
- `engine/tests/test_hardening.py`, `backend/tests/test_reviewer.py`: policy-derived and permitted labelled regression tests; old tests that loaded other datasets were replaced.

## Synthetic explanation examples

The full reproducible records are in `engine/examples/hardening-audits.jsonl`. They use active policy, own-damage claim type, standard repair, EUR 900 quote, both documents present and all review flags False unless changed below.

**Routine:** `SYN-AUDIT-ROUTINE` returns `routine_processing`, primary `ROUTINE_ALL_CHECKS_PASSED`. The trace explicitly checks inactive-policy=False, non-own-damage=False, each of injury/dispute/duplicate/conflict=False, and `900 > 1500 = False`. Both document-absence predicates are False. All ten facts are known, so review and information request are excluded.

**Missing information:** `SYN-AUDIT-MISSING` has a blank quote. It returns `request_information`, primary `INFO_UNKNOWN_REQUIRED_FACT`. Quote evidence is `state=missing`, `parsed_value=null`; its threshold predicate is `UNKNOWN`. All other review triggers are `NO_MATCH`. No known review reason exists, while the quote remains unresolved, so routine processing is excluded. UNKNOWN is not asserted to be False.

**Escalation with missing data:** `SYN-AUDIT-INJURY` has `injury_reported=True` and blank `incident_report_present`. It returns `human_review`, primary `HR_INJURY`. The injury condition is `True == True = True` (`MATCH`, policy v1 rule 1). The report is `missing`; its absence predicate is `UNKNOWN`. Both the review reason and unresolved report are recorded. Known review takes priority over an information request; routine is excluded because the injury trigger matches.

All examples provide the full nine-rule trace, observed values, policy hash, source references, missing-information checks, alternatives and deterministic conclusion. They recommend a handling step, not payment.

## Verification and limitations

Run `python -m unittest engine.tests.test_hardening backend.tests.test_reviewer -v`, `python -m engine validate-v1`, and optionally `node --check backend/web/workbench.js`.

All **24 hardening tests pass**, including their individual trigger, parser and validation subcases; JavaScript syntax checks pass. Synthetic CSV and comparison commands also complete with the required seven columns and companion audits. The labelled regression is **14/14**, with **0/14 incorrect routine referrals**, **0/14 unnecessary escalations**, no mismatches, and two cases with unknown structured facts correctly handled. The saved independent regression report is `eval/hardening-development.json`. These results are not a generalization claim. Candidate accuracy is **not measured**. Synthetic predicate tests are conformance checks, not independent ground truth.

Known boundaries: generated checks cover predicate leaves and selected precedence interactions, not exhaustive compound-rule combinations. Unsupported schemas fail validation. Ambiguous whole-file CSV syntax fails atomically; recoverable record errors get explicit blank outcomes and a nonzero exit. Separate companion files are not a multi-file transaction. Historical records lacking identity/input/policy hashes need a separately reviewed migration; they are rejected rather than silently replaced. Owner approval is a review event, not production deployment. Browser layout was not visually verified because browser automation was unavailable.

## Change management and use

Start with `python -m backend --open`, then visit http://127.0.0.1:8765. Choose a synthetic claim and expand **Why this decision?**. Machine output and reviewer correction history remain separate.

Encode an actual supplied v2 in a new file/version with source references. Validate it, inspect generated conformance results and compare synthetic/authorized inputs with the CLI or browser. Open claims get independent recommendation-change and rule-impact flags. Stored closed claims are retained verbatim; CSV fixtures without history retain an explicitly computed exercise result. Only the configured owner credential can record review approval; no policy is activated automatically.

Example safe export: `python -m engine batch engine/tests/fixtures/synthetic_claims.csv outputs/hardening/synthetic-results.csv --audit outputs/hardening/synthetic-audit.jsonl`.

## Data-access confirmation

During this hardening task, no unlabelled/practice/hidden case dataset or cached output derived from those datasets was opened, parsed or evaluated. The only case-data reads used for verification were the explicitly labelled development CSV and new synthetic fixtures. Earlier work in this conversation predates this restriction; its old database and generated outputs were left untouched and were not used for this task.
