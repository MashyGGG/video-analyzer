import hashlib
import json
import subprocess
from pathlib import Path

from app.services.sources.adapters import MAX_BYTES
from app.services.sources.security import SourceError


def validate(path: Path) -> dict[str, str | int]:
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise SourceError("MEDIA_TOO_LARGE")
    with path.open("rb") as stream:
        signature = stream.read(12)
    if (
        len(signature) < 12
        or signature[4:8] != b"ftyp"
        or signature[8:12]
        not in (
            b"isom",
            b"iso2",
            b"mp41",
            b"mp42",
            b"avc1",
            b"qt  ",
            b"M4V ",
        )
    ):
        raise SourceError("MEDIA_INVALID")
    try:
        probe = subprocess.run(
            [
                "timeout",
                "--kill-after=2",
                "15s",
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-max_alloc",
                "67108864",
                "-f",
                "mov",
                "-enable_drefs",
                "0",
                "-use_absolute_path",
                "0",
                "-show_entries",
                "format=format_name,duration:stream=codec_type,width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
        data = json.loads(probe.stdout)
        duration = int(float(data["format"]["duration"]) * 1000)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        if not 0 < duration <= 180_000 or not 0 < video["width"] <= 4096 or not 0 < video["height"] <= 4096:
            raise SourceError("MEDIA_LIMIT_EXCEEDED")
        if "mp4" not in data["format"]["format_name"].split(","):
            raise SourceError("MEDIA_INVALID")
        subprocess.run(
            [
                "timeout",
                "--kill-after=2",
                "45s",
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-max_alloc",
                "67108864",
                "-threads",
                "1",
                "-protocol_whitelist",
                "file",
                "-f",
                "mov",
                "-enable_drefs",
                "0",
                "-use_absolute_path",
                "0",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-an",
                "-threads",
                "1",
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=50,
            check=True,
        )
    except SourceError:
        raise
    except (
        OSError,
        ValueError,
        OverflowError,
        TypeError,
        KeyError,
        StopIteration,
        subprocess.SubprocessError,
    ):
        raise SourceError("MEDIA_INVALID") from None
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "sha256": digest,
        "bytes": size,
        "duration_ms": duration,
        "container": "mp4/mov",
        "validation": "full-video-decode:a02.1",
    }
