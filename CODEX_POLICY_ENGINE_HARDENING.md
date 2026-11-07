# Codex Task: Harden the Taktile Hackathon Policy-Driven Claims Triage Engine

## Goal

Improve the **existing implementation** of our deterministic, dynamically configurable motor-claims triage engine. Its current classifications are not all correct. Audit the implementation against the **written fictional policy**, fix any policy-logic bugs, add strong validation and versioning, and produce **deeply inspectable, evidence-based explanations** for each recommendation.

**Do not replace the rules engine with a trained model.** The policy is the authority. The labelled development examples are regression tests, **not** a source from which to invent or optimize rules.

Work inside the current repository. Inspect its architecture first, retain working interfaces wherever practical, make focused improvements, and provide runnable tests and a short implementation summary.

## 0. NON-NEGOTIABLE DATA ACCESS RESTRICTION

**DO NOT OPEN, READ, PARSE, INSPECT, SAMPLE, SEARCH THROUGH, PRINT, LOAD, OR RUN INFERENCE ON ANY UNLABELLED CASE DATA.** This includes:

- `unlabelled_practice_cases.csv` **under any path**.
- Files with names such as `unlabeled*`, `unlabelled*`, `practice_cases*`, `hidden_cases*`, `evaluation_cases*`, `test_cases_hidden*`, or any private/hidden evaluation set.
- Copies, cached extracts, artifacts, previews, summaries, or generated outputs sourced from those files.

Do **not** use `head`, `tail`, `cat`, Python/Pandas, shell globs, `rg`, `grep`, or test/inference scripts that indirectly read these files. Exclude them from broad recursive content searches, batch runs, and automated test discovery. You may see their **filenames** in a directory listing; do not open their contents. **Do not access them even to verify that the engine works.**

**Permitted sources of truth and validation:**

1. `Participant policy v1 — Fictional motor claims triage.docx` (official rule specification; locate safely by filename if needed).
2. `20261105_Taktile_thinc! Hackathon Case Study.pdf` (official challenge and delivery requirements).
3. `labelled_development_cases.csv` (14 explicitly labelled *development* cases; permitted for tests only).
4. Existing repository **source code, tests, docs, and configuration**, provided they do not contain or embed unlabelled/hidden-case content. Inspect source files safely and exclude prohibited data paths.
5. New synthetic test cases **you construct from the policy**, without looking at any prohibited data.

If any existing code, job, or test automatically loads all CSVs or recursively scans datasets, **disable or narrow it** before running anything. Never ingest unlabelled data into an LLM context, prompt, debug log, or test report.

## 1. Understand the intended outcome

For each claim, recommend exactly one *next handling step*:

- `human_review`: a known rule demands specialist review.
- `request_information`: information required to apply the policy is absent or unreadable, and no known human-review trigger exists.
- `routine_processing`: no review trigger exists and required information is sufficient.

**`routine_processing` does NOT mean claim approval or payment.** Do not use words such as "approved", "covered", "paid", or "fraud proven" to describe the triage recommendation.

The `claim_summary` is descriptive only. **Structured fields are the source of truth** and determine the outcome. Do not infer or fill missing structured values from narrative text. Do not use an LLM to override or substitute for the written policy.

## 2. Encode the official policy v1 exactly

Apply rules in this **strict precedence order**:

### Priority 1: known human-review triggers

Return `human_review` if **any known** condition below is satisfied:

1. `policy_active_on_incident == False`.
2. `claim_type != "motor_own_damage"` (only when the claim type is known and readable).
3. `injury_reported == True`.
4. `liability_disputed == True`.
5. `duplicate_flag == True`.
6. `evidence_conflict == True`.
7. `quote_eur > 1500` (**strictly greater than**; €1,500.00 itself does not trigger review).

If there are several triggers, capture **all** of them in the audit trace, not just the first. For compatibility, select a **single deterministic primary `rule_id`** using the above documented ordering.

**CRITICAL:** A known human-review trigger takes priority over missing information. For example, an injury is reported and the incident-report field is blank → `human_review`, with the blank field also shown in the explanation.

### Priority 2: missing or unreadable information

If **no** human-review trigger is known, return `request_information` when required structured information is blank, absent, malformed, or unreadable, or when either:

- `incident_report_present == False`, or
- `itemized_quote_present == False`.

Do not collapse `unknown` into `False` or `True`. For instance, a blank `injury_reported` is **unknown**, not proof that there was no injury. A missing `quote_eur` is **unknown**, not €0.

Check the policy's wording regarding an absent *input field*. Treat unknowns in decision-bearing structured fields conservatively. `repair_type` is a recognized structured field: preserve and validate it, and document explicitly how its absence is handled under the policy's general missing-field rule. `claim_summary` alone must never overturn structured-data decisions. `case_id` and `case_status` are metadata with separate validation requirements (below).

If there are multiple missing fields, list all of them. Choose a stable primary missing-information `rule_id` for the output.

### Priority 3: routine processing

Return `routine_processing` **only if** no human-review rule matches **and** no required structured fact/document is missing.

**Important policy-specific caveats:**

- `repair_type == "ev_high_voltage_battery"` is **not by itself a human-review trigger in v1**. Do not invent such a trigger. It may become relevant only if the actual future policy change says so.
- Do not add fraud scoring, confidence thresholds, claim-summary sentiment, liability assumptions, or other unstated business rules.
- A `False` for one of `injury_reported`, `liability_disputed`, `duplicate_flag`, or `evidence_conflict` means that **that particular** trigger is not known to be present; it does not settle all other checks.

## 3. Data parsing and robust validation

Read CSVs by header names, **not positional indexes**. Expected fields from the labelled development schema are:

`case_id`, `case_status`, `claim_summary`, `policy_active_on_incident`, `claim_type`, `repair_type`, `quote_eur`, `incident_report_present`, `itemized_quote_present`, `injury_reported`, `liability_disputed`, `duplicate_flag`, `evidence_conflict`.

`expected_v1` appears in the **labelled development CSV only** and is the expected answer for testing; it is **not an input** to the decision function and must never leak into explanations or production recommendations.

Implementation requirements:

- Parse boolean strings carefully (e.g., `True`/`False` with case/whitespace normalization); do **not** use `bool("False")`. Any unsupported or empty token becomes *unknown* with a validation note, not a truthy value.
- Parse `quote_eur` as a finite decimal value (prefer `Decimal`); reject blank, invalid, non-finite, and negative amounts as unknown/invalid, never silently coerce them to zero. Avoid silent reinterpretation of ambiguous localized separators.
- Strip irrelevant whitespace from enums, but do not silently transform an unknown claim type into `motor_own_damage`.
- Handle missing CSV headers explicitly and consistently; if the row is still classifiable due to a known escalation trigger, preserve that conservative recommendation and report schema issues. Missing identifiers or invalid status must produce an explicit record-level validation issue rather than being guessed.
- Preserve `unknown` distinctly from a known `False` and from a known `True` in internal data structures and user-facing audit data.
- Define a consistent strategy for unexpected enum values: unknown/invalid values cannot be taken as evidence for routine processing. A known non-`motor_own_damage` claim type is a review trigger; a truly unreadable/absent claim type is an information gap. Document the distinction.
- Avoid crashes from malformed rows, missing keys, capitalization, empty strings, extra columns, or type mismatches. Return structured errors where valid output is impossible.
- Deterministic output: same validated input and same policy version must produce the same recommendation, rule ID, and substantive explanation.
- Never interpret the summary text as an alternative source of structured truth.

## 4. Dynamic, versioned policies (without hard-coded rewrite)

Keep the engine independent from policy data. Prefer a clear, checked JSON/YAML policy configuration or a small validated typed policy specification containing:

- immutable `version` and optional checksum/content hash;
- ordered rule definitions with stable IDs and human-readable descriptions;
- predicate operators (`eq`, `neq`, `gt`, `is_unknown`, etc.) with explicit type handling;
- priority for known human-review conditions before missing-information conditions;
- relevant numeric thresholds and enumerations;
- clear source attribution (policy section / rule).

**Do not execute policy text as arbitrary Python/JavaScript (`eval`, code injection, etc.).** Validate policy structure when loading. New versions must be separate immutable artifacts. Do not mutate or silently overwrite v1.

The actual v2 policy change is announced during the hackathon. **Do not invent it or reverse-engineer it from examples.** Build a way to load a genuinely supplied v2 configuration later, with the smallest possible code change. Before v2 is provided, report honestly that it is unavailable rather than pretending a made-up v2 is official.

When a real v2 arrives, allow policy-owner review/approval, run regression checks, and make differences inspectable at both the rule and case levels.

## 5. Open vs closed claims and recheck behavior

- **Open claims:** evaluate the applicable v1 and v2 rule sets; flag `needs_recheck` when the new policy affects a pending decision or its governing rule, even where the final recommendation happens to be unchanged. Record why it is affected. Do not naively define "affected" as only a changed label if rule applicability also matters.
- **Closed claims:** keep the original v1 decision and version intact. `recommendation_v2` must repeat the retained v1 recommendation; `needs_recheck` must be `False`; `rule_v2` should remain the retained v1 rule attribution. Do not quietly re-adjudicate closed cases.
- When a trustworthy previously persisted closed-case recommendation exists, use that historical immutable record rather than recomputing and replacing it. For a batch fixture with no historical decision record, state that the retained v1 classification is computed for the exercise.
- An absent/invalid `case_status` must not be assumed `open` or `closed`. Record it as a validation issue and avoid falsely claiming that a case was reopened or finalized.

Preserve an append-only audit/history record of the original machine recommendation, any reviewer override, its reason, reviewer identity, timestamp, and policy version. Never silently replace the original recommendation. Only the authorized policy owner should approve a new policy version.

## 6. Deep, inspectable explanations for **every** classification

I need a **complete factual justification** for why the system routed each case to its recommendation. This means a structured, reproducible **decision audit trail** rather than a generic one-line explanation or a language model's speculative reasoning.

For each evaluated case and each applicable policy version, generate a detailed JSON audit object (or equivalent structured representation), plus a readable explanation built **deterministically from that object**. The record should include:

1. `case_id`, `case_status`, `policy_version`, `policy_hash` (if available), final `recommendation`, and chosen stable `rule_id`.
2. **Observed structured evidence:** fields used by the rules, their parsed values, and whether each value is `known`, `missing`, or `invalid`; distinguish an explicit `False` from unknown.
3. **Complete rule evaluation:** each human-review trigger, the exact condition, observed input, and result `MATCH`, `NO_MATCH`, or `UNKNOWN`; show threshold and comparator explicitly (for example, `1500 > 1500` is `False`).
4. **Missing-information checks:** missing/unreadable fields and missing required documents, with the observed values that establish the gap.
5. **Priority resolution:** why an escalation superseded an information request, or why a missing-data result was chosen over routine processing.
6. **Conclusion:** a clear, compact-but-substantive prose summary naming all key reasons, with evidence values and policy references. For routine cases, explicitly document that all review triggers were tested and none matched, and that required information is present.
7. **Alternatives excluded:** concise policy-grounded explanation of why the other two next-step labels do not apply. Do not speculate about fraud, fault, insurance payout, or unsupported outcomes.
8. **Version differences (when v2 exists):** what exact rule(s) changed, whether this case matched an affected condition, how its classification/rule changed (if at all), why `needs_recheck` is true/false, and why closed cases remain unchanged.
9. **Validation and uncertainty:** all missing/invalid inputs, explicitly noting facts that were *not* determined.
10. **Traceability:** source rule IDs and original written policy version. If a reviewer changes a recommendation, show machine output and override separately with the recorded reviewer reason.

Do not output private/hidden LLM chain-of-thought, invented mental steps, or unsupported rationale. The requirement is **auditable rule evaluation with verifiable observed facts**, not a model's internal thought process.

### Example explanation style (synthetic case)

> **Recommendation: `human_review` (policy v1; primary rule `HR_INJURY`).** `injury_reported=True` matches the policy's injury review trigger. The incident report is missing (`incident_report_present=UNKNOWN`), which would normally cause `request_information`; however, under policy v1, a **known human-review trigger takes priority over missing documents**. Therefore the next step is human review. `routine_processing` is excluded because a human-review trigger is present. `request_information` alone is excluded because escalation has higher priority. The missing report remains an unresolved fact and is recorded for the reviewer. This recommendation **does not approve payment**.

Also provide a similarly detailed, evidence-backed explanation for `request_information` and `routine_processing`. Make structured traces accessible in the reviewer UI (e.g., expandable "Why this decision?" panels), and preserve a concise summary in the batch CSV's required `explanation` column. If technically feasible, provide a separate detailed audit JSONL/CSV artifact rather than stuffing everything into one spreadsheet cell.

## 7. Safe development and comprehensive tests

**Before making changes:** inspect the existing rules logic, parsing, precedence, data model, policy loader, output generation, and tests. Identify specific defects with references to the policy. Do not overfit implementation to the 14 examples.

### Allowed regression tests

Run the engine against `labelled_development_cases.csv` **only**, compare predictions to `expected_v1`, and report all mismatches by `case_id`, predicted label, expected label, primary rule, and a short cause. Goal: **14/14 correct under official v1**, without case-specific IDs or summary-text shortcuts. A 14/14 score is necessary but not proof of generalization.

### Synthetic policy-derived tests (write yourself)

Add tests covering at least:

- Quote below threshold, **exactly €1,500**, and above threshold.
- `ev_high_voltage_battery` with otherwise routine facts stays routine under v1.
- Each individual human-review trigger and multiple simultaneous triggers.
- An injury or other review trigger **plus** a blank document/field still produces `human_review`.
- Missing quote, missing itemized quote, missing incident report, blank/unknown boolean, unreadable claim type, malformed/negative/NaN/infinite quote, extra whitespace, and reordered CSV columns.
- Unknown vs explicit `False`; the string `"False"` must parse to `False`.
- Claim text contradictory to structured fields: structured fields control the output.
- Routine processing only when all requisite inputs are known and no review trigger matches.
- Closed claim remains unchanged after a policy update; open policy-affected claim gets appropriate `needs_recheck`; an unaffected open claim is not incorrectly flagged.
- Determinism; stable rule IDs; explanation values matching parsed facts; all three recommendations have complete traces.
- New policy config validation, version immutability, bad operators, and missing configuration.
- Reviewer override logging with actor/reason/version/time and original recommendation preserved.
- Required batch CSV schema and output completeness, including multi-row processing and partial input failures.

Use a **synthetic test-only v2** if needed for verifying the generic version-change machinery, clearly labelled as a *test fixture* and **not** the official hackathon policy v2. Never use it as the competition v2.

## 8. Quality reporting

For each real policy version available, report:

- Overall exact-match accuracy against **available labelled ground truth**.
- Confusion matrix among `human_review`, `request_information`, and `routine_processing`.
- Count and rate of **incorrect routine-processing recommendations** (clearly specify denominator, e.g., all evaluated cases and/or predicted-routine cases).
- Count and rate of **unnecessary human escalations** (define precisely, e.g., predicted `human_review` when true label is not `human_review`).
- Separate performance on cases affected by v2 **once official v2 labels/rules are available**.
- Number of claims with missing inputs and how they were handled.
- Where data or labels are unavailable, display `not measured` rather than fabricating a metric.

Never claim to know outcomes for unlabelled cases, never compute metrics on prohibited datasets, and never invent reviewer override statistics; the provided development data contains no override history.

## 9. Required batch interface

Preserve or implement a working CLI/service entry point that accepts an arbitrary future CSV of claims **without inspecting any unlabelled/practice/hidden data now**. It must emit a CSV with **exactly these required columns** (additional companion audit file is allowed):

`case_id, recommendation_v1, recommendation_v2, needs_recheck, rule_v1, rule_v2, explanation`

The judge will use a hidden CSV in this shape. Ensure output order and identifiers remain consistent, valid boolean serialization is clear, failures are surfaced, and the engine does not accidentally leak `expected_v1` or text guesses into decisions. When official v2 is supplied, produce proper v1/v2 values and closed-claim retention. Until then, do not fabricate an official v2.

## 10. Definition of done / final Codex response

Make actual code, configuration, and test improvements. Then report:

1. **Root causes found:** each invalid behavior, why it violated policy, and the specific fix.
2. **Architecture:** where the versioned policy config is stored; how the evaluation engine, validation, explanations, human overrides, and batch path work.
3. **Verification:** command(s) to run, labelled regression result (expected 14/14 if fully fixed), synthetic test results, any remaining failures or ambiguities. Do not conceal failures.
4. **Explanation example:** one detailed audit trace each for a synthetic routine case, missing-information case, and escalation-with-missing-data case.
5. **Change management:** how to add an official v2 config and compare its effects on *open* versus *closed* cases.
6. **Files changed:** concise list and usage instructions for demo and CSV export.
7. **Data-access confirmation:** explicitly state that **no unlabelled/practice/hidden case dataset was opened, parsed, or evaluated**.

**Priority order if time is short:** policy correctness → unknown/validation handling → versioned configuration → mandatory CSV path → detailed deterministic audit explanations → regression/synthetic tests → reviewer UI polish. Do not sacrifice correctness or violate the data-access restriction for a more visually polished interface.
