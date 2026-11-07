# Policy Replay

Taktile track · thinc! hack MUC · 7–8 November 2026

Policy Replay will help a motor-insurance reviewer answer one question when a policy changes: **Which open claims need a second look, and why?** The weekend deliverable is a CSV decision engine and a reviewer app that explains the same decisions.

## Run the reviewer API

For the browser workbench, run `python -m backend --open` and use **http://127.0.0.1:8765**. On Windows you can also double-click `backend/start-workbench.cmd`. It includes sample claims, editable facts, CSV upload, policy comparison, downloads, and saved reviewer corrections. See the [browser workbench guide](backend/README.md). Python 3.10+ is required; no extra packages are needed.

From the repository root, start the local service with Python 3.9 or newer:

```sh
python3 -m backend --ui-origin http://localhost:5173
```

Open [DEV-001](http://127.0.0.1:8765/api/claims/DEV-001) to read its original decision. Rafik can connect the reviewer screen using the [API contract and correction example](contract/api.md). The [engine guide](engine/README.md) covers the CSV command and [measured v1 results](eval/v1-development.json). Run all tests with `python3 -m unittest discover -v`.

## Start together

Read the [Taktile brief](Usecase/20261105_Taktile_thinc%21%20Hackathon%20Case%20Study.pdf) and unpack the [participant materials](Usecase/20261105_Taktile_thinc%21%20Hackathon%20Case%20Study%20Material.zip). The pack contains policy v1, 14 labelled development claims, and 12 unlabelled practice claims.

In the first 15 minutes, agree on one example result containing the case ID, open/closed status, recommendation, policy version, matched rule, and supporting facts. Use **DEV-001**. Its €650 parking scrape with complete paperwork goes to `routine_processing` under v1. Sayed can implement the engine and Rafik can build the screen against that example.

## Two-agent build plan

| Milestone | Sayed · Rules, CSV, evaluation & backend | Rafik · Reviewer app, business case & demo |
| --- | --- | --- |
| First working slice | Encode v1 in its specified order and read the official CSV format. Give Rafik a sample result, a command to reproduce it, and the API format for reading a decision and saving a reviewer correction. | Build the claim list and detail view. Show the decisive facts and clause. Build the correction form against Sayed’s API and display the original recommendation and audit history. |
| Before the Saturday 18:00 rule release | Persist reviewer corrections, reviewer identity, reason and policy version in the database alongside the original decision. Evaluate v1 against all 14 labels. Check the €1,500 boundary (DEV-010), a blank quote (DEV-013), and a known injury with a blank report field (DEV-014). | Connect the screen to Sayed’s API and verify that a saved correction survives refresh. Build a cost calculator with editable assumptions for claim volume, staff time, and costs of different errors. |
| When v2 arrives on Discord | Preserve v1 and implement the published change. Flag affected open claims. For closed claims, retain the v1 recommendation in v2 and set `needs_recheck` to `False`. | Independently work out which sample claims the new clause should affect. Compare with Sayed’s results and build **Preview policy change**, with old and new decisions, the changed clause, and the relevant fact. |
| Sunday handoff | Deliver the batch command and a quality report for each version. Include counts and denominators for correct routing, incorrect routine routing, and unnecessary human review. Break out changed cases. Own the final merge. | Use the measured error rates to show annual cost before and after, net benefit, payback, and the cost of applying v2. Own the demo and the judge’s live override. |

Work on separate branches, `codex/sayed-engine` and `codex/rafik-app`. At each handoff, share the pull request, one command or click path to try, and the expected result.

## Integration checks

- **Before 18:00:** Run DEV-001 from CSV to screen. Open DEV-002 and show why its missing incident report triggers `request_information`. Save a reviewer correction and reload it.
- **After v2:** Compare the engine with Rafik’s independent expectations. Check an affected open case and a closed case. Use the unlabelled practice CSV for a fresh-file run and labelled examples for accuracy measurements.
- **Before judging:** Rafik runs an unfamiliar CSV using Sayed’s instructions. Sayed acts as the judge and completes an override in Rafik’s UI without coaching.

The judges’ batch output must use these columns in this order:

```csv
case_id,recommendation_v1,recommendation_v2,needs_recheck,rule_v1,rule_v2,explanation
```

## Five-minute demo

1. **0:00–1:00 · Rafik** opens one easy claim and one incomplete claim. Point to the fact and policy clause that explain each route.
2. **1:00–2:30 · Rafik and Sayed** preview the official policy change. Rafik opens an affected claim. Sayed explains why its route changed and shows a closed claim that retained its decision.
3. **2:30–3:30 · Judge** corrects a recommendation and enters a reason. Refresh the page and show the audit history.
4. **3:30–5:00 · Sayed and Rafik** show before-and-after quality, including changed cases. Rafik adjusts one cost assumption and closes on the effect on payback. Name the next test before rollout.

## Hackathon references

Case assignment is announced on Discord on Saturday at 13:30. The Taktile policy update is scheduled for 18:00 there. Jonathan, Senior Forward Deployed Engineer, is the on-site Taktile contact. The case uses hidden test claims. [Taktile brief on Drive](https://drive.google.com/file/d/1zUfKqMNmND-2Uz-qP3rJc4bHHLwuXHBW/view?usp=sharing) · [Participant pack on Drive](https://drive.google.com/file/d/1SUolqZMWaMn7FX2gravpVW67sAqIc3s5/view?usp=drive_link)

**NAP VC side challenge.** Across all three cases, the jury looks for an intuitive, polished user experience, an original idea built around the user, and a pitch that makes the value immediately clear.

**Other tracks.** Each case partner presents at the Saturday opening for about ten minutes.

- **Dash0.** [Challenge brief](Usecase/Dash0_Hackathon_Challenge.pdf) · [Perses](https://perses.dev) · [Alert thresholds](https://www.dash0.com/docs/dash0/monitoring/alerting/alerting-model#the-dollarthreshold-extension) · [Dashboard import](https://www.dash0.com/docs/api-reference/operations/post/api/import/dashboard) · [Check rule import](https://www.dash0.com/docs/api-reference/operations/post/api/import/check-rules) · [Starter repo](https://github.com/vimouzin/dash0-dashboard-migrator) · [Dash0 sign-in](https://accounts.dash0.com/sign-in) · [Datadog](https://www.datadoghq.com/) · [Datadog test assets](https://github.com/DataDog/integrations-core)
- **Reonic.** [Challenge brief](Usecase/Reonic_Hackathon_Challenge_final.pdf). The separately supplied project dataset is for the hackathon team’s local use.
