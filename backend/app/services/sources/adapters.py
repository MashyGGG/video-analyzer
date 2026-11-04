import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

from app.services.sources.security import SourceError

VERSION = "yt-dlp/2026.10.26:a02.1"
MAX_BYTES = 200 * 1024 * 1024


class SourceAdapter(Protocol):
    def acquire(self, url: str, dest: Path) -> None: ...


def classify(message: str) -> SourceError:
    message = message.lower()
    for words, code, retryable in (
        (("429", "too many requests"), "SOURCE_RATE_LIMITED", True),
        (("timed out", "timeout"), "SOURCE_TIMEOUT", True),
        (("login", "sign in", "cookies", "private video", "authentication"), "SOURCE_AUTH_REQUIRED", False),
        (("403", "captcha", "drm", "geo", "forbidden"), "SOURCE_ACCESS_DENIED", False),
        (("404", "not found", "removed", "unavailable"), "SOURCE_EXPIRED", False),
        (("larger than", "max-filesize", "file too large"), "MEDIA_TOO_LARGE", False),
        (("requested format",), "SOURCE_UNSUPPORTED", False),
    ):
        if any(word in message for word in words):
            return SourceError(code, retryable)
    return SourceError("SOURCE_CHANGED")


class YtDlpAdapter:
    def acquire(self, url: str, dest: Path) -> None:
        argv = [
            "timeout",
            "--kill-after=3",
            "160s",
            sys.executable,
            "-m",
            "app.services.sources.download_cli",
            "--ignore-config",
            "--no-plugin-dirs",
            "--no-js-runtimes",
            "--no-remote-components",
            "--no-playlist",
            "--no-geo-bypass",
            "--proxy",
            "http://egress:8080",
            "--socket-timeout",
            "8",
            "--retries",
            "0",
            "--extractor-retries",
            "0",
            "--fragment-retries",
            "0",
            "--no-check-formats",
            "--max-filesize",
            str(MAX_BYTES),
            "--limit-rate",
            "4M",
            "--no-progress",
            "--no-cache-dir",
            "--no-part",
            "--no-continue",
            "--no-overwrites",
            "--fixup",
            "never",
            "--format",
            "best[ext=mp4][protocol=https]",
            "--output",
            str(dest),
            "--",
            url,
        ]
        # Anonymous file in the container's bounded /tmp tmpfs; no persistent raw tool logs.
        with tempfile.TemporaryFile() as log:
            try:
                result = subprocess.run(
                    argv,
                    stdout=log,
                    stderr=log,
                    timeout=165,
                    check=False,
                    env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
                )
            except subprocess.TimeoutExpired:
                raise SourceError("SOURCE_TIMEOUT", True) from None
            log.seek(0)
            message = log.read(65536).decode("utf-8", "replace")
            if result.returncode in (124, 137, 143):
                raise SourceError("SOURCE_TIMEOUT", True)
            if result.returncode in (-25, 153) or (dest.is_file() and dest.stat().st_size > MAX_BYTES):
                raise SourceError("MEDIA_TOO_LARGE")
            if result.returncode:
                raise classify(message)
        if not dest.is_file():
            raise SourceError("SOURCE_CHANGED")
        if dest.stat().st_size > MAX_BYTES:
            raise SourceError("MEDIA_TOO_LARGE")


def adapter_for(platform: str) -> SourceAdapter:
    if platform not in ("douyin", "tiktok", "bilibili", "youtube"):
        raise SourceError("SOURCE_UNSUPPORTED")
    return YtDlpAdapter()
