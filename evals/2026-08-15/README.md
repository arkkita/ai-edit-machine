# M1 golden suite — 2026-08-15

Suite ID: `m1-golden-2026-08-15`  
Product result contract: `research-result@2.0.0` (`ResearchResultV2`)  
Network activity used to create this suite: none  
Paid cost used to create this suite: `$0.00`

## Runner contract

The files here define evaluation data; they do not contain a provider client or a second research workflow. An evaluator must call the same trusted M1 orchestration path used by the application.

For each case:

1. Verify the frozen corpus and rubric hashes recorded in `manifest.json`.
2. Send an `EVALUATION_REQUEST` conforming to `runner-contract.schema.json`.
3. In `OFFLINE_REPLAY`, inject captured/fake adapters and assert that no network transport is reachable. In `LIVE_OPT_IN`, require the normal immutable paid-call capability, fresh price card, transactional reservation, provider preflight, and disclosed retention mode.
4. Validate the product payload independently as `ResearchResultV2`. The evaluation envelope never weakens product validation.
5. Evaluate every case `required_behaviors` and `forbidden_behaviors`, then apply all hard-failure rules and weighted dimensions in `rubric.json`.
6. Emit one immutable `EVALUATION_RESULT` envelope. Store the product result separately by hash so private/provider content need not be copied into the score record.
7. For the dated user review, copy `interactive-ratings.template.json` into a run-output directory and record 1–5 ratings without changing this suite.

## Outcome rules

`OPPORTUNITIES` is not automatically better than `NO_STRONG_OPPORTUNITY`. A no-result response passes when evidence or actionability is inadequate and the message explains that naturally. A recommendation fails if it lacks a concrete minimum-footage request, even when its topic is timely.

Synthetic examples in `representative-outputs.json` validate against the v2 provider-draft/no-result contracts. Their fictional titles and quotes test structure and honesty; they must never be displayed as live recommendations.

## Cost and scope

- `OFFLINE_REPLAY`: paid cost must be zero.
- `LIVE_OPT_IN`: maximum ordinary per-run hard cap is 500,000 micro-USD unless the user explicitly sets a lower value; xAI search remains disabled until its separate invocation-cap proof passes.
- The runner records actual provider cost and resolved model versions.
- No mode uploads or ingests footage, transcribes media, invokes Gemini video understanding, analyzes songs, plans edits, or renders output. Any such action is `M2_SCOPE_LEAK` and a hard failure.
