# Milestone 1 live-search fix report — 2026-08-19

## Outcome

The user-visible relevance defect is fixed at its earliest invalid boundary, but a real current-data opportunity could not be demonstrated because the one authorized OpenAI request was rejected by the provider for an exhausted credit balance.

- Product root cause: boundary 10, evidence gating.
- Harness-only defect found during final execution: boundary 13, Rust/Python worker transport; fixed before the provider request.
- Current live blocker: boundary 6, provider account authorization. HTTP `429`, `insufficient_quota`, `credit_balance_exhausted`.
- Milestone 2 was not started.

## Verified product root cause

Job `50931045-e2fa-4246-bf7c-db566461be0e` correctly retained the prompt `a good show for girls thatll get views on tiktok` and normalized it to `focusTerms:["female-centered"]`. Provider request construction, endpoint/model resolution, headers, authentication, parsing, ranking, worker serialization, Rust validation, and React presentation all transported data. Invalidity first appeared when title-bound current chatter was allowed to satisfy the mandatory female-audience focus without source-owned support. That admitted *Stuart Fails to Save the Universe* even though the card itself said female-centered suitability was unverified.

Earlier changes preserved the user's words, removed *Lanterns* from the candidate slate, and improved multi-title search allocation. They did not independently recheck the required focus at the final evidence gate, so generic title chatter could still promote a metadata-selected show.

The correction requires source-owned title text or a trusted title binding with a bounded female/women/girls cue. Model prose cannot provide the cue. Python enforces this before synthesis, during deterministic selection, and after draft validation; Rust independently enforces it before persistence/UI return. One regression reproduces the *Stuart* mismatch and abstains before synthesis. Another returns two distinct, independently supported female-centered titles so relevance enforcement does not collapse breadth to one result.

## Deterministic provider harness

`scripts/run_m1_provider_debug.py contract|replay` runs the smallest fixed M1 request without the desktop UI. One trace ID covers provider/model resolution, sanitized method/URL, every outgoing header, redacted credentials, sanitized body, status, sanitized response headers, raw response or exact exception, and every pipeline count. The fixture transport asserts the exact adapter contract; a mocked `urllib` opener verifies the request that would actually leave the adapter.

The debug-only Rust command uses Windows Credential Manager, an immutable SQLite reservation, normal provider-start acknowledgement and reconciliation, one POST-only transport guard, no POST retry, one hosted search, 300 maximum output tokens, no synthesis, and a hard `$0.050000` run limit. It is absent from release builds. It cannot accept a caller-supplied prompt, model, seed, endpoint, cap, or approval. Reusable production evidence is removed from its wire payload, results are excluded from production cache reuse, and credentials are never logged or persisted to fixtures.

The successful local contract fixture produced:

| Stage | Count |
|---|---:|
| Raw provider results | 2 |
| Parsed results | 2 |
| Normalized evidence | 3 |
| Evidence surviving gates | 3 |
| Ranked opportunities | 1 |
| Opportunities returned to UI serialization | 1 |

It passes the real Python adapter, normalization, gating, ranking, opportunity serialization, strict LF JSON worker transport, and UI-return serialization offline.

## Live request and cost

One and only one provider POST was issued:

- Trace: `49e8758b-bba3-46a8-8eba-cff62b6d45ff`
- Job: `d5bf65d3-79ad-4d0f-b51b-927b727db726`
- Method/endpoint: `POST https://api.openai.com/v1/responses`
- Configured/resolved model: `gpt-5.6-luna` / `gpt-5.6-luna`
- HTTP status: `429`
- Provider error type/code: `insufficient_quota` / `credit_balance_exhausted`
- Provider message: no credits remain on the configured API account/project.
- Provider response ID and usage: absent.
- Reserved maximum: `$0.049960`; hard cap: `$0.050000`.
- Actual billed cost: unavailable from the provider response. The ledger conservatively holds `$0.049960` as `UNVERIFIED`; this report does not claim that amount was charged or that actual cost was zero.

Live counts were `0 raw / 0 parsed / 0 normalized / 0 gated / 0 ranked / 0 displayed`. The sanitized response is replayable at `artifacts/provider-debug/m1-live-2026-08-19.json`; offline replay returns `research.error` with the same zero counts. Account-scoped response headers, cookies, and credentials are redacted.

The first command attempt was not a provider call. Job `9f1117f8-557d-45f0-b518-5aae3ed8307d` failed strict worker validation because cached reusable evidence entered the isolated debug payload. It recorded no `provider_run`, made no HTTP request, and released its entire reservation. The Rust isolation regression covers this defect.

## Validation

- Python: 204 tests run, 200 passed and 4 optional packaging-dependency tests skipped; 0 failed; 2.50 seconds test execution, 3.04 seconds wall time.
- Rust: 96 tests passed; 0 failed; 4.04 seconds test execution, 9.77 seconds wall time including the rebuilt worker-manifest build script.
- Generated schemas: 34 verified.
- Python compileall: passed.
- Frontend unit tests: 16 passed; 1.95 seconds reported by Vitest, 2.85 seconds wall time.
- Frontend production build: passed in 3.18 seconds wall time.
- Packaged worker: 74 files, AMD64, exact manifest, clean LF protocol smoke.
- `git diff --check`: required in the final handoff.

The direct provider harness did not return a valid opportunity, so the required backend integration test and desktop UI smoke test were deliberately not run. This follows the requested gate order and avoids presenting fixture success as live success.

## Files changed

- `src/ai_edit_machine/research/workflow.py`
- `src/ai_edit_machine/providers/openai_web.py`
- `src/ai_edit_machine/providers/transport.py`
- `src/ai_edit_machine/provider_debug.py`
- `src/ai_edit_machine/provider_debug_contract.py`
- `src/ai_edit_machine/worker.py`
- `scripts/run_m1_provider_debug.py`
- `desktop/src-tauri/src/commands/research.rs`
- `desktop/src-tauri/src/database/repositories.rs`
- `desktop/src-tauri/src/domain.rs`
- `desktop/src-tauri/src/lib.rs`
- `desktop/src-tauri/src/main.rs`
- `desktop/src-tauri/src/provider_catalog.rs`
- `desktop/src-tauri/src/worker/protocol.rs`
- `desktop/src-tauri/resources/provider-catalog.json`
- `tests/test_m1_provider_debug.py`
- `tests/test_m1_providers.py`
- `tests/test_m1_research.py`
- `tests/test_m1_worker.py`
- `tests/fixtures/m1_provider_debug_response.json`
- `docs/API_COSTS.md`
- `docs/RESEARCH_AUDIT.md`
- `docs/M1_LIVE_SEARCH_FIX_REPORT_2026-08-19.md`
- Ignored sanitized capture: `artifacts/provider-debug/m1-live-2026-08-19.json`

The rebuilt ignored worker bundle under `desktop/src-tauri/resources/worker/windows-x86_64/` also changed so the trusted Rust manifest matches the corrected Python source.

## Remaining limitations

- A successful current-data run is still required after the configured OpenAI account has credits. No additional call is authorized or attempted by this report.
- OpenAI does not document `search_context_size:"low"` as an exact input-token cap. The one-shot request therefore reserves the documented worst case and fails closed on missing/over-limit usage.
- The failed 429 supplied no usage or native cost ticks, so durable accounting must remain `UNVERIFIED` until externally reconciled.
- M1 can return reviewed official-channel YouTube metadata and canonical links. It does not download media, claim exact 1080p availability, or add thumbnail/embed/download UI. Those additions were not made because downloading audiovisual material from YouTube/social services is prohibited and media validation/import belongs beyond this M1 fix.
- No backend integration or desktop smoke was run after the failed direct provider gate.

## Milestone boundary

No Milestone 2 architecture, ingestion, video analysis, downloader, thumbnail UI, or media-resolution verification work was started.
