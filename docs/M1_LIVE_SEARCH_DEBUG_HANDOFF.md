# Milestone 1 Live Search Debug Handoff

Date: 2026-08-19 (America/Los_Angeles)

Status: debugging stopped at the user's request. Do not run another packaged UI loop or make another paid provider call from this handoff without a new, evidence-backed reason and fresh user authorization.

## Repository checkpoint

- Baseline checkpoint commit: `f464faa` (`checkpoint: preserve M1 live-search debug state`)
- This is the repository's root commit. Before it, the project had never been committed and nearly every project file was untracked.
- The checkpoint preserves the complete repository state that existed when the debugging stop was requested.
- Repository-local Git identity was set only so the checkpoint could be created:
  - `user.name=Codex Checkpoint`
  - `user.email=codex-checkpoint@local`
- No reset, clean, deletion, staging of ignored secrets, provider call, application run, test run, or build was performed while creating this handoff.

## Scope and stop boundary

This handoff covers Milestone 1 research only. No Milestone 2 work was started. In particular, this work did not add footage ingestion, media download, transcription, video understanding, shot detection, creative video planning, rendering, timelines, reframing, Topaz processing, After Effects automation, or protected-media acquisition.

The current stop boundary is deliberate:

- Do not click a paid consent button.
- Do not consume the stale consent preview that was open during the last UI inspection.
- Do not launch another full packaged UI test.
- Do not run another paid OpenAI request merely to see whether the result changes.
- Do not begin another fix until the evidence and hypotheses below have been reviewed.

## Exact expected behavior

The primary reproduction prompt is exactly:

```text
a good show for girls thatll get views on tiktok
```

Its deterministic normalized intent must remain:

```json
{
  "schemaVersion": "2.0.0",
  "query": "a good show for girls thatll get views on tiktok",
  "mediaKinds": ["TV_EPISODE"],
  "focusTerms": ["female-centered"],
  "freshnessDays": 14,
  "maxResults": 5,
  "region": "US",
  "spoilerPolicy": "CURRENT_EPISODE",
  "exclusions": []
}
```

For an evidence-supported result, packaged Screen B is expected to show:

- At least one real Opportunity card, and multiple distinct cards when separate titles independently pass the evidence gate.
- A specific current show that is supportably appropriate for the explicit female-centered request. The system must not silently replace the audience constraint with romance, and it must not present an audience-unknown title as though it satisfied that constraint.
- A supportable why-now claim.
- Two current, title-bound discussion signals from independent owner groups. Future plc sister publications count as one owner, not independent signals.
- An evidence-specific creative hook and useful emotional edit direction.
- Clickable provenance.
- No invented episode, scene, quote, speaker, character identity, or footage location.

For every rendered Opportunity, packaged Screen C is expected to show a complete `FootageRequest` with:

- Ranked required, optional, and alternative recommendations where those buckets are applicable.
- The smallest useful footage set rather than a whole season by default.
- Useful search suggestions.
- Honest `VERIFIED`, `STRONGLY_SUPPORTED`, `LIKELY_INFERRED`, or `UNKNOWN` certainty.
- Scene- or character-specific language only when source-owned evidence supports it.
- A generic scene pack when an exact scene is not supported.
- A canonical official YouTube watch link when the reviewed adapter accepted one.
- No article headline copied as a requested scene.
- No statement or implication that the application watched, transcribed, or downloaded a linked video.

Milestone 1 was also expected to prove, after this exact prompt worked:

1. A second ordinary prompt, such as `new shows that could be popular on TikTok rn`, produces a useful Opportunity and complete Footage Request.
2. Replaying the exact first prompt produces a whole-result cache hit with a `$0` maximum reservation, no provider requests, and the same Opportunities and Footage Requests.
3. An intentionally unsupported control returns an honest no-opportunity result without manufacturing evidence.

Those three completion proofs have not been finished against the current packaged r72 identity.

## Exact current behavior

There are two distinct current facts that must not be conflated.

### Latest persisted paid run

The latest persisted paid run for the exact prompt is job `50931045-e2fa-4246-bf7c-db566461be0e`, created locally at 2026-08-19 00:56:43. It completed with job and research status `SUCCEEDED` and persisted one Opportunity.

The sole Opportunity is:

```text
Stuart Fails to Save the Universe: Current-episode comedic and character moments; female-centered suitability is unverified
```

Persisted details:

- Media kind: `TV_EPISODE`
- Evidence gate: `LOW_CONFIDENCE`
- Why now: TVmaze lists `Spoiler: Stuart Makes a Wallet` as Season 1, Episode 4; the card correctly says this metadata is not official why-now proof.
- Discussion titles rendered in the card:
  - `How Much Effort It Took To Pull Off That Matrix Joke In Stuart Saves The Universe`
  - `10 Best TV Shows Like Stuart Fails To Save The Universe - TVLine`
- Footage summary: `Smallest evidence-bound footage request for this research opportunity.`
- Best request: `Give me a Stuart Fails to Save the Universe scene pack.`
- Minimum request: `The smallest useful set is a Stuart Fails to Save the Universe scene pack.`
- Optional improvement: `If you have it, the official Stuart Fails to Save the Universe clip would add another emotional option.`
- Alternative: none.
- Warnings correctly describe unknown source suggestions as broad inspection targets rather than verified scenes.

This is a technical success but not the required product success. The title itself admits that female-centered suitability is unverified, so it does not supportably satisfy the user's explicit audience constraint. It is also only one card, and the complete packaged Screen B/Screen C, cache-replay, second-prompt, and unsupported-control proofs were not completed for r72.

The latest paid run reconciled:

| Provider operation | Provider run | Result | Usage | Actual cost |
| --- | --- | --- | --- | ---: |
| TVmaze metadata | `3a017772-fd23-4272-b67a-8d064ea83ff8` | Success | 38 requests | $0 |
| OpenAI web verification | `c6eb5c38-cb96-4ec1-90a6-302fe0091858` | Success | 40 requests; 14 hosted web-search calls; 134,285 input; 44,120 cached input; 3,202 output; 1,063 reasoning tokens | $0.253789 |
| YouTube official metadata | `dff12451-2a4c-459b-a610-20aeeb7127e4` | Success | 5 requests | $0 |
| OpenAI synthesis | `ec98543b-16de-4dce-a744-93a23bb226b9` | Success | 1 request; 6,315 input; 0 cached input; 2,439 output; 978 reasoning tokens; no repair | $0.020949 |
| **Total** |  |  |  | **$0.274738** |

The verifier and synthesis maximum reservations of `$0.341998` and `$0.156000` were released after reconciliation.

### Current packaged r72 state

The current code identities are:

- Provider catalog: `m1-2026-08-18-r72`
- Bundle cache model: `openai:gpt-5.6-luna|catalog:m1-2026-08-18-r72`
- Bundle cache prompt: `m1-research-2026-08-18-r68+catalog:m1-2026-08-18-r72`
- Rust host prompt: `m1-research-2026-08-18-r61`
- OpenAI web configuration: `m1-openai-web-2026-08-18-r60`
- Current research-audit SHA-256 referenced by the catalog: `89a75c5dcc25a49574b1ba8046c9250304d17ab451fc11371753be86fcb70c48`

The verified r72 executable was rebuilt after a UI draft-persistence fix. The packaged UI was visually checked only far enough to prove that the exact prompt, 14-day freshness, and maximum result count of 5 survived a Settings round trip and that the consent preview showed a maximum of approximately `$0.498`. No paid r72 run was started after that UI rebuild. The preview is now stale and must not be consumed.

Recorded release hashes from that build:

- Executable SHA-256: `30EFA71C99A8E58AF8BA2D10C837BC7DFFC84E7954921AD90C067B6C526CF23A`
- Packaged worker SHA-256: `345B0121578F890C945C80FCCA8E7AA1C5446900E8EA6679DCB7F9B5E03D7AEC`

## Latest sanitized error

The latest failed job immediately before the successful one was `9ee84e51-fb12-4b15-922b-479db8f61729`, created locally at 2026-08-18 22:03:42. Its exact persisted sanitized error is:

```text
provider is unavailable: 1 validation error for FootageRequestDraftV2   Value error, optional-improvement copy must match optional sources [type=value_error, input_value={'summary': 'Broad scene-...ker, or intro moment.']}, input_type=dict]     For further information visit https://errors.pydantic.dev/2.13/v/value_error
```

That failure occurred after successful retrieval, YouTube metadata, and synthesis:

| Provider operation | Provider run / response | Usage | Actual cost |
| --- | --- | --- | ---: |
| TVmaze | `158aa863-8030-44c2-a6a0-9cf119d82887` | 38 requests | $0 |
| OpenAI verifier | Run `e1c6fff5-5fe3-4fb8-ab4e-428b620f201b`; aggregate `responses-batch:19cdafd728703e394e073c7c381a4e7a181faa88ca405d4865cc39ddea77dd4f` | 40 requests; 14 tools; 118,789 input; 44,120 cached; 3,002 output; 1,029 reasoning | $0.237093 |
| YouTube | `8d014d77-96b3-49ed-b37c-e32df406e524` | 5 requests | $0 |
| OpenAI synthesis | Run `5dfeea65-5ff2-49ed-b37c-e32df406e524`; response `resp_021cdb0e79eb557e016a853999d94487d08c4049bdbb2e8dfd` | 1 request; 6,316 input; 1,994 output; 516 reasoning | $0.018280 |
| **Total** |  |  | **$0.255373** |

The immediate cause was deterministic fallback construction: it added an optional official YouTube source but retained natural-language copy that did not include the corresponding optional-improvement sentence. The subsequent change made both deterministic fallback paths call the canonical `render_natural_request(...)`, and a full Rust-boundary regression was added. Job `50931045-e2fa-4246-bf7c-db566461be0e` then crossed that boundary successfully, so this specific schema-copy mismatch is considered fixed. It is not the same as the remaining audience/retrieval-quality defect.

## Provider, endpoint, and resolved model

The paid provider involved in the live-search issue is OpenAI.

| Operation | Provider | Endpoint | Configured model | Resolved model | Storage/tool mode |
| --- | --- | --- | --- | --- | --- |
| Canonical web verifier | OpenAI Responses API | `https://api.openai.com/v1/responses` | `gpt-5.6-luna` | `gpt-5.6-luna` | `store:false`; built-in `web_search`; bounded staged requests |
| Evidence synthesis | OpenAI Responses API | `https://api.openai.com/v1/responses` | `gpt-5.6-luna` | `gpt-5.6-luna` | `store:false`; strict JSON Schema output; no web tool |
| Candidate metadata | TVmaze | Fixed reviewed TVmaze API hosts in the adapter | n/a | n/a | Public metadata only |
| Official video metadata | YouTube Data API | Fixed Google API hosts in the adapter | n/a | n/a | Exact trusted titles and reviewed official channel IDs; no media/transcripts |

The OpenAI key and YouTube key remain in Windows Credential Manager. Their values were not read, printed, logged, exported, put in a command, stored in SQLite, or included in this document.

## Currently suspected request/header issue

There is no current evidence of an HTTP request-header defect.

The production transport constructs these HTTP headers:

```text
Authorization: Bearer [REDACTED; revealed only in memory to the fixed transport]
Accept: application/json
Content-Type: application/json
```

It posts only to the fixed HTTPS host `api.openai.com`, rejects redirects, caps a provider response at 4 MiB, and strictly parses JSON. The latest OpenAI verifier and synthesis calls both succeeded, which makes a missing authorization, accept, or content-type header unlikely.

The word “header” used during debugging more likely referred to the canonical Python-to-Rust result boundary. Rust currently reports the coarse error code `opportunity_header` if any one of these checks fails:

- Opportunity or request schema is not v2.
- Opportunity media kind and media identity disagree.
- Media identity is invalid or the media kind was not requested.
- Focus or confidence is invalid.
- Evidence gate is not `PASSED` or `LOW_CONFIDENCE`.
- Evidence is empty or contains more than 30 items.
- Score shape is invalid.

The immediately preceding live failure was not an HTTP-header failure and did not reach `opportunity_header`; it was a Pydantic `FootageRequestDraftV2` consistency failure. The most plausible request-shape problem was stale natural-language request copy after a deterministic fallback changed its required/optional/alternative source buckets. That exact mismatch has been fixed and regressed.

If a future run again reports `opportunity_header`, do not change HTTP headers first. Add or use a sanitized offline diagnostic that identifies which canonical subcheck failed, then reproduce that exact result bundle at the Rust boundary.

## Sanitized outgoing and incoming records

Raw wire bodies, response bodies, and response headers were not persisted. This is intentional: provider payloads can contain untrusted page content and credentials must never enter logs. Therefore, the following outgoing records are reconstructed shapes from the checked-in request builders, not captured wire logs.

### OpenAI verifier outgoing request shape

```http
POST /v1/responses HTTP/1.1
Host: api.openai.com
Authorization: Bearer [REDACTED]
Accept: application/json
Content-Type: application/json
```

```json
{
  "model": "gpt-5.6-luna",
  "store": false,
  "parallel_tool_calls": false,
  "reasoning": {"effort": "none"},
  "max_output_tokens": "[bounded per-stage allocation within 5,333 aggregate tokens]",
  "max_tool_calls": 1,
  "tool_choice": "required",
  "tools": [
    {
      "type": "web_search",
      "search_context_size": "low",
      "filters": {
        "allowed_domains": "[one reviewed owner partition]",
        "blocked_domains": "[direct-social denylist]"
      }
    }
  ],
  "include": ["web_search_call.action.sources"],
  "instructions": "[versioned bounded verifier instructions]",
  "input": "[host-authored immutable-title current-TV query with canonical after:YYYY-MM-DD cutoff]"
}
```

The staged verifier capability for the latest successful run allowed at most 40 provider requests, 14 web-search tool calls, 170,000 input tokens, 5,333 aggregate output tokens, and `$0.341998`. Every possible staged body was conservatively preflighted before the first paid call.

### OpenAI verifier incoming persisted metadata

```json
{
  "outcome": "SUCCESS",
  "providerRequestId": "responses-batch:360ac0738e0cedf95ac68799a238d33bde42c06362fe1ff49f83d69afa7043d1",
  "configuredModel": "gpt-5.6-luna",
  "resolvedModel": "gpt-5.6-luna",
  "promptVersion": "m1-research-2026-08-18-r61",
  "requests": 40,
  "toolInvocations": 14,
  "inputTokens": 134285,
  "cachedInputTokens": 44120,
  "outputTokens": 3202,
  "reasoningTokens": 1063,
  "repairUsed": false,
  "actualMicroUsd": 253789
}
```

Fourteen hashed `web_search_call` invocation identities are persisted, but raw provider search payloads are not. The aggregate identifier and usage above are sufficient to correlate the run without exposing provider content or credentials.

### OpenAI synthesis outgoing request shape

```http
POST /v1/responses HTTP/1.1
Host: api.openai.com
Authorization: Bearer [REDACTED]
Accept: application/json
Content-Type: application/json
```

```json
{
  "model": "gpt-5.6-luna",
  "store": false,
  "parallel_tool_calls": false,
  "max_output_tokens": "[bounded by the synthesis capability]",
  "instructions": "[versioned evidence-only synthesis instructions]",
  "input": "[canonical intent plus accepted evidence only]",
  "text": {
    "format": {
      "type": "json_schema",
      "name": "m1_research_synthesis_v2",
      "strict": true,
      "schema": "[lowered ResearchSynthesisDraftV2 schema]"
    }
  }
}
```

### Latest failed incoming application record

No HTTP error was persisted. All four provider runs succeeded, then the application emitted this sanitized job event:

```json
{
  "eventType": "FAILED",
  "jobId": "9ee84e51-fb12-4b15-922b-479db8f61729",
  "message": "provider is unavailable: 1 validation error for FootageRequestDraftV2   Value error, optional-improvement copy must match optional sources [type=value_error, input_value={'summary': 'Broad scene-...ker, or intro moment.']}, input_type=dict]     For further information visit https://errors.pydantic.dev/2.13/v/value_error"
}
```

## Attempted fixes and measured results

The repository had no pre-debug Git baseline, so the sequence below is reconstructed from persisted jobs, versioned comments/regressions, provider-run records, and the active debugging handoff. It deliberately separates measured facts from inference.

### Audience, evidence, and output fixes

| Attempt | Change | Measured result |
| --- | --- | --- |
| Preserve explicit audience intent | Recognized `for girls`, `for women`, `female audience`, and similar wording as deterministic `female-centered`; stopped converting the request to romance. | Worked. Every recent exact-prompt job persisted `focusTerms:["female-centered"]`, 14-day freshness, 5 results, `TV_EPISODE`, and US region. |
| Deterministic TVmaze audience affinity | Used bounded TVmaze-owned title/summary cues and excluded candidates with no supported audience cue when the explicit constraint is applied at candidate filtering. | Improved the initial slate, but downstream retrieval/synthesis still produced a Stuart card whose own copy says female suitability is unverified. The end-to-end constraint is therefore not yet reliable. |
| Owner-partitioned exact searches | Split exact-title searches into Future plc and reviewed non-Future owner lanes; prevented sister Future publications from counting independently. | Ownership semantics remained intact, but early allocation selected poor titles and missed known current two-owner coverage. |
| Multiple-title synthesis | Asked synthesis for every independently qualified title; added a deterministic evidence-gated fallback for omitted distinct titles. | No weakening of the gate. Most live attempts still had zero qualified cards; latest successful run produced only one card. |
| Evidence-bound Footage Requests | Prevented article headlines from becoming scene requests; required exact article-to-TVmaze-cast joins for named characters; kept exact scenes provisional and unknown locations honest. | Offline regressions pass. Latest persisted result uses a safe broad scene pack rather than inventing a scene. |
| Reviewed official YouTube adapter | Restricted searches to exact trusted titles and reviewed official channel IDs; rejected interviews, BTS, recaps, wrong titles, stale uploads, and unreviewed channels; emitted canonical watch links only. | Live metadata requests succeeded. A prior official HBO Max preview was accepted without inspecting media. Adding the optional clip exposed the natural-copy mismatch described above. |
| Two coverage-discovery searches | Added one Future and one reviewed non-Future discovery search over the immutable TVmaze slate; a cited response may only reorder an exact supplied title; discovery prose never becomes evidence. | The model could no longer inject arbitrary titles, but zero-selector responses and noisy hosted source ordering continued to starve exact known pages. |
| Exact dynamic-body preflight | Preflighted every possible exact-title request body before the first paid call and included the canonical `after:YYYY-MM-DD` cutoff. | Preserved Rust-owned capability enforcement; did not by itself improve retrieval quality. |
| Model-less YouTube diagnostic identity | Persisted a Rust-only internal endpoint identity while UI model remains `n/a`. | Packaged diagnostic showed YouTube `ready`; no key was exposed. This did not affect OpenAI retrieval quality. |
| Cached-discussion live revalidation | Prevented a reusable cached current discussion from completing an owner mix without fresh live revalidation. | Removed a cached false-positive route; subsequent runs remained honest but frequently abstained. |
| Current-page and headline validation | Dropped generic/unrelated headlines, required exact title binding and source-owned current dates, and rejected stale cached rows. | Removed unrelated accepted articles. It also exposed that hosted source allocation, not the evidence gate, was the limiting factor. |
| Zero-discovery fallback | Ensured zero coverage selectors cannot suppress the exact-title lane. | Exact searches still run when discovery returns nothing; live runs could still miss measurable pages. |
| Query simplification | Removed season, audience, month, and character terms from ordinary exact-title queries; retained immutable title, generic current-TV discriminator, and canonical cutoff. | Fixed known query overconstraint from live r56. One-word title collisions remained noisy. |
| Narrow owner retries | Reserved final TV retrieval slots for durable Future and PRISA owner partitions. | Recovered known pairs in offline fixtures; live source ordering could still bury the useful page behind many irrelevant owner-domain results. |
| Fourteen-search capability rebalance | Rebalanced request/tool/token reservation so two discovery, ten exact-title, and two precision searches fit the unchanged per-run hard cap. | Removed an under-authorized search plan, but later attempts hit input and output ceilings until additional budgeting fixes landed. |
| Owner-completion allocation | Stopped spending both final owner searches on one stochastic model-selected title; searched the bounded immutable slate and added a guarded second-owner completion tranche. | Offline regressions cover r60/r64/r66. Live ordering still placed exact valid sources too late in some responses. |
| Anti-monopoly page queue | Bounded the precision prefix, interleaved candidates/owners, and prevented 24 irrelevant precision pages from starving 104 ordinary exact-title sources. | Fixed the measured r63 starvation shape offline. A later live response still hid valid exact pages behind generic rows in the same owner lanes. |
| Late exact-hint ranking | Prioritized source title/URL hints that independently name the immutable seed and used current source-owned dates only as allocation hints; direct-page validation remains authoritative. | Exact r64-r70 regressions pass. A fresh paid proof was not completed after the final packaged rebuild. |
| Input capability reallocation | Raised/rebalanced the aggregate verifier input allowance within the cost reservation after live runs exceeded the old ceiling. | Latest successful verifier used 134,285 input tokens within a 170,000-token capability. Earlier ceiling failures stopped recurring in that run. |
| Output rollover | Replaced equal fixed per-response output slices with bounded rollover of reported unused output while preserving a floor for remaining searches and the unchanged aggregate cap. | Resolved the measured r68 shape where request 6 exhausted a 430-token slice while 3,823 aggregate output tokens remained. Offline cap invariants pass. |
| Role-prefixed character join | Accepted an exact role-prefixed article character reference only when it joins the immutable TVmaze performer record; retained rejection for nonjoining names. | Exact offline regression passes; no invented identity was added to the latest card. |
| Canonical natural request rendering | Both deterministic scene-level and broad-scene fallback builders now render natural copy from their final required/optional/alternative source lists. | Fixed job `9ee84e51-...`'s optional-improvement mismatch. The next exact run, `50931045-...`, succeeded across Python and Rust boundaries. |
| Full Rust-boundary regression | Added `metadata_low_scene_request_with_official_clip_passes_full_rust_boundary`. | Passes in the last known Rust suite and protects source buckets, copy, search queries, evidence, and policy together. |
| Parent-owned research form draft | Moved Screen A draft state to `App`, added an intentional reset path, and updated tests so visiting Settings no longer resets the exact prompt to the default romance example. | Packaged r72 visually preserved the exact prompt, 14 days, and max 5 through a Settings round trip. No paid r72 research was started afterward. |
| Cache/catalog identity advances | Advanced host, provider registry, catalog, and bundle-cache identities as behavior changed. | Prevents older whole-result cache entries from silently proving newer behavior. It also means the current r72 `$0` cache replay remains unproven. |

### Exact-prompt live outcome ledger

This table is a concise persisted history. `0 cards` means an honest `SUCCEEDED` research job with no Opportunity persisted; it is not product completion for an ordinary prompt.

| Local time | Job | Host prompt / web registry | Persisted outcome |
| --- | --- | --- | --- |
| 2026-08-18 08:06 | `2e74c86a-ab9d-4600-bd1e-545c55aa2049` | r40 / r39 | Succeeded, 0 cards. Retrieval selected five titles before measuring coverage; 128 URLs, 30 fetched pages, zero accepted current discussions. |
| 2026-08-18 09:34 | `ea5a7eda-4b8c-48ec-81ed-d3d19ab62667` | r41 / r40 | Succeeded, 0 cards. Discovery/coverage allocation still admitted noisy or unrelated hints; regression work removed the cached false-positive path. |
| 2026-08-18 10:11 | `a7f0fa06-15e1-43ff-9e16-3f27ab889843` | r42 / r41 | Succeeded, 0 cards. |
| 2026-08-18 10:34 | `258a735b-452c-48c3-bc92-78fe392482f8` | r43 / r42 | Succeeded, 0 cards. |
| 2026-08-18 10:48 | `cdd8b5d9-a10c-4605-a0bd-01919b6e1528` | r44 / r43 | Succeeded, 0 cards. |
| 2026-08-18 11:16 | `d5e5fc60-7a73-4888-bfc6-da2d515cff29` | r45 / r44 | Succeeded, 0 cards. |
| 2026-08-18 12:06 | `f1180543-f27c-455f-902e-aa427d6bd460` | r46 / r45 | Succeeded, 0 cards; synthesis ran but no Opportunity survived/persisted. |
| 2026-08-18 12:48 | `c0a46621-8238-4821-b766-e8380c3a3a8f` | r47 / r46 | Failed: OpenAI exceeded the authorized input-token ceiling. |
| 2026-08-18 13:03 | `28064954-5a9b-4ef7-9f23-b2bd21258237` | r48 / r47 | Succeeded, 0 cards. |
| 2026-08-18 16:37 | `419bae34-2ede-4435-b9bd-fad39bd7a8b2` | r49 / r48 | Succeeded, 0 cards. |
| 2026-08-18 17:01 | `c09473bb-a605-4181-a6f3-c04984ca1799` | r50 / r49 | Succeeded, 0 cards. |
| 2026-08-18 17:20 | `349b926f-a58a-4329-8159-49435bbcd982` | r51 / r50 | Succeeded, 0 cards. |
| 2026-08-18 17:41 | `6a3ecd77-9e09-483f-b389-21f722754fd2` | r52 / r51 | Succeeded, 0 cards. |
| 2026-08-18 18:07 | `85b948ba-3a22-4e7e-a424-746606481742` | r53 / r52 | Succeeded, 0 cards. |
| 2026-08-18 19:10 | `f463605b-5eda-4e9c-bba3-a9aa06a2b4d6` | r55 / r54 | Succeeded, 0 cards. |
| 2026-08-18 19:57 | `7d941902-5cef-4e1c-bce2-b4b4c2e72dbb` | r56 / r55 | Failed: OpenAI exceeded the authorized input-token ceiling. |
| 2026-08-18 20:19 | `82c2c1a7-a8c5-4687-9166-f1b5d3c21413` | r57 / r56 | Failed: OpenAI response ended with `{"reason":"max_output_tokens"}`. |
| 2026-08-18 20:32 | `32c9dfc1-407e-4d4c-ba8b-ab6eaafc5848` | r58 / r57 | Succeeded, 0 cards. |
| 2026-08-18 21:18 | `24c1233a-593c-48c4-bb74-01c9f310aada` | r59 / r58 | Succeeded, 0 cards. |
| 2026-08-18 22:03 | `9ee84e51-fb12-4b15-922b-479db8f61729` | r60 / r59 | Failed after all provider calls: optional-improvement copy did not match optional sources. |
| 2026-08-19 00:56 | `50931045-e2fa-4246-bf7c-db566461be0e` | r61 / r60 | Succeeded, 1 low-confidence Stuart card; card explicitly says female-centered suitability is unverified. |

An earlier job, `bfcadd3e-2e98-42da-854c-e3f3dc967983`, persisted one male-led `Lanterns` card before deterministic audience preservation was implemented. That result is not acceptable evidence that the exact audience request worked.

## Files changed during the debugging sequence

Because there was no commit before debugging began, Git cannot produce a historically exact “before debugging” diff. The checkpoint now prevents that problem for future work. The following is the complete set of files known from the live-debug changes and their corresponding regressions/identity updates in the active handoff. Files merely inspected while writing this document are not included.

### Python runtime

- `src/ai_edit_machine/research/intent.py`
- `src/ai_edit_machine/research/workflow.py`
- `src/ai_edit_machine/providers/tvmaze.py`
- `src/ai_edit_machine/providers/openai_web.py`
- `src/ai_edit_machine/providers/openai_synthesis.py`
- `src/ai_edit_machine/providers/youtube.py`

### Rust trusted host and packaged configuration

- `desktop/src-tauri/src/credentials/mod.rs`
- `desktop/src-tauri/src/commands/credentials.rs`
- `desktop/src-tauri/src/commands/diagnostics.rs`
- `desktop/src-tauri/src/commands/research.rs`
- `desktop/src-tauri/src/database/repositories.rs`
- `desktop/src-tauri/src/domain.rs`
- `desktop/src-tauri/src/provider_catalog.rs`
- `desktop/src-tauri/resources/provider-catalog.json`

### Desktop UI

- `desktop/src/App.tsx`
- `desktop/src/App.test.tsx`
- `desktop/src/screens/FindEditScreen.tsx`
- `desktop/src/screens/FindAndCost.test.tsx`

### Offline regressions and documentation

- `tests/test_m1_providers.py`
- `tests/test_m1_research.py`
- `docs/RESEARCH_AUDIT.md`
- `docs/M1_COMPLETION_REPORT_2026-08-15.md`
- `docs/M1_LIVE_SEARCH_DEBUG_HANDOFF.md` (this handoff)

If a later forensic review finds a debugging edit outside this list, use `f464faa` as the immutable baseline and record the correction. Do not infer historical authorship from file modification times; the repository was initially populated as untracked files.

## Tests currently known to pass

These results are the last completed validation set before the user stopped the loop. They were not rerun while creating this handoff.

- Python: 195 tests passed; 4 optional worker-build tests skipped.
- Generated contracts: all 34 schemas verified.
- Python bytecode compilation: `compileall` passed.
- Frontend: 16 Vitest tests passed.
- Frontend: strict TypeScript and Vite production build passed.
- Rust: 91 tests passed.
- Rust: `cargo check --locked --all-targets` passed.
- Verified release script completed and reported:
  - `Verified packaged worker: 74 files, AMD64, protocol clean.`
  - `Verified Tauri release worker resource.`
  - `Built and verified the optimized M1 Tauri application.`

`cargo fmt` was not run because the `rustfmt` component is missing. No component installation was authorized or attempted.

Relevant exact regressions include:

- Explicit female-audience intent preservation without genre stereotyping.
- TVmaze exclusion of high-weight shows without supported female-audience affinity.
- Owner-partitioned multi-result TV search.
- Zero-discovery exact-title recovery.
- Narrow Future/PRISA owner retries for known `Furious` coverage.
- Precision-page anti-starvation and late exact-hint owner completion.
- Aggregate output rollover without exceeding the authorized cap.
- Role-prefixed character-to-TVmaze-performer joining.
- Cached discussion live revalidation.
- Official-video optional source and clickable scene-label behavior.
- `metadata_low_scene_request_with_official_clip_passes_full_rust_boundary`.
- Screen A exact-draft persistence through Settings.

Passing offline tests do not establish that the ordinary live prompt is useful. The persisted latest card is the contrary product-level evidence.

## Smallest known reproduction

Do not execute this reproduction while the stop instruction remains active. It is documented for the next authorized investigation.

### Product-level live reproduction

1. Start the verified packaged executable.
2. Enter exactly `a good show for girls thatll get views on tiktok`.
3. Use freshness 14 days, maximum results 5, region US, and TV episode media kind.
4. Preview consent. Under current price/configuration identities, the expected maximum is `$0.341998` for verification plus `$0.156000` for synthesis, total `$0.497998` (rendered as approximately `$0.498`), with the `$0.50` run hard limit.
5. Only after fresh explicit authorization, approve once and wait for completion.
6. Inspect Screen B and Screen C, then inspect the corresponding read-only SQLite rows.

The smallest currently known failure signature is either:

- Current r61 behavior: a single `LOW_CONFIDENCE` Stuart card whose own title says female-centered suitability is unverified; or
- The now-regressed prior r60 boundary failure: optional official clip exists but `naturalRequest.optionalImprovement` does not match the optional source bucket.

### Offline boundary reproduction for the resolved schema mismatch

Construct a metadata-low-confidence scene-pack result with one reviewed official YouTube clip in `optional_sources`, then pass the complete worker bundle through Rust validation. Before the fix, deterministic fallback copy omitted the optional-improvement line and `FootageRequestDraftV2` rejected the object. The exact Rust regression is `metadata_low_scene_request_with_official_clip_passes_full_rust_boundary`.

### Read-only database reproduction

Using SQLite read-only mode, inspect:

- Job `50931045-e2fa-4246-bf7c-db566461be0e` for the current product gap.
- Job `9ee84e51-fb12-4b15-922b-479db8f61729` for the latest sanitized failure.
- Their `provider_run`, `cost_entry`, `opportunity`, `footage_request`, and `job_event` rows.

Never edit the ledger, budget, evidence, cache, job, or result rows directly.

## Hypotheses that remain untested

1. **Explicit audience must survive the final gate, not only candidate normalization.** A deterministic rule may be missing between TVmaze candidate affinity and final fallback construction: when the intent contains explicit `female-centered`, an Opportunity whose own supported copy says suitability is unverified should probably be excluded or cause an honest abstention.
2. **Known `Furious` coverage may still be retrieval-unstable.** Offline fixtures prove the allocation logic for a known current Future/PRISA pair, but a fresh live response may order sources differently or omit them.
3. **Late exact-source prioritization has no final r72 paid proof.** The latest live success used host r61/web registry r60, but the packaged r72 UI rebuild itself was only tested through consent preview.
4. **Multiple independently qualified female-centered titles are unproven.** The synthesis/fallback supports multiple cards offline, but no current live exact-prompt run has visibly proved them.
5. **Screen C rendering of the latest optional official clip is unproven in r72.** The stored contract is complete; every rendered link, bucket, certainty label, and natural sentence still needs visual inspection when live testing is resumed.
6. **Whole-result cache replay is unproven for current identities.** Catalog/cache identity advances intentionally invalidate older results, so a `$0` preview and no-provider replay must be demonstrated only after a genuinely acceptable current result exists.
7. **The second ordinary prompt and unsupported control remain unproven.** Do not infer them from the exact-prompt result.
8. **`opportunity_header` remains too coarse if it recurs.** A future failure could be any of eight subchecks; no new live run should be spent until a complete failing result can be replayed offline with finer sanitized diagnostics.
9. **Provider-body observability is deliberately limited.** Because raw response bodies and headers are not persisted, stored metadata alone cannot always distinguish malformed structured provider output from a deterministic post-processing mismatch. Any added diagnostic must remain bounded and sanitized and must not store web page bodies, secrets, or unrestricted provider payloads.
10. **Aggregate token headroom may still vary.** The latest verifier fit within 170,000 input and 5,333 aggregate output tokens, but hosted-search response variance could still approach either cap. A future change needs an offline budget proof before another paid check.
11. **The `Stuart` discussion signals may be title-bound yet semantically weak for the requested audience.** Their independence and currentness do not establish female-centered affinity. That distinction needs a deterministic, evidence-backed decision rather than synthesis wording alone.

## Approaches that must not be repeated without new evidence

- Do not perform repeated paid reruns after an honest abstention or weak card without first identifying one new measured failure mechanism and adding an exact offline regression.
- Do not treat “tests pass” as evidence that an ordinary live prompt is useful.
- Do not increase search, page, tool, token, or cost budgets merely to create another chance at a different hosted-search order.
- Do not change HTTP authorization/content headers in response to `opportunity_header` or a Pydantic contract error.
- Do not rely on prompt wording alone to guarantee coverage, owner diversity, evidence quality, audience affinity, or output-contract consistency.
- Do not treat discovery prose, a hosted search's source list, source ordering, or model-selected titles as evidence. Direct-page validation remains authoritative.
- Do not reintroduce season, audience, month, or character terms into ordinary exact-title queries without a measured retrieval comparison; live r56 showed those terms could hide an otherwise accepted page.
- Do not let one title, owner, or precision lane monopolize the direct-page fetch budget; live r63 showed 24 irrelevant precision pages could starve 104 ordinary exact-title sources.
- Do not use fixed per-call output slices that strand unused aggregate output; live r68 measured that failure.
- Do not count Future plc sister publications as independent.
- Do not weaken the evidence gate to force a card.
- Do not count a YouTube clip as an independent discussion signal or as proof that a scene was watched.
- Do not copy an article headline into a requested scene or assert an exact scene, quote, speaker, or footage location without source-owned support.
- Do not make several retrieval/ranking changes at once and then spend a paid run without a fixture isolating each changed behavior.
- Do not edit SQLite ledger, budget, evidence, cache, or result rows to manufacture a pass.
- Do not move credentials into environment variables, commands, fixtures, logs, screenshots, source, or SQLite.
- Do not build a release with raw Cargo. Use only `scripts\build_verified_m1_release.ps1` after relevant offline validation when work is explicitly resumed.
- Do not advance into Milestone 2 while this Milestone 1 gate remains open.

## Recommended next starting point when work is explicitly resumed

Start offline from the persisted successful result, not from another provider call. Trace why an intent with `focusTerms:["female-centered"]` can retain an Opportunity whose own evidence says female-centered suitability is unverified. Encode the intended decision as one exact Python workflow regression and one full Rust-boundary result regression. Only then decide whether a fresh packaged paid test contains genuinely new information.

This recommendation is documentation only. No additional fix was started.
