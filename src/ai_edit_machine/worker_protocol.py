"""Strict LF-delimited JSON framing shared by the packaged M1 worker."""

from __future__ import annotations

import json
from typing import Any, BinaryIO


PROTOCOL_VERSION = "1.0.0"
WORKER_VERSION = "0.1.0-m1.1b-dev"
WORKER_TARGET = "windows-x86_64"
MAX_FRAME_BYTES = 4 * 1024 * 1024


class WorkerProtocolError(RuntimeError):
    pass


def hello_frame() -> dict[str, str]:
    return {
        "messageType": "hello",
        "protocolVersion": PROTOCOL_VERSION,
        "workerVersion": WORKER_VERSION,
        "target": WORKER_TARGET,
    }


def read_json_frame(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one exact LF frame; clean EOF is returned only between jobs."""

    frame = stream.readline(MAX_FRAME_BYTES + 2)
    if frame == b"":
        return None
    if len(frame) > MAX_FRAME_BYTES + 1:
        raise WorkerProtocolError("worker protocol frame exceeded 4 MiB")
    if not frame.endswith(b"\n"):
        raise WorkerProtocolError("worker protocol frame was truncated")
    if frame.endswith(b"\r\n"):
        raise WorkerProtocolError("worker protocol requires LF, not CRLF")
    payload_bytes = frame[:-1]
    if not payload_bytes or len(payload_bytes) > MAX_FRAME_BYTES:
        raise WorkerProtocolError("worker protocol frame is empty or oversized")
    try:
        text = payload_bytes.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkerProtocolError("worker protocol frame is not strict UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise WorkerProtocolError("worker protocol top-level value must be an object")
    return payload


def write_json_frame(stream: BinaryIO, payload: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise WorkerProtocolError("outbound worker payload is not strict JSON") from error
    if not encoded or len(encoded) > MAX_FRAME_BYTES or b"\n" in encoded:
        raise WorkerProtocolError("outbound worker frame is empty, multiline, or oversized")
    stream.write(encoded)
    stream.write(b"\n")
    stream.flush()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerProtocolError("worker protocol JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise WorkerProtocolError(f"non-finite JSON number is forbidden: {value}")
