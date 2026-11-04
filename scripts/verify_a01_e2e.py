"""Run browser/CPU acceptance on an isolated Compose project; preserve historical evidence."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from audit.run_probe import sanitize

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "video-analyzer-e2e"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir or ROOT / "evidence/A01-e2e/runs" / stamp
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    for key in list(env):
        if any(word in key.upper() for word in ("API_KEY", "TOKEN", "PASSWORD", "COOKIE", "SECRET")):
            env.pop(key)
    env.update(
        VA_WEB_PORT="17810",
        VA_API_PORT="17811",
        COMPOSE_PROJECT_NAME=PROJECT,
        VA_E2E_INFRA="1",
        NEXT_TELEMETRY_DISABLED="1",
        PYTHONUTF8="1",
    )
    secrets = [(ROOT / ".secrets" / n).read_text().strip() for n in ("postgres_password", "redis_password")]
    commands = []

    def clean(value: str) -> str:
        for secret in secrets:
            value = value.replace(secret, "<redacted>")
        return sanitize(value, ROOT)

    def run(argv: list[str], *, cwd: Path = ROOT, timeout: int = 180, check: bool = True) -> str:
        started = time.monotonic()
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15
                )
            else:
                os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate(timeout=15)
            code = 124
        record = dict(
            argv=[clean(value) for value in argv],
            cwd=clean(str(cwd)),
            exit_code=code,
            timed_out=timed_out,
            seconds=round(time.monotonic() - started, 3),
            stdout=clean(stdout),
            stderr=clean(stderr),
        )
        commands.append(record)
        (output / "commands.json").write_text(
            json.dumps(commands, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{code}: " + clean(" ".join(argv)), flush=True)
        if check and code:
            raise RuntimeError("Command failed: " + " ".join(argv))
        return stdout

    def compose(*argv: str, **kwargs) -> str:
        return run(["docker", "compose", "-p", PROJECT, *argv], **kwargs)

    owned = False
    result = dict(
        scope="A01 CPU regression and A02 generated-media acquisition/browser/isolation; no model or platform-success claim",
        compose_project=PROJECT,
        started_at_utc=datetime.now(UTC).isoformat(),
        status="FAIL",
    )
    try:
        if compose("ps", "--all", "--format", "json").strip():
            raise RuntimeError(
                "Isolated test project already has containers; refusing to interrupt an existing run"
            )
        owned = True
        compose("--progress", "plain", "build", "api", "frontend", timeout=900)
        compose("up", "-d", "--wait", "--wait-timeout", "150", timeout=240)
        run(
            [
                sys.executable,
                "scripts/acceptance_a01.py",
                "--compose-project",
                PROJECT,
                "--api-port",
                "17811",
                "--web-port",
                "17810",
                "--output-dir",
                str(output / "infrastructure"),
            ],
            timeout=420,
        )
        npm = "npm.cmd" if os.name == "nt" else "npm"
        run([sys.executable, "scripts/acceptance_a02.py", "--compose-project", PROJECT,
             "--api-port", "17811", "--output-dir", str(output / "acquisition")], timeout=420)
        report = ROOT / ".artifacts/playwright/infra.json"
        report.unlink(missing_ok=True)
        run([npm, "run", "test:e2e:infra"], cwd=ROOT / "frontend", timeout=420, check=False)
        browser_exit_code = commands[-1]['exit_code']
        data = json.loads(clean(report.read_text(encoding="utf-8")))
        (output / "playwright.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        stats = data["stats"]
        if browser_exit_code or stats["unexpected"] or stats["flaky"] or stats["skipped"] or not stats["expected"]:
            raise RuntimeError("Browser acceptance contains failures, flaky/skipped tests or no tests")
        result["browser_counts"] = {key: stats[key] for key in ("expected", "unexpected", "flaky", "skipped")}
        compose("up", "-d", "--wait", "--wait-timeout", "90", timeout=180)
        run(
            [
                sys.executable,
                "scripts/doctor.py",
                "--services",
                "--compose-project",
                PROJECT,
                "--api-port",
                "17811",
                "--web-port",
                "17810",
            ],
            timeout=90,
        )
        result["status"] = "PASS"
    except Exception as error:
        result["error"] = clean(f"{type(error).__name__}: {error}")
    finally:
        if owned:
            try:
                # Capture final health/logs and stop only containers created by this run; preserve volumes.
                compose("up", "-d", "--wait", "--wait-timeout", "90", timeout=180)
                compose("ps", "--all", "--format", "json")
                logs = compose("logs", "--no-color", "--tail", "100")
                (output / "services.log").write_text(clean(logs), encoding="utf-8")
            except Exception as error:
                result["cleanup_error"] = clean(str(error))
                result["status"] = "FAIL"
            finally:
                try:
                    compose("down", "--remove-orphans", timeout=120)
                except Exception as error:
                    result["cleanup_error"] = clean(str(error))
                    result["status"] = "FAIL"
        (output / "summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
