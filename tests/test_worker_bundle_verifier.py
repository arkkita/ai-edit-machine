from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PEFILE_AVAILABLE = importlib.util.find_spec("pefile") is not None
if PEFILE_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location(
        "verify_worker_bundle",
        ROOT / "scripts" / "verify_worker_bundle.py",
    )
    assert SPEC is not None and SPEC.loader is not None
    verify_worker_bundle = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(verify_worker_bundle)


class ReleasePackagingConfigurationTests(unittest.TestCase):
    def test_tauri_maps_the_resource_directory_without_a_flattening_glob(self) -> None:
        config = json.loads(
            (ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["bundle"]["resources"], {"resources/": ""})

        package = json.loads(
            (ROOT / "desktop" / "package.json").read_text(encoding="utf-8")
        )
        self.assertIn("tauri:build:verified", package["scripts"])
        self.assertIn("verify:release-worker", package["scripts"])


@unittest.skipUnless(PEFILE_AVAILABLE, "worker-build verification dependencies are optional")
class WorkerBundleVerifierTests(unittest.TestCase):
    def test_protocol_reader_rejects_duplicate_keys(self) -> None:
        frame = io.BytesIO(b'{"messageType":"hello","messageType":"hello"}\n')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            verify_worker_bundle._next_frame(frame, timeout_seconds=1.0)

    def test_protocol_reader_rejects_nonfinite_numbers(self) -> None:
        frame = io.BytesIO(b'{"value":NaN}\n')
        with self.assertRaisesRegex(ValueError, "non-finite JSON"):
            verify_worker_bundle._next_frame(frame, timeout_seconds=1.0)

    def test_reference_layout_rejects_flattened_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            reference = temporary / "reference"
            built = temporary / "built"
            (reference / "_internal").mkdir(parents=True)
            built.mkdir()
            (reference / "_internal" / "python312.dll").write_bytes(b"runtime")
            (built / "python312.dll").write_bytes(b"runtime")

            with self.assertRaisesRegex(
                ValueError,
                "does not exactly match the verified source bundle",
            ):
                verify_worker_bundle._verify_reference_layout(
                    built,
                    verify_worker_bundle._plain_files(built),
                    reference_root=reference,
                )

    def test_reference_layout_accepts_exact_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            reference = temporary / "reference"
            built = temporary / "built"
            (reference / "_internal").mkdir(parents=True)
            (built / "_internal").mkdir(parents=True)
            (reference / "worker-contract.json").write_bytes(b"contract")
            (built / "worker-contract.json").write_bytes(b"contract")
            (reference / "_internal" / "python312.dll").write_bytes(b"runtime")
            (built / "_internal" / "python312.dll").write_bytes(b"runtime")

            verify_worker_bundle._verify_reference_layout(
                built,
                verify_worker_bundle._plain_files(built),
                reference_root=reference,
            )


if __name__ == "__main__":
    unittest.main()
