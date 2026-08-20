"""Run the dated, network-inert M1.1 intent and ranking calibration suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_edit_machine.research.evaluation import (  # noqa: E402
    RankingEvaluationCandidate,
    evaluate_live_regression_fixture,
    evaluate_model_bakeoff,
    evaluate_ranking_profiles,
)
from ai_edit_machine.research.intent import intent_from_query  # noqa: E402
from ai_edit_machine.research.ranking import (  # noqa: E402
    DEFAULT_RANKING_PROFILE_ID,
)


DEFAULT_SUITE = ROOT / "evals" / "2026-08-19-m1.1"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} root must be an object")
    return value


def run(suite: Path) -> dict[str, object]:
    corpus = _load(suite / "corpus.json")
    rubric = _load(suite / "rubric.json")
    packets = _load(suite / "ranking-packets.json")
    model_packet = _load(suite / "model-bakeoff.json")
    live_packet_path = suite / "live-regression-2026-08-19-run5.json"
    cases = corpus.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise ValueError("M1.1 golden corpus must contain exactly ten cases")
    case_results: list[dict[str, object]] = []
    for raw in cases:
        if not isinstance(raw, dict):
            raise ValueError("M1.1 case must be an object")
        prompt = raw.get("prompt")
        expected_facets = raw.get("expected_facets")
        if not isinstance(prompt, str) or not isinstance(expected_facets, list):
            raise ValueError("M1.1 case prompt/facets are malformed")
        intent = intent_from_query(prompt)
        interpretation = intent.interpretation
        if interpretation is None:
            raise ValueError("M1.1 parser omitted its interpretation")
        actual_facets = {item.facet_id for item in interpretation.facets}
        checks = {
            "facet_subset": set(map(str, expected_facets)).issubset(actual_facets),
            "broad_query": interpretation.broad_query is bool(raw.get("broad_query")),
            "clarification": interpretation.clarification_needed
            is bool(raw.get("clarification_needed")),
            "search_question_recall": len(interpretation.search_questions)
            >= int(raw.get("minimum_search_questions", 0)),
            "max_results": (
                intent.max_results == int(raw["max_results"])
                if "max_results" in raw
                else True
            ),
            "tiktok_disclaimer": (
                interpretation.short_form_inference_disclaimer is not None
                and not interpretation.direct_tiktok_data_used
                if "short_form_edit_potential" in actual_facets
                else True
            ),
        }
        case_results.append(
            {
                "case_id": raw.get("case_id"),
                "passed": all(checks.values()),
                "checks": checks,
                "facet_ids": sorted(actual_facets),
                "search_question_count": len(interpretation.search_questions),
            }
        )

    raw_candidates = packets.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("ranking packets are missing")
    candidates = [
        RankingEvaluationCandidate(
            candidate_id=str(item["candidate_id"]),
            expected_relevance=int(item["expected_relevance"]),
            components={
                str(key): float(value)
                for key, value in item["components"].items()
            },
        )
        for item in raw_candidates
        if isinstance(item, dict)
    ]
    ranking = evaluate_ranking_profiles(candidates)
    model_bakeoff = evaluate_model_bakeoff(model_packet)
    live_regression = (
        evaluate_live_regression_fixture(_load(live_packet_path))
        if live_packet_path.exists()
        else None
    )
    selected = ranking[DEFAULT_RANKING_PROFILE_ID]
    offline_checks_passed = (
        all(item["passed"] for item in case_results)
        and selected["pairwise_accuracy"] == 1.0
        and selected["top_candidate_id"] == "audience_editable_supported"
    )
    return {
        "schema_version": "1.0.0",
        "suite_id": corpus.get("suite_id"),
        "mode": "OFFLINE_REPLAY",
        "actual_cost_micro_usd": 0,
        "m2_operations_performed": False,
        "rubric_dimensions": rubric.get("dimensions"),
        "case_results": case_results,
        "ranking_profiles": ranking,
        "model_bakeoff": model_bakeoff,
        "live_regression": live_regression,
        "selected_ranking_profile": DEFAULT_RANKING_PROFILE_ID,
        "offline_checks_passed": offline_checks_passed,
        "milestone_completion_gate_met": (
            bool(live_regression["completion_gate_met"])
            if live_regression is not None
            else False
        ),
        "passed": offline_checks_passed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-dir", type=Path, default=DEFAULT_SUITE)
    args = parser.parse_args(argv)
    result = run(args.suite_dir.resolve())
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
