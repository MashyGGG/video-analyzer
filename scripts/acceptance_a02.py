"""Real isolated Compose A02 acceptance, using only a generated colour video.

Download queue failure is deliberately injected, never claimed as platform success.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--api-port", type=int, default=17811)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    checks: list[dict] = []
    report: dict = {"started": datetime.now(UTC).isoformat(), "checks": checks,
                    "platform_success": "BLOCKED: no authorized platform samples provided",
                    "fixture": "generated colour video; no third-party content"}

    def compose(*argv: str) -> str:
        result = subprocess.run(["docker", "compose", "-p", args.compose_project, *argv], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=100)
        if result.returncode:
            raise RuntimeError("Compose acceptance operation failed (raw output withheld)")
        return result.stdout.strip()

    def python(service: str, code: str) -> str:
        return compose("exec", "-T", service, "python", "-c", code)

    def check(name: str, result: bool) -> None:
        checks.append({"name": name, "pass": bool(result)})
        if not result:
            raise AssertionError(name)

    owner = "a" * 64  # Synthetic capability, never a user's live session.

    def api(path: str, data: bytes | dict | None = None, *, other_owner: bool = False) -> tuple[int, dict]:
        headers = {"X-Owner": "b" * 64 if other_owner else owner, "X-Authorized": "true"}
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        else:
            headers["Content-Type"] = "application/octet-stream"
        request = urllib.request.Request(f"http://127.0.0.1:{args.api_port}/api/v1/{path}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def terminal(identifier: str) -> dict:
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            _, payload = api(f"acquisition/jobs/{identifier}")
            if payload.get("state") in ("SUCCEEDED", "FAILED_PERMANENT"):
                return payload
            # Condition-based polling, not a fixed test delay.
            time.sleep(0.25)
        raise TimeoutError("real acquisition queue did not finish")

    try:
        versions = python("worker-media", "import subprocess,json,yt_dlp.version; print(json.dumps({'ffmpeg':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0], 'ytdlp':yt_dlp.version.__version__}))")
        report["versions"] = json.loads(versions)
        report["ffmpeg_build"] = python("worker-media", "import subprocess; print(subprocess.check_output(['ffmpeg','-L'],stderr=subprocess.STDOUT,text=True))")
        for extension in ("mp4", "mov"):
            fixture = python("worker-media", f"import subprocess,base64,pathlib; p='/tmp/a02-fixture.{extension}'; subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=5','-t','1','-c:v','mpeg4',p],check=True); print(base64.b64encode(pathlib.Path(p).read_bytes()).decode()); pathlib.Path(p).unlink()")
            media = base64.b64decode(fixture)
            code, created = api("assets/upload", media)
            check(f"{extension}_upload_accepted", code == 202)
            identifier = created["job_id"]
            final = terminal(identifier)
            check(f"{extension}_real_decode_sha256", final["state"] == "SUCCEEDED" and final["validation"]["sha256"] == hashlib.sha256(media).hexdigest())
            check(f"{extension}_ownership", api(f"acquisition/jobs/{identifier}", other_owner=True)[0] == 404)
            persisted = python("worker-media", f"from pathlib import Path; import hashlib; p=Path('/data/original/{identifier}/source.mp4'); print(hashlib.sha256(p.read_bytes()).hexdigest())")
            check(f"{extension}_cached_file", persisted == final["validation"]["sha256"])
            compose("restart", "worker-media")
            check(f"{extension}_restart_persistence", api(f"acquisition/jobs/{identifier}")[1]["validation"] == final["validation"])
        _, invalid = api("assets/upload", b"<html>not-video</html>")
        invalid_final = terminal(invalid["job_id"])
        check("fake_media_rejected", invalid_final["state"] == "FAILED_PERMANENT" and invalid_final["error"]["code"] == "MEDIA_INVALID")
        check("failure_staging_cleaned", python("worker-media", f"from pathlib import Path; print(Path('/data/staging/{invalid['job_id']}').exists())") == "False")
        for url in ("https://127.0.0.1/a", "https://169.254.169.254/latest", "https://douyin.com.evil.test/1"):
            check("unsafe_source_" + str(len(checks)), api("assets/resolve", {"text": url, "authorized": True})[0] == 400)
        _, source = api("assets/resolve", {"text": "https://v.douyin.com/A02Synthetic/", "authorized": True})
        identifier = source["source_id"]
        python("api", f"from app.acquisition import update; update('{identifier}', platform='fault_injected')")
        check("download_queue_accepted", api(f"assets/{identifier}/acquire", b"")[0] == 202)
        final = terminal(identifier)
        check("real_download_task_failure_fallback", final["state"] == "FAILED_PERMANENT" and final["error"]["code"] == "SOURCE_UNSUPPORTED" and final["fallback"] == "upload")
        for service in ("worker-download", "worker-media"):
            isolated = python(service, "import socket; s=socket.socket(); s.settimeout(2);\ntry:\n s.connect(('1.1.1.1',443)); print('OPEN')\nexcept OSError:\n print('BLOCKED')\nfinally:\n s.close()")
            check(service + "_public_route_blocked", isolated == "BLOCKED")
            check(service + "_nonroot", compose("exec", "-T", service, "id", "-u") == "10001")
        for target in ("127.0.0.1:443", "169.254.169.254:443", "douyin.com:80", "evil.test:443"):
            result = python("worker-download", f"import socket; s=socket.create_connection(('egress',8080),timeout=5); s.sendall(b'CONNECT {target} HTTP/1.1\\r\\nHost: {target}\\r\\n\\r\\n'); print(s.recv(4096).decode().splitlines()[0]); s.close()")
            check("gateway_rejects_" + target, "403" in result)
        check("gateway_has_no_secrets", python("egress", "from pathlib import Path; print(Path('/run/secrets/postgres_password').exists() or Path('/data/original').exists())") == "False")
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = f"{type(error).__name__}: {error}"
    report["counts"] = {"passed": sum(c["pass"] for c in checks), "failed": sum(not c["pass"] for c in checks), "skipped": 0}
    (args.output_dir / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
