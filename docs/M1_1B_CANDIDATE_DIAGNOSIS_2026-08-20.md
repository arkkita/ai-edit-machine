# M1.1b offline candidate diagnosis — live regression run 5

Fixture: `evals/2026-08-19-m1.1/live-regression-2026-08-19-run5.json`

Run ID: `55812119-c5dd-432f-bb4c-c64c1823f39d`

Run timestamp: `2026-08-19T15:15:56.924Z`
Fixture SHA-256: `cd62a5f82efc175011bf42e2343b7a27c9a3a26a2dd88e92e929c264ad9403c4`

This report is a replay-only diagnosis. It made no provider call, did not read or change SQLite, and did not infer missing historical scores.

## Verified first-loss point

All eight researched candidates were removed before synthesis at the female-audience evidence floor. Three candidates had no current discussion retrieval at all; five had current coverage but no source-owned evidence of female-skewing fandom appeal. No candidate reached the final ranker, so no final score, concept, footage request, schema serialization, Rust handoff, or UI display limit caused this run's zero results.

The live fixture retained no per-candidate TVmaze discovery-rank components. Those fields are therefore marked `NOT_RECORDED`; the selected order and slot family are known, but an exact historical numeric shortlist score cannot honestly be reconstructed.

## Thresholds active in the run

- Audience evidence floor: direct female-audience evidence, or at least 2 distinct affinity cues.
- Official-primary evidence shape: 1 current official primary + 1 independent current signal, across at least 2 groups.
- Metadata-only evidence shape: 1 exact current TVmaze episode + 2 current signal owner groups, across at least 3 groups.
- Final ranker: audience fit ≥ 0.40; inferred short-form edit potential ≥ 0.35; footage actionability ≥ 0.35.
- Concept gate: specificity ≥ 0.50 and total ≥ 0.45.

## Candidate summary

| # | Candidate | Discussion owners | Audience fit | Evidence shape | Exact first gate | Failure class |
|---:|---|---:|---:|---|---|---|
| 1 | Stuart Fails to Save the Universe | 2 | 0.05 | pass | audience-fit:evidence-floor | EVIDENCE_RELATED |
| 2 | Furious | 0 | 0.05 | fail | audience-fit:evidence-floor | RETRIEVAL_RELATED |
| 3 | Fightland | 1 | 0.05 | fail | audience-fit:evidence-floor | EVIDENCE_RELATED |
| 4 | Paris is Always a Good Idea | 1 | 0.05 | fail | audience-fit:evidence-floor | EVIDENCE_RELATED |
| 5 | Las Azules | 0 | 0.05 | fail | audience-fit:evidence-floor | RETRIEVAL_RELATED |
| 6 | My Brilliant Career | 1 | 0.05 | fail | audience-fit:evidence-floor | EVIDENCE_RELATED |
| 7 | The Librarians: The Next Chapter | 0 | 0.05 | fail | audience-fit:evidence-floor | RETRIEVAL_RELATED |
| 8 | Lanterns | 2 | 0.05 | pass | audience-fit:evidence-floor | EVIDENCE_RELATED |

## 1. Stuart Fails to Save the Universe

- Why shortlisted: Selected as female-audience-prior discovery slot 1 of 6 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: Official channel HBO Max published a title-bound video labeled: Stuart Fails to Save the Universe | Episode 4 Preview | HBO Max. Supporting metadata: TVmaze lists Spoiler: Stuart Makes a Wallet as Season 1 Episode 4.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: 2 current title-bound article signal(s) across 2 owner group(s). These are qualitative coverage leads, not a fandom census or direct TikTok data.
- Story/episode evidence: TVmaze lists Spoiler: Stuart Makes a Wallet as Season 1 Episode 4. 4 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.15; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: openai:ARTICLE, tvmaze:METADATA, youtube:OFFICIAL_CLIP
- Exact rejection gate: `audience-fit:evidence-floor` (EVIDENCE_RELATED)
- Additional blockers: concept:not-attempted, footage:not-attempted
- Evidence references:
  - `48b42116-c4b9-4b6b-95ea-b443353a3e72` / `ARTICLE` / `owner:penske-media` — 10 Best TV Shows Like Stuart Fails To Save The Universe - TVLine
  - `dd02c364-ccdb-4397-b679-a81b6c84f501` / `ARTICLE` / `owner:future-plc` — I don't think Sheldon and Leonard will return to Stuart Fails to Save the Universe after HBO Max show creators told me one important detail
  - `dbe204cb-e952-4971-857b-fac10c4ab9e7` / `METADATA` / `publisher:tvmaze` — Stuart Fails to Save the Universe cast listing
  - `893119b7-b615-4d79-a222-772d705287ed` / `METADATA` / `publisher:tvmaze` — Stuart Fails to Save the Universe — S01E04: Spoiler: Stuart Makes a Wallet
  - `99a3ed9f-665c-46c9-8359-6fd302ff58a1` / `OFFICIAL_CLIP` / `youtube-channel:ucx-kwltklb83hdi6ukectjq` — Stuart Fails to Save the Universe | Episode 4 Preview | HBO Max
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.6019 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.6667 (2 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.1500 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 1.0000 (4 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## 2. Furious

- Why shortlisted: Selected as female-audience-prior discovery slot 2 of 6 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: TVmaze lists They Make a Noise Like Feathers as Season 1 Episode 6.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: No usable current title-bound discussion signal was retrieved.
- Story/episode evidence: TVmaze lists They Make a Noise Like Feathers as Season 1 Episode 6. 4 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.00; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: tvmaze:METADATA
- Exact rejection gate: `audience-fit:evidence-floor` (RETRIEVAL_RELATED)
- Additional blockers: retrieval:no-current-title-bound-discussion, concept:not-attempted, footage:not-attempted
- Evidence references:
  - `f7992886-da69-4125-8a83-e32ae602e317` / `METADATA` / `publisher:tvmaze` — Furious cast listing
  - `a69ae9e8-604c-4f92-9968-ed7ca99e5c40` / `METADATA` / `publisher:tvmaze` — Furious — S01E06: They Make a Noise Like Feathers
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.8593 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.0000 (0 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.0000 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 0.2500 (1 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## 3. Fightland

- Why shortlisted: Selected as female-audience-prior discovery slot 3 of 6 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: TVmaze lists No Innocents as Season 1 Episode 3.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: 1 current title-bound article signal(s) across 1 owner group(s). These are qualitative coverage leads, not a fandom census or direct TikTok data.
- Story/episode evidence: TVmaze lists No Innocents as Season 1 Episode 3. 9 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.00; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: openai:ARTICLE, tvmaze:METADATA
- Exact rejection gate: `audience-fit:evidence-floor` (EVIDENCE_RELATED)
- Additional blockers: evidence:insufficient-independent-source-shape, concept:not-attempted, footage:not-attempted
- Evidence references:
  - `c9293b83-cce8-4594-bc01-b7827c73e9ba` / `ARTICLE` / `owner:future-plc` — All the US dramas you can watch on UK services: 22-28 August
  - `4864fbe5-39ce-49c8-ab1d-4616f9b1168c` / `METADATA` / `publisher:tvmaze` — Fightland cast listing
  - `4aae4da1-be99-48f8-9a59-0db47d3ff9df` / `METADATA` / `publisher:tvmaze` — Fightland — S01E03: No Innocents
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.6718 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.3333 (1 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.0000 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 0.5000 (2 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## 4. Paris is Always a Good Idea

- Why shortlisted: Selected as female-audience-prior discovery slot 4 of 6 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: TVmaze lists Knightly as Season 1 Episode 4.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: 1 current title-bound article signal(s) across 1 owner group(s). These are qualitative coverage leads, not a fandom census or direct TikTok data.
- Story/episode evidence: TVmaze lists Knightly as Season 1 Episode 4. 9 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.30; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: openai:ARTICLE, tvmaze:METADATA
- Exact rejection gate: `audience-fit:evidence-floor` (EVIDENCE_RELATED)
- Additional blockers: evidence:insufficient-independent-source-shape, concept:not-attempted, footage:not-attempted
- Evidence references:
  - `daf79c94-8d27-44a8-9b3a-71d47b6ef829` / `ARTICLE` / `owner:future-plc` — I Loved The Eiffel Tower Scene In Paris Is Always A Good Idea, But Shooting It Sounds Rough
  - `7e96d788-c96b-4923-89d9-9847b1783bb7` / `METADATA` / `publisher:tvmaze` — Paris is Always a Good Idea cast listing
  - `f03925a7-341e-45b0-82ca-13607043d4ba` / `METADATA` / `publisher:tvmaze` — Paris is Always a Good Idea — S01E04: Knightly
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.5736 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.3333 (1 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.3000 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 0.5000 (2 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## 5. Las Azules

- Why shortlisted: Selected as female-audience-prior discovery slot 5 of 6 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: TVmaze lists Filiberto as Season 2 Episode 2.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: No usable current title-bound discussion signal was retrieved.
- Story/episode evidence: TVmaze lists Filiberto as Season 2 Episode 2. 4 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.00; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: tvmaze:METADATA
- Exact rejection gate: `audience-fit:evidence-floor` (RETRIEVAL_RELATED)
- Additional blockers: retrieval:no-current-title-bound-discussion, concept:not-attempted, footage:not-attempted
- Evidence references:
  - `a669bf2d-c50c-43dd-928d-2ecbf584c8e8` / `METADATA` / `publisher:tvmaze` — Las Azules cast listing
  - `757ed53e-c1b4-4b41-b404-e3bd0b6cf82b` / `METADATA` / `publisher:tvmaze` — Las Azules — S02E02: Filiberto
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.9903 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.0000 (0 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.0000 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 0.2500 (1 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## 6. My Brilliant Career

- Why shortlisted: Selected as female-audience-prior discovery slot 6 of 6 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: TVmaze lists TA TA as Season 1 Episode 6.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: 1 current title-bound article signal(s) across 1 owner group(s). These are qualitative coverage leads, not a fandom census or direct TikTok data.
- Story/episode evidence: TVmaze lists TA TA as Season 1 Episode 6. 9 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.00; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: openai:ARTICLE, tvmaze:METADATA
- Exact rejection gate: `audience-fit:evidence-floor` (EVIDENCE_RELATED)
- Additional blockers: evidence:insufficient-independent-source-shape, concept:not-attempted, footage:not-attempted
- Evidence references:
  - `11673db1-180f-46e5-8421-ee03874b77ce` / `ARTICLE` / `owner:future-plc` — My Brilliant Career is Netflix's best period drama to date — even Bridgerton can't hold a candle to this level of chaotic passion
  - `71559bad-3b4d-4075-90f6-370483fb8a52` / `METADATA` / `publisher:tvmaze` — My Brilliant Career cast listing
  - `b9554ac6-d0e1-4084-8df4-6fc9efa3a1f0` / `METADATA` / `publisher:tvmaze` — My Brilliant Career — S01E06: TA TA
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.5617 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.3333 (1 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.0000 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 0.5000 (2 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## 7. The Librarians: The Next Chapter

- Why shortlisted: Selected as broad scripted/editable discovery slot 1 of 2 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: TVmaze lists And Descartes' Dilemma as Season 2 Episode 6.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: No usable current title-bound discussion signal was retrieved.
- Story/episode evidence: TVmaze lists And Descartes' Dilemma as Season 2 Episode 6. 4 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.00; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: tvmaze:METADATA
- Exact rejection gate: `audience-fit:evidence-floor` (RETRIEVAL_RELATED)
- Additional blockers: retrieval:no-current-title-bound-discussion, concept:not-attempted, footage:not-attempted
- Evidence references:
  - `ed105ac0-3422-4f7d-8175-3f84532cb7be` / `METADATA` / `publisher:tvmaze` — The Librarians: The Next Chapter cast listing
  - `330513f8-ee5c-4e34-a6d1-d9be1e7f9fe8` / `METADATA` / `publisher:tvmaze` — The Librarians: The Next Chapter — S02E06: And Descartes' Dilemma
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.8861 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.0000 (0 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.0000 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 0.2500 (1 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## 8. Lanterns

- Why shortlisted: Selected as broad scripted/editable discovery slot 2 of 2 by the TVmaze discovery ordering over fresh scripted/editable metadata. This was a discovery prior, not audience or fandom proof. The historical fixture did not persist the numeric focus, creative-affinity, episode-title, provider-weight, region, official-host, or recency rank components.
- Current hook: TVmaze lists Pilot as Season 1 Episode 1.
- Audience evidence: No source-owned evidence of female-skewing fandom appeal was retained.
- Fandom evidence: 3 current title-bound article signal(s) across 2 owner group(s). These are qualitative coverage leads, not a fandom census or direct TikTok data.
- Story/episode evidence: TVmaze lists Pilot as Season 1 Episode 1. 6 cast identity record(s) were retained. No verified quote, relationship history, or episode-scene description was retained.
- Inferred short-form signal: Observed evidence-only lower bound 0.15; insufficient to label a supported edit concept. This is an inferred cross-platform diagnostic, not a virality probability, and direct TikTok data was not used.
- Source categories: openai:ARTICLE, tvmaze:METADATA
- Exact rejection gate: `audience-fit:evidence-floor` (EVIDENCE_RELATED)
- Additional blockers: concept:not-attempted, footage:not-attempted
- Evidence references:
  - `50cd683d-7092-4893-920c-082f414ed8a9` / `ARTICLE` / `owner:future-plc` — 5 biggest new shows to stream this week — including 'Reacher' and 'Lanterns'
  - `80f81c55-da19-42c1-a42e-790411238032` / `ARTICLE` / `owner:iac` — HBO’s Next Must-See TV Event Is a Superhero ‘True Detective’
  - `4adffbe2-7c6c-4e1a-bbed-51972f67306a` / `ARTICLE` / `owner:future-plc` — Lanterns release schedule: When is episode 2 on HBO Max and NOW TV?
  - `813bf433-37c1-45c6-a565-70af6d860ad5` / `METADATA` / `publisher:tvmaze` — Lanterns cast listing
  - `0bea56a7-04b4-4fde-aeb9-3fe3b25c981c` / `METADATA` / `publisher:tvmaze` — Lanterns — S01E01: Pilot
- Scores and thresholds:
  - audience_fit: 0.05 (final threshold 0.40; evidence floor pass=false)
  - freshness: 0.8147 (diagnostic replay from the current hook and 14-day window)
  - fandom_velocity: 0.6667 (2 discussion owner group(s))
  - observed pre-concept short-form lower bound: 0.1500 (final threshold 0.35; not a virality probability)
  - observable source_diversity: 0.7500 (3 total groups)
  - intent_fit, relationship/character salience, footage_actionability, evidence_quality, uncertainty_penalty, total, and every concept score: `NOT_COMPUTED` because no candidate reached synthesis/final ranking.

## Diagnosis

- Candidate recall was large (4,027 raw; 3,660 fresh and constraint-surviving), but semantic web expansion retained no citation-bound candidate selectors, so TVmaze metadata ordering chose all eight deep-research titles.
- Five candidates had at least one current title-bound article; three had none. None had source-owned evidence satisfying the female-skewing audience floor.
- Stuart and Lanterns had enough source-owner shape to reach synthesis if audience support existed. The other six also lacked the required evidence shape (or any current discussion at all).
- No candidate reached opportunity scoring, editorial concept synthesis, footage generation, deduplication, or UI serialization. Therefore the zero-result run was not caused by a final rank threshold, schema serialization, Rust, or a frontend display cap.
- The Stuart official Episode 4 preview verifies only a title-bound preview. The fixture does not verify a cameo, encounter, quote, parent-series relationship beat, or cross-series story bridge, so a Stuart concept or footage request would have been unsupported.
