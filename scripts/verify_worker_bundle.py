"""Validate and smoke-test a packaged Windows-x64 M1 worker bundle."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import BinaryIO

import pefile


MAX_FRAME_BYTES = 4 * 1024 * 1024
EXPECTED_TARGET = "windows-x86_64"
EXPECTED_LAUNCHER = "ai-edit-machine-worker.exe"
EXPECTED_CONTRACT = "worker-contract.json"
PE_MACHINE_AMD64 = 0x8664
WORKER_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")


def _trusted_windows_directories() -> tuple[Path, Path]:
    if sys.platform != "win32":
        raise ValueError("worker bundle verification requires Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise ValueError("Windows System32 could not be resolved")
    system32 = Path(buffer.value).resolve(strict=True)
    windows = system32.parent
    if not windows.is_dir() or system32.name.casefold() != "system32":
        raise ValueError("Windows returned an unexpected system directory")
    return windows, system32


def _plain_files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink() or os.path.isjunction(root):
        raise ValueError("worker bundle root must be a plain directory")
    files: list[Path] = []
    casefolded: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink() or os.path.isjunction(path):
            raise ValueError("worker bundle cannot contain links or junctions")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("worker bundle contains an unsupported entry")
        relative = path.relative_to(root).as_posix()
        if any(ord(character) < 32 for character in relative) or ":" in relative:
            raise ValueError("worker bundle path is not canonical")
        folded = relative.casefold()
        if folded in casefolded:
            raise ValueError("worker bundle contains a case-insensitive path collision")
        casefolded.add(folded)
        files.append(path)
    return sorted(files)


def _file_manifest(root: Path, files: list[Path]) -> dict[str, tuple[int, str]]:
    manifest: dict[str, tuple[int, str]] = {}
    for path in files:
        before = path.stat(follow_symlinks=False)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat(follow_symlinks=False)
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
        ):
            raise ValueError("worker bundle changed while it was being verified")
        relative = path.relative_to(root).as_posix()
        manifest[relative] = (after.st_size, digest.hexdigest())
    return manifest


def _verify_reference_layout(
    root: Path,
    files: list[Path],
    *,
    reference_root: Path,
) -> None:
    reference_files = _plain_files(reference_root)
    actual = _file_manifest(root, files)
    expected = _file_manifest(reference_root, reference_files)
    if actual == expected:
        return

    missing = sorted(expected.keys() - actual.keys())
    unexpected = sorted(actual.keys() - expected.keys())
    changed = sorted(
        path for path in expected.keys() & actual.keys() if expected[path] != actual[path]
    )
    details: list[str] = []
    if missing:
        details.append(f"missing={missing[:5]}")
    if unexpected:
        details.append(f"unexpected={unexpected[:5]}")
    if changed:
        details.append(f"changed={changed[:5]}")
    raise ValueError(
        "built worker does not exactly match the verified source bundle: "
        + "; ".join(details)
    )


def _verify_pe_targets(files: list[Path]) -> None:
    pe_files = [
        path for path in files if path.suffix.casefold() in {".exe", ".dll", ".pyd"}
    ]
    if not pe_files or not any(path.suffix.casefold() == ".pyd" for path in pe_files):
        raise ValueError("one-folder worker must contain its launcher and Python runtime files")
    for path in pe_files:
        try:
            image = pefile.PE(str(path), fast_load=True)
        except pefile.PEFormatError as error:
            raise ValueError(f"worker PE is malformed: {path.name}") from error
        try:
            if image.FILE_HEADER.Machine != PE_MACHINE_AMD64:
                raise ValueError(f"worker PE is not AMD64: {path.name}")
        finally:
            image.close()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("worker contract contains a duplicate JSON key")
        value[key] = item
    return value


def _reject_nonfinite(item: str) -> None:
    raise ValueError(f"worker contract contains non-finite JSON: {item}")


def _load_worker_contract(root: Path) -> dict[str, str]:
    path = root / EXPECTED_CONTRACT
    if not path.is_file() or path.is_symlink() or os.path.isjunction(path):
        raise ValueError("worker contract is missing or not a plain file")
    raw = path.read_bytes()
    if not raw or len(raw) > 4_096:
        raise ValueError("worker contract is empty or oversized")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("worker contract is not strict UTF-8 JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "protocolVersion",
        "target",
        "workerVersion",
    }:
        raise ValueError("worker contract fields do not match the frozen contract")
    protocol_version = value.get("protocolVersion")
    target = value.get("target")
    worker_version = value.get("workerVersion")
    if (
        not isinstance(protocol_version, str)
        or not isinstance(target, str)
        or not isinstance(worker_version, str)
        or protocol_version != "1.0.0"
        or target != EXPECTED_TARGET
        or WORKER_VERSION.fullmatch(worker_version) is None
    ):
        raise ValueError("worker contract protocol, target, or version is invalid")
    return {
        "protocolVersion": protocol_version,
        "target": target,
        "workerVersion": worker_version,
    }


def _read_frame(stream: BinaryIO, output: queue.Queue[bytes]) -> None:
    output.put(stream.readline(MAX_FRAME_BYTES + 2))


def _next_frame(stream: BinaryIO, *, timeout_seconds: float) -> dict[str, object]:
    output: queue.Queue[bytes] = queue.Queue(maxsize=1)
    reader = threading.Thread(target=_read_frame, args=(stream, output), daemon=True)
    reader.start()
    try:
        raw = output.get(timeout=timeout_seconds)
    except queue.Empty as error:
        raise TimeoutError("worker protocol frame timed out") from error
    if not raw or len(raw) > MAX_FRAME_BYTES + 1 or not raw.endswith(b"\n"):
        raise ValueError("worker emitted an empty, truncated, or oversized frame")
    if raw.endswith(b"\r\n"):
        raise ValueError("worker emitted CRLF; protocol requires LF only")
    try:
        value = json.loads(
            raw[:-1].decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("worker emitted invalid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError("worker frame must be a JSON object")
    return value


def _smoke_protocol(root: Path, *, contract: dict[str, str]) -> None:
    launcher = root / EXPECTED_LAUNCHER
    if not launcher.is_file():
        raise ValueError("worker launcher is missing")
    system_root, system32 = _trusted_windows_directories()
    environment = {
        "AI_EDIT_WORKER_PROTOCOL": "1.0.0",
        "PATH": os.pathsep.join((str(root), str(system32))),
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTHONUTF8": "1",
        "SystemRoot": str(system_root),
        "WINDIR": str(system_root),
    }
    process = subprocess.Popen(
        [str(launcher)],
        cwd=root,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert process.stdout is not None
        hello = _next_frame(process.stdout, timeout_seconds=5.0)
        if set(hello) != {"messageType", "protocolVersion", "target", "workerVersion"}:
            raise ValueError("worker hello fields do not match the frozen protocol")
        if hello != {
            "messageType": "hello",
            "protocolVersion": contract["protocolVersion"],
            "target": contract["target"],
            "workerVersion": contract["workerVersion"],
        }:
            raise ValueError("worker hello version or target is incorrect")

        request_id = str(uuid.uuid4())
        shutdown = {
            "messageType": "shutdown",
            "payload": {
                "reason": "packaged worker smoke test",
                "schemaVersion": "1.0.0",
            },
            "protocolVersion": "1.0.0",
            "requestId": request_id,
        }
        assert process.stdin is not None
        process.stdin.write(
            json.dumps(shutdown, separators=(",", ":"), sort_keys=True).encode("utf-8")
            + b"\n"
        )
        process.stdin.flush()
        acknowledgement = _next_frame(process.stdout, timeout_seconds=5.0)
        if acknowledgement != {
            "messageType": "shutdown.ack",
            "payload": {"schemaVersion": "1.0.0"},
            "protocolVersion": "1.0.0",
            "requestId": request_id,
        }:
            raise ValueError("worker shutdown acknowledgement is not the frozen envelope")
        process.wait(timeout=5.0)
        if process.returncode != 0:
            raise ValueError("worker exited unsuccessfully after shutdown")
        trailing = process.stdout.read(MAX_FRAME_BYTES + 1)
        if trailing:
            raise ValueError("worker emitted trailing stdout after shutdown acknowledgement")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--reference-bundle",
        type=Path,
        help="require exact relative paths, sizes, and SHA-256 values from this bundle",
    )
    args = parser.parse_args()
    root = args.bundle.resolve(strict=True)
    files = _plain_files(root)
    if len(files) < 2:
        raise ValueError("one-folder worker bundle is unexpectedly empty")
    if args.reference_bundle is not None:
        reference_root = args.reference_bundle.resolve(strict=True)
        _verify_reference_layout(root, files, reference_root=reference_root)
    _verify_pe_targets(files)
    contract = _load_worker_contract(root)
    _smoke_protocol(root, contract=contract)
    print(f"Verified packaged worker: {len(files)} files, AMD64, protocol clean.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, TimeoutError, ValueError) as error:
        print(f"Worker bundle verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
