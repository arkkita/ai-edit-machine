# AI Edit Machine — Durable Agent Instructions

## Current project state

Milestone 0 (research and architecture) is complete. Milestone 1 (trend/opportunity researcher) is implemented and awaiting user review. Milestone 2 has **not** been authorized. Read `docs/RESEARCH_AUDIT.md`, `docs/ARCHITECTURE.md`, `docs/MILESTONES.md`, `docs/EDIT_GRAMMAR.md`, `docs/API_COSTS.md`, `docs/DATA_MODEL.md`, and `docs/AI_CONTRACTS.md` before changing architecture or starting a milestone.

Do not skip milestone gates. When a milestone is complete, report its evidence and wait for explicit user approval before starting the next one.

## Non-negotiable product rules

- Default output is 4:3; never stretch footage. An explicit project aspect override is allowed.
- Rough-cut approval happens before Topaz, After Effects, or other expensive final effects.
- Exact picture cuts resolve to decoded local video-frame PTS with source/stream signatures, increasing frame index, rational timebase, and trusted resolution evidence. Audio uses its own decoded-sample range and evidenced stream-origin mapping. Transcript, ASR, beat, and cloud times are anchors/constraints only, never final cut authority.
- Never let an LLM invent arbitrary velocity curves, effect keyframes, crop paths, filter graphs, code, commands, SQL, or filesystem paths.
- A model may choose only registered, versioned, currently enabled presets. Unknown/free-form values fail validation.
- Every AI scene/clip choice must be explainable and linked to evidence, source range, and intended creative role.
- Research must produce concrete footage requirements, not vague inspiration.
- Every recommended opportunity ends in a natural-language, minimum-effort `FootageRequest` with ranked `required_sources[]`, `optional_sources[]`, and `alternative_sources[]`. It answers what the user should obtain, why each item matters, how it may serve the future intro/montage/payoff/callback, and what to search for. Multi-episode, multi-season, trailer, individual-clip, and scene-pack requests are first-class; never request a whole season when a smaller useful set is supported.
- Missing footage, unverified quotes, uncertain identities, and weak evidence must be admitted.
- Footage facts use exactly `VERIFIED`, `STRONGLY_SUPPORTED`, `LIKELY_INFERRED` (displayed as “LIKELY / INFERRED”), or `UNKNOWN`. Never fabricate an episode, scene location, speaker, or quote. A recurring but unverified quote stays an unverified lead and may justify a safer scene-pack alternative, not a falsely precise episode request.
- Research ranks actionable creative opportunities, not raw popularity. It must be allowed to return “No strong opportunity found under these constraints.” Never state a virality probability or certainty.
- Never defeat DRM, protected streaming systems, access controls, paywalls, or platform download restrictions.
- Assume the user supplies lawfully obtained footage/music. Do not download audiovisual material from YouTube or social/streaming services.
- Preserve the user's existing After Effects look. The supplied AEP and its hash are canonical; do not re-create or overwrite it from guessed property IDs.
- Preserve the supplied Topaz preset byte-for-byte. Do not silently translate legacy model/control IDs into the current product.
- Never overwrite, edit in place, rename, move, or use a source file as an output/temp target.
- Centralize model/provider configuration and record configured plus resolved model/snapshot for every run.
- Validate all structured AI outputs with strict canonical contracts and domain checks before persistence/execution.
- Treat stored validation reports as claims: execution recomputes the canonical plan+compiler fingerprint, verifies the trusted compiler run/boundary evidence, requires every mandatory gate code, and reruns timing/grammar/audio/preset/duration checks.
- Cache expensive media analysis by source hash + tool/model/prompt/schema/config version.
- Track every paid call/tool invocation and reserve conservative cost before network activity.
- Never silently exceed a hard cost limit. A UI warning is not enforcement.
- No secrets in source control, SQLite, logs, command lines, screenshots, fixtures, or model prompts. Production keys live in Windows Credential Manager through Rust.
- Build and test milestone by milestone. Do not implement the finished app in a giant pass.
- Do not add dependencies casually. State purpose, maintenance, license, binary/VRAM/packaging cost, and why the standard/current stack is insufficient.
- Prefer current maintained tools, but do not upgrade merely because a number is newer; the pinned media/GPU matrix must pass.
- Reference videos are canonical style evidence. If written style rules conflict with measured references, flag the conflict and prefer the measured evidence unless the user directs otherwise.
- Keep modules small and cohesive. Do not create a giant monolithic `app.py`, provider switch statement, or general agent loop.

## Approved architecture direction

- Desktop: Tauri 2 + React + strict TypeScript on supported Windows 11 x64.
- Trust boundary: renderer is untrusted; Rust owns files, secrets, SQLite, process supervision, capability checks, and Windows Job Objects.
- Worker: persistent packaged Python sidecar using one UTF-8 JSON object per LF-terminated line on inherited stdin/stdout. For M1 development bundles, the Rust host embeds the build-time version/Windows-x64 target and an exact relative-path/size/SHA-256 manifest for every worker file; it rejects missing, extra, tampered, wrong-target, or substituted-manifest bundles before launch. A one-folder package must cover its launcher, archives, DLLs, PYDs, and resources—not only the EXE—and launches with sanitized Python/DLL search inputs. Tauri packaging must preserve the one-folder relative hierarchy (including PyInstaller's `_internal/`) and the optimized built-resource tree must exactly match and protocol-smoke against the verified source bundle; map-style recursive globs that flatten resources are forbidden. Shipped builds additionally require Authenticode on every PE at the commercial packaging gate. Protocol stdout is exclusive; diagnostics use stderr. Frames are capped at 4 MiB, the handshake times out after 5 seconds, and malformed/oversized/truncated frames or unexpected EOF fail the job and restart the worker. No localhost FastAPI server for v1.
- Python: begin the packaging matrix on pinned CPython 3.12 and uv; end users install neither.
- Persistence: local SQLite WAL + foreign keys + numbered migrations + FTS5. The future Rust build must vendor and preflight SQLite >=3.51.3; the current Python runtime's older SQLite is not release evidence.
- Research: TVmaze + official pages; Grok 4.6 X Search as qualitative lead generator with 4.3 cost fallback; OpenAI web search as canonical verifier; official-channel YouTube metadata/links only.
- Disabled by default: TMDB under current AI terms, direct Reddit, direct X, unapproved TheTVDB, deep-research modes.
- Video semantics: Gemini 3.7 Flash is the intended primary later-milestone video-understanding/creative-editing model; Gemini 3.6 Flash is the clean rollback for outage, unsupported features, API regression, or measured quality regression. IDs stay centralized/configurable, the 3.7-vs-3.6 golden comparison remains mandatory, and age alone is not a reason to make 3.6 the normal default. The internal media/episode/shot/scene/dialogue/character/relationship/event/emotional-beat/visual-moment/candidate/evidence/provenance contracts are provider-independent so a materially better model or architecture may replace Gemini after focused research. Cloud timestamps are approximate until resolved locally.
- Media truth: ffprobe/FFmpeg, subtitle-first timing, local ASR/alignment, PySceneDetect, Beat This, and librosa.
- Rendering: validated EDL compiled to typed FFmpeg argv/filter graphs. No shell-generated commands from model text.
- Finishing: current Topaz manual handoff first; optional exact-version legacy TVAI adapter later; fixed audited AE ExtendScript + `aerender` only in Milestone 6.
- Manual Topaz work is an external user-owned step, represented as `WAITING_FOR_USER_EXTERNAL_PROCESS` with import/skip/cancel acknowledgement; never claim process progress or cancellation control.

Any proposed substitution must be researched against current official sources and documented in `docs/RESEARCH_AUDIT.md` plus an architecture decision. Never silently substitute a model, provider, tool, license tier, or product generation.

## Style rules

The active grammar is `DIALOGUE_DROP_EDIT_V1` in `docs/EDIT_GRAMMAR.md`.

- Dialogue/context setup target is 12–19 seconds, allowed 5–24 seconds when story evidence supports it. One canonical reference breaks the written 20-second suggestion at approximately 22.6 seconds.
- Montage cadence accelerates markedly; reference-informed visual cells are commonly about 0.5–1.1 seconds, but cuts remain shot/beat/story-driven.
- Reserve roughly 1.8–2.2 seconds for an optional black/title ending when that preset is selected.
- Transition strengths are not calibrated by Milestone 0. Do not invent numeric blur/glow settings.
- Only `STATIC` is operationally defined until velocity presets pass controlled source/render tests and user approval.
- Intro dialogue uses deterministic `INTRO_DIALOGUE_SUBTITLE`: Arial Regular unless measurement establishes a more accurate font, all lowercase, exactly `- ` at the start of every subtitle event, horizontally centered near the lower safe margin, preferably no more than two lines, and restrained styling. The renderer—not AI—owns typography, case, prefix, placement, size, spacing, color, opacity, shadow/softness, alignment, maximum width, and segmentation rules. Reference measurements govern values that can be supported; unresolved values remain explicitly uncalibrated rather than guessed. This does not make every subtitle treatment in every grammar universal.

## Source and artifact safety

- Canonicalize and validate all paths in the trusted core. Use app-issued handles across the UI/worker boundary.
- Working files live in an app-owned job directory. Each publishable artifact is staged in an app-owned hidden directory on the destination volume.
- Write create-new temp → close → ffprobe/hash/size verify → same-volume atomic replace. Cross-volume/UNC/reparse-point destinations require an explicit verified copy protocol and may never be described as atomic.
- Put every child process in a kill-on-close Windows Job Object. Try cooperative cancellation, then bounded termination.
- Persist source hash/stream signature and re-check before dependent work. Changed source invalidates cache; it is never “fixed” in place.
- Long-running/reference inspection fingerprints source hash, size, and mtime both before and after all passes and fails closed on change. AE JSX writes only to a unique `.unvalidated` quarantine; after the post-check, the audited wrapper atomically publishes a verified provenance sidecar before the final report. A final AE report is consumable only when that sidecar exists and its report/source hashes match.
- Generated AEPs are copies in finishing run directories. Never save into the canonical reference AEP.

## AI and evidence discipline

- Use versioned Pydantic contracts with `extra="forbid"`, conservative provider schemas, and independent domain validation.
- Allow at most one bounded repair attempt; never repair absent evidence, missing footage, quotes, IDs, or timestamps by invention.
- Refusal and incomplete outputs are typed outcomes.
- Keep release/event/publication/retrieval dates distinct.
- One official primary source plus two independent qualitative signals is the normal M1 evidence gate. Otherwise return low confidence. A current exact TVmaze episode-identity record plus at least two independent current title-bound discussion signals may support an explicitly `LOW_CONFIDENCE` card when no official why-now page can be verified; metadata alone or metadata plus one signal must abstain, and this path cannot promote an episode scene, quote, or speaker.
- A primary record must directly support the why-now claim; a merely official but old or unrelated clip does not pass the gate.
- Never call search output a census, consensus, or virality probability. Keep platform metrics in their original platform/units.
- Quotes require authoritative verification; otherwise mark paraphrase or unverified lead.
- A footage source item carries purpose, priority, effort/usefulness rank, verification level, evidence IDs, and quote verification separately. Search queries are discovery suggestions only; the app never downloads protected or audiovisual media for the user.
- Face/speaker clusters do not establish named character identity. User-confirmed aliases do.
- Search retrieval does not license the underlying page, post, image, or clip. Persist canonical ID/URL, separate dates, minimal excerpt/paraphrase, hash, and policy metadata—not unrestricted provider payloads or social bodies. Enforce TTL, refresh, purge, deletion, attribution, and kill-switch rules.

## Cost and provider rules

- Release workers do not read `.env` for provider authority, model selection, keys, or budgets. Paid calls require an immutable per-job capability and durable reservation issued by Rust; environment overrides are development/test-only.
- Load a fresh price card, estimate a worst case including tools/output/reasoning/one repair, reserve transactionally, execute within matching limits, and reconcile actual usage.
- Use integer micro-USD in the ledger. Record provider-native usage/cost ticks as supplied.
- Concurrent identical calls use single-flight locking.
- Never infer a model exists from a prompt/document. Preflight the configured ID and record the resolved ID.
- Treat xAI search spend as hard-bounded only after a live adversarial test proves the selected request can cap invocations. Use one active tool type, `parallel_tool_calls=false`, bounded turns/output, and reconcile `usage.cost_in_usd_ticks`; otherwise leave that adapter disabled.
- Before every cloud query or upload, show provider/model, reservation, retention/data-use/no-storage mode, cache status, and local/cheaper alternative. Private/copyrighted footage additionally requires estimated upload size plus explicit project-scoped consent.

## Development workflow

Before edits:

1. Confirm the approved milestone and its explicit non-scope in `docs/MILESTONES.md`.
2. Inspect `git status`; preserve unrelated user work.
3. Inspect relevant contracts/data migrations and canonical reference hashes.
4. For any current model/version/price/term claim, verify first-party documentation.

While editing:

- Use narrow provider/tool interfaces and inject fakes for tests.
- Keep provider SDK types at adapter boundaries; domain code uses canonical contracts.
- Make workflows deterministic/idempotent outside bounded model calls.
- Log IDs/timing/usage/cost and sanitized errors, never secrets/private payloads.
- Add offline tests before optional live/golden tests. Live tests require a flag and a hard dollar cap.
- M1 tests cover multi-episode/multi-season requests, required vs optional sources, a scene-pack alternative, search suggestions, verified and uncertain quote cases, exclusions/freshness/provenance, source priority/purpose/verification, minimum useful footage, budget enforcement, and the honest no-opportunity outcome.
- Do not make network installs or generate lockfiles with unreviewed dependency resolution without authorization.

Before any Milestone 2 implementation, perform a fresh, focused video-ingestion/long-video architecture study against the evaluation dimensions in `docs/MILESTONES.md`. Evaluate native long-video/multi-video models, provider caches, hierarchical or scene-level multimodal indexing, embeddings/RAG, coarse-to-fine and adaptive sampling, subtitle/audio/shot-first filtering, batch/asynchronous work, hybrid RTX 4060 local preprocessing, and project-level cross-episode reasoning. Document estimated/measured quality, subtle-reaction retention, timing, multi-episode behavior, cost, latency, cacheability, privacy, limits, licensing, stability, and maintenance. The current independently cacheable source-map → project scene library → targeted fine-pass strategy is a proposal, not doctrine. Do not implement this research or any video ingestion during M1.

Before handoff:

- Run the relevant offline tests, schema export/check, compile/type checks, and changed-file review.
- Report what changed, what was deliberately not changed, validation evidence, costs incurred, risks, and the next approval gate.
- Do not commit, stage, push, publish, install system software, or call paid providers unless the user asked/approved that action.

## Current minimal Python checks

From the repository root:

```powershell
python -m unittest discover -s tests -v
python scripts/export_contract_schemas.py --check
python -m compileall -q src scripts
```

Reference analysis requires explicit FFmpeg/ffprobe paths, bounded subprocesses, `-nostdin` on FFmpeg calls, collision checks, and report output restricted to `artifacts/reference-analysis/`. After Effects may reuse an existing instance for `afterfx.exe -r`: require AE to be closed plus explicit user confirmation, abort if a project is visible, never call `app.quit()`, and write only a create-new report under a unique `.unvalidated` quarantine. The wrapper polls for that report with a bounded timeout; it never waits for, stops, or kills the long-lived After Effects GUI. Only after post-source and JSON/hash checks does it publish matching provenance and then the final report. Only a supervisor-owned `aerender.exe` process may be treated as safely cancellable.
