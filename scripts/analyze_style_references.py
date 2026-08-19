"""Read-only, deterministic measurements for short style-reference videos.

This deliberately reports signals rather than guessing creative intent.  It requires
an FFmpeg build with ffprobe and never writes beside or modifies source media.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SCENE_RE = re.compile(r"pts_time:(?P<time>[0-9.]+)")
SCORE_RE = re.compile(r"lavfi\.scene_score=(?P<score>[0-9.]+)")
BLACK_RE = re.compile(
    r"black_start:(?P<start>[0-9.]+) black_end:(?P<end>[0-9.]+) "
    r"black_duration:(?P<duration>[0-9.]+)"
)
SILENCE_START_RE = re.compile(r"silence_start: (?P<start>-?[0-9.]+)")
SILENCE_END_RE = re.compile(
    r"silence_end: (?P<end>-?[0-9.]+) \| silence_duration: (?P<duration>[0-9.]+)"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_ROOT = (REPOSITORY_ROOT / "artifacts" / "reference-analysis").resolve()
COMMAND_TIMEOUT_SECONDS = 300


def run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path, ffprobe: Path) -> dict[str, Any]:
    result = run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def scene_candidates(path: Path, ffmpeg: Path, threshold: float) -> list[dict[str, float]]:
    result = run(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            f"select='gt(scene,{threshold})',metadata=print",
            "-an",
            "-f",
            "null",
            "NUL",
        ]
    )
    text = result.stderr.decode("utf-8", "replace")
    pending_time: float | None = None
    candidates: list[dict[str, float]] = []
    for line in text.splitlines():
        time_match = SCENE_RE.search(line)
        if time_match:
            pending_time = float(time_match.group("time"))
        score_match = SCORE_RE.search(line)
        if score_match and pending_time is not None:
            candidates.append(
                {"time_seconds": pending_time, "scene_score": float(score_match.group("score"))}
            )
            pending_time = None
    return candidates


def pcm_rms(path: Path, ffmpeg: Path, sample_rate: int = 8_000, window_ms: int = 100) -> dict[str, Any]:
    result = run(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
    )
    raw = result.stdout
    samples = memoryview(raw).cast("h")
    window_size = sample_rate * window_ms // 1000
    values: list[float] = []
    for offset in range(0, len(samples), window_size):
        window = samples[offset : offset + window_size]
        if not window:
            continue
        power = sum(int(sample) * int(sample) for sample in window) / len(window)
        values.append(math.sqrt(power) / 32768.0)
    floor = 1e-9
    dbfs = [20 * math.log10(max(value, floor)) for value in values]
    deltas = [abs(dbfs[index] - dbfs[index - 1]) for index in range(1, len(dbfs))]
    strongest = sorted(range(1, len(dbfs)), key=lambda index: deltas[index - 1], reverse=True)[:12]
    return {
        "sample_rate": sample_rate,
        "window_ms": window_ms,
        "median_dbfs": round(statistics.median(dbfs), 3),
        "p10_dbfs": round(sorted(dbfs)[max(0, int(len(dbfs) * 0.10) - 1)], 3),
        "p90_dbfs": round(sorted(dbfs)[min(len(dbfs) - 1, int(len(dbfs) * 0.90))], 3),
        "largest_level_changes": [
            {
                "time_seconds": round(index * window_ms / 1000, 3),
                "absolute_delta_db": round(deltas[index - 1], 3),
            }
            for index in strongest
        ],
    }


def black_and_silence(path: Path, ffmpeg: Path) -> dict[str, Any]:
    result = run(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.25:pix_th=0.10:pic_th=0.97",
            "-af",
            "silencedetect=n=-45dB:d=0.25",
            "-f",
            "null",
            "NUL",
        ]
    )
    text = result.stderr.decode("utf-8", "replace")
    black_segments = [
        {
            "start_seconds": float(match.group("start")),
            "end_seconds": float(match.group("end")),
            "duration_seconds": float(match.group("duration")),
        }
        for match in BLACK_RE.finditer(text)
    ]
    silence_starts: list[float] = []
    silent_segments: list[dict[str, float]] = []
    for line in text.splitlines():
        start_match = SILENCE_START_RE.search(line)
        if start_match:
            silence_starts.append(float(start_match.group("start")))
        end_match = SILENCE_END_RE.search(line)
        if end_match:
            start = silence_starts.pop(0) if silence_starts else float(end_match.group("end")) - float(
                end_match.group("duration")
            )
            silent_segments.append(
                {
                    "start_seconds": start,
                    "end_seconds": float(end_match.group("end")),
                    "duration_seconds": float(end_match.group("duration")),
                }
            )
    return {
        "black_detection": {
            "minimum_duration_seconds": 0.25,
            "pixel_threshold": 0.10,
            "picture_ratio_threshold": 0.97,
            "segments": black_segments,
        },
        "silence_detection": {
            "minimum_duration_seconds": 0.25,
            "threshold_dbfs": -45,
            "segments": silent_segments,
        },
    }


def interval_summary(duration: float, cuts: list[dict[str, float]]) -> dict[str, Any]:
    boundaries = [0.0, *(cut["time_seconds"] for cut in cuts), duration]
    intervals = [right - left for left, right in zip(boundaries, boundaries[1:]) if right > left]
    return {
        "count": len(cuts),
        "median_seconds": round(statistics.median(intervals), 3) if intervals else None,
        "minimum_seconds": round(min(intervals), 3) if intervals else None,
        "maximum_seconds": round(max(intervals), 3) if intervals else None,
    }


def analyze(
    path: Path,
    ffmpeg: Path,
    ffprobe: Path,
    threshold: float,
    source_handle: str,
) -> dict[str, Any]:
    initial_stat = path.stat()
    initial_sha256 = sha256(path)
    metadata = probe(path, ffprobe)
    duration = float(metadata["format"]["duration"])
    candidates = scene_candidates(path, ffmpeg, threshold)
    streams = metadata["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    audio = next((stream for stream in streams if stream["codec_type"] == "audio"), None)
    report = {
        "source_handle": source_handle,
        "display_name": path.name,
        "size_bytes": initial_stat.st_size,
        "source_observation": {
            "size_bytes": initial_stat.st_size,
            "modified_time_ns": initial_stat.st_mtime_ns,
        },
        "sha256": initial_sha256,
        "duration_seconds": duration,
        "video": {
            "codec": video["codec_name"],
            "width": video["width"],
            "height": video["height"],
            "display_aspect_ratio": video.get("display_aspect_ratio"),
            "average_frame_rate": video.get("avg_frame_rate"),
            "pixel_format": video.get("pix_fmt"),
        },
        "audio": None
        if audio is None
        else {
            "codec": audio["codec_name"],
            "sample_rate": int(audio["sample_rate"]),
            "channels": audio["channels"],
            "level_envelope": pcm_rms(path, ffmpeg),
        },
        "scene_detection": {
            "method": "FFmpeg scene score; candidates are not automatically accepted editorial cuts",
            "threshold": threshold,
            "candidates": candidates,
            "interval_summary": interval_summary(duration, candidates),
        },
    }
    report.update(black_and_silence(path, ffmpeg))
    final_stat = path.stat()
    final_sha256 = sha256(path)
    if (
        final_sha256 != initial_sha256
        or final_stat.st_size != initial_stat.st_size
        or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
    ):
        raise RuntimeError(f"source changed during analysis: {source_handle}")
    return report


def canonical_key(path: Path) -> str:
    """Return a Windows-safe comparison key without relying on input spelling."""

    return os.path.normcase(str(path.resolve())).casefold()


def validated_output_path(output: Path, inputs: list[Path]) -> Path:
    target = output.resolve()
    try:
        target.relative_to(ANALYSIS_ROOT)
    except ValueError as error:
        raise ValueError(f"--output must be inside {ANALYSIS_ROOT}") from error
    input_keys = {canonical_key(path) for path in inputs}
    if canonical_key(target) in input_keys:
        raise ValueError("report output must not collide with any source input")
    return target


def atomic_write_json(target: Path, rendered: str) -> None:
    """Write on the destination volume, verify, and atomically replace the report."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="x",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.name}.",
            suffix=".partial",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary_name = stream.name
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        temporary = Path(temporary_name)
        parsed = json.loads(temporary.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict) or "references" not in parsed:
            raise ValueError("temporary report verification failed")
        os.replace(temporary, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def tool_provenance(executable: Path) -> dict[str, Any]:
    resolved = executable.resolve(strict=True)
    version = run([str(resolved), "-version"]).stdout.decode("utf-8", "replace")
    return {
        "display_name": resolved.name,
        "sha256": sha256(resolved),
        "version_and_build_configuration": version.strip().splitlines(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--scene-threshold", type=float, default=0.22)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    resolved_inputs = [path.resolve(strict=True) for path in args.paths]
    output = validated_output_path(args.output, resolved_inputs) if args.output else None

    report = {
        "analysis_version": "1.1.0",
        "script_sha256": sha256(Path(__file__).resolve()),
        "tools": {
            "ffmpeg": tool_provenance(args.ffmpeg),
            "ffprobe": tool_provenance(args.ffprobe),
        },
        "command_templates": {
            "probe": "ffprobe -v error -show_format -show_streams -of json SOURCE",
            "scene": "ffmpeg -nostdin -hide_banner -i SOURCE -vf select='gt(scene,THRESHOLD)',metadata=print -an -f null NUL",
            "audio_pcm": "ffmpeg -nostdin -hide_banner -loglevel error -i SOURCE -vn -ac 1 -ar 8000 -f s16le pipe:1",
            "black_silence": "ffmpeg -nostdin -hide_banner -i SOURCE -vf blackdetect=d=0.25:pix_th=0.10:pic_th=0.97 -af silencedetect=n=-45dB:d=0.25 -f null NUL",
        },
        "limitations": [
            "Scene-score peaks include flashes, dissolves, and other transitions.",
            "Audio level changes do not identify dialogue, songs, beats, or creative intent.",
            "Exact velocity curves cannot be recovered reliably from a flattened render.",
        ],
        "references": [
            analyze(
                path,
                args.ffmpeg,
                args.ffprobe,
                args.scene_threshold,
                f"style-reference-{chr(ord('A') + index)}",
            )
            for index, path in enumerate(resolved_inputs)
        ],
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if output:
        atomic_write_json(output, rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
