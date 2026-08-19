# Editing Grammar and Reference Evidence

**Grammar ID:** `DIALOGUE_DROP_EDIT_V1`  
**Evidence date:** 2026-08-15  
**Status:** structural grammar and `INTRO_DIALOGUE_SUBTITLE` behavior accepted; subtitle fill/softness plus transition strengths and velocity curves remain intentionally calibration-gated until controlled visual tests

The supplied references are canonical evidence. Written rules are defaults; where a flattened reference contradicts them, the contradiction is recorded rather than erased.

## Evidence set and reproducibility

The originals were read in place and never modified. SHA-256 identifies the exact assets:

| Asset | SHA-256 | Role |
|---|---|---|
| `tiktok_7637159222106393878_576p.mp4` | `2b0c5009e1f5ba05caffa617b27bbc194c513bbf6a7df8946e8e3029ebb432fb` | Flattened style reference A |
| `tiktok_7668861927111527703_576p.mp4` | `62a14fcdcd3e9d27da14a3e4fe7eb665f14dc4e7c8c0b192349781eec25473e4` | Flattened style reference B |
| `tiktok_7668899659435363606_576p.mp4` | `38d61c9f634c7bfc41d9c3a4244bdd0811cdb6fff54d60d7b20369842f6fb138` | Flattened style reference C |
| `CC.aep` | `739ae13787a9153042cab31b4a18cb70fdb0184034fd6299994efde0c20e7b44` | Canonical AE finishing-look asset |
| `THE ONE.json` | `8af10debc7e72c81edf2f73df492a9af48ef63c7407119d856076006e5eb99be` | Canonical legacy Topaz preset |

Reproducible measurement code is in `scripts/analyze_style_references.py` and `scripts/inspect_after_effects_project.jsx`. The media report schema v1.1 records the script hash, FFmpeg/ffprobe executable hashes, complete version/build text, command templates, source handles/display names, and no absolute source path. `references/STYLE_ANNOTATIONS.json` records the three human-selected cadence breakpoints, reviewer method, source hashes, and exact regeneration commands for contact sheets/handoff strips. Local generated reports/images live under `artifacts/reference-analysis/`.

The media script hashes/observes each source before analysis and again after every probe/audio/black/silence pass, failing if hash/size/mtime changes. It uses ffprobe metadata, FFmpeg scene-score candidates at threshold 0.22, a 100 ms mono RMS envelope, and black/silence checks. Machine candidates are not editorial truth; the annotation record makes the human visual decision explicit. The first ephemeral review-image invocation was not preserved, so M0 now defines and regenerates review assets from the recorded canonical commands instead of pretending the earlier shell history was complete.

Limitations:

- Scene-score peaks also detect flashes, black bridges, dissolves, and effect transients; they are candidate boundaries, not truth.
- Flattened renders cannot reliably reveal original source cadence, optical-flow choices, or numeric time-remap curves.
- Audio RMS changes are not dialogue/music/beat labels. The structural breakpoints below are visually measured cadence changes; exact song handoffs need audio/beat analysis in the product.
- Baked subtitles, glow, source lighting, grading, and platform recompression make exact effect-strength reconstruction unsafe.

## Measured reference structure

| Ref | Container picture | Duration | Visual setup → montage breakpoint | Setup cadence | Montage cadence | Ending evidence |
|---|---|---:|---:|---|---|---|
| A | 768×576, exact 4:3, 30 fps | 36.733 s | 22.600 s | Sparse dialogue scene; major candidates at 2.400, 9.667, 17.733, 20.500, 22.600 s | Mostly 0.4–0.8 s cells through about 34.600 s | Black-backed creator/title treatment begins about 34.600 s; final 0.732 s audio is below −45 dBFS detector threshold. |
| B | 576×576, 1:1, 30 fps | 29.142 s | 16.733 s | Dialogue/reaction cuts roughly 0.6–2.7 s | Underlying visual cells roughly 0.5–1.1 s; FFmpeg overcounts repeated black/blur transition frames | Near-black from 27.267–29.100 s (1.833 s). |
| C | 746×576, 373:288 ≈ 1.295:1, 30 fps | 27.233 s | 14.567 s | Dialogue/context candidates mostly 2.0–3.4 s, with one short reaction | Cleanest montage evidence: commonly 0.67–0.80 s, one longer hold | Near-black from 25.333–27.200 s (1.867 s). |

Across the three references:

- total duration range is 27.233–36.733 s; median is 29.142 s;
- visual setup breakpoints are 14.567, 16.733, and 22.600 s; median is 16.733 s;
- the montage is a decisive cadence acceleration, not merely a continuation of dialogue cutting;
- endings reserve about 1.8–2.2 s for black/creator-title resolution;
- the B handoff/interior pattern contains repeated dark bridge frames and blurred entries concentrated within roughly 10–14 frames at 30 fps; this is a style option, not proof that every cut uses it;
- subtitle treatments vary: A/C use small pale-yellow/cream lowercase text around the vertical center while B uses a larger white uppercase variant. For `DIALOGUE_DROP_EDIT_V1`, the user-approved `INTRO_DIALOGUE_SUBTITLE` below makes the A/C lowercase family canonical but deliberately moves it to the lower safe area. B remains evidence for a possible future variant, not the active intro preset.

The 100 ms RMS envelopes had medians of −19.952, −15.878, and −19.920 dBFS respectively. These are measurements of the compressed reference files, not loudness targets.

## Conflicts and decisions

| Written assumption | Reference evidence | Decision |
|---|---|---|
| Intro is conceptually 5–20 s | Ref A's cadence switch is about 22.6 s | Keep 5–20 s as the target. Permit up to 24 s when the contextual setup earns it; do not truncate solely to satisfy a hard number. |
| Default output is 4:3 | A is 4:3, C is close to 4:3, B is square | Keep 4:3 as product default, expose an explicit aspect override, and never stretch. Square is a supported later/project choice, not the new default. |
| One signature blur/glow look | B visibly uses dark bridge/blur entry behavior; A/C differ | Define approved deterministic variants. Default remains restrained blur/glow; dark bridge is opt-in. Exact strengths await controlled tests. |
| Subtitle styling might be one preset | A/C use a small lowercase pale-yellow/cream family near vertical center; B is a larger white uppercase variant | `DIALOGUE_DROP_EDIT_V1` now has one deterministic `INTRO_DIALOGUE_SUBTITLE`. The user-approved lower placement overrides the references' center placement. B is non-canonical for this preset. Color/softness remain calibration-gated because a flattened composite cannot reveal source RGBA/effects exactly. |
| AE project may contain the whole style | Supplied AEP contains finishing adjustments only | Treat it as canonical finishing look, not evidence for edit cadence, transitions, or velocity. |

## `DIALOGUE_DROP_EDIT_V1`

### Global invariants

- Output aspect is 4:3 unless the user explicitly chooses another supported aspect.
- Sources are never stretched or overwritten. Crop/reframe is explicit per clip and reviewable.
- The rough cut contains no expensive final effects. It proves footage, ordering, dialogue continuity, handoff, and rhythm.
- Every selected segment has a story/energy role, evidence IDs, source range, and explanation.
- Exact boundaries resolve to local shot/transcript/beat evidence. A model locator alone is never an edit boundary.
- Do not include a required moment that is absent. Return a footage gap and alternative.
- No LLM-authored filter graph, keyframe, crop path, or numeric velocity curve.

### A. Contextual dialogue setup

Purpose: make the later montage emotionally legible to someone who may not know the source scene.

- Allowed length: 5–24 s; ordinary target 12–19 s; measured reference median 16.733 s.
- Prefer one coherent exchange or cause→reaction→hinge sequence over unrelated quote fragments.
- Establish who matters, the relationship/tension, and the emotional question.
- Preserve turn-taking, reaction shots, room tone, and enough pre/post-roll to avoid clipped consonants or robotic pacing.
- Use transcript/subtitle endpoints as semantic anchors, then resolve each picture cut to a decoded local video-frame PTS with stream identity. Maintain screen direction and dialogue continuity unless the concept intentionally breaks them; preserve audio as a separately resolved sample-stream range.
- Intro line text must derive from verified transcript/subtitle evidence and is rendered only with `INTRO_DIALOGUE_SUBTITLE`; the model cannot restyle it.
- Finish on a hinge: realization, accusation, look, action, or phrase whose meaning the montage can answer.

#### `INTRO_DIALOGUE_SUBTITLE`

This is the canonical contextual/dialogue-intro preset for `DIALOGUE_DROP_EDIT_V1`. It is not a universal subtitle rule for other grammars or a claim that every supplied reference uses the same treatment.

Deterministic behavior:

- Arial Regular is the default font until controlled font comparison identifies a closer reproducible match. Font substitution is not a model choice.
- Render text in lowercase. Every subtitle event starts with exactly one ASCII hyphen followed by one space: `- `. For example, spoken `That Is Not Me` renders as `- that is not me`.
- Center horizontally. Place the subtitle block near the bottom with its lower edge at the 8% frame-height lower safe inset. This user-approved placement intentionally overrides the A/C reference placement near vertical center.
- Target representative lowercase glyph ink at about 3.5% of frame height; derive the actual font size from the selected font's measured metrics and store it in the render manifest. Use a provisional 1.15 em line advance, maximum text width 78% of frame width, and at most two lines. These geometry values must pass a later controlled subtitle-render golden before execution is enabled.
- Segment at natural phrase/punctuation or speaker-turn boundaries; prefer one readable phrase per event, balance two-line breaks, avoid one-word orphan lines, and never change wording to make it fit. Timing comes from transcript/subtitle evidence, not model-invented word times.
- Use a restrained pale-yellow/cream family, with fixed fill, opacity, shadow/softness, alignment, spacing, and antialiasing owned by the versioned renderer preset. The exact fill/opacity/shadow values remain `CALIBRATION_REQUIRED`: M1 does not render subtitles, and later execution must fail closed rather than substitute an AI- or developer-guessed hex/effect.

Native 576 px reference measurements supporting the provisional geometry:

| Measurement | A/C observation | Decision |
|---|---|---|
| Vertical position | High-confidence glyph ink spans about `y=278–299`, centered at 50.0–50.4% frame height | Evidence is central, but the approved product preset moves to the lower safe area and records that override. |
| Glyph ink height | Commonly 16–22 px (2.8–3.8% H); antialiased/compressed fringe can reach about 28 px (4.9% H) | Use 3.5% H representative ink as the initial scalable geometry target. |
| Line width | Widest measured C line is about 435/746 px (58.4% W) | A 78% W hard maximum leaves room for longer dialogue without making the measured examples a forced width. |
| Composite color | Selected-sample median RGB varies roughly `[194–236, 181–225, 114–162]`; bright interiors reach roughly `[242–255, 209–239, 149–183]` | This supports a pale-yellow/cream family but cannot invert the original fill, opacity, glow, or shadow through background and compression. Do not freeze a guessed hex from these composites. |
| Multiline/spacing | The sampled material does not provide enough clean, controlled multiline evidence | Treat 1.15 em as a provisional deterministic test value, not a measured reference fact; calibrate before subtitle rendering ships. |

The AI may identify or transcribe candidate dialogue, subject to evidence validation. It may not alter capitalization, prefix, font, placement, sizing rule, line spacing, width, color treatment, opacity, shadow/softness, alignment, or segmentation policy. Those fields are a versioned deterministic preset.

### B. Song handoff

Purpose: make the switch feel authored rather than like two clips concatenated.

- Anchor to a verified dialogue end/reaction and a selected beat/downbeat/song-section boundary.
- Explicit audio plan fields: dialogue tail, music pre-lap, handoff point, source-audio fade, song fade, optional hit/accent.
- Dialogue remains intelligible; do not hide a necessary final word under the track.
- A hard drop is allowed only when selected by a named handoff preset and explained.
- Rough-cut audio is the decision authority. Final finishing may not move the approved handoff frame silently.

### C. Main montage

Purpose: develop one emotional thesis with rising specificity and energy.

- Reference-informed starting cadence: approximately 0.5–1.1 s visual cells at 30 fps, with intentional longer holds for recognition/emotion. This is a search range, not a cut-every-N-frames rule.
- Snap candidates to approved beat/downbeat subdivisions only after preserving viable local shot boundaries.
- Prefer progression: establish motif → develop/contrast → intensify → payoff. Avoid a bag of visually attractive but semantically unrelated shots.
- Limit near-duplicate composition/action unless repetition is the concept. Ref B demonstrates deliberate visual repetition, so repetition is permitted only with an explicit motif rationale.
- Preserve face/action readability through transitions. If a transition obscures the subject or important gesture, downgrade to a clean cut.
- Use source audio only when specified (dialogue echo, impact, breath); otherwise the song is the montage audio authority.

### D. Ending

Purpose: resolve rather than simply run out of clips.

- Choose a final image/gesture that answers the setup or leaves an intentional question.
- Reference-derived optional end bed/title duration: 1.8–2.2 s.
- `END_ON_IMAGE`, `END_TO_BLACK`, and `END_TITLE_BLACK` are separate deterministic choices.
- Creator/title text is optional, user-owned, and outside AI quote generation.

## Transition preset contract

The exact cut remains a frame boundary. A preset supplies a fixed envelope around that frame; global user parameters may scale an audited preset but a model cannot emit keyframes.

| Preset | Current status | Intended behavior |
|---|---|---|
| `CLEAN_CUT` | Ready for rough cuts | No finishing transition. |
| `BLUR_GLOW_SOFT` | Structural definition only | Readable subject; blur begins shortly before the cut, peaks at/near it, resolves shortly after; restrained glow and optional tiny exposure accent. Default finishing candidate. |
| `BLUR_GLOW_MEDIUM` | Uncalibrated | Same fixed envelope with stronger audited global values. User opt-in. |
| `BLUR_GLOW_HARD` | Uncalibrated | Maximum approved envelope; never automatically selected in v1. |
| `DARK_BRIDGE` | Reference-derived option, uncalibrated | Short low-luma/black bridge plus blurred incoming recovery. Ref B suggests a roughly 10–14 frame total event at 30 fps; use only after visual testing. |

No blur radius, glow threshold/intensity, exposure amount, or exact frame envelope is frozen by M0. Those numbers cannot be separated reliably from the flattened sources and are absent from the AEP. Milestone 6 must render a controlled test grid, compare against the references, and obtain user approval before these presets become production defaults.

Accordingly, the M0 execution registry and generated `CompiledEditPlan` schema accept only `CLEAN_CUT@1`; all blur/glow/dark-bridge names are non-executable vocabulary until calibration.

## Velocity preset contract

Reserved grammar vocabulary is:

- `STATIC`
- `SOFT_PUSH`
- `SOFT_PULL`
- `IMPACT`

Only `STATIC@1` is operationally defined and accepted by the current trusted `CompiledEditPlan`: source playback at the validated native rate, with source/timeline duration agreement under the declared one-output-frame conform tolerance. The other names are never exported as current provider/execution choices and **do not yet imply numeric curves**. The supplied AEP has no time-remapped layer and flattened references are insufficient to recover source-to-output speed. Milestone 5 may show the reserved vocabulary; execution remains disabled until each profile has:

- a versioned curve definition outside prompts;
- allowed clip-duration/source-handle constraints;
- audio policy;
- frame interpolation policy;
- FFmpeg/AE equivalence test or a declared single renderer;
- visual golden outputs and user approval.

Invalid/free-form values fail validation. A string such as `100 -> 437 -> 28 -> 191` is never accepted.

## Supplied After Effects look

The M0 scripted inventory opened `CC.aep` in installed AE 25.4, read the project DOM, and closed it without saving. It is evidence about this run—not a claim that `afterfx.exe -r` creates a separate/headless instance. Future inspection uses `scripts/run_after_effects_inspection.ps1` to require AE closed/confirmation and poll with a bounded timeout. The JSX aborts if a project is visible, never calls `app.quit()`, and writes only into a unique `.unvalidated` quarantine. After the report appears, the wrapper checks the post-AEP hash+size+mtime, validates JSON and report hash, atomically publishes matching provenance, and only then exposes the final report; consumers must require and recheck that sidecar. A timeout or source change never creates the final report, and the wrapper never waits for, stops, or kills the long-lived GUI. The inventory found:

- composition `Comp 1`: 1920×1080, 23.978958 fps, 2.251970 s, two adjustment layers;
- no source footage, transition layers, time remapping, or keyframed effect values;
- adjustment layer 1: `Unsharp Mask` (`ADBE Unsharp Mask2`) then `Lumetri Color` (`ADBE Lumetri`);
- adjustment layer 2: `FilmConvert Nitrate` (`FC NITRATE`).

Observed raw parameters include:

- Unsharp Mask: Amount 15, Radius 40, Threshold 0, effect opacity 100;
- Lumetri: Creative Sharpen 35, Vibrance 34, saturation 100; other exposed basic correction values are neutral in the inventory;
- FilmConvert: Film Stock index 1; Film Chroma/Luma/Color and Cineon-to-Print 100; Film Size 8; raw Exposure 18.716552734375; Temperature 3.74331665039062; Tint 0; raw Size 0.69999998807907; Strength/Saturation 100; plus the stored curve points.

Plugin enum IDs and units are not reinterpreted. The canonical rule is to copy/use the AEP or a user-exported preset after version preflight, not reconstruct it from display names. Its 16:9 dimensions do not override the product's 4:3 output default; the finishing adapter must create/use an appropriate output comp while preserving the adjustment look.

## Supplied Topaz preset

`THE ONE.json` identifies legacy `veaiversion: 7.1.0`, matching the installed Topaz Video AI 7.1.0. Preserve the JSON byte-for-byte. Audited fields:

- output: ProRes 422 Standard (`prores-422-std-win`) MOV, AAC 320 kb/s, no alpha, original frame numbering behavior, create output directory;
- enhancement enabled: model `prob-4`, video type 1, auto mode 2, compress 0, detail 70, sharpen 1, denoise 0, dehalo 1, deblur 1, add noise 0, recover original detail 100, focus fix off;
- stabilization, motion blur, slow motion, HDR, grain, and second enhancement disabled;
- aspect ratio locked, no crop-to-fit, output FPS mode 0, output-size method 1.

These are legacy product IDs, not permission to map them silently onto current Topaz Video controls. Current-product v1 integration is manual handoff. A legacy automated adapter requires exact-version discovery, CLI smoke test, licensed local installation, and user opt-in.

## Grammar validation

Before rough rendering, reject a plan when any invariant fails:

- either endpoint lacks source/stream-signature fingerprint, stream index/type, decoded frame/sample authority, resolver evidence, or matching timebase; video frame indices must increase with PTS;
- end PTS ≤ start PTS or clip extends outside the source;
- model locator has not been resolved locally;
- dialogue continuity/required handles are missing;
- footage request marks a required moment that analysis says is absent;
- aspect/crop would stretch or place the declared focal region outside frame;
- transition/velocity/handoff preset is unknown or not enabled for the current milestone;
- a `STATIC@1` source duration or cumulative plan conform error exceeds one output frame, clip order/timeline is non-contiguous, or the terminal clip carries a transition;
- the role sequence is not intro dialogue/reaction → exactly one 5–24 second handoff boundary → montage/payoff/ending, or intro dialogue lacks mapped source audio;
- picture/audio ranges are conflated, use the wrong stream type, or their evidenced stream-origin mapping disagrees by more than one audio sample;
- the selected beat does not rationally quantize to the claimed handoff frame/error, or the typed dialogue-tail/pre-lap/fades/song range cannot cover the timeline;
- crop/reframe, source handles, audio policy, song/beat handoff, ending, exact duration, registry versions, or trusted validation report is absent; the report must have the mandatory code set, compiler-run provenance, and recomputable plan fingerprint;
- explanation or supporting transcript/shot/evidence IDs are missing;
- duration, duplicate, beat, or budget constraints cannot be satisfied;
- generated artifact would target a source path.

If constraints cannot be satisfied, return structured gaps and alternatives. Do not auto-relax a safety, source, or budget rule.
