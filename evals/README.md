# Milestone 1 evaluation package

This directory contains the dated offline/golden evaluation definition for the Milestone 1 opportunity researcher. It does not ingest media, call a video model, or implement any Milestone 2 behavior.

The frozen suite is [`2026-08-15/manifest.json`](2026-08-15/manifest.json). It covers the eight niches committed during Milestone 0, the user's explicit romance/romcom quality-bar prompt, exclusion and freshness boundaries, prompt-injection resistance, and the valid outcome where no worthwhile opportunity exists.

## What is—and is not—golden

- Prompts, behavioral expectations, rubric, runner envelope, and synthetic representative structures are frozen and machine-readable.
- Representative outputs are deliberately fictional. They demonstrate contract shape, natural footage-request language, verification honesty, multi-season sourcing, and minimum-footage behavior; they are not current entertainment claims.
- A real current recommendation cannot be frozen indefinitely. Live results must use evidence retrieved for the dated run and are judged against the rubric rather than against a permanently expected show title.
- The suite builder made no provider calls and incurred no paid cost.

## Evaluation modes

1. `OFFLINE_REPLAY` feeds captured/fake provider records through the same normalization, evidence, recommendation, budget, and persistence boundaries used by production. It must never make a network call.
2. `LIVE_OPT_IN` is run only through the trusted M1 cost/capability path after provider preflight and a disclosed hard budget. It records configured and resolved model IDs, price cards, retention mode, latency, and actual cost.
3. `INTERACTIVE_REVIEW` presents the dated live result to the user and records the human ratings defined in [`rubric.json`](2026-08-15/rubric.json).

The evaluation runner consumes one case from [`corpus.json`](2026-08-15/corpus.json) and emits an envelope conforming to [`runner-contract.schema.json`](2026-08-15/runner-contract.schema.json). The product result inside that envelope must independently validate against the current canonical M1 contracts; the runner schema is not a substitute for product validation.

## Pass rule

A case passes only when:

- no hard failure in the rubric occurs;
- all case-specific required behaviors pass;
- exclusions and freshness are respected;
- any recommendation has evidence-backed why-now and creative-hook separation plus a conversational, minimum-effort footage request;
- an evidence-poor case may truthfully return `NO_STRONG_OPPORTUNITY` without being penalized;
- the weighted rubric score is at least 80/100, with no dimension scored zero;
- live paid work stays inside the trusted reservation and records actual cost.

The M1 handoff must save the completed dated runner results and interactive ratings without rewriting this frozen suite. Milestone 2 remains a separate approval gate.
