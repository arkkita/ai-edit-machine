from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location(
    "run_m1_1_evaluation",
    ROOT / "scripts" / "run_m1_1_evaluation.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


class M11EvaluationTests(unittest.TestCase):
    def test_dated_ten_prompt_golden_set_passes_offline(self) -> None:
        result = RUNNER.run(ROOT / "evals" / "2026-08-19-m1.1")

        self.assertTrue(result["passed"], json.dumps(result, indent=2))
        self.assertEqual(len(result["case_results"]), 10)
        self.assertEqual(result["actual_cost_micro_usd"], 0)
        self.assertFalse(result["m2_operations_performed"])
        self.assertTrue(result["offline_checks_passed"])
        self.assertFalse(result["milestone_completion_gate_met"])

    def test_exact_regression_has_explicit_inference_and_search_recall(self) -> None:
        result = RUNNER.run(ROOT / "evals" / "2026-08-19-m1.1")
        case = next(
            item
            for item in result["case_results"]
            if item["case_id"] == "female-short-form-broad"
        )

        self.assertTrue(case["passed"])
        self.assertGreaterEqual(case["search_question_count"], 8)
        self.assertIn("female_skewing_fandom", case["facet_ids"])
        self.assertIn("short_form_edit_potential", case["facet_ids"])
        self.assertTrue(case["checks"]["tiktok_disclaimer"])

    def test_selected_profile_beats_newness_only_candidate(self) -> None:
        result = RUNNER.run(ROOT / "evals" / "2026-08-19-m1.1")
        selected = result["ranking_profiles"][result["selected_ranking_profile"]]
        control = result["ranking_profiles"]["m1.1-freshness-heavy-control-v1"]

        self.assertEqual(selected["pairwise_accuracy"], 1.0)
        self.assertEqual(selected["top_candidate_id"], "audience_editable_supported")
        self.assertGreater(
            selected["scores"]["audience_editable_supported"],
            selected["scores"]["brand_new_weak_audience"],
        )
        self.assertGreater(
            selected["pairwise_accuracy"],
            control["pairwise_accuracy"],
        )
        self.assertGreater(
            control["scores"]["brand_new_weak_audience"],
            control["scores"]["audience_supported_less_fresh"],
        )

    def test_model_bakeoff_records_blocked_ids_without_fake_scores(self) -> None:
        result = RUNNER.run(ROOT / "evals" / "2026-08-19-m1.1")
        bakeoff = result["model_bakeoff"]
        by_family = {
            item["required_configuration"]: item
            for item in bakeoff["configurations"]
            if item["required_configuration"] in {"A", "B"}
        }

        self.assertEqual(
            by_family["A"]["execution_status"],
            "BLOCKED_OFFICIAL_ID_UNVERIFIED",
        )
        self.assertEqual(
            by_family["B"]["execution_status"],
            "BLOCKED_OFFICIAL_ID_UNVERIFIED",
        )
        self.assertIsNone(by_family["A"]["scores"])
        self.assertIsNone(by_family["B"]["scores"])
        self.assertIsNone(bakeoff["best_measured_configuration_id"])

        current = next(
            item
            for item in bakeoff["configurations"]
            if item["required_configuration"] == "CURRENT"
        )
        self.assertEqual(
            current["execution_status"],
            "NOT_RUN_NO_ELIGIBLE_SYNTHESIS_PACKET",
        )
        self.assertIsNone(current["scores"])

    def test_live_regression_grades_abstention_without_claiming_completion(self) -> None:
        result = RUNNER.run(ROOT / "evals" / "2026-08-19-m1.1")
        live = result["live_regression"]

        self.assertEqual(live["outcome"], "NO_STRONG_OPPORTUNITY")
        self.assertTrue(live["honest_abstention"])
        self.assertTrue(live["candidate_shortage_explained"])
        self.assertTrue(live["safety_relevance_regression_prevented"])
        self.assertFalse(live["quality_target_met"])
        self.assertFalse(live["completion_gate_met"])
        self.assertEqual(live["candidate_counts"]["serialized"], 0)
        self.assertEqual(live["rubric_grades"]["useful_candidate_count"], 0.0)
        self.assertIsNone(live["rubric_grades"]["footage_specificity"])
        self.assertFalse(any(live["hard_failure_flags"].values()))


if __name__ == "__main__":
    unittest.main()
