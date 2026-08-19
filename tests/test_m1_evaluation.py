from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location(
    "run_m1_evaluation", ROOT / "scripts" / "run_m1_evaluation.py"
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


class M1EvaluationTests(unittest.TestCase):
    def test_offline_runner_uses_real_workflow_with_zero_cost_and_no_m2(self) -> None:
        suite = ROOT / "evals" / "2026-08-15"
        manifest = RUNNER.validate_manifest(suite)
        self.assertEqual(manifest["suite_id"], "m1-golden-2026-08-15")
        corpus = json.loads((suite / "corpus.json").read_text("utf-8"))
        rubric = json.loads((suite / "rubric.json").read_text("utf-8"))
        case = next(
            item
            for item in corpus["cases"]
            if item["case_id"] == "explicit-no-strong-opportunity"
        )
        result = RUNNER.run_case(case, rubric)
        self.assertEqual(result["mode"], "OFFLINE_REPLAY")
        self.assertEqual(result["product_result_status"], "NO_STRONG_OPPORTUNITY")
        self.assertEqual(result["reserved_cost_micro_usd"], 0)
        self.assertEqual(result["actual_cost_micro_usd"], 0)
        self.assertFalse(result["m2_operations_performed"])
        self.assertIsNone(result["providers"][0]["configured_model"])
        self.assertEqual(len(result["dimension_scores"]), 9)

    def test_all_frozen_cases_use_real_workflow_and_pass_structural_rubric(self) -> None:
        suite = ROOT / "evals" / "2026-08-15"
        corpus = json.loads((suite / "corpus.json").read_text("utf-8"))
        rubric = json.loads((suite / "rubric.json").read_text("utf-8"))
        statuses = {}
        for case in corpus["cases"]:
            with self.subTest(case=case["case_id"]):
                result = RUNNER.run_case(case, rubric)
                statuses[case["case_id"]] = result["product_result_status"]
                self.assertTrue(result["passed"], msg=json.dumps(result, indent=2))
                self.assertEqual(result["weighted_score"], 100)
                self.assertEqual(result["actual_cost_micro_usd"], 0)
                self.assertFalse(result["m2_operations_performed"])
                self.assertTrue(
                    all(item["configured_model"] is None for item in result["providers"])
                )
                self.assertTrue(
                    all(
                        "synthetic" in item["capability"]
                        and "no provider contacted" in item["capability"]
                        for item in result["providers"]
                    )
                )
        self.assertEqual(statuses["quality-bar-romcom-three-days"], "OPPORTUNITIES")
        self.assertEqual(
            statuses["explicit-no-strong-opportunity"],
            "NO_STRONG_OPPORTUNITY",
        )

    def test_opportunity_fixture_is_deterministic_and_actionable(self) -> None:
        suite = ROOT / "evals" / "2026-08-15"
        corpus = json.loads((suite / "corpus.json").read_text("utf-8"))
        case = next(
            item
            for item in corpus["cases"]
            if item["case_id"] == "quality-bar-romcom-three-days"
        )
        first_output, first, _ = RUNNER._run_offline(case)
        second_output, second, _ = RUNNER._run_offline(case)
        self.assertEqual(first.model_dump(mode="json"), second.model_dump(mode="json"))
        self.assertEqual(len(first.opportunities), 1)
        request = first.footage_requests[0]
        self.assertEqual(len(request.required_sources), 2)
        self.assertEqual(len(request.optional_sources), 1)
        self.assertEqual(len(request.alternative_sources), 1)
        self.assertTrue(request.intro_leads)
        self.assertEqual(
            request.required_sources[0].quote.status.value,
            "VERIFIED",
        )
        self.assertEqual(
            request.alternative_sources[0].quote.status.value,
            "UNVERIFIED_LEAD",
        )
        self.assertGreaterEqual(len(first_output.evidence_sources), 5)

    def test_creative_copy_is_evidence_specific_not_shared_boilerplate(self) -> None:
        suite = ROOT / "evals" / "2026-08-15"
        corpus = json.loads((suite / "corpus.json").read_text("utf-8"))
        selected = {
            item["case_id"]: item
            for item in corpus["cases"]
            if item["case_id"] in {"m0-current-tv-episode", "m0-character"}
        }
        rendered = {}
        for case_id, case in selected.items():
            output, result, _ = RUNNER._run_offline(case)
            opportunity = result.opportunities[0]
            signal_texts = [
                claim.text
                for claim in output.evidence_claims
                if claim.claim_kind.value == "VIEWER_DISCUSSION"
                and claim.verification.value == "SECONDARY_CORROBORATED"
            ]
            self.assertTrue(
                any(text in opportunity.creative_hook for text in signal_texts)
            )
            self.assertNotIn("as an evidence-led edit using only moments", opportunity.creative_hook)
            rendered[case_id] = opportunity.emotional_edit_direction
        self.assertNotEqual(
            rendered["m0-current-tv-episode"], rendered["m0-character"]
        )


if __name__ == "__main__":
    unittest.main()
