# Retakt

**Claims, complete in one call.** Built for the Taktile track at thinc! hack MUC, 7–8 November 2026.

Retakt helps motor insurers in two places: when a customer reports a claim, and when the insurer changes its rules. A driver reports damage on their phone in under two minutes. The insurer sees every claim decided by its own policy, with the reason. When the policy changes, Retakt replays every open claim and shows which ones need a second look, and why.

## Try it

| What | Link | Who it is for |
| --- | --- | --- |
| **Insurer web app** | **[the-empty-white-space.lovable.app](https://the-empty-white-space.lovable.app/)** | Claims handlers and reviewers |
| **Customer phone app** | **[retakt.92-5-27-43.sslip.io](https://retakt.92-5-27-43.sslip.io/)** | The driver who reports a claim |

Both run online, so no installation is needed. Use a desktop browser. The phone app opens inside a phone frame. All claims, people and policies in the demo are fictional.

## The concept

Today, about 1 in 5 car claims bounces back to the customer because something is missing. Each time, that means a week of waiting. A handler spends about 15 minutes checking documents by hand on every claim. When the insurer changes a rule, it takes about three weeks until the new rule is applied everywhere.

Retakt fixes all three:

1. **Decision engine.** Every claim is decided by the insurer's written policy, rule by rule. Each decision names the rule that matched, the facts behind it and the policy clause. Missing facts stay unknown and are never invented.
2. **Policy replay.** Upload a new policy version and Retakt runs every claim against it. You see which open claims change, from which decision to which, and because of which rule. Closed claims keep their original decision.
3. **AI assistant (Rico).** On the phone, Rico collects the facts by chat or voice call. It asks for the documents the policy needs, so a claim arrives complete and doesn't bounce back.

## How to test it

### 1. Report a claim as the driver (phone app)

Open the [phone app](https://retakt.92-5-27-43.sslip.io/).

- **New claim:** chat with the assistant. It collects the six facts it needs: what happened, the date, the place, the insurance number, an email and whether anyone was hurt. Then attach the incident report and the itemized repair quote, check the summary and press **Submit claim**.
- **Call Rico:** talk to Rico instead of typing. The microphone only starts after you press **Start call**. The facts Rico hears appear on screen, and you can correct them.
- **My claims:** see your drafts and submitted claims. Unfinished claims reopen with their details and attachments. **Save and continue later** keeps a half-finished claim.

### 2. Review claims as the insurer (web app)

Open the [web app](https://the-empty-white-space.lovable.app/).

- **Landing page:** watch the open claims get routed under policy v1. Drag the quote threshold to see live which claims would change route.
- **Overview:** all open claims with their decision. Filter by decision and click a claim to see the rule, the reason and the facts that decided it. **Edit claim** records a correction with a reason and your name.
- **Policy Update:** upload a new policy version (for example `v2`) and apply it. The page shows how many claims changed, a heatmap of old versus new decisions, the changes per rule, and the cost of manual review compared with Retakt.
- **History:** closed claims. Their decisions are protected and can't be corrected.
- **Submitted claims** (inbox icon): claims that came in from the phone app, with the engine's recommendation and the original documents.
- **Rico:** the green assistant in the corner answers questions about claims. Hold it down to open the text chat.

### 3. Follow one claim end to end

1. Report a claim in the phone app and submit it.
2. Open **Submitted claims** in the web app and find the claim.
3. Read the recommendation and the rule behind it.
4. Change the policy under **Policy Update** and look at which open claims move.

## The decision rules (policy v1)

Rules are checked in this order:

1. **Human review** (`v1.1`): the policy wasn't active on the day of the damage, the claim isn't own-damage, someone was injured, liability is disputed, the claim may be a duplicate, the evidence conflicts, or the quote is above €1,500.
2. **Request information** (`v1.2`): the incident report or the itemized quote is missing.
3. **Routine processing** (`v1.3`): everything else.

A blank field counts as a missing fact (`v1.missing`). It's never filled in by guessing.

## Business case

Figures for one insurer with 150,000 claims a year:

| | |
| --- | --- |
| Net saving for the insurer | **€873k a year** (€1.37M saved minus €500k fees), payback under 6 months |
| Cost per policy change | **−70%** (€62k → €18k), live the same day instead of in about three weeks |
| Claims sent back to the customer | **21% → 0%**, about €165k saved a year |
| Revenue per insurer | **€500k a year** (€50k licence + €3 per claim), 73% gross margin |
| Market | **€52M** in fees a year across the US, UK and France (17.3M car claims a year) |

**Rollout:** in months 1–3 a human checks every intake and the AI learns from each correction. From month 4, Retakt runs on its own, with 5% spot checks. The target is 92%+ complete intakes, in line with market benchmarks of 92–96%.

## What's in this repository

| Folder | Contents |
| --- | --- |
| `engine/` | Decision engine for policy v1 and v2, CSV batch command |
| `eval/` | Quality reports against the labelled cases |
| `backend/` | HTTP API, claim intake, evidence checks, reviewer corrections and audit history |
| `app/` | Insurer web app (Lovable, submodule [`rafik-324/thinc-hack`](https://github.com/rafik-324/thinc-hack)) |
| `demo/chat-redesign/` | Customer phone app and its preview server |
| `contract/` | API contract, batch output columns, database schema |
| `data/taktile/` | Taktile case data: labelled and unlabelled claims, policy v1 |

Run everything locally with the engine, the API and the full rehearsal script: see **[DEVELOPMENT.md](DEVELOPMENT.md)**.

Quick start:

```sh
python3 -m engine --help                     # decision engine and CSV batch
python3 -m backend --ui-origin http://localhost:5173   # local API
python3 -m unittest discover -v              # all tests
```

## Team

Built by Sayed (engine, backend) and Rafik (apps, business case, demo).
