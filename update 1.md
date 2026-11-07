# Update 1 — Explainable Insurance Triage Decisions

## Task for Claude / Coding Agent

Improve the existing **“Why this decision?”** experience in our Taktile thinc! Hackathon insurance claims platform. The deterministic, dynamically configurable insurance triage engine is already working on the 14 labelled development cases. **Do not rebuild it, retrain it, or change its classification logic unless a clearly demonstrated violation of the official policy requires a narrowly scoped fix.**

This update is exclusively about making each recommendation understandable, evidence-based, traceable, and easy to audit. Do not modify the AI chatbot or unrelated screens.

## 0. Source of truth and hard restrictions

1. Use **`Participant policy v1 — Fictional motor claims triage.docx`** as the authority for v1 decision behavior; use **`20261105_Taktile_thinc! Hackathon Case Study.pdf`** for judging and output requirements. Locate the actual filenames in the repository if necessary.
2. Use **`labelled_development_cases.csv`** (14 cases) only to verify that classification outputs remain unchanged and correct. Labels are *not* learned rules.
3. **Do not open, read, parse, sample, analyze, test against, or derive anything from `unlabelled_practice_cases.csv` or any hidden evaluation file**. Avoid broad data-file globbing or scripts that accidentally read those files. Use policy-derived synthetic fixtures for edge cases.
4. The structured claim fields, not `claim_summary`, determine classifications. Never infer a blank field from narrative text. Never invent facts.
5. The engine recommends a *next handling step*, not payment approval or rejection.
6. Do not create a second classification implementation inside the frontend, explanation generator, or LLM.

## 1. User-facing outcome

When a reviewer clicks a case and selects **“Why this decision?”**, show the following, in this order:

### A. Immediate decision summary (always visible)

- Clearly name and describe one of `routine_processing`, `request_information`, or `human_review`.
- Provide **one or two plain-language sentences** stating the actual decisive fact(s), numerical thresholds where relevant, and **why the selected route applies**.
- Display policy version and decisive rule identifier(s).
- Say explicitly that `routine_processing` means continuation to normal downstream handling, **not approval to pay**.

### B. Key decision factors (always visible)

Show only the most important facts initially, with the **actual field value** and its relevance:

- Matched escalation conditions, if any.
- Missing required facts/documents, if any.
- Relevant satisfied checks where useful (not a wall of green checkmarks).
- Clearly distinct statuses: **Triggered**, **Satisfied / Not triggered**, **Missing / Unknown**, and **Not evaluated**.
- Never display unknown as false, zero, present, or safe.

### C. Detailed rule evaluation (expandable)

For each rule actually evaluated, show:

- Stable rule ID and policy version.
- Human-readable rule description.
- Source field name and original/canonical value.
- Operator and right-hand side (e.g., `quote_eur > 1500`).
- Evaluation result (`matched`, `not_matched`, or `unknown`), including any not-evaluated step.
- Whether the rule was decisive, corroborating, lower priority, or not applicable.
- The order / precedence that produced the selected outcome.

If the engine uses short-circuit evaluation, **do not claim later conditions were evaluated**. Either accurately record non-execution or add an explicit non-decisional diagnostic evaluation mode that does not affect outcomes.

### D. “Why not the other outcomes?” (expandable)

Explain the two alternatives based on actual rule results and precedence, not generic label descriptions. For instance:

- Human review instead of information request: a known escalation trigger takes precedence even if documents are missing.
- Information request instead of routine: a required field is absent, preventing confirmation that routine handling is allowed.
- Routine instead of human review: no known escalation triggers matched, all necessary facts were available, and required documents were present.

### E. “What could change the outcome?” (optional, expandable)

Only show a **verified policy-grounded hypothetical**, computed using the **same engine** on an in-memory copied case, never by editing real evidence.

Example: if a case has a €1,800 quote as its only issue, lowering the *hypothetical verified estimate* to €1,500 would remove that specific escalation. Before saying this would produce `routine_processing`, check that no other triggers or missing facts remain. Otherwise say it would remove **only that trigger**.

Do not offer counterfactuals that imply altering factual evidence to obtain payment.

## 2. Exact policy v1 behavior to respect

Apply the official policy in this order:

1. `human_review` when **any known** condition is satisfied: policy inactive on incident date; `claim_type` is not `motor_own_damage`; `injury_reported`, `liability_disputed`, `duplicate_flag`, or `evidence_conflict` is true; or `quote_eur > 1500`.
2. Otherwise, `request_information` when `incident_report_present` or `itemized_quote_present` is false, or a required field is missing/unreadable/unknown.
3. Otherwise, `routine_processing`.

**Known human-review triggers outrank missing information.** A quote of exactly €1,500 does *not* meet the `> 1500` escalation rule. `repair_type = ev_high_voltage_battery` is not, by itself, an escalation rule under v1. Do not manufacture additional policy checks.

Display only reasons that are supported by the official policy version in effect. Read thresholds and rule names from versioned policy configuration, not duplicated constants in UI text.

## 3. Implementation architecture

Inspect the existing code first, then implement a minimal, compatible separation of responsibilities:

**Decision engine → immutable evaluation trace → deterministic explanation formatter → UI component.**

- The **decision engine** remains the sole authority that produces `recommendation` and matched rule(s).
- The **evaluation trace** captures facts and rule outcomes *as the engine executes*; avoid reconstructing conclusions from just the final label.
- The **explanation formatter** converts only recorded observations into concise, understandable text. It must never run a competing set of policy rules or fabricate evidence.
- The **frontend** renders the summary, factors, rule evaluation, alternative outcomes, and optional counterfactual.
- Use existing components, API routes, policy objects, and persistence conventions. Avoid breaking batch mode, the manual workspace, reviewer overrides, or version history.

A possible trace shape (adapt to current architecture rather than forcing this schema):

```json
{
  "case_id": "EXAMPLE-01",
  "policy_version": "v1",
  "recommendation": "human_review",
  "decisive_rule_ids": ["QUOTE_THRESHOLD"],
  "evaluations": [
    {
      "rule_id": "QUOTE_THRESHOLD",
      "priority": 1,
      "field": "quote_eur",
      "actual_value": 1800,
      "operator": ">",
      "expected_value": 1500,
      "result": "matched",
      "decisive": true
    }
  ],
  "missing_fields": [],
  "summary": "Human review is required because the €1,800 repair estimate exceeds the €1,500 limit in policy v1."
}
```

The example rule ID above is **illustrative**. Retain the application's existing official/internal stable rule IDs where possible; do not falsely imply the policy document assigns that exact ID.

Preserve original/raw field values alongside validated canonical values if the application already supports that; do not expose values or checks that were not actually available.

## 4. Required explanation examples

Test the implementation with policy-derived synthetic examples and actual labelled development cases (without hardcoding their outcomes):

1. **Routine:** Active policy, `motor_own_damage`, €650 quote, false escalation flags, required documents present. Say no review conditions matched and required information is complete; clarify that payment is not approved.
2. **Request information:** Same but incident report absent. Explicitly name the missing incident report and why routine processing cannot proceed.
3. **Human review (threshold):** €1,800 quote, otherwise valid. Show `€1,800 > €1,500`, threshold rule matched, and why this prevents routine handling.
4. **Priority conflict:** Injury true, incident-report field missing, €350 quote. Explain that the known injury trigger requires human review and outranks the information gap; still disclose the unknown field.
5. **Unknown quote:** Quote amount blank, otherwise valid. Say threshold cannot be evaluated, not that quote is €0; request information.
6. **Exactly at boundary:** €1,500 quote, otherwise valid. Show `€1,500 > €1,500` is false; no escalation from amount alone.
7. **EV repair:** `ev_high_voltage_battery`, €900, otherwise valid. Do not label EV work as a human-review trigger under v1.
8. **Multiple triggers:** Injury true and quote €1,800. Show both matched reasons when actually evaluated; explain why escalation is required without obscuring the evidence.

In every scenario, ensure the shown conclusion matches the decision engine's result exactly.

## 5. Dynamic policy versions and historical decisions

- Explanations must be generated against the **exact policy version used for that decision**.
- When v2 is supplied later, changing its rules must update displayed thresholds, factor labels, and rule comparisons without rewriting the frontend logic.
- In policy comparison views, explicitly show what changed under each version and identify the actual changed rule(s).
- For **closed claims**, retain the v1 recommendation as required by the hackathon; distinguish historical outcomes from any hypothetical comparison. Do not overwrite decision history.
- Preserve reviewer overrides separately from engine recommendations, with reviewer, reason, version, and timestamp if available.

## 6. UX requirements

- The decision headline and decisive reason should be readable at a glance.
- Prefer a short summary and expandable detail instead of an enormous table of all rules.
- Use consistent labels, restrained colors, simple visual hierarchy, and readable numerical comparisons.
- For unknowns, display **“Unknown — information needed”**, not a positive-looking checkmark.
- For rules skipped by short-circuiting, display **“Not evaluated”** rather than **“Passed.”**
- Make explanations readable to a user without an insurance background, while preserving rule IDs and technical details for auditors.
- Ensure the panel works for both manually created cases and uploaded CSV cases.
- Do not call any explanation “AI reasoning”; these are deterministic rule evaluations and explanations.

## 7. Regression and acceptance tests

Implement tests for both **decision/explanation consistency** and unchanged overall behavior:

1. All 14 labelled development classifications remain correct; report results before and after code changes.
2. Engine and UI agree on recommendation, policy version, decisive rules, thresholds, and unknown fields.
3. A missing value never appears as a confirmed negative/zero or as evidence of safety.
4. Human-review precedence over missing information is correctly described.
5. Exact `> 1500` boundary behavior is shown, including €1,500 exactly.
6. No imaginary EV repair escalation is introduced.
7. Counterfactual text is produced only when supported by an actual re-evaluation, and identifies other still-blocking conditions.
8. Versioned explanations remain historically accurate after later policy configurations are loaded.
9. Identical claim facts under the same policy version get the same decision and explanation in manual and batch modes.
10. The required judging output CSV columns remain intact: `case_id, recommendation_v1, recommendation_v2, needs_recheck, rule_v1, rule_v2, explanation`.
11. No unlabelled or hidden data was accessed during development or tests.
12. No chatbot files or unrelated UI/business functionality was modified.

## 8. Delivery and reporting

Implement the feature in the existing platform, then report:

- Files and modules changed.
- What the user sees when clicking **“Why this decision?”**.
- How the trace is captured, formatted, and tied to a policy version.
- Screenshots or examples for one routine case, one missing-information case, one escalation case, and a case with competing conditions.
- Commands used to run tests, results for the 14 labelled cases, and any remaining known limitations.

**Definition of done:** Any claim's “Why this decision?” panel clearly communicates the decisive rule, evidence, precedence, alternatives, unknowns, and policy version. It is understandable, correct, reproducible, and cannot disagree with the underlying deterministic engine.
