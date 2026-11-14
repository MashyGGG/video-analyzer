"""Build a physical timeline from local video, retaining decoded frame timestamps."""

import hashlib
import json
import os
import shutil
import subprocess
import threading
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from scenedetect.detectors import ContentDetector

cv2.setNumThreads(1)
MAX_FRAMES = 30000
MAX_DURATION_MS = 180000
MAX_SHOTS = 200
FRAME_BYTES = 320 * 180 * 3
INPUT_OPTIONS = ["-protocol_whitelist", "file,pipe", "-f", "mov", "-enable_drefs", "0", "-use_absolute_path", "0"]


class MediaError(Exception):
    """A bounded, credential-free error suitable for a job status."""


def _run(argv: list[str], timeout: float = 90) -> bytes:
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise MediaError("MEDIA_PROCESS_FAILED") from exc
    expired = threading.Event()

    def kill() -> None:
        expired.set()
        try:
            process.kill()
        except OSError:
            pass

    timer = threading.Timer(timeout, kill)
    timer.start()
    output = bytearray()
    try:
        assert process.stdout is not None
        while chunk := process.stdout.read(65536):
            output.extend(chunk)
            if len(output) > 32 * 1024 * 1024:
                raise MediaError("MEDIA_LIMIT_EXCEEDED")
        if process.wait(timeout=5) or expired.is_set():
            raise MediaError("MEDIA_PROCESS_FAILED")
        return bytes(output)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaError("MEDIA_PROCESS_FAILED") from exc
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout:
            process.stdout.close()


def _probe(path: Path) -> tuple[dict, list[dict]]:
    prefix = ["ffprobe", "-v", "error", *INPUT_OPTIONS]
    try:
        meta = json.loads(_run(prefix + ["-show_streams", "-show_format", "-of", "json", str(path)], 30))
        video = next(s for s in meta["streams"] if s["codec_type"] == "video")
        if not 0 < int(video["width"]) <= 4096 or not 0 < int(video["height"]) <= 4096:
            raise MediaError("MEDIA_LIMIT_EXCEEDED")
        frames = json.loads(_run(prefix + ["-select_streams", "v:0", "-show_frames", "-show_entries",
            "frame=best_effort_timestamp,pkt_duration,duration", "-of", "json", str(path)], 60))["frames"]
        if not frames or len(frames) > MAX_FRAMES:
            raise MediaError("MEDIA_LIMIT_EXCEEDED")
        time_base = Fraction(video["time_base"])
        timestamps = [int(frame["best_effort_timestamp"]) for frame in frames]
        if time_base <= 0 or any(a >= b for a, b in zip(timestamps, timestamps[1:], strict=False)):
            raise MediaError("MEDIA_TIMESTAMP_INVALID")
        first = timestamps[0]
        offsets = [int((value - first) * time_base * 1000) for value in timestamps]
        if any(a >= b for a, b in zip(offsets, offsets[1:], strict=False)):
            raise MediaError("MEDIA_TIMESTAMP_RESOLUTION")
        last_duration = int(frames[-1].get("duration") or frames[-1].get("pkt_duration") or 0)
        duration_basis = "decoded_frame_duration"
        if last_duration <= 0:
            stream_end = int(video.get("start_pts", first)) + int(video.get("duration_ts", 0))
            last_duration = stream_end - timestamps[-1]
            duration_basis = "stream_duration"
            if last_duration <= 0:
                raise MediaError("MEDIA_TIMESTAMP_INVALID")
        duration = int((timestamps[-1] - first + last_duration) * time_base * 1000)
        if not 0 < duration <= MAX_DURATION_MS or offsets[-1] >= duration:
            raise MediaError("MEDIA_LIMIT_EXCEEDED")
        deltas = [b - a for a, b in zip(timestamps, timestamps[1:], strict=False)]
        # A one-tick difference can be normal rounding at a rational frame rate.
        vfr = bool(deltas and max(deltas) - min(deltas) > 1)
        rotation = next((int(item["rotation"]) for item in video.get("side_data_list", []) if "rotation" in item),
                        int(video.get("tags", {}).get("rotate", 0)))
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        metadata = {"duration_ms": duration, "duration_basis": duration_basis,
                    "width": int(video["width"]), "height": int(video["height"]),
                    "container": str(meta["format"]["format_name"]), "video_codec": str(video["codec_name"]),
                    "rotation": rotation, "video_stream_index": int(video["index"]),
                    "audio_stream_indices": [int(s["index"]) for s in meta["streams"] if s["codec_type"] == "audio"],
                    "audio_present": any(s["codec_type"] == "audio" for s in meta["streams"]),
                    "time_base": str(video["time_base"]), "avg_frame_rate": video.get("avg_frame_rate", "0/0"),
                    "variable_frame_rate": vfr, "source_start_pts": first,
                    "sha256": digest}
        return metadata, [{"pts": pts, "timestamp_ms": ms} for pts, ms in zip(timestamps, offsets, strict=False)]
    except MediaError:
        raise
    except (KeyError, ValueError, TypeError, StopIteration, ZeroDivisionError, OSError, json.JSONDecodeError) as exc:
        raise MediaError("MEDIA_INVALID") from exc


def _detect(path: Path, count: int) -> list[int]:
    command = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1", "-filter_threads", "1", *INPUT_OPTIONS, "-i", str(path),
               "-map", "0:v:0", "-an", "-vf", "scale=320:180",
               "-fps_mode", "passthrough", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise MediaError("MEDIA_PROCESS_FAILED") from exc
    expired = threading.Event()

    def kill() -> None:
        expired.set()
        try:
            process.kill()
        except OSError:
            pass

    timer = threading.Timer(180, kill)
    timer.start()
    detector = ContentDetector(threshold=27.0, min_scene_len=1)
    cuts = []
    index = 0
    try:
        assert process.stdout is not None
        while True:
            data = bytearray()
            while len(data) < FRAME_BYTES:
                part = process.stdout.read(FRAME_BYTES - len(data))
                if not part:
                    break
                data.extend(part)
            if not data:
                break
            if len(data) != FRAME_BYTES or index >= count:
                raise MediaError("MEDIA_FRAME_MISMATCH")
            frame = np.frombuffer(data, dtype=np.uint8).reshape((180, 320, 3))
            cuts.extend(detector.process_frame(index, frame))
            index += 1
        if process.wait(timeout=5) or expired.is_set() or index != count:
            raise MediaError("MEDIA_FRAME_MISMATCH")
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaError("MEDIA_PROCESS_FAILED") from exc
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout:
            process.stdout.close()
    return [int(c) for c in cuts if 0 < int(c) < count]


def analyze(source: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink() or not source.is_file() or source.is_symlink():
        raise MediaError("MEDIA_PATH_INVALID")
    staging = output.parent / (".media-" + uuid4().hex)
    try:
        metadata, frames = _probe(source)
        cuts = _detect(source, len(frames))
        if len(cuts) >= MAX_SHOTS:
            raise MediaError("MEDIA_LIMIT_EXCEEDED")
        boundaries = [0, *sorted(set(cuts)), len(frames)]
        indices = [(a + b - 1) // 2 for a, b in zip(boundaries, boundaries[1:], strict=False)]
        staging.mkdir(parents=True, exist_ok=False)
        expression = "+".join(f"eq(n\\,{n})" for n in indices)
        _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1", "-filter_threads", "1", *INPUT_OPTIONS, "-i", str(source),
              "-map", "0:v:0", "-an", "-vf", f"select={expression},scale=640:640:force_original_aspect_ratio=decrease", "-fps_mode", "vfr", "-start_number", "0",
              "-q:v", "3", str(staging / "frame_%04d.jpg")], 180)
        shots = []
        for number, (start, end, reference) in enumerate(zip(boundaries, boundaries[1:], indices, strict=False)):
            name = f"frame_{number:04d}.jpg"
            image = staging / name
            with image.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            thumb_name = f"thumb_{number:04d}.jpg"
            decoded = cv2.imread(str(image))
            if decoded is None:
                raise MediaError("MEDIA_FRAME_MISMATCH")
            height, width = decoded.shape[:2]
            scale = min(320 / width, 180 / height, 1.0)
            thumbnail = cv2.resize(decoded, (max(1, round(width * scale)), max(1, round(height * scale))))
            if not cv2.imwrite(str(staging / thumb_name), thumbnail):
                raise MediaError("MEDIA_PROCESS_FAILED")
            start_ms = frames[start]["timestamp_ms"]
            end_ms = frames[end]["timestamp_ms"] if end < len(frames) else metadata["duration_ms"]
            shots.append({"shot_id": f"shot_{number + 1:04d}", "start_ms": start_ms,
                          "end_ms": end_ms, "review_flags": ["short_shot"] if end_ms - start_ms < 300 else [],
                          "transition": "unknown", "thumbnail": thumb_name,
                          "reference": {**frames[reference], "file": name, "sha256": digest}})
        result = {"schema_version": "1.0.0", "algorithm": "scenedetect-content:0.6.7.1", "metadata": metadata,
                  "shots": shots, "semantic_segments": []}
        (staging / "timeline.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise MediaError("MEDIA_PATH_INVALID")
        os.rename(staging, output)
        return result
    except MediaError:
        raise
    except (OSError, ValueError) as exc:
        raise MediaError("MEDIA_PROCESS_FAILED") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
