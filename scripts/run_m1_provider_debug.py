"""Run the M1 provider contract/replay harness without the desktop UI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_edit_machine.provider_debug import (  # noqa: E402
    format_report,
    load_fixture,
    run_replay,
)


DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "m1_provider_debug_response.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Development-only, zero-cost M1 OpenAI request-contract and replay harness."
        )
    )
    parser.add_argument(
        "mode",
        choices=("contract", "replay"),
        help="contract asserts the exact request; replay also runs every local M1 stage",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="sanitized provider response fixture",
    )
    arguments = parser.parse_args()
    fixture = load_fixture(arguments.fixture.resolve())
    report = run_replay(fixture, assert_contract=True)
    if arguments.mode == "contract":
        expected = {
            "raw_provider_results": 2,
            "parsed_results": 2,
            "normalized_evidence": 3,
            "evidence_surviving_gates": 3,
            "ranked_opportunities": 1,
            "opportunities_returned_to_ui": 1,
        }
        if report["counts"] != expected:
            raise AssertionError(
                f"provider-debug contract stage counts changed: {report['counts']!r}"
            )
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
