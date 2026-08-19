# AI Edit Machine Milestone Plan

The product is built as a sequence of independently testable proofs. Later work does not compensate for a weak earlier proof: if opportunity research is poor, do not add video analysis; if clip selection is poor, do not add effects.

## Gate discipline

Every milestone has five required exits:

1. Contract/schema version is frozen for the next milestone.
2. Offline unit/integration tests pass with no paid calls.
3. A bounded live/golden evaluation passes where the feature depends on current external data.
4. Cost, privacy, policy, cancellation, cache, and failure behavior are visible.
5. The user explicitly approves progression.

## Milestone 0 — research and architecture

**Status:** complete. Milestone 1 was explicitly approved on 2026-08-15; Milestone 2 remains unapproved.

Delivered in this milestone:

- fresh August 2026 technology, provider, price, license, hardware, desktop, and finishing audit;
- architecture and trust-boundary decision;
- programmatic inventory of three style videos, the supplied AEP, and the Topaz preset;
- data model and strict AI-contract design;
- API budget/reservation design;
- durable project rules in `AGENTS.md`;
- minimal Python contract/config tests and reproducible reference-analysis scripts;
- exact implementation gates for Milestones 1–7.

M0 intentionally does not install a toolchain, create provider accounts, call paid APIs, render footage, or scaffold the full Tauri UI.

## Milestone 1 — trend/opportunity researcher

**Status:** implemented and awaiting user review on 2026-08-15. Milestone 2 remains unapproved.

### Goal

Given a natural-language niche prompt, return useful, current, evidence-backed edit opportunities and an actionable footage request. This milestone proves that the product can answer “what should I edit right now, and what should I obtain?”

### Exact approved scope

#### Desktop foundation

- Bootstrap Tauri 2 + React + strict TypeScript after Rust/uv/Node/WebView2 diagnostics pass.
- Implement Screen A **Find an edit**, Screen B **Opportunities**, and Screen C **Footage Request**.
- Add a small Settings/Diagnostics surface for provider status, configured/resolved model IDs, price-card age, query/upload retention and data-use modes, cache/purge policy, and hard budgets.
- Package one Python worker health/research sidecar and complete protocol handshake, progress, cancellation, clean shutdown, and restart-interruption recovery.
- At build time, embed in the Rust host the worker's version/Windows-x64 target plus an exact relative-path/size/SHA-256 manifest. Verify every one-folder launcher/archive/DLL/PYD/resource and reject missing, extra, modified, wrong-target, or substituted-manifest bundles before launch; sanitize Python/DLL search inputs. M1 is a development package, not yet an Authenticode-signed commercial release.
- Add WinCred `CREDENTIAL_TYPE_GENERIC` create/validate/delete with namespaced targets and `CRED_PERSIST_LOCAL_MACHINE`; never display a saved key or let an SDK fall back to ambient environment credentials.
- Add minimal Tauri capability files, restrictive CSP, blocked remote navigation, allow-listed system-browser URLs, bounded invoke/protocol payloads, production devtools off, and a release permission audit. Generic shell/filesystem/process/opener permissions fail acceptance.

#### Research domain

- Strict `ResearchIntent` parsing: media type, niche, relationship/character/topic, region, freshness window, spoiler policy, exclusions, and result count.
- TVmaze adapter for television release/episode/cast facts with attribution and cache policy.
- Official studio/distributor/network page discovery and verification through OpenAI web search, including `store:false` where no Responses state is intended; official pages are the film-release baseline while licensed metadata is disabled.
- YouTube Data API adapter restricted to configured official studio/network/streamer channel IDs; canonical links only in M1, no embeds/downloads/transcript scraping, no engagement-derived score, and public metadata refresh/delete within 30 days.
- Grok 4.6 X Search adapter for qualitative fandom leads only after an adversarial invocation-cap test. Use one active tool type, `parallel_tool_calls=false`, fixed turns/output, native `usage.cost_in_usd_ticks` reconciliation, and eligible verified ZDR when configured; 4.3 is a measured fallback.
- Optional xAI Web Search secondary path. Direct X, Reddit, TMDB, and unapproved TheTVDB adapters remain disabled.
- Provider capability/model preflight, timeouts, bounded retry, kill switch, and live-call opt-in.

#### Evidence and recommendation engine

- Normalize provider IDs, canonical URLs, titles/authors/channels, query/window, source-created/updated, page-published, event/release, retrieved, refresh/purge/delete timestamps, excerpt type, confidence, policy, content hash, and cost.
- Deduplicate syndicated/circular sources and distinguish publication date from the event/release date.
- Gate a normal-confidence opportunity on one verified primary that directly supports the why-now event plus two independent qualitative signals. An old/unrelated official clip does not qualify. A current exact TVmaze episode-identity record plus at least two independent current title-bound discussion signals may support only an explicitly low-confidence card when no official why-now page is verifiable; metadata alone or metadata plus one signal must return no opportunity, and this fallback never verifies a scene, quote, or speaker.
- Score only explainable factors: release freshness, independent-source count, cross-source agreement, and scene/relationship specificity.
- Never label a result “viral,” “guaranteed,” or platform consensus. Do not blend incomparable engagement metrics.
- Exact quotes require citable official verification. Otherwise return a paraphrase or `unverified_quote_lead`.
- Generate a conversational `FootageRequest` that answers “what exactly should I go get so this edit can be made?” It carries ranked `required_sources[]`, `optional_sources[]`, and `alternative_sources[]`; multi-episode, multi-season, trailer, individual-clip, and scene-pack requests are first-class.
- Each requested source can identify show/title, season, episode number/title, character/relationship/topic, specific scene or moment, short quote and speaker, likely context, priority, purpose (`INTRO`, `MONTAGE`, `PAYOFF`, `OPTIONAL_CALLBACK`), emotional rationale, verification level, source/evidence quality, and discovery search queries. Fields remain unknown rather than invented.
- Use `VERIFIED`, `STRONGLY_SUPPORTED`, `LIKELY_INFERRED` (UI: “LIKELY / INFERRED”), and `UNKNOWN` consistently for footage facts. Exact quotes require citable authoritative proof; recurring fan discussion without episode proof remains an unverified lead and should produce a safer request/alternative.
- Rank sources by creative usefulness and user effort. State the minimum useful footage set, avoid requesting unnecessary episodes/whole seasons, and offer a scene pack when it can replace excessive acquisition. Search terms are discovery assistance only; the user supplies lawful local media.
- Think ahead to a possible contextual intro by identifying evidence-supported conversations, confessions, arguments, revelations, exchanges, realizations, quotes, and immediate reactions and explaining why they could lead into a montage. Never call one the final intro before actual local footage analysis.

#### Persistence and cost

- Numbered SQLite migrations for research runs, evidence, opportunities, footage requests, jobs, provider runs, cache entries, and the cost ledger.
- Policy-aware provider TTL/refresh/purge/deletion behavior and per-provider kill switches. Persist canonical IDs/URLs, minimal excerpt/paraphrase and hashes—not unrestricted search/provider bodies.
- Pre-call cost preview and transactional reservation. Suggested defaults: $0.25 warning, $0.50 hard cap per ordinary research run, direct X disabled.
- Before every cloud request, display provider/model, price/reservation, retention/data-use/no-storage mode, cache status, and local/cheaper alternative. Release workers require a Rust-issued immutable job capability; `.env` can authorize development tests only.
- Record configured/resolved model, prompt/schema versions, provider request ID, exclusive outcome, usage, search/tool calls, provider-native cost ticks, actual micro-USD, retention mode, and cache result.

#### Testing and evaluation

- Offline fake-provider contract suites and captured-response fixtures.
- Unit tests for strict/provider schemas, server-owned UUIDs, date normalization, URL canonicalization, copied-source independence, expired/retracted/lead-only gates, quote claims, policy TTL, component-derived cost, rounding/overflow/cache, reservation, and hard-cap races.
- Research-domain tests for multiple requested episodes and seasons; required versus optional footage; scene-pack alternatives; source priority, purpose, effort, verification level, and evidence provenance; useful search queries; verified quote+episode and uncertain quote/episode; no fabricated certainty; exclusions and freshness; minimum useful footage; and an honest no-worthwhile-opportunity result.
- Integration tests for LF-framed protocol limits/EOF/stdout corruption; missing/extra/tampered/wrong-target worker files; auxiliary DLL/PYD/archive mutation; sibling-manifest substitution; exact hierarchy/hash/protocol verification of the worker after Tauri copies it into the optimized release tree; hostile Python/DLL/provider/budget environment variables; cancellation; cache replay; migration; redacted logs; Tauri capabilities/navigation/CSP; and provider failure matrices.
- Recorded live conformance fixtures for each enabled provider schema. xAI also gets an adversarial maximum-turn/tool billing test; failure keeps the adapter disabled.
- A small dated golden set of varied niches: current TV episode, current film/trailer, relationship, character, broad genre, spoiler-free, obscure/no-evidence, and malicious prompt content.
- Interactive evaluation with the user before M2. Include a query such as “romance/romcom TV, preferably a new episode from the last three days, no K-drama, no reality TV.” Save ratings for relevance, recency, why-now clarity, emotional/editorial specificity, evidence quality, verified-vs-inferred honesty, intro potential, minimum-footage usefulness, search-query usefulness, latency, and total cost.

### M1 acceptance criteria

M1 passes only when all are true:

- A natural-language query produces 1–5 independently qualified, genuinely useful cards or an honest “insufficient evidence” result. Never pad a strong single result to reach an arbitrary count; the evidence gate and footage actionability decide the count.
- Each card separates why-now evidence from the creative edit hook and exposes clickable sources/retrieval dates.
- Episode/release facts are verified, not inferred from fandom posts.
- Every recommendation naturally explains what it is, why now, what viewers are discussing, which relationship/character/moment matters, useful quotes and their certainty, what emotional edit and possible intro it might support, and its evidence/provenance.
- Every recommendation has a concrete, attainable, multi-source-capable footage request with useful search terms, essential/optional/alternative sources, and a smallest useful footage set that minimizes user acquisition effort as well as API cost.
- Missing exact footage/quote knowledge is stated; no timestamp is invented.
- Repeating the same run inside its cache window avoids equivalent paid calls.
- A pre-call estimate appears and the trusted reservation cannot be exceeded by concurrent/correction/tool paths. xAI search counts as hard-bounded only after the adversarial proof; otherwise the adapter is disabled.
- Cancellation leaves no orphan worker/provider job and restart marks interrupted local jobs correctly.
- Offline tests pass; the approved live golden run remains inside its disclosed budget.
- The release build passes the Tauri capability/CSP/navigation/devtools permission audit and ignores hostile provider/budget environment variables.
- The user judges the interactive recommendations useful enough to continue.
- Representative requests make the user reasonably willing to obtain the named footage; popularity without an actionable creative reason does not pass.

### Explicit M1 non-scope

- No user footage upload, source probing, transcription, video model call, shot detection, or semantic media index.
- No song upload/analysis, intro selection, montage planning, rough-cut rendering, timeline, crop tracking, velocity implementation, Topaz, AE, or final effects.
- No generic browser, social analytics dashboard, social-post archive, or popularity prediction.
- No TMDB/Reddit/direct-X dependency and no media downloads from YouTube or protected services.

### Stop gate

After the M1 interactive report, stop for user approval. The handoff reports all relevant test/schema/type results, the dated interactive/golden evaluation, actual paid API cost, configured/resolved provider model versions, architecture changes, several representative outputs, known limitations, and explicit confirmation that no M2 implementation occurred and the focused video-ingestion study remains recorded at the M2 approval boundary. If relevance, evidence, footage requests, or cost are weak, iterate M1 rather than starting M2.

## Milestone 2 — footage intelligence

**Status:** not approved. The focused research below is a required part of the future M2 approval boundary, not permission to begin it during M1.

### Goal

User selects a lawfully obtained episode, trailer, or scene pack and receives a searchable, cached, evidence-backed understanding of exactly what is present.

### Deliverables

- **Mandatory approval-boundary research before implementation:** repeat a focused current study of long-video ingestion, indexing, caching, retrieval, and cross-video reasoning. Evaluate native long-/multi-video models; persistent provider contexts/file reuse/video-token caching; multimodal embeddings/RAG; hierarchical scene memory; coarse-to-fine and adaptive resolution/FPS sampling; subtitle-, audio-, shot-, character-, relationship-, and event-first filtering; compressed representations; batch/asynchronous work; local GPU preprocessing; hybrid local/cloud designs; scene-pack handling; and any new August 2026 capabilities.
- Score alternatives on creative understanding, subtle reaction/eye-contact/touch/pause/insert/transition-handle retention, dialogue/audio understanding, temporal precision, multi-episode/season reasoning, per-hour cost, latency, cacheability/repeated-edit economics, RTX 4060 8 GB and 64 GB feasibility, complexity, provider stability, API/file/context limits, privacy/storage, licensing, reliability, and maintainability. Publish measured or clearly labeled estimated costs/quality implications and why the final strategy wins. Do not retain the proposal below merely because M0 approved it.
- Safe file ingest/fingerprint, ffprobe inventory, disk-space estimate, optional proxy creation, immutable source handling.
- Subtitle-first extraction; drift check; local ASR/alignment fallback; optional reviewed OCR path.
- Local shot/fade boundaries with frame, PTS/timebase, confidence, and representative frames.
- Provider-independent contracts and adapters for source media, episode, shot, scene, dialogue segment, character, relationship, event, emotional beat, visual moment, scene candidate, temporal evidence, semantic description, confidence, reusable provider-cache identifier, and analysis provenance.
- Unless the focused research selects a better strategy: independently cacheable source maps, merged into a project/show scene library, compact cross-source retrieval for the planner, and higher-detail analysis only for shortlisted moments. One source would normally receive one primary semantic pass, but multi-video joint reasoning must be evaluated when it materially improves story/relationship understanding.
- Explicit-consent Gemini 3.7 primary semantic pass plus targeted rescans and clean Gemini 3.6 rollback for API regression, outage, unsupported features, or measured quality regression. Keep IDs configurable and compare both on the golden set; model age alone never makes 3.6 the normal default. Replace Gemini if the focused research demonstrates a materially better practical model/architecture.
- Character/relationship evidence graph, transcript/shot links, candidate scenes, quote candidates, uncertainty, and user-confirmed aliases.
- Reusable source/show cache for decoded timing, subtitles/transcript, shots/scenes, character/relationship/events, visual descriptors/embeddings where justified, coarse maps, fine shortlisted analyses, and provider cache references. Invalidate only for corruption/source change, material schema/model improvement, richer creative need, or explicit user request.
- Multi-file `FootageCheck` comparing requested versus available material across episodes/scene packs, admitting missing moments, distinguishing required from optional gaps, and saying when the current footage is sufficient. Missing optional footage never blocks an otherwise strong edit.
- Pre-call `VideoAnalysisEstimate` where practical: duration, resolution, sampling, token estimate, file count, cached/uncached state, coarse/fine passes, model/provider, batch/flex rate, server cache reuse, and per-source/total estimated cost.
- FTS5 transcript/description retrieval; Qwen text embeddings only if a golden test proves value.

### Exit

On representative multi-file supplied footage, users can find a line/moment/character, inspect supporting shots/transcript, understand required versus optional coverage, reuse previously indexed episodes, and trust locally verified timestamps. Cloud locators never become cuts without resolution. Test independently before song work.

## Milestone 3 — song and creative edit planner

### Goal

Given a research brief, verified footage map, and user-selected song/section, create multiple emotionally coherent edit plans—no final effects.

### Deliverables

- Manual song-section mode first; optional automatic section suggestions.
- Beat/downbeat grid from Beat This and structure features from librosa, with confidence/manual override.
- Three intro candidates and three main concepts by default, each with thesis, emotional arc, footage coverage, risks, and why each clip belongs.
- Deterministic constraint solver for duration, dialogue continuity, local shot boundaries, beat grid, diversity, aspect/crop safety, and audio handoff.
- Versioned immutable plan candidates with alternatives/explanations, deterministically compiled into `CompiledEditPlan` only after exact decoded-stream, handle, crop, audio/song, ending, enabled-preset, duration, and validation-report checks.

### Exit

Plans pass schema/domain validation and a human can understand, compare, and reject individual choices before anything expensive runs.

## Milestone 4 — rough-cut renderer

### Goal

Render several fast, effect-free 4:3 rough cuts that prove the selected moments and story work.

### Deliverables

- Validated EDL → typed FFmpeg filter graph compiler.
- Default center/manual 4:3 crop, normalized proxy settings, dialogue/song handoff, simple fades only where explicitly planned.
- Rendering uses either an explicitly selected/preflighted user FFmpeg binary or an already approved controlled build; the decision cannot wait until M7.
- `-nostdin`/dedicated progress and optional cancellation pipes, bounded timeouts, progress/cancel/recovery, destination-volume staging, output verification, truthful cross-volume/network fallback, provenance manifest, and reproducible command record.
- Side-by-side playback of A/B/C with explanations and cost/time summary.

### Exit

The user watches a rough cut and believes the system chose the right clips. Do not proceed because rendering works technically; creative selection is the proof point.

## Milestone 5 — editable timeline and alternatives

### Goal

Human can fix one AI decision without regenerating the whole plan.

### Deliverables

- Trim, replace, reorder, mute/include, crop-position override, and partial regeneration.
- Ranked alternatives with “why this clip” and evidence links.
- Named velocity vocabulary may be shown, but only registry-enabled/versioned presets enter `CompiledEditPlan`. Until calibration, execution remains `STATIC@1` and `CLEAN_CUT@1`; no arbitrary curve UI/model output.
- Immutable plan revisions, undo/redo, changed-region rerender, preference signals, and stale-artifact invalidation.

### Exit

User changes one clip and only dependent artifacts regenerate. Approved edit lock is explicit.

## Milestone 6 — Topaz and After Effects finishing

### Goal

Convert an approved rough cut into the user's existing polished look through deterministic, recoverable integrations.

### Deliverables

- Mezzanine export and current Topaz manual `WAITING_FOR_USER_EXTERNAL_PROCESS` handoff with import/skip/cancel acknowledgement; no claimed external progress/cancellation.
- Optional legacy TVAI **7.1.0** adapter only after exact-patch allowlist, license evidence, CLI smoke test, and preset golden output.
- Supplied AEP as versioned canonical look template; with AE closed and user confirmation, fixed audited bootstrap JSX that never calls `app.quit()`; work-order/sentinel protocol; supervisor-owned `aerender` progress and output verification.
- FilmConvert Nitrate effect match-name/presence plus plugin binary hash or installer evidence and a known-input golden smoke render. Unknown version evidence blocks deterministic finishing; no plugin redistribution.
- User-approved blur/glow presets and separately stored velocity curves calibrated through controlled tests.
- Serialized GPU/AE work, disk estimate, cancellation/recovery, and source/intermediate/final manifests.

### Exit

At least one approved edit survives Topaz/AE from a clean copied template, matches the reference look under user review, is reproducible from its manifest, and never modifies its source or canonical assets.

## Milestone 7 — polish

Potential work is evidence-gated:

- preference learning from explicit user decisions;
- face-track-assisted 4:3 reframing;
- season-wide semantic library and optional multimodal embedding benchmark;
- additional measured editing grammars;
- richer project history/batch concepts/cost analytics;
- optional stronger short-rough-cut critic;
- packaging, signed updater, clean-VM matrix, accessibility, telemetry opt-in, privacy controls, and commercial readiness.

Do not add a feature merely because a model/library supports it. Each addition needs a measured user benefit, latency/VRAM budget, license review, failure fallback, and deletion/cache policy.
