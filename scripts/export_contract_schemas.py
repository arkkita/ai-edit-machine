"""Export/check versioned schemas from the separated contract registries."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from ai_edit_machine.contracts import (  # noqa: E402
    CANONICAL_STORAGE_CONTRACTS,
    PROVIDER_OUTPUT_CONTRACTS,
    TRUSTED_EXECUTION_CONTRACTS,
)
from ai_edit_machine.provider_schema import (  # noqa: E402
    PROVIDER_DIALECTS,
    lower_provider_schema,
)
from ai_edit_machine.m1_contracts import (  # noqa: E402
    CANONICAL_STORAGE_CONTRACTS_V2,
    PROVIDER_OUTPUT_CONTRACTS_V2,
)


SCHEMA_GROUPS = {
    "canonical": CANONICAL_STORAGE_CONTRACTS,
    "execution": TRUSTED_EXECUTION_CONTRACTS,
}
LEGACY_FLAT_SCHEMA_NAMES = (
    "cost-estimate",
    "edit-plan",
    "evidence-record",
    "footage-request",
    "model-run-envelope",
    "research-intent",
    "trend-opportunity",
)


def _lower_provider_node(value: object, dialect: str) -> object:
    """Compatibility name retained for the existing exporter tests."""

    return lower_provider_schema(value, dialect)


def rendered_schema(
    group: str,
    name: str,
    model: type,
    provider_dialect: str | None = None,
    version: str = "v1",
) -> str:
    schema = copy.deepcopy(model.model_json_schema(mode="validation"))
    if provider_dialect is not None:
        schema = _lower_provider_node(schema, provider_dialect)
        group_path = f"provider/{provider_dialect}"
        schema["$comment"] = (
            "Provider baseline only; M1 adapter conformance must verify the live API."
        )
    else:
        group_path = group
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = (
        f"https://ai-edit-machine.local/contracts/{version}/{group_path}/{name}.schema.json"
    )
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def expected_outputs(output_root: Path) -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    for group, contracts in SCHEMA_GROUPS.items():
        for name, model in contracts.items():
            target = output_root / group / f"{name}.schema.json"
            outputs[target] = rendered_schema(group, name, model)
    for dialect in PROVIDER_DIALECTS:
        for name, model in PROVIDER_OUTPUT_CONTRACTS.items():
            target = output_root / "provider" / dialect / f"{name}.schema.json"
            outputs[target] = rendered_schema(
                "provider",
                name,
                model,
                provider_dialect=dialect,
            )
    return outputs


def expected_outputs_v2(output_root: Path) -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    for name, model in CANONICAL_STORAGE_CONTRACTS_V2.items():
        target = output_root / "canonical" / f"{name}.schema.json"
        outputs[target] = rendered_schema("canonical", name, model, version="v2")
    for dialect in PROVIDER_DIALECTS:
        for name, model in PROVIDER_OUTPUT_CONTRACTS_V2.items():
            target = output_root / "provider" / dialect / f"{name}.schema.json"
            outputs[target] = rendered_schema(
                "provider",
                name,
                model,
                provider_dialect=dialect,
                version="v2",
            )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "contracts" / "v1",
    )
    args = parser.parse_args()

    outputs = expected_outputs(args.output)
    v2_output = args.output.parent / "v2"
    outputs.update(expected_outputs_v2(v2_output))
    mismatches: list[str] = []
    for target, expected in outputs.items():
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != expected:
                mismatches.append(str(target))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(expected, encoding="utf-8", newline="\n")

    legacy_files = [
        args.output / f"{name}.schema.json" for name in LEGACY_FLAT_SCHEMA_NAMES
    ]
    for legacy_file in legacy_files:
        if legacy_file.exists():
            if args.check:
                mismatches.append(f"unexpected legacy schema: {legacy_file}")
            else:
                legacy_file.unlink()

    if mismatches:
        print("Generated contract schemas are stale, missing, or unexpectedly retained:")
        for mismatch in mismatches:
            print(f"  {mismatch}")
        return 1
    action = "Verified" if args.check else "Exported"
    print(f"{action} {len(outputs)} generated contract schemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
