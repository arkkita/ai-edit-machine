from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPORTER_PATH = REPOSITORY_ROOT / "scripts" / "export_contract_schemas.py"
SPEC = importlib.util.spec_from_file_location("schema_exporter", EXPORTER_PATH)
assert SPEC is not None and SPEC.loader is not None
schema_exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schema_exporter)


def assert_strict_objects(test: unittest.TestCase, node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            assert_strict_objects(test, item)
        return
    if not isinstance(node, dict):
        return
    properties = node.get("properties")
    if isinstance(properties, dict):
        test.assertFalse(node.get("additionalProperties", True))
        test.assertEqual(set(node.get("required", [])), set(properties))
    for value in node.values():
        assert_strict_objects(test, value)


class SchemaExportTests(unittest.TestCase):
    def test_provider_baselines_require_every_declared_property(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            outputs = schema_exporter.expected_outputs(Path(temporary_directory))
            provider_outputs = {
                path: json.loads(rendered)
                for path, rendered in outputs.items()
                if "provider" in path.parts
            }
        self.assertEqual(len(provider_outputs), 9)
        for schema in provider_outputs.values():
            assert_strict_objects(self, schema)

    def test_execution_schemas_never_appear_in_provider_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            outputs = schema_exporter.expected_outputs(Path(temporary_directory))
        provider_names = {
            path.name for path in outputs if "provider" in path.parts
        }
        self.assertNotIn("cost-estimate.schema.json", provider_names)
        self.assertNotIn("compiled-edit-plan.schema.json", provider_names)

    def test_openai_baselines_omit_unsupported_string_length_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            outputs = schema_exporter.expected_outputs(root)
            outputs.update(schema_exporter.expected_outputs_v2(root.parent / "v2"))
        openai_outputs = {
            path: rendered
            for path, rendered in outputs.items()
            if "provider" in path.parts and "openai" in path.parts
        }
        self.assertEqual(len(openai_outputs), 7)
        for rendered in openai_outputs.values():
            self.assertNotIn('"minLength"', rendered)
            self.assertNotIn('"maxLength"', rendered)


if __name__ == "__main__":
    unittest.main()
