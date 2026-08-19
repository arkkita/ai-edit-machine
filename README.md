# AI Edit Machine

AI Edit Machine is a planned local Windows workflow for finding timely TV/movie fandom-edit opportunities, understanding user-supplied footage and music, proposing explainable edits, rendering fast rough cuts, and applying the user's deterministic finishing look only after approval.

## Status

Milestone 0 research/architecture and the Milestone 1 trend/opportunity researcher are implemented. **Milestone 1 is awaiting user review; Milestone 2 has not been approved.** The dated, network-inert M1 golden evaluation and representative outputs are in [evals/](evals/README.md).

Start here:

- [M1 implementation report (2026-08-15)](docs/M1_COMPLETION_REPORT_2026-08-15.md)
- [Research audit](docs/RESEARCH_AUDIT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Milestones and exact M1 scope](docs/MILESTONES.md)
- [Measured editing grammar](docs/EDIT_GRAMMAR.md)
- [API costs](docs/API_COSTS.md)
- [Data model](docs/DATA_MODEL.md)
- [AI contracts](docs/AI_CONTRACTS.md)
- [Agent rules](AGENTS.md)

## Milestone 1 implementation

- Tauri 2 + React 19 + strict TypeScript Screens A–C and Settings/Diagnostics.
- A trusted Rust core that owns Windows Credential Manager access, SQLite migrations/WAL/FTS5, provider policy and price catalogs, transactional cost reservations, cache/single-flight, normalized persistence, link allow-listing, and worker supervision.
- A pinned CPython 3.12/PyInstaller one-folder worker using a strict LF-framed JSON protocol. The Rust release embeds and verifies the exact 74-file Windows-x64 bundle manifest before launch.
- Provider-independent M1 research/evidence/footage contracts, TVmaze metadata, OpenAI web verification and synthesis, guarded YouTube official-channel support, and disabled-by-default xAI search until its live invocation-cap proof passes.
- Evidence-bound, conversational multi-source footage requests with required/optional/alternative items, minimum useful footage, search suggestions, quote/episode certainty, and provisional intro leads.
- A frozen 13-case dated evaluation that includes nine synthetic opportunity cases and four honest no-opportunity cases.

M1 contains no footage ingestion, transcription, video understanding, song analysis, edit planning, rendering, subtitles, Topaz, or After Effects execution. Those remain behind later milestone approvals.

## Offline validation

The pinned workspace runtimes can validate the complete M1 implementation without contacting a provider:

```powershell
python -m unittest discover -s tests -v
python scripts/export_contract_schemas.py --check
python -m compileall -q src scripts tests
python scripts/run_m1_evaluation.py
cd desktop
npm.cmd test
npm.cmd run build
cd src-tauri
cargo test --all-targets --offline
```

The generated Windows worker is independently checked with `scripts/verify_worker_bundle.py`. From `desktop/`, `npm.cmd run tauri:build:verified` builds the optimized no-installer application, verifies that Tauri preserved the exact 74-file source hierarchy/hashes in its release-resource tree, and smoke-tests the copied worker protocol. `npm.cmd run verify:release-worker` repeats only the post-build gate. These commands do not call a research provider or modify supplied reference assets.

## Current provider posture

- TVmaze metadata is enabled and free, with attribution and quota controls.
- OpenAI `gpt-5.6-luna` is the enabled M1 web-verification/synthesis model, but a user-supplied Windows Credential Manager key and successful current preflight are required before any paid call.
- YouTube is disabled until a reviewed official-channel registry is bundled.
- xAI search is disabled until its adversarial live invocation/cost proof passes.
- Gemini 3.7 Flash is configuration/documentation only in M1; it is the intended primary video model for a later approved milestone, with Gemini 3.6 Flash as rollback.

## Secrets

`.env.example` is for local development/tests only and cannot authorize a release-worker call. Production provider keys belong in namespaced non-roaming Windows Credential Manager entries; the trusted Rust core issues immutable per-job paid-call capability and budget. Never commit `.env` or real keys.
