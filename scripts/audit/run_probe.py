"""Run one reviewed audit command without a shell; save sanitized reproducible evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def sanitize(value: str, root: Path) -> str:
    for prefix in (str(root).replace("\\", "\\\\"), str(root), str(root).replace("\\", "/")):
        value = re.sub(re.escape(prefix), "<workspace>", value, flags=re.I)
    user = os.environ.get("USERPROFILE", "")
    if user:
        for prefix in (user.replace("\\", "\\\\"), user, user.replace("\\", "/")):
            value = re.sub(re.escape(prefix), "<user>", value, flags=re.I)
    value = re.sub(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@", r"\1<redacted>@", value)
    value = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "<redacted-key>", value)
    return value


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    for key in list(env):
        if re.search(r"(?i)(api.?key|token|secret|password|cookie|credential)", key):
            env.pop(key, None)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", CI="1", NEXT_TELEMETRY_DISABLED="1")
    started = datetime.now(timezone.utc).isoformat()
    before = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(command, cwd=args.cwd, env=env, shell=False, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
        try:
            stdout, stderr = proc.communicate(timeout=args.timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code = 124
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=15)
            else:
                proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                stdout, stderr = exc.stdout or b"", exc.stderr or b""
                proc.stdout.close()
                proc.stderr.close()
    except FileNotFoundError as exc:
        code, stdout, stderr = 127, "", str(exc)
    stdout = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout
    stderr = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    result = dict(started_at_utc=started, duration_seconds=round(time.monotonic() - before, 3),
                  cwd=sanitize(str(Path(args.cwd).resolve()), root),
                  argv=[sanitize(s, root) for s in command], exit_code=code, timed_out=timed_out,
                  credentials_removed=True, stdout=sanitize(stdout, root), stderr=sanitize(stderr, root))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    display = {**result, "stdout": result["stdout"][-2500:], "stderr": result["stderr"][-2500:],
               "evidence_file": str(output).replace("\\", "/")}
    print(json.dumps(display, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
