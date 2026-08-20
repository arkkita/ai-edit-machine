# Structured AI Contracts

AI output is untrusted data. Provider schema modes improve syntax; they do not establish factuality, safe paths, valid source IDs, frame-accurate timing, affordable execution, or good editing taste.

## Contract layers and ownership

1. **Provider draft** — only fields a model is allowed to author, lowered to the selected provider's conservative JSON Schema dialect.
2. **Canonical storage contract** — strict, versioned Pydantic record with trusted IDs/provenance added by the host.
3. **Domain validation** — database membership, evidence coverage/independence/freshness, media bounds, enabled presets, policy, and budget.
4. **Trusted execution contract** — deterministic compiler output. Models never author costs, paths, commands, filter graphs, effect values, or executable plans.

`src/ai_edit_machine/contracts.py` has three disjoint registries:

- `PROVIDER_OUTPUT_CONTRACTS`: `ResearchIntent`, `TrendOpportunityDraft`, `FootageRequestDraft`;
- `CANONICAL_STORAGE_CONTRACTS`: intent, evidence, persisted opportunity/request, and model-run envelope;
- `TRUSTED_EXECUTION_CONTRACTS`: `CostEstimate` and `CompiledEditPlan`.

Pydantic models run with `strict=True`, `extra="forbid"`, frozen values, bounded primitives, UUIDv4 IDs, and explicit outcome validators. Decode provider JSON through the JSON-validation path; do not obtain Python coercion by constructing models from arbitrary dictionaries. Server IDs are omitted from drafts, then preallocated/injected by trusted code. A model-selected evidence/claim ID must belong to the exact allowlist sent in that request.

The scaffold implements only the contracts listed above. `ResearchPlan`, `FootageCheck`, `SemanticScene`, `SceneCandidate`, `SongMap`, `IntroCandidate`, `EditConcept`, `CreativeExplanation`, `RoughCutCritique`, and `JobEvent` are planned milestone contracts, not current code.

## Stored model-run envelope

The trusted adapter pairs a payload with a schema-valid envelope:

```json
{
  "schema_version": "1.0.0",
  "schema_name": "trend-opportunity-draft",
  "prompt_version": "m1-opportunity-v1",
  "trace_id": "bc397018-02a3-4377-a60e-03a61d430087",
  "job_id": "919c5c73-4184-4591-947c-e123d5f4d27a",
  "provider": "xai",
  "configured_model": "grok-4.6",
  "resolved_model": "provider-returned-id-or-fingerprint",
  "generated_at": "2026-08-15T12:00:00Z",
  "input_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "outcome": "SUCCESS",
  "payload_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "refusal": null,
  "incomplete": null
}
```

The outcome is exclusive: `SUCCESS` requires a payload hash and no error detail; `REFUSAL` requires only refusal detail; `INCOMPLETE` requires only incomplete detail. Usage, tool calls, citations, retention mode, provider request ID, immutable price card, and cost live on the associated trusted `model_run`.

## Evidence and claims

An evidence record keeps these facts distinct:

- source creation/update, page publication, event/release, and retrieval times;
- query and exact time window;
- provider record ID and canonical URL;
- short quote, paraphrase, or unverified-lead type;
- primary/corroborated/lead/stale/retracted state;
- policy class plus refresh, purge, expiry, and deletion obligations;
- content hash and minimal excerpt.

Search access is not a license to archive the underlying page, post, image, or clip. Store the minimum normalized evidence permitted by policy rather than unrestricted provider responses or social bodies.

An opportunity draft uses structured references:

```text
claim_id + role + independence_group + supports_why_now
```

`PASSED` requires at schema level one `PRIMARY_WHY_NOW` reference and two `QUALITATIVE_SIGNAL` references across at least three groups. Trusted database joins then prove that IDs exist, the primary directly supports the why-now claim, signals are genuinely independent, and none is stale, expired, retracted, lead-only, or copied from the same origin. An official clip qualifies as primary only when its publication/content directly establishes the current event.

A `VERIFIED` footage quote requires an authoritative `quote_claim_id`. M1 can provide wording only when that claim survives the trusted join; otherwise it emits a paraphrase or unverified lead. M2 resolves wording and timing against user-supplied subtitles/media. Episode identity, scene location, speaker, and quote wording are separate claims and cannot promote one another by association.

### M1.1 interpretation, funnel, and ranking contracts

`ResearchIntentV2` owns a versioned `IntentInterpretation`: strict facets for
hard constraints, soft preferences, audience, platform fit, and creative edit;
semantic evidence questions; editable presentation metadata; clarification
state; and the direct-TikTok-data/inference disclosure. Deterministic parsing
may supply useful priors for a vague request but cannot turn gender into a rigid
genre assumption.

`CandidateFunnelV1` names all fourteen requested boundaries and bounded
rejection codes. Counts are nonnegative and must not be silently omitted from a
development diagnostic. The final Rust mapping recomputes received/displayed
counts from the validated opportunity array rather than trusting model prose.
For each deeply researched title, `CandidateDiagnosticV1` adds a bounded
shortlist reason, retained current hook, audience/fandom/story evidence, source
categories and evidence IDs, inferred short-form note, typed score/threshold
traces, exact rejection gate, and one of retrieval/evidence/threshold/supported
classifications. `CandidateScoreTraceV1.status=NOT_COMPUTED` is mandatory for a
ranker component or gate the title never reached; diagnostics cannot invent a
numeric substitute. Recovery-attempt counts and a specific coverage warning
are canonical funnel fields, not UI-only prose.

`OpportunityQualityScoreV1` records the profile ID, every component, the
uncertainty penalty, and the recomputed total. `ShortFormEditPotentialV1` is a
named proxy with evidence-linked signals and a categorical band; it cannot
represent a TikTok virality probability or imply direct data when the intent
contract says none was used.

### Editorial concept contract

The canonical dependency graph is:

```text
Opportunity
  -> exactly one FandomStoryDossier
  -> one to four supported EditorialConcept records
  -> exactly one selected EditorialConcept
  -> exactly one selected concept-specific FootageRequest
```

`FandomStoryDossierV1` is the evidence-to-concept boundary. It separates
verified facts from inferences for the current hook, named characters and
central relationship, episode/season/trailer/clip/announcement source,
quote leads, franchise/parent/sequel/spinoff connection, relationship or
character history, current fan interest, audience/fandom support,
uncertainties, and evidence references. Its `dossier_id` must match the parent
opportunity and every child concept. Editorial synthesis receives this dossier,
not unbounded provider prose or release metadata alone.

`EditorialConceptV1` is a child of exactly one dossier/opportunity and includes a
specific central subject, optional relationship, core emotion, viewer hook,
why-fans-care explanation, current event, typed contextual/legacy connection,
one-to-three intro leads, song handoff, three-to-six functional montage beats,
ending/payoff, evidence, verification status, structure-derived score,
uncertainties, and a concept-owned `FootageRequestV2`. The request repeats the
exact `concept_id`; the top-level selected request must be byte-for-byte the
request owned by `recommended_concept_id`. Unsupported or zero-concept
opportunities are invalid, and `NO_STRONG_OPPORTUNITY` must contain no dossier,
concept, or request.

Domain validation requires a concrete current hook, intro direction, montage
progression, payoff, actionable source request, and supporting evidence. It
rejects generic “get clips from this show” language, unsupported exact quotes
or episode locators, fan interpretation presented as verified fact, and a
cross-title source without evidence of the exact canonical bridge. Different
concepts may request different sources. Every card carries the provisional
notice that later local footage analysis may confirm, change, or reject it.

## Multi-source footage request

Every selected supported concept has one conversational `FootageRequest`, not a prose-only afterthought. Its canonical shape includes:

```text
required_sources[]       smallest sources essential to the concept
optional_sources[]       useful improvements whose absence must not block work
alternative_sources[]    lower-effort or safer substitutions, including scene packs
suggested_search_queries[]
minimum_useful_set       explicit explanation of the least the user should obtain
natural_summary          BEST / ALTERNATIVE / MINIMUM / OPTIONAL IMPROVEMENT guidance
concept_id               exact selected EditorialConcept identity
```

Each requested-source item can carry show/title, nullable season and episode number/title, source kind, characters/relationship/topic, scene/moment, likely context, short quote and nullable speaker, priority, estimated user effort, purpose (`INTRO`, `MONTAGE`, `PAYOFF`, `OPTIONAL_CALLBACK`), emotional rationale, evidence references/quality, and one of exactly `VERIFIED`, `STRONGLY_SUPPORTED`, `LIKELY_INFERRED`, or `UNKNOWN`; presentation renders `LIKELY_INFERRED` as “LIKELY / INFERRED.” Unknown fields remain absent/unknown; they are never filled by model repair. Quote wording and episode location each need their own supporting claim. A scene-pack alternative is valid when fan discussion establishes a moment but not its precise episode, or when it minimizes acquisition better than many episodes.

Numeric season identifiers are bounded to `0..9999`, not `0..999`: current metadata providers legitimately use calendar years such as `2026` as season identifiers for some daily and continuing series. The wider bound does not infer a season; the exact value still needs the same episode-identity evidence and trusted provider/domain validation as any other locator.

Domain validation proves that required items form a nonempty minimum useful set, optional items are not presented as blockers, alternative groups can actually substitute for named required groups, priorities/orders are coherent, evidence IDs belong to the run allowlist, search suggestions are nonempty discovery queries rather than download instructions, and every factual precision is no stronger than its evidence. Presentation code renders these contracts naturally; it must not reduce them to sterile labels.

A valid presentation can therefore say: “I found a verified quote that could make a strong intro. Give me S3E3 so the later video model can inspect that conversation. For the payoff, also give me S3E5. If locating episodes is awkward, a Belly + Conrad multi-season scene pack is the lower-effort alternative. S1E4 is optional callback material.” If the quote is recurring but its episode is unverified, it instead says so and recommends the scene pack or named scenes without inventing an episode. Suggested queries such as `Belly Conrad season 3 episode 3 scenes`, `Belly Conrad scene pack`, or an exact short quoted phrase are discovery suggestions only.

The research workflow may return `NO_STRONG_OPPORTUNITY` with an explanation and evidence summary. It is invalid to manufacture a recommendation merely to satisfy a requested result count. Opportunity language can describe a strong current edit opportunity, never a virality probability or guarantee.

## Time and stream contracts

Four concepts must not be conflated:

```text
ApproximateLocator  model/search hint with uncertainty and observations
SemanticAnchor      transcript/ASR/beat constraint; useful for search, not a cut
ResolvedBoundary    one decoded stream PTS + timebase + stream index + evidence
TimelineFrame       deterministic output-frame position after conform
```

Each endpoint of a `ResolvedMediaRange` carries source UUID/hash, stream-signature hash, stream index/type, PTS/timebase, boundary kind, resolver ID, resolution-evidence UUID, and confidence. Endpoints must agree on source/stream and have increasing PTS; video frame indices must also increase. Picture endpoints must be decoded video frames (or a user-confirmed decoded frame); audio endpoints must be decoded audio samples. Separate audio/video ranges retain their different timebases. An evidenced asset-clock mapping stores both stream origins and proves mapped start/end agreement within one audio sample.

Transcript, subtitle, ASR, cloud, and beat timestamps can constrain a resolver but never appear as picture-boundary authority. Domain tests must cover VFR video, negative container starts, distinct audio/video timebases and offsets, and beat-to-frame quantization.

Future video-analysis contracts are provider-independent: source media, episode, shot, scene, dialogue segment, character, relationship, event, emotional beat, visual moment, scene candidate, temporal evidence, confidence, semantic description, reusable provider-cache identifier, and analysis provenance. Gemini-specific fields remain inside an adapter envelope. Before M2 implements these contracts, the focused current long-video study in `MILESTONES.md` may revise their exact schema and migration deliberately; it may not be bypassed by coding the M0 proposal during M1.

## Trusted compiled edit plan

`CompiledEditPlan` is runtime-owned and is not exported to any provider. It includes:

- grammar/version and enabled preset-registry version;
- output aspect/frame rate and explicit conform policy;
- immutable ordered clip IDs;
- per-clip decoded picture range, source handles, crop/reframe spec, separate audio policy/range, timeline frames, beat anchor, evidence, and rationale;
- selected song source range, song timeline origin, beat handoff, dialogue tail/music pre-lap/source+song fades/accent, and exact rational beat-to-frame error;
- deterministic ending choice/duration and exact expected duration;
- compiler version, input fingerprint, timestamp, and passed validation checks.

The M0 safe registry exports only `STATIC@1`, `CLEAN_CUT@1`, and center crop. A static source duration must match its timeline duration within the declared one-output-frame conform tolerance, and cumulative plan error also stays within one frame. Orders must be `0..n-1` in timeline order, clips must be contiguous, all nonterminal clips get a clean cut, and the terminal clip gets no unusable transition.

The grammar validator requires `INTRO_DIALOGUE` (with mapped source audio), optional intro reactions, exactly one `HANDOFF` boundary at 5–24 seconds, then at least one `MONTAGE` with only montage/payoff/ending roles afterward. The handoff clip references the selected beat. Trusted rational arithmetic derives the nearest output frame (ties forward), verifies the reported exact error within half a frame, and proves the selected song range covers the picture timeline. Dialogue-tail, pre-lap, fades, and accent are typed—not prose-only.

The validation report must contain the exact mandatory gate-code set, a trusted compiler-run UUID, and a SHA-256 that binds canonical plan fields plus compiler version. The execution boundary recomputes that fingerprint, joins the compiler run and boundary/evidence UUIDs to trusted records, and reruns the mandatory validators; a JSON report saying “passed” is never sufficient by itself. A future schema must represent intentional gaps explicitly before gaps are allowed.

Reserved names (`SOFT_PUSH`, `SOFT_PULL`, `IMPACT`, blur/glow strengths, and dark bridge) remain grammar vocabulary only. They cannot enter an executable contract until a versioned runtime registry, handle/audio/interpolation rules, golden renders, and user approval exist.

`INTRO_DIALOGUE_SUBTITLE` is likewise a renderer-owned, versioned style preset. A model supplies only evidence-backed dialogue text/segmentation candidates. It cannot author or override case, the exact `- ` prefix, font, placement, size/width/line-spacing rules, color/opacity/shadow treatment, or alignment. Subtitle rendering remains outside M1.

## Trusted cost estimate

`CostEstimate` is backend-only. Every component stores a Decimal quantity plus integer micro-USD unit price and maximum. Trusted validation rounds the multiplication upward, proves every component maximum, derives the total as the exact component sum, checks expected ≤ maximum, and checks already-spent/reserved + maximum ≤ hard limit. Provider-native cost ticks remain alongside the ledger entry. Models may not author, summarize into, or overwrite money fields.

## Provider schema lowering

`scripts/export_contract_schemas.py` emits:

```text
contracts/v1/provider/{xai,openai,gemini}/...
contracts/v1/canonical/...
contracts/v1/execution/...
```

The current provider lowerers form an offline baseline: every object property is required, objects forbid additional properties, defaults/format assumptions are removed, and runtime validation reapplies the stronger canonical constraints. M1 must add recorded conformance fixtures against each live configured provider before calling a dialect production-compatible. An unsupported provider keyword may be removed only with the weakened constraint logged and re-enforced locally.

## Validation pipeline

```text
provider response
  → transport/refusal/incomplete classification
  → provider schema parse
  → strict provider draft
  → trusted ID injection/canonical record
  → evidence/policy/domain validation
  → cost/execution validation
  → immutable payload + validation report persistence
```

Required domain checks include:

- all selected IDs belong to the exact project/source/request allowlist;
- evidence directly supports its assigned claim/role and is current/independent;
- release/event/publication/retrieval dates are not substituted for one another;
- source boundaries are locally decoded, stream-identified, in bounds, and have required handles;
- required footage exists or a structured gap remains;
- preset name and version are registered and enabled;
- aspect/crop cannot stretch or exceed source bounds;
- source/output paths cannot collide;
- planned provider/tool work fits an already durable reservation;
- footage request source buckets, priorities, purposes, verification levels, quote/episode evidence, alternatives, search suggestions, and minimum useful set are coherent and minimize unnecessary acquisition;
- exclusions/freshness are honored and an empty/no-strong-opportunity outcome remains valid.

## Retry, refusal, and logging

- Transport/rate retries are provider-aware, bounded, idempotent, and remain inside the existing reservation.
- A syntax/schema/domain failure permits at most one repair call with concise validation errors. Never repair absent evidence, footage, quotes, IDs, dates, or timestamps by invention.
- A second failure is stored and surfaced; no permissive parser or regex salvage reaches persistence/execution.
- Refusal and incomplete are terminal typed outcomes, not generic malformed JSON.
- One idempotency key maps to one logical operation; attempts cannot double-commit entities, cost, or artifacts.
- Log versions, IDs, phase/errors, latency, retries, token/cache/tool use, native cost ticks, reconciled micro-USD, and hashes. Never log secrets, signed URLs, full private transcripts/frames, hidden reasoning, or unsanitized provider bodies.

## Example M1 provider draft

```json
{
  "schema_version": "1.0.0",
  "media_kind": "TV_EPISODE",
  "title": "Example series — S02E04",
  "focus": {
    "characters": ["Character A", "Character B"],
    "relationship_or_topic": "trust after a reversal"
  },
  "why_now": "A newly released episode put this relationship at the center of current discussion.",
  "creative_hook": "Set up the broken promise, then contrast earlier trust with the reversal.",
  "evidence": [
    {
      "claim_id": "c9d19fa8-e18a-4394-a84e-c87e62be0825",
      "role": "PRIMARY_WHY_NOW",
      "independence_group": "official-network",
      "supports_why_now": true
    },
    {
      "claim_id": "fc3be219-5f92-45b2-a922-f61a02020782",
      "role": "QUALITATIVE_SIGNAL",
      "independence_group": "x-discussion",
      "supports_why_now": true
    },
    {
      "claim_id": "5a5ef14d-91aa-4930-8ee5-449f28904b9e",
      "role": "QUALITATIVE_SIGNAL",
      "independence_group": "independent-editorial",
      "supports_why_now": true
    }
  ],
  "evidence_gate": "PASSED",
  "confidence": 0.78,
  "caveats": ["Exact dialogue and scene timestamps require supplied media."]
}
```

This demonstrates shape, not a factual recommendation. The backend validates each claim and generates the opportunity/request UUIDv4 IDs.

## Versioning

- Patch: documentation/non-behavioral clarification; parser remains compatible.
- Minor: backward-compatible optional value understood by new consumers.
- Major: required field or semantic change; create a new schema/prompt and migration/adapter.

Never rewrite an old stored model result to appear as if it was produced under a newer schema.
