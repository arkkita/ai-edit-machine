# M1.1 baseline checkpoint — 2026-08-19

This record freezes the functioning Milestone 1 live-search configuration before
M1.1 quality-calibration production changes. It does not authorize or include
Milestone 2 work.

## Source state

- Branch before checkpoint: `master`
- Parent commit: `57f43f2` (`docs: add M1 live-search debug handoff`)
- Checkpoint tag: `m1-live-search-r73-checkpoint-2026-08-19`
- The checkpoint commit contains all tracked and untracked M1 live-search work
  present at the start of the M1.1 session. No prior work was discarded.
- Provider registry: `m1-2026-08-19-r73`
- Bundle cache namespace/schema: `research-bundle-v2` /
  `research-result-bundle/2.0.0`
- Bundle model key: `openai:gpt-5.6-luna|catalog:m1-2026-08-19-r73`
- Bundle prompt key:
  `m1-research-2026-08-19-r69+catalog:m1-2026-08-19-r73`

## Resolved live providers and endpoints

| Role | Provider / resolved model | Endpoint(s) | State and material flags |
|---|---|---|---|
| Release discovery | TVmaze public metadata | `https://api.tvmaze.com/schedule`, `https://api.tvmaze.com/schedule/web` | Enabled; `tvmaze-metadata-v1`; US linear plus web schedules; 12–38 planned requests depending on freshness window, policy ceiling 40; no paid call. |
| Current-web verification | OpenAI / configured and preflight-resolved `gpt-5.6-luna` | `POST https://api.openai.com/v1/responses`; preflight `GET https://api.openai.com/v1/models/gpt-5.6-luna` | Enabled; `openai-web-evidence-v1`; built-in `web_search`; `store:false`; `parallel_tool_calls:false`; `tool_choice:"required"` for search passes; low search context; reasoning effort `none`; up to 14 tool calls, 40 verifier requests, 170,000 input tokens, and 5,333 output tokens in the ordinary plan. |
| Structured synthesis | OpenAI / configured and preflight-resolved `gpt-5.6-luna` | `POST https://api.openai.com/v1/responses` | Enabled under the same privacy policy; no web tool; `store:false`; `parallel_tool_calls:false`; one initial attempt plus at most one bounded repair; combined reserve 30,000 input and 8,000 output tokens. |
| Official video metadata | YouTube Data API v3 / preflight-resolved `youtube-data-api-v3` | `https://www.googleapis.com/youtube/v3/search`; preflight `https://www.googleapis.com/youtube/v3/i18nLanguages` | Enabled; `youtube-public-metadata-v1`; exact title searches; locally restricted to eight reviewed official channel IDs; at most five `search.list` requests; metadata/links only, never audiovisual retrieval. |
| X search lead generation | xAI / intended `grok-4.6` with `grok-4.3` fallback | Intended `POST https://api.x.ai/v1/responses` | Disabled. No request is authorized until a live adversarial test proves hard invocation bounds and the retention/privacy configuration is approved. |

The persisted local preflight rows inspected read-only on 2026-08-19 report
`gpt-5.6-luna` and `youtube-data-api-v3` as available and resolved exactly to
their configured identifiers. Credentials remain in Windows Credential Manager
and are not recorded here.

## Cost and development-only flags

- OpenAI price card ID: `7f771320-9944-465d-98a1-924ed837fe34`.
- Recorded Luna rates: $0.20 / 1M input tokens, $0.02 / 1M cached input
  tokens, $1.20 / 1M output tokens, and $0.01 per web-search call.
- Ordinary maximum reservation: $0.1804 for verification plus $0.0312 for
  synthesis, $0.2116 total, below the existing $0.50 per-run hard limit.
- Development-only diagnostic CLI: `--m1-provider-debug-live` with mode
  `M1_PROVIDER_ONE_SHOT` and run scope
  `m1-provider-debug-live-2026-08-19-v1`.
- The diagnostic is unavailable to production release behavior, permits exactly
  one search-tool invocation, saves only sanitized fixtures, and has a $0.05
  hard cap / $0.04996 worst-case reservation.

## Baseline validation

- `python -m unittest discover -s tests -v`: 204 passed, 4 optional
  worker-packaging checks skipped.
- `python scripts/export_contract_schemas.py --check`: 34 schemas verified.
- `python -m compileall -q src scripts`: passed.
- `npm.cmd test` in `desktop/`: 4 files / 16 tests passed.
- `git diff --check`: passed.
- Rust tests could not run in this environment: the repository requires Rust
  1.95 while only Rust 1.92 is installed. No toolchain was installed or changed.

This baseline is the rollback point for M1.1. The functioning live path, strict
evidence handling, financial authorization boundary, and M1 scope remain
non-negotiable throughout calibration.
