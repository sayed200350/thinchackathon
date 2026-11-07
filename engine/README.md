# Motor claim triage

Run from the repository root with Python 3.9 or newer. The engine uses the Python standard library.

## Commands

```sh
python3 -m engine decide data/taktile/labelled_development_cases.csv DEV-001
python3 -m engine batch data/taktile/unlabelled_practice_cases.csv /tmp/policy-replay-v1.csv
python3 -m eval.quality data/taktile/labelled_development_cases.csv
python3 -m unittest discover -s engine/tests -v
```

The first command returns the [shared decision example](../contract/example-result-DEV-001.json). The batch command accepts the organizer’s CSV format and writes the [seven judge columns](../contract/batch-output.md) in input order. Use distinct input and output files. A failed run preserves an existing output file.

## Backend integration

Call `from engine import decide`, then `decide(claim, policy_version="v1")` with a dictionary from the CSV or the corresponding API record. The return value is a JSON-ready dictionary. The function performs no file or network I/O. It requires a case ID and an open/closed status. A named policy version must exist, so a request for an unreleased version raises `ValueError`.

| Rule | Decisive evidence |
| --- | --- |
| `v1.1` | Inactive cover, out-of-scope claim, injury, dispute, duplicate, conflicting evidence, or a quote above €1,500. These known triggers take priority over missing facts. |
| `v1.2` | At least one required document is explicitly absent. |
| `v1.missing` | A structured policy fact is missing or unreadable. Its normalized evidence value is JSON `null`. |
| `v1.3` | Complete qualifying case with no review trigger. Exactly €1,500 is within the routine limit. |

Amounts in the supplied CSV use a decimal point without currency symbols or grouping. The engine compares decimal amounts before producing JSON. The source row holds the original inputs. The decision names the facts used to route the case. The free-text summary and development label never participate in routing.

## Replay and evaluation

The current export is a **v1 preview**. For open cases, the v2 recommendation, recheck flag, and v2 rule are empty until the official change arrives. For closed cases, both versions carry the retained v1 recommendation and rule, and `needs_recheck` is `False`. The replay test exercises changed and unchanged open cases with a synthetic second rule. Wire the published v2 implementation into the batch command before judge submission.

The [development report](../eval/v1-development.json) uses all 14 supplied labels. The error-rate denominator is all labelled claims, which lets the business case multiply the rates by annual volume. The report also gives the confusion matrix, individual mismatches, and results for cases with blank structured facts. The 12 practice cases have no labels and provide a batch-format check.

After the official update, compare against independently reviewed v2 labels and report the changed subset separately. In a pilot, sample routine referrals and escalations, investigate incorrect routine routing, and link later reviewer corrections and final outcomes to the recorded decision version. The policy owner should review disputed examples before adding them to the release tests.
