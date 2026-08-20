# M1.1 live relevance, recall, and editorial calibration report — 2026-08-19

## Status

**Implementation and offline validation are complete, but the M1.1 live
usefulness acceptance gate is not met.** The exact regression query was rerun
live. The calibrated pipeline correctly rejected the former weak sole
recommendation and returned an explained `NO_STRONG_OPPORTUNITY`, but it did
not produce the required several useful live opportunities. This is an honest
M1.1 handoff for user review, not a claim that the milestone has passed.

Milestone 2 remains unapproved and no M2 implementation, media acquisition,
media inspection, transcription, video-model call, shot analysis, or rendering
was performed.

## Safe rollback point

- Checkpoint commit: `0d46768c5d5c3fb818d1eefd1e152a13565a69a5`
- Checkpoint tag: `m1-live-search-r73-checkpoint-2026-08-19`
- Branch: `master`
- Baseline record: `docs/M1_1_BASELINE_CHECKPOINT_2026-08-19.md`
- The checkpoint captured the functioning M1 live path before production
  changes. No existing work was discarded.

## Resolved production configuration after M1.1

| Role | Exact binding and endpoint | Current state |
|---|---|---|
| Release discovery | TVmaze public metadata; `https://api.tvmaze.com/schedule` and `https://api.tvmaze.com/schedule/web` | Enabled. Broad M1.1 edit prompts retain up to 30 current metadata candidates; normal request ceiling remains 40. |
| Current-web verification | OpenAI Responses; configured and preflight-resolved `gpt-5.6-luna`; `POST https://api.openai.com/v1/responses` and model preflight `GET https://api.openai.com/v1/models/gpt-5.6-luna` | Enabled with `store:false`, `parallel_tool_calls:false`, low search context, 20 web-search tools, at most 40 verifier requests, 230,000 input tokens, and 7,500 output tokens. |
| Editorial synthesis | OpenAI Responses; configured/resolved `gpt-5.6-luna`; `POST https://api.openai.com/v1/responses` | Enabled only after evidence and audience gates. One attempt plus at most one bounded repair; reservation covers 30,000 input and 8,000 output tokens per attempt boundary. It was correctly not started in the final live replay. |
| Official video metadata | YouTube Data API v3; resolved `youtube-data-api-v3`; `https://www.googleapis.com/youtube/v3/search` | Enabled for exact titles and eight reviewed official channel IDs, five requests maximum, metadata/links only. |
| X search | xAI | Disabled by the trusted catalog because a live hard invocation-cap proof is absent. |
| Gemini/Google grounding | No approved adapter or price-card binding | Not used. No requested-but-unverified model was silently substituted. |
| TikTok, direct Reddit, TMDB | No approved direct production source | Not used. Short-form potential remains an explicitly labeled cross-platform inference. |

The embedded registry is `m1.1-2026-08-19-r74`; bundle identities are
`openai:gpt-5.6-luna|catalog:m1.1-2026-08-19-r74` and
`m1.1-research-2026-08-19-r70+catalog:m1.1-2026-08-19-r74`. The immutable
OpenAI price card is `4320de07-8d0f-4217-bd92-a577064ca7b6` at $0.20/M input,
$0.02/M cached input, $1.20/M output, and $0.01/web-search call.

The exact live-calibration entry point is debug-only, bypasses shared result
and evidence caches, writes create-new sanitized fixtures, and transactionally
enforces the aggregate `m1-1-live-calibration-2026-08-19-v1` $2.00 cap. Release
builds do not expose it.

## Verified root causes of the former one-result failure

The baseline live run was not limited by the frontend, serialization, a
provider error, or the cost cap. The first material loss was candidate
allocation: at least 94 current TV titles existed, 15 were forwarded, and only
five were deeply exact-searched. Those searches did not express the request's
audience, fandom, short-form editability, character, relationship, or emotional
moment semantics.

The evidence gate then admitted only `Stuart Fails to Save the Universe`, the
only title that happened to receive two current independently owned discussion
sources. The old score had no audience-fit or short-form component and gave a
generic scene-pack fallback excessive footage-actionability credit. Synthesis
failed a local validation, after which that deterministic fallback became the
sole card. Deduplication, schema validation, Rust transport, and React displayed
the complete one-card array; none caused the loss.

M1.1 fixes those failure modes with typed intent, a wider staged pool, semantic
research questions, an audience evidence floor, an explainable rank profile,
strict editorial concepts, and a generic-concept fail-closed gate. It does not
blacklist Stuart or any other title.

## Candidate funnel: before and final live replay

Regression prompt:

> find shows for girls that'll likely be popular on tiktok

| Funnel boundary | Baseline functioning M1 | Final M1.1 live replay (`55812119-c5dd-432f-bb4c-c64c1823f39d`) |
|---|---:|---:|
| 1. Parsed intent | 1, but only TV + `female-centered` token | 1 typed interpretation with 9 visible facets |
| 2. Generated search variants | 14 retrieval calls; no semantic questions | 10 semantic evidence questions |
| 3. Raw release candidates | At least 94 matching shows; exact row count unrecorded | 4,027 release rows |
| 4. After freshness filtering | Not recorded | 3,660 |
| 5. After hard exclusions | Not recorded | 3,660 |
| 6. After audience-fit screening | Not recorded | 3,660; audience remains a soft metadata prior, with factual support enforced at the evidence gate |
| 7. Selected for social research | 5 deeply searched; 15 metadata titles forwarded | 8 deeply validated from a 30-title metadata pool |
| 8. With usable social/editorial evidence | 4 title bindings / 5 sources | 5 titles |
| 9. Surviving evidence + requested-audience gates | 1 | 0 |
| 10. Surviving deduplication | 1 | 0 |
| 11. Sent to final ranker | 1 deterministic fallback | 0 |
| 12. Final opportunities serialized | 1 | 0 |
| 13. Final opportunities received by Rust | 1 | 0; the debug host parsed and validated the canonical no-op result |
| 14. Final opportunities displayed by UI | 1 | Not launched for the final replay; the tested UI contract would display zero cards plus the shortage explanation |

The final source now derives an explicit `evidence_or_audience_gate=5` shortage
reason for this shape: three of eight deep candidates lacked usable current
discussion evidence; the other five had some usable evidence but did not
jointly satisfy currentness, owner diversity, and requested-audience support.
The immutable live fixture retains the exact wording emitted during that run;
its individual counts already expose the same 5-to-0 boundary.

## What the final live evidence did and did not support

The final replay examined 47 normalized sources and 88 claims: 38 metadata
records, eight current discussion signals, and one verified why-now source. The
verified why-now source was an official HBO Max `Stuart Fails to Save the
Universe` Episode 4 preview; it did not prove the requested audience fit.

The five titles with at least one usable discussion source were:

| Title | Current live evidence outcome |
|---|---|
| `Paris is Always a Good Idea` | One current Future-owned article; insufficient independent-owner coverage. |
| `My Brilliant Career` | One current Future-owned review; an audience-affine premise/headline is not evidence of a female-skewing fandom and owner coverage was insufficient. |
| `Fightland` | One current Future-owned availability article; insufficient owner and audience evidence. |
| `Lanterns` | Current articles from Future and IAC-owned sites, but no adequate evidence of female-skewing fandom/edit culture for this query. |
| `Stuart Fails to Save the Universe` | Current multi-owner coverage plus an official preview, but no adequate female-audience or edit-culture evidence. It was therefore lowered out rather than rescued by newness. |

`Furious`, `Las Azules`, and `The Librarians: The Next Chapter` received no
usable current title-bound discussion evidence in the final deep slate. The two
semantic discovery searches executed but produced zero citation-bound title
selectors and zero independently validated discovery-page hints, so this is
the first remaining recall weakness. No direct TikTok claim, quote, episode
dialogue, cameo, relationship, or franchise connection was invented to force a
card through.

### Before and after result

- Before: one unexplained `Stuart Fails to Save the Universe` fallback with no
  convincing audience evidence and a generic scene-pack request.
- After: `NO_STRONG_OPPORTUNITY`; zero cards; the requested interpretation,
  inferred-TikTok disclaimer, all funnel counts, shortage cause, and broadening
  choices are exposed. This prevents the original bad recommendation but does
  **not** satisfy the several-useful-opportunities acceptance criterion.

## Implemented M1.1 behavior

- Typed hard constraints, soft preferences, audience intent, platform intent,
  and creative-edit intent. The exact prompt yields visible priorities for TV,
  female-skewing fandom, short-form edit potential, fan-edit culture,
  recognizable subjects, emotionally legible moments, visual/quote moments,
  current relevance, and character/relationship salience.
- Ten semantic research questions for the regression prompt rather than one
  literal search string. Direct TikTok searching is excluded.
- A 30-title broad metadata pool, two 15-title semantic discovery partitions,
  an eight-title deep-validation slate, distinct missing-owner retry allocation,
  and unchanged direct-page/title/date/owner validation.
- A fourteen-stage candidate funnel in Python, Rust, and React, with explicit
  shortage suggestions and derived gate-loss diagnostics.
- Selected rank profile `m1.1-intent-editorial-v1`, recording `intent_fit`,
  `audience_fit`, `freshness`, `fandom_velocity`,
  `short_form_edit_potential`, relationship/character salience,
  `footage_actionability`, `evidence_quality`, `source_diversity`, and
  `uncertainty_penalty`.
- Strict `EditorialConcept` contracts and provider schemas. A concept requires
  a subject, current hook, intro direction, handoff, three-to-six-beat montage
  progression, ending/payoff, evidence, uncertainty, and its own
  smallest-useful-set footage request. Generic “get clips from this show” copy
  fails validation.
- Evidence-bound cross-season and cross-series sources, explicit legacy
  connection classifications, and fail-closed rumored cameo/false franchise
  handling.
- Concept selection updates the footage request; UI cards expose Why now, What
  fans care about, Edit ideas, Intro, Montage arc, Payoff, Footage needed, and
  expandable sources. “Generate another idea”, “More like this”, “Too generic”,
  and “I don't care about this angle” are wired through local feedback.
- Local ratings for great, relevant-but-boring, wrong audience, not actually
  trending, weak evidence, vague footage, and hide-this-type. No automated
  training was added.

## Editorial-concept regression coverage

No live title passed the final evidence packet gate, so no live concept was
generated and no live footage request can honestly be shown. The following are
synthetic, evidence-pattern fixtures used to prove the contracts—not current
show recommendations:

1. **Recognition -> shared history -> present payoff.** Intro on a verified
   current reunion/recognition; montage from early distrust through trust,
   rupture, and loyalty; return to the present reaction. Minimum source set:
   one current episode plus one compact relationship scene pack from the
   evidence-proven parent series.
2. **Non-romance character resilience.** Intro on a current failure or reaction;
   montage through earlier failures, persistence, and changed choices; end on
   the current payoff. Minimum source set: the current source plus a focused
   multi-season character scene pack, not a whole series.
3. **Comedy callback gaining affectionate meaning.** Intro on an explicit
   current callback; montage the original comic friction, repeated variations,
   and growing affection; return to the callback after its meaning changes.
   Minimum source set: the current callback source plus the smallest supported
   legacy clip set or scene pack.

The fixture suite also proves two concepts for one opportunity can require
different footage, an unknown episode remains inferred with no invented
locator, and an exact quote remains absent unless authoritative evidence binds
it. All concepts remain provisional until later, separately approved footage
analysis.

## Ranking and evaluation results

| Evaluation | Result |
|---|---|
| Dated intent golden set | 10/10 prompts passed parser/facet/clarification/search-question checks |
| Selected `m1.1-intent-editorial-v1` | Pairwise relevance accuracy 1.000; correct audience-supported editable title ranked first |
| Balanced comparison | Pairwise relevance accuracy 1.000 |
| Freshness-heavy control | Pairwise relevance accuracy 0.833; demonstrated the expected newness misordering |
| Exact live interpretation | 100/100 |
| Exact live honesty | 100/100 |
| Exact live useful-candidate count | 0; target not met |
| Exact live card-level audience/editability/footage grades | Not measured because no card passed; they are `null`, not fabricated positive scores |
| Exact live safety regression | Passed: no single unexplained card, unsupported TikTok claim, weak-audience card, newness-dominated card, vague footage request, or unsupported quote/episode |
| M1.1 milestone completion gate | **Not met** |

## Provider/model role audit

| Requested configuration | Finding |
|---|---|
| A: Grok 4.6 + X Search | First-party xAI documentation reviewed on 2026-08-19 documented Grok 4.5, not the requested 4.6 ID. Blocked fail-closed; no substitution and no spend. |
| B: Gemini 3.7 Flash + Google Search grounding | First-party Google documentation reviewed on 2026-08-19 documented Gemini 3.6 Flash, not the requested 3.7 ID. Blocked fail-closed; no substitution and no spend. |
| C: GPT-5.6 Sol/Terra + web search | Official OpenAI documentation verified both requested IDs, but the trusted application has no reviewed Sol/Terra price-card and adapter binding. They were not run because the diagnosed failure was retrieval/gating and changing the production trust boundary was not yet justified. |
| Current: GPT-5.6 Luna | Web verification was measured. Final run: $0.226893, 159,064 ms, 40 requests, 20 web-search calls. Editorial synthesis was not started because no eligible evidence packet existed, so editorial-model quality was not scored. |

There is therefore no fabricated “bake-off winner”: measured editorial output
count is zero. The production default remains the existing Luna binding with
the staged 30 -> 8 retrieval plan and preserved fallbacks. A future M1.1
iteration needs an eligible shared evidence packet and approved adapter/price
bindings before a paid editorial comparison can select a different default.

## Live spend and latency

| Run | Outcome | Latency | Actual OpenAI cost |
|---|---|---:|---:|
| 1 | Clean no-op; 4 usable titles, 0 gated | 145,671 ms | $0.228636 |
| 2 | Clean no-op; 6 usable titles, 0 gated | 155,543 ms | $0.224864 |
| 3 | Provider stopped after two requests with `max_output_tokens`; sanitized incomplete fixture retained | 57,314 ms | $0.031057 |
| 4 | Clean no-op; 6 usable titles, 0 gated | 147,089 ms | $0.229341 |
| 5 | Final clean no-op; 5 usable titles, 0 gated | 159,064 ms | $0.226893 |
| **Total** | Five create-new sanitized fixtures | — | **$0.940791** |

The aggregate charged-or-held amount was $0.940791 against the authorized
$2.00 hard cap, leaving $1.059209 unused. No further live calls were made after
the final evidence freeze.

## Files changed

- Canonical/provider contracts and exported schemas for intent, funnel,
  opportunity scoring, editorial concepts, and concept-specific footage.
- Python intent, TVmaze discovery, OpenAI retrieval/synthesis adapters, ranking,
  evaluation, footage, workflow, and worker protocol code.
- Rust domain validation, provider planning/catalog, worker protocol, commands,
  persistence, local feedback migration/repository, and debug-only budgeted
  calibration runner.
- React/TypeScript contracts, interpretation/funnel/result screens, concept
  selection, feedback, footage-request selection, tests, and styles.
- Dated golden corpus, rubric, ranking packets, model audit, sanitized live
  fixtures, evaluation runner, architecture/contracts/data/cost/research docs,
  and regression diagnosis.

## Validation evidence

The final validation sweep is recorded here after completion:

- Python unit tests: 231 passed; four optional worker-verifier dependency tests
  skipped.
- Contract schema export/check: 38 generated schemas verified.
- Python compile check: passed for `src` and `scripts`.
- Dated M1.1 evaluation runner: passed all offline checks; live completion gate
  explicitly false.
- Rust 1.95 tests: 97 passed; debug application build passed.
- React/UI: four files / 17 tests passed; TypeScript and Vite production
  frontend build passed.
- Packaged worker: rebuilt offline with CPython 3.12.14 and PyInstaller 6.22.0;
  exact 74-file AMD64 manifest, handshake, shutdown, and protocol checks passed.
- `git diff --check`: passed after removing one Markdown trailing-space marker.
- Optimized Rust `cargo check --release`: not completed because the user-owned
  checkpoint desktop and worker processes hold the existing release resource
  tree open. They were deliberately not terminated. This is a lock-state
  limitation, not a compiler/test failure; the normal debug build and all Rust
  tests passed.

The desktop release was deliberately not repackaged or launched: the backend
did not meet the strong-results gate, and the running user-owned checkpoint app
was left untouched.

## Regressions prevented

- A new title cannot outrank better audience/edit opportunities on freshness
  alone.
- A gender/audience request cannot be satisfied solely by a genre stereotype or
  model-written rationale.
- Direct TikTok popularity cannot be claimed when direct data was not used.
- One result cannot silently imply exhaustive cultural coverage.
- Generic “get clips” footage copy cannot pass the M1.1 editorial gate.
- Cross-title footage cannot appear without an evidence-bound canonical bridge.
- Rumored cameos, false franchises, unsupported quotes, episode locators, and
  speakers fail closed.
- Two concepts for the same opportunity retain different footage requests.
- The calibration ledger cannot exceed $2.00 and cannot run in release builds.

## Known remaining weaknesses and next M1.1 gate

1. The currently approved web publisher corpus often yields only one current
   independent owner for a promising title; direct X, Reddit, and TikTok data
   remain unavailable.
2. The final semantic discovery searches returned no citation-bound selectors,
   so TVmaze ordering still determined the eight-title deep slate. Candidate
   allocation is broader but not yet reliably semantically adaptive.
3. The exact query did not yield a live synthesis packet, so editorial concept
   creativity, footage specificity, and hallucination rates were validated by
   strict offline fixtures rather than representative live cards.
4. The user requirement for at least three representative live opportunities,
   concepts, and concept-specific footage requests is unmet.
5. The final desktop package was not produced because the backend usefulness
   gate failed; UI behavior is covered offline only.

The next action, if authorized, is another **M1.1** relevance iteration focused
on lawful audience/fandom evidence recall and semantic candidate allocation,
then a single bounded replay from the remaining authorization. Do not begin
Milestone 2.
