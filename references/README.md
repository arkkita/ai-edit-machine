# Reference assets

The canonical user assets were supplied outside this repository under `Documents/Codex/Ai-Edit-Machine/References`. They were not moved or modified. `REFERENCE_MANIFEST.json` identifies them by relative name and SHA-256.

Do not overwrite or silently convert these files. The flattened videos are style evidence, `CC.aep` is the canonical finishing-look source, and `THE ONE.json` is a legacy Topaz Video AI 7.1.0 preset. See `docs/EDIT_GRAMMAR.md` for measured findings and limitations.

`STYLE_ANNOTATIONS.json` is the machine-readable M0 human review record for cadence breakpoints and deterministic review-asset command templates. Generated contact sheets/reports belong under ignored `artifacts/reference-analysis/`. The media analyzer performs pre/post source fingerprint checks. AE JSX output remains in a unique `.unvalidated` quarantine until the wrapper passes its post-AEP checks, publishes matching provenance, and then exposes the final report; a report without that matching sidecar is invalid.

`SUBTITLE_MEASUREMENTS.json` records the dated native-frame A/C subtitle sample set, sampled timestamps and derived-frame hashes, approximate ink geometry/composited RGB evidence, and the user-approved `INTRO_DIALOGUE_SUBTITLE` decision. The measured reference placement is near 50% frame height; the canonical bottom placement at an 8% lower safe inset is an explicit product override. Exact fill, opacity, shadow, and glow/softness remain `CALIBRATION_REQUIRED`.
