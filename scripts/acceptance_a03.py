"""Exercise A03 using synthetic media and an isolated real Compose project."""

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    project = "video-analyzer-a03-" + uuid4().hex[:8]
    env = os.environ.copy()
    env.update(COMPOSE_PROJECT_NAME=project, VA_API_PORT="17831", VA_WEB_PORT="17830")
    checks: list[dict] = []
    report: dict = {"scope": "A03 real Compose, generated local video; not real-video F1 acceptance",
                    "started_utc": datetime.now(UTC).isoformat(), "checks": checks, "status": "FAIL"}
    started = False

    def compose(*command: str, timeout: int = 600) -> None:
        result = subprocess.run(["docker", "compose", "-p", project, *command], cwd=ROOT, env=env,
                                capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"compose {' '.join(command[:2])} exited {result.returncode}")

    def check(name: str, condition: bool) -> None:
        checks.append({"name": name, "pass": bool(condition)})
        if not condition:
            raise AssertionError(name)

    def api(path: str, body: bytes | None = None, other: bool = False) -> tuple[int, bytes]:
        headers = {"X-Owner": ("b" if other else "a") * 64, "X-Authorized": "true"}
        request = urllib.request.Request("http://127.0.0.1:17831/api/v1/" + path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def wait(path: str, terminal: set[str]) -> dict:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status, body = api(path)
            if status != 200:
                raise RuntimeError("status endpoint failed")
            value = json.loads(body)
            if value.get("state") in terminal:
                return value
            # Poll a condition until the deadline; the interval does not assert completion.
            import threading

            threading.Event().wait(0.25)
        raise TimeoutError("worker did not reach a terminal state")

    try:
        compose("build", "api", "frontend", timeout=900)
        started = True
        compose("up", "-d", "--wait", "--wait-timeout", "150", timeout=240)
        with tempfile.TemporaryDirectory(prefix="a03-fixture-") as temporary:
            source = Path(temporary) / "fixture.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=red:s=160x90:r=10:d=1", "-f", "lavfi", "-i",
                            "color=blue:s=160x90:r=10:d=1", "-filter_complex", "concat=n=2:v=1:a=0[out]",
                            "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
                           check=True, capture_output=True, timeout=30)
            status, body = api("assets/upload", source.read_bytes())
        check("upload_accepted", status == 202)
        identifier = json.loads(body)["asset_id"]
        acquired = wait(f"acquisition/jobs/{identifier}", {"SUCCEEDED", "FAILED_PERMANENT"})
        check("real_media_queue_acquired", acquired["state"] == "SUCCEEDED")
        path = f"assets/{identifier}/timeline"
        check("timeline_request_accepted", api(path, b"")[0] == 202)
        finished = wait(path, {"SUCCEEDED", "FAILED"})
        check("real_timeline_queue_succeeded", finished["state"] == "SUCCEEDED")
        code, body = api(path + "/result")
        result = json.loads(body)
        shots = result["shots"]
        check("two_shots_with_expected_cut", code == 200 and len(shots) == 2
              and abs(shots[1]["start_ms"] - 1000) <= 150)
        check("timestamps_and_no_audio", shots[0]["start_ms"] == 0
              and shots[0]["end_ms"] == shots[1]["start_ms"]
              and shots[1]["end_ms"] == result["metadata"]["duration_ms"]
              and result["metadata"]["audio_present"] is False)
        for shot in shots:
            reference = shot["reference"]
            code, image = api(path + "/frames/" + reference["file"])
            import hashlib

            check("reference_" + shot["shot_id"], code == 200 and image.startswith(b"\xff\xd8")
                  and hashlib.sha256(image).hexdigest() == reference["sha256"]
                  and shot["start_ms"] <= reference["timestamp_ms"] < shot["end_ms"])
        check("other_owner_denied", api(path + "/result", other=True)[0] == 404
              and api(path + "/frames/" + shots[0]["reference"]["file"], other=True)[0] == 404)
        report["status"] = "PASS"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if started:
            try:
                compose("down", "--volumes", "--remove-orphans", timeout=120)
            except Exception as error:
                report["cleanup_error"] = f"{type(error).__name__}: {error}"
                report["status"] = "FAIL"
        report["finished_utc"] = datetime.now(UTC).isoformat()
        (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                       encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
