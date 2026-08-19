from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "analyze_style_references.py"
SPEC = importlib.util.spec_from_file_location("reference_analyzer", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
reference_analyzer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference_analyzer)


class ReferenceSafetyTests(unittest.TestCase):
    def test_output_must_stay_inside_analysis_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            source = root / "source.mp4"
            source.write_bytes(b"source")
            outside = root.parent / "unsafe-report.json"
            with patch.object(reference_analyzer, "ANALYSIS_ROOT", root / "approved"):
                with self.assertRaises(ValueError):
                    reference_analyzer.validated_output_path(outside, [source])

    def test_output_cannot_collide_with_source_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            source = root / "Source.MP4"
            source.write_bytes(b"source")
            with patch.object(reference_analyzer, "ANALYSIS_ROOT", root):
                with self.assertRaises(ValueError):
                    reference_analyzer.validated_output_path(source, [source])

    def test_atomic_report_is_verified_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "report.json"
            rendered = json.dumps({"references": [], "analysis_version": "test"}) + "\n"
            reference_analyzer.atomic_write_json(target, rendered)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["references"], [])
            self.assertEqual(list(target.parent.glob("*.partial")), [])

    def test_analysis_rejects_source_hash_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.mp4"
            source.write_bytes(b"unchanged test bytes")
            metadata = {
                "format": {"duration": "1.0"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 640,
                        "height": 480,
                    }
                ],
            }
            with (
                patch.object(
                    reference_analyzer,
                    "sha256",
                    side_effect=["a" * 64, "b" * 64],
                ),
                patch.object(reference_analyzer, "probe", return_value=metadata),
                patch.object(reference_analyzer, "scene_candidates", return_value=[]),
                patch.object(
                    reference_analyzer,
                    "black_and_silence",
                    return_value={"black_detection": {}, "silence_detection": {}},
                ),
            ):
                with self.assertRaises(RuntimeError):
                    reference_analyzer.analyze(
                        source,
                        Path("ffmpeg.exe"),
                        Path("ffprobe.exe"),
                        0.22,
                        "style-reference-test",
                    )

    def test_after_effects_inspector_cannot_quit_application(self) -> None:
        jsx = (REPOSITORY_ROOT / "scripts" / "inspect_after_effects_project.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIsNone(re.search(r"\bapp\.quit\s*\(", jsx))
        self.assertNotIn("AI_EDIT_AEP_REPORT_ROOT", jsx)
        self.assertIn("AI_EDIT_AE_INSPECTION_CONFIRMED", jsx)

    def test_after_effects_wrapper_binds_pre_and_post_source_hashes(self) -> None:
        wrapper = (
            REPOSITORY_ROOT / "scripts" / "run_after_effects_inspection.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("sourceHashBefore", wrapper)
        self.assertIn("sourceHashAfter", wrapper)
        self.assertIn("After Effects is running", wrapper)
        self.assertIn("ConfirmedAfterEffectsClosed", wrapper)

    def test_after_effects_wrapper_waits_for_report_with_bounded_timeout(self) -> None:
        wrapper = (
            REPOSITORY_ROOT / "scripts" / "run_after_effects_inspection.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("ReportTimeoutSeconds", wrapper)
        self.assertIn("Timed out waiting for the quarantined After Effects inspection report", wrapper)
        self.assertRegex(wrapper, r"while \(-not \(Test-Path[^\n]+\$stagingReport")
        self.assertIn("Start-Sleep -Milliseconds 250", wrapper)
        self.assertNotIn("WaitForExit", wrapper)
        self.assertNotRegex(wrapper, r"\b(?:Stop-Process|Kill)\b")

    def test_after_effects_wrapper_exposes_only_provenance_bound_report(self) -> None:
        wrapper = (
            REPOSITORY_ROOT / "scripts" / "run_after_effects_inspection.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(".unvalidated", wrapper)
        self.assertIn("$env:AI_EDIT_AEP_REPORT = $stagingReport", wrapper)
        self.assertNotIn("$env:AI_EDIT_AEP_REPORT = $report", wrapper)
        source_check = wrapper.index("$sourceHashAfter -ne $sourceHashBefore")
        parse_check = wrapper.index("$parsedReport = Get-Content")
        provenance_publish = wrapper.index(
            "[System.IO.File]::Move($provenanceTemporary, $provenancePath)"
        )
        report_publish = wrapper.index(
            "[System.IO.File]::Move($stagingReport, $report)"
        )
        self.assertLess(source_check, parse_check)
        self.assertLess(parse_check, provenance_publish)
        self.assertLess(provenance_publish, report_publish)


if __name__ == "__main__":
    unittest.main()
