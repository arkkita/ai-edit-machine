# API Costs and Hard-Budget Design

**Price snapshot:** 2026-08-19, USD.
Prices are estimates from current official pages, not quotes. The application must show a fresh pre-call estimate and persist the price-card source/effective/check time used.

## Current unit prices used for planning

| Provider/capability | Planning price | Official source |
|---|---:|---|
| xAI requested `grok-4.6` / fallback | No executable price card: the 2026-08-19 first-party recheck did not establish the requested 4.6 identifier. | [xAI pricing](https://docs.x.ai/developers/pricing) |
| xAI X Search / Web Search | Documentation audited, but no M1 authorization while the exact model/cap binding is unverified. | [xAI X Search](https://docs.x.ai/developers/tools/x-search) |
| OpenAI `gpt-5.6-luna` | $0.20/M input; $0.02/M cached input; $1.20/M output | [OpenAI Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) |
| OpenAI web search | $0.01 per call plus model-rate search-content tokens | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| OpenAI `gpt-5.6-terra` / `sol` optional critics | Terra $2/M input, $12/M output; Sol $5/M input, $30/M output | [OpenAI models](https://developers.openai.com/api/docs/models) |
| Google Gemini 3.6 Flash through 2026-12-31 | $0.75/M input; $3.75/M output; batch/flex half price. Requested 3.7 was not established and has no executable card. | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Google Gemini 3.6 Flash from 2027-01-01 | $1.50/M input; $7.50/M output | [Gemini 3.6 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash) |
| OpenAI `gpt-transcribe` | about $0.0045/minute | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| OpenAI `whisper-1` | $0.006/minute | [Whisper-1](https://developers.openai.com/api/docs/models/whisper-1) |
| Direct X API Post read | $0.005/resource | [X API pricing](https://docs.x.com/x-api/getting-started/pricing) |
| YouTube Data API | quota, no per-call dollar price; current granular default is 100 `search.list` calls/day in the separate Search Queries bucket | [YouTube `search.list`](https://developers.google.com/youtube/v3/docs/search/list) |
| TVmaze | free CC BY-SA or $250/month Startup commercial tier | [TVmaze plans](https://www.tvmaze.com/api/plans) |
| TheTVDB conditional license | Parent-company revenue tiers: under $50k free with attribution; $50k–$250k $1k/year; $250k–$1M $10k/year; $1M+ custom | [TheTVDB API information](https://thetvdb.com/api-information) |

The OpenAI Luna model page and central pricing table were rechecked on 2026-08-19. They now publish `$0.20/M` input, `$0.02/M` cached input, and `$1.20/M` output. This is a new immutable price card; historical reservations and reconciled costs remain attached to the cards that authorized them. Production still requires a fresh immutable card and resolved-model preflight rather than treating this document as executable pricing.

## Per-operation estimates

### Milestone 1 ordinary opportunity run

The current M1.1 production plan uses free TVmaze metadata, one bounded Luna
web-verification capability, optional official YouTube metadata, and one Luna
structured-synthesis capability. xAI and Google are not part of the executable
M1.1 plan.

The verifier reserves twenty built-in web-search calls before consent. The host
uses broad coverage followed by candidate-scoped exact-title owner lanes for up
to eight titles, all through Responses with `tool_choice="required"`; assistant
prose never becomes evidence. The host consumes each hosted tool's complete
`web_search_call.action.sources` list and independently validates pages. The
verifier may additionally make credential-free public-page checks within a
forty-request aggregate ceiling; those checks remain HTTPS-only, DNS-pinned,
exact-host, byte-bounded, and subject to the same source/date/identity
validation. The [official OpenAI Web Search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
documents the complete source list and required/auto distinction.

The current trusted verifier capability reserves at most 230,000
provider-reported input tokens, 7,500 output tokens, and twenty searches. At the
current Luna rates that is **$0.255000**. Synthesis reserves 30,000 input plus
8,000 output tokens for the first attempt and an equal **$0.015600** allowance
for the one syntax-only repair, for a **$0.031200** synthesis maximum. The
complete ordinary M1.1 cloud maximum is **$0.286200**, below the independent
$0.50 ordinary-run hard cap. Public-page and TVmaze checks carry no provider
charge but remain request- and time-bounded. Provider-added search context can
make reported billable input exceed the locally estimated request-body size;
the higher accounting ceiling is therefore separate from the tighter request
body cap.

The development-only M1 provider probe is a different, fixed capability: exactly one hosted search, at most 198,000 reported input tokens and 300 output tokens, no synthesis, no repair, and no network retry. Its conservative reservation is **$0.049960** under an independent immutable **$0.050000** run-scope cap. It is compiled out of release builds, uses the ordinary Rust-owned credential lookup and cost ledger, and a committed or held first paid request prevents a second authorization. `search_context_size="low"` is not described as an exact billable-token cap; any provider-reported overrun is still reconciled and surfaced.

The M1.1 calibration command is also development-only but exercises the full
normal live plan for the one fixed regression prompt. Every run uses the same
immutable `m1-1-live-calibration-2026-08-19-v1` scope under a **$2.000000**
aggregate hard cap. A full run reserves **$0.286200**; six such unresolved/full
reservations total $1.717200 and a seventh would total $2.003400, so the trusted
transaction rejects it before network activity. The command forces fresh
provider calls, neither reads nor writes reusable/shared research caches, saves
only a credential-checked create-new sanitized canonical fixture, and is absent
from production behavior.

As of the M1.1b offline checkpoint on **2026-08-20**, that immutable scope has
reconciled **$0.940791** of paid provider usage, leaving **$1.059209** before the
$2.000000 ceiling. M1.1b implementation, the eight-candidate regression
diagnosis, fixtures, schema work, backend checks, and UI checks made **zero**
additional paid calls. At most one bounded live regression rerun is permitted
after the complete offline evaluation passes; the same Rust reservation ledger
must reject it before network activity if aggregate capacity is insufficient.

The token values above are conservative accounting ceilings calibrated from observed usage with margin, not claims that `search_context_size` hard-caps billed input. Opaque provider call IDs are stored only as bounded SHA-256-derived audit labels. A response that reports usage beyond any reserved dimension is still reconciled as an overrun and held conservatively; it is not discarded as malformed, silently undercounted, or allowed to authorize a later call. Historical ledger entries remain bound to the immutable price card that authorized them; discovering a newer card does not silently rewrite prior reservations or actuals. The earlier one-call `$0.0912` verifier diagnostic authorization is exhausted and is not reusable under the corrected card.

Direct X is excluded from that default. Reading 100 Posts can add about **$0.50** before related User reads or reasoning. It requires a separate estimate/opt-in.

Official-video enrichment uses at most one YouTube `search.list` call for each already-trusted title, capped at five titles per M1 run. Since the June 2026 granular-quota transition, each call consumes one call from the separate Search Queries bucket; the documented default is 100 `search.list` calls/day. The app records the exact request count in its quota ledger even though the dollar reservation is zero. Search is global, but local acceptance is restricted to the reviewed official channel-ID registry and exact trusted-title bindings. No `videos.list`, media, transcript, thumbnail, embed, or download request is made by the M1 adapter.

### 45-minute footage understanding

This is a provisional planning example, not the frozen M2 architecture. Before M2, the required focused long-video study must compare provider caching/file reuse, multi-video prompts, hierarchical indexes, adaptive/coarse-to-fine sampling, and hybrid local/cloud filtering. The selected design must optimize creative quality and repeated-edit economics—not merely minimize the first API call.

Gemini documents about 100 video/audio tokens per second at low resolution and 300 per second at default resolution:

| Pass | Assumption | 2026 input | 8k output | Approx. total |
|---|---:|---:|---:|---:|
| Low-resolution map | 2,700 s × 100 = 270k tokens | $0.2025 | $0.0300 | **$0.2325** |
| Default-resolution full pass | 2,700 s × 300 = 810k tokens | $0.6075 | $0.0300 | **$0.6375** |
| Five-minute targeted rescan | 300 s × 300 = 90k tokens | $0.0675 | 2k output = $0.0075 | **$0.0750** |

Rates approximately double in 2027. The current proposal is one independently cacheable source map plus only necessary targeted rescans—not repeated full default-resolution passes. It may change if pre-M2 research demonstrates a better approach. A coarse pass may reduce search space, but fine analysis must preserve subtle facial reactions, eye contact, touch, emotional pauses, visual parallels, insert shots, and transition handles in shortlisted regions.

A future multi-source preview should be itemized rather than hiding one total:

```text
VIDEO ANALYSIS ESTIMATE
S1E4  already indexed                         $0.00
S2E6  new coarse source map                  $0.14 estimated
S3E3  new coarse source map                  $0.17 estimated
targeted high-detail pass                    $0.06 estimated
total                                        $0.37 estimated
```

The actual estimate accounts, where the provider makes it practical, for duration, resolution, sampling rate, estimated tokens/upload bytes, file count, cached/uncached state, coarse and fine passes, configured/resolved model, batch/flex pricing, provider file/context reuse, and uncertainty. Each source remains separately attributable so a long-lived show library can report a true `$0.00` cache reuse rather than estimating it again.

Local subtitle extraction, PySceneDetect, Beat This, librosa, and local ASR have no marginal API charge. Optional cloud transcription adds about **$0.20** (`gpt-transcribe`) or **$0.27** (`whisper-1`) for 45 minutes, before chunking overhead.

### Planning and rough-cut critique

- Creative plan from a cached scene/song map, 20k Gemini input + 5k output: about **$0.034** at 2026 rates.
- Thirty-second Gemini rough-cut review at default video token rate, 9k input + 2k output: about **$0.014**.
- Contact-sheet/transcript critic at 20k input + 4k output: roughly Luna **$0.009**, Terra **$0.088**, or Sol **$0.22**, before image-token variance. Sol is an explicit escalation only.

### Expected first-edit envelope

At 2026 rates, a normal first edit with one M1 research run, one low-resolution episode map, one targeted rescan, planning, and a few short critiques is roughly **$0.50–$1.00**. A default-resolution full episode, optional cloud ASR, extra research, or direct X can raise it to about **$1.00–$2.00**.

Subsequent concepts that reuse the same local/cloud analysis should usually be **$0.05–$0.30**. These values exclude electricity, storage, and existing Adobe/Topaz/FilmConvert license costs; those integrations have no API per-run charge in this design.

## Budget hierarchy

Hard limits apply independently and cumulatively:

- per provider request;
- per operation (research, video map, rescan, critic);
- per job/run;
- per project;
- optional daily/monthly user ceiling.

The most restrictive remaining limit wins. A UI warning is not a hard limit. A hard limit must be enforced transactionally in the trusted backend.

## Reservation algorithm

1. Load a non-stale `PriceCard` for the resolved model/tool.
2. Estimate maximum billable input from text/file/video duration, provider token rules, and provider-added retrieval/search context; keep any tighter request-payload bound distinct from the billed-usage ceiling.
3. Add configured maximum output/reasoning, maximum search/tool calls, and one permitted repair call.
4. Add a configurable uncertainty margin when provider accounting is not exact.
5. In one SQLite immediate transaction, calculate remaining caps and insert a `RESERVED` cost entry. If any cap would be exceeded, reject before network activity.
6. Execute with provider token/tool limits that match the reservation.
7. Reconcile provider-reported usage and actual charge; store raw provider cost ticks where available, convert to integer micro-USD, and release unused reservation.
8. If usage is missing, charge the conservative reservation and mark `USAGE_UNVERIFIED` until reconciled.
9. Never begin the next call if remaining budget is insufficient. Cancellation is not assumed to refund a remote call.

Use integer micro-USD in the ledger, not floating-point money. Store the human-readable Decimal price string and units on the immutable price-card snapshot.

For xAI search, `max_turns` does not itself cap individual tool invocations. A production request uses one active tool type, `parallel_tool_calls=false`, fixed turns/output, and a reservation covering the tested worst case; actual native `usage.cost_in_usd_ticks` is reconciled. An adversarial live billing fixture must prove the ceiling. If the cap cannot be demonstrated, that adapter is disabled rather than described as hard-budget-safe.

The trusted `CostEstimate` derives each component maximum by rounding Decimal quantity × integer micro-USD unit price upward, then derives total maximum as the exact component sum. Models cannot author or repair estimate totals.

## Required estimate contract

Every paid operation preview includes:

- provider and configured/resolved model;
- price-card URL, effective/check time, currency, and units;
- input estimate and method (`tokens`, `video_seconds`, `audio_minutes`, tool calls);
- maximum output/reasoning/tool/repair allowance;
- low/expected/high estimate;
- cache status and cheaper/local alternative;
- project/run limit, amount already spent/reserved, and remaining balance;
- retention/data-use/no-storage summary for **every** cloud query or upload, including current default 30-day xAI request/response retention and OpenAI abuse-monitoring/application-state behavior;
- eligible ZDR or `store:false` mode and how the adapter verifies that it actually applied.

The user confirms the operation class, not each microscopic retry. Retries may occur only inside the displayed reservation.

## Cache and duplicate-call rules

A paid semantic result cache key includes:

```text
provider + resolved model/snapshot + operation + prompt version + schema version
+ normalized parameters + input content hash + source freshness bucket + privacy mode
```

- Trend evidence expires by provider policy/freshness; local media maps are independently content-addressed per source and long-lived. A show library should reuse indexed episodes across later edits and invalidate only the affected analysis layer for corruption/source change, material schema/model improvement, a richer creative need, or explicit user request. Provider cache expiry is separate from local semantic-map validity.
- A semantically similar prompt is not automatically the same cache key when freshness matters.
- Concurrent identical requests use single-flight locking so only one paid call runs.
- Failed/refused/incomplete responses are recorded but not reused as successful results.
- Model/schema/prompt changes invalidate only affected layers, not the entire project.

## Price-card freshness and failure policy

- Bundle no price as unquestioned truth. Seed a documented catalog, then verify before first live use and whenever older than seven days.
- If model availability or pricing cannot be verified, live use fails closed with a diagnostic; local/offline features continue.
- Persist the exact card with each reservation so historical costs remain explainable after prices change.
- Provider-free quotas (for example YouTube) still need a quota ledger and preflight; “$0” does not mean unlimited.
- Subscription/licensing tiers such as TVmaze/TheTVDB are app configuration with entitlement evidence, not hidden operating assumptions.

## Suggested default controls

| Operation | Warning | Hard cap | Default behavior |
|---|---:|---:|---|
| M1 ordinary research | $0.25 | $0.50 | Direct X/deep research off; xAI search enabled only after invocation-cap proof |
| One 45-minute semantic map | $0.50 | $0.90 | Low resolution first; one targeted rescan allowance |
| Optional cloud transcription | $0.20 | $0.35 | Local first; explicit cloud opt-in |
| Short rough-cut critique batch | $0.10 | $0.25 | Gemini/Luna first; Terra/Sol explicit escalation |
| Ordinary first-edit project | $1.00 | $2.00 | Warn before any path that crosses $1 |

Defaults are configuration, not promises. The estimate UI shows the current calculated values and lets the user lower—not silently raise—hard limits.
