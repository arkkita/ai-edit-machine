# M1.1 live relevance regression diagnosis — 2026-08-19

Scope: Milestone 1.1 only. No footage ingestion, video understanding, or other
Milestone 2 work is included.

## Regression

User regression prompt:

> find shows for girls that’ll likely be popular on tiktok

The closest persisted successful live run used
`tv series for girls most likely to get views on tiktok` and returned only
`Stuart Fails to Save the Universe`. The distinction is immaterial to the
baseline parser: both become a television request with the single
`female-centered` focus token, a fourteen-day freshness window, and a default
five-result target. The exact user wording is retained as the permanent M1.1
regression prompt.

## Verified baseline funnel

The live run ID is `40a959b4-9ee0-4e0a-ab34-20b35e7a3e4b`. Counts below come
from its canonical result, immutable normalized evidence, provider accounting,
and bounded warnings in the local SQLite database. `Not recorded` is an
instrumentation gap, not a zero.

| Stage | Baseline count | Evidence |
|---|---:|---|
| Parsed intent | 1 | TV episode; `female-centered`; 14 days; US; max 5. No audience, platform-fit, or edit-intent structure existed. |
| Generated search variants | 14 tool invocations | Two owner-partitioned prepasses, two exact-title searches for each of five candidates, and two precision retries. These were retrieval variants, not semantic interpretations of TikTok editability. |
| Raw release candidates | At least 94 matching current shows | TVmaze warning reported 94 matching shows before its bounded shortlist. Pre-freshness raw schedule rows were not recorded. |
| After freshness filtering | Not recorded | The adapter applied the rolling fourteen-day window but exposed no stage count. |
| After hard exclusions | Not recorded | The query had no explicit exclusions; the adapter exposed no stage count. |
| After audience-fit screening | Not recorded | The deployed run did not expose this boundary. The source checkpoint's later female-title guard had not produced this persisted result. |
| Selected for social research | 5 deeply searched titles | Fifteen TVmaze titles were forwarded to verification, eight could enter its seed slate, but the staged owner-partition plan deeply exact-searched only five: Stuart, Furious, Fightland, The Real Housewives: Ultimate Girls Trip, and Baylen Out Loud. |
| With usable current social/editorial evidence | 4 title bindings / 5 discussion sources | Two sources bound Stuart; one each bound Furious, Fightland, and a revalidated Paris is Always a Good Idea cache lead. Direct TikTok, Reddit, and X data were not used. |
| Surviving evidence gates | 1 | Only Stuart had two independent current title-bound discussion owners. |
| Surviving deduplication | 1 | One distinct title. |
| Sent to final ranker | 1 | Model synthesis yielded no trusted surviving card; one deterministic low-confidence fallback entered final ordering. |
| Final opportunities serialized | 1 | Canonical result contains one opportunity and one footage request. |
| Final opportunities received by Rust | 1 | Rust persisted one normalized opportunity row. |
| Final opportunities displayed by UI | 1 | The React screen maps the complete Rust opportunity array and has no slice/result cap. |

## First verified loss and contributing causes

The first material recall loss was inside candidate allocation, before final
ranking: TVmaze had a much wider current slate, but the live verifier deeply
searched only five titles. The exact-title/owner query plan did not generate
semantic questions about female-skewing fandom, ships, emotional moments,
short-form edit culture, character salience, or usable source material.

The next loss was the evidence gate. Only Stuart happened to collect two
independently owned current title-bound articles, so it was the sole eligible
fallback. The gate behaved as designed; the retrieval slate feeding it was too
narrow and poorly aligned.

The final ranker could not correct this. Its score contained only release
freshness, cross-source agreement, scene specificity, and footage
actionability. The Stuart fallback scored approximately 0.808 despite having no
measured audience-fit or short-form-edit-potential component. Its vague scene
pack request received 0.96 footage actionability, exposing a second scoring
defect. Newness and evidence count therefore received credit without a direct
representation of the human request.

One synthesized recommendation also failed local why-now-role validation. The
deterministic fallback then produced the displayed card. Deduplication, schema
validation, Rust serialization, and React rendering did not remove additional
valid results. Provider accounting completed successfully and no cost cap or
provider failure caused the one-card result.

## Required instrumentation correction

M1.1 will add a development-only, value-free candidate-funnel report with all
fourteen stages, bounded rejection reason codes, distinct-title counts, and the
provider/model/prompt identifiers. Normal runs will retain the compact shortage
summary needed by the UI. The report will never store credentials, unrestricted
provider payloads, or private content.

This diagnosis intentionally precedes changes to model choice, ranking weights,
or evidence gates.

## Post-change live finding

The exact prompt was rerun through the normal providers using the bounded
debug-only calibration host. Final job
`55812119-c5dd-432f-bb4c-c64c1823f39d` expanded 4,027 raw release rows to a
30-title metadata pool, deeply validated eight titles, found usable current
discussion evidence for five, and admitted zero through the combined
current/source-diversity/requested-audience gate. It returned an explained
`NO_STRONG_OPPORTUNITY`; Stuart was not rescued by freshness or generic
fallback copy.

This prevents the original weak sole-result regression but does not meet the
several-useful-opportunities acceptance criterion. The full before/after,
provider audit, $0.940791 aggregate cost, evaluation, and remaining recall
weaknesses are recorded in `docs/M1_1_CALIBRATION_REPORT_2026-08-19.md`.
