"""Exercise an already started, isolated A01 Compose stack. Never deletes persistent volumes."""

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=3100)
    parser.add_argument("--compose-project", default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evidence/A01")
    args = parser.parse_args()
    evidence = args.output_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    records, checks = [], []
    env = os.environ.copy()
    for key in list(env):
        if any(term in key.upper() for term in ("API_KEY", "TOKEN", "PASSWORD", "COOKIE", "SECRET")):
            del env[key]
    values = [
        (ROOT / ".secrets" / name).read_text().strip() for name in ("postgres_password", "redis_password")
    ]

    def safe(text: str) -> str:
        for value in values:
            text = text.replace(value, "<redacted>")
        return text.replace(str(ROOT), "<workspace>")

    def run(argv: list[str], timeout: int = 90) -> str:
        before = time.monotonic()
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        records.append(
            dict(
                argv=argv,
                exit_code=result.returncode,
                seconds=round(time.monotonic() - before, 3),
                stdout=safe(result.stdout),
                stderr=safe(result.stderr),
            )
        )
        if result.returncode:
            raise RuntimeError("Command failed: " + " ".join(argv))
        return result.stdout

    def compose(*argv: str, timeout: int = 90) -> str:
        project = ["-p", args.compose_project] if args.compose_project else []
        return run(["docker", "compose", *project, *argv], timeout)

    def probe(action: str, token: str = "") -> dict:
        argv = ["exec", "-T", "api", "python", "-m", "app.infra_probe", action]
        if token:
            argv.extend(["--token", token])
        return json.loads(compose(*argv))

    def check(name: str, condition: bool) -> None:
        checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
        if not condition:
            raise AssertionError(name)

    api = f"http://127.0.0.1:{args.api_port}"
    web = f"http://127.0.0.1:{args.web_port}"

    def http(url: str) -> tuple[int, dict | str]:
        try:
            response = urllib.request.urlopen(url, timeout=8)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read().decode()
            return response.code, json.loads(body) if "json" in response.headers.get(
                "Content-Type", ""
            ) else body

    def wait_ready() -> None:
        for _ in range(30):
            try:
                if http(api + "/api/v1/health/ready")[0] == 200:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        raise TimeoutError("API did not become ready")

    token = uuid.uuid4().hex
    started = datetime.now(UTC).isoformat()
    try:
        config = json.loads(compose("config", "--format", "json"))
        check(
            "no_cloud_model_keys",
            all(
                not any("API_KEY" in k for k in s.get("environment", {})) for s in config["services"].values()
            ),
        )
        check(
            "data_ports_private", all(not config["services"][s].get("ports") for s in ("postgres", "redis"))
        )
        wait_ready()
        code, payload = http(api + "/api/v1/health/ready")
        check("ready_without_model", code == 200 and payload["models"] == "not_configured")
        check("frontend_page", "Video Analyzer" in http(web)[1])
        check("frontend_live", http(web + "/health/live")[0] == 200)
        check("frontend_api_proxy", http(web + "/api/health")[0] == 200)
        check("real_celery_roundtrip", probe("queue")["real_queue_roundtrip"])
        check("migration_replay", all(probe("migrations").values()))
        before = probe("write", token)
        check("persistent_markers_created", before["redis_persisted"] and before["file_persisted"])
        compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "120", timeout=180)
        wait_ready()
        after = probe("read", token)
        check("database_identity_persisted", before["installation"] == after["installation"])
        check("redis_data_persisted", after["redis_persisted"])
        check("work_files_persisted", after["file_persisted"])
        for service in ("postgres", "redis"):
            compose("stop", service)
            try:
                check(f"{service}_failure_live_200", http(api + "/api/v1/health/live")[0] == 200)
                check(f"{service}_failure_ready_503", http(api + "/api/v1/health/ready")[0] == 503)
                check(f"{service}_failure_proxy_503", http(web + "/api/health")[0] == 503)
            finally:
                compose("start", service)
                wait_ready()
            check(f"{service}_recovered", http(api + "/api/v1/health/ready")[0] == 200)
        check("queue_after_recovery", probe("queue")["real_queue_roundtrip"])
        # Frontend itself remains live when the API is offline.
        compose("stop", "api")
        try:
            check("frontend_up_when_api_down", http(web + "/health/live")[0] == 200)
            check("frontend_reports_api_down", http(web + "/api/health")[0] == 503)
        finally:
            compose("start", "api")
            wait_ready()
        check("application_non_root", compose("exec", "-T", "api", "id", "-u").strip() == "10001")
        logs = compose("logs", "--no-color", "--tail", "300")
        check("no_local_secrets_in_logs", not any(value in logs for value in values))
    except Exception as error:
        checks.append(dict(name=type(error).__name__, status="FAIL", detail=safe(str(error))))
    finally:
        try:
            compose("start", "postgres", "redis", "api")
            wait_ready()
            probe("clean", token)
        except Exception:
            checks.append(
                dict(name="cleanup", status="FAIL", detail="Restore stack using documented commands")
            )
        result = dict(
            started_at_utc=started,
            scope="A01 real CPU infrastructure; not model/platform/release acceptance",
            passed=sum(c["status"] == "PASS" for c in checks),
            failed=sum(c["status"] == "FAIL" for c in checks),
            skipped=0,
            checks=checks,
            commands=records,
        )
        (evidence / "acceptance.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({k: v for k, v in result.items() if k != "commands"}, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
