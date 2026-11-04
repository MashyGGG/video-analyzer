"""Capture A02 quality gates into a fresh evidence directory."""
import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true")
    args = parser.parse_args()
    output = ROOT / "evidence/A02/checks" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=False)
    results = []
    checks = [
        ("ruff", "backend", ["uv", "run", "--frozen", "ruff", "check", "app", "migrations", "tests", "../scripts/acceptance_a02.py", "../scripts/verify_a02_checks.py", "../scripts/verify_a01_e2e.py"]),
        ("mypy", "backend", ["uv", "run", "--frozen", "mypy"]),
        ("pytest", "backend", ["uv", "run", "--frozen", "pytest", "-q"]),
    ]
    if not args.backend_only:
        checks.append(("frontend", "frontend", ["npm.cmd" if os.name == "nt" else "npm", "run", "verify"]))
    for name, directory, argv in checks:
        result = subprocess.run(argv, cwd=ROOT / directory, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        text = result.stdout + "\n" + result.stderr
        text = text.replace(str(ROOT), "<repo>").replace(str(Path.home()), "<home>")
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        (output / f"{name}.log").write_text(text, encoding="utf-8")
        counts = None
        if name == "pytest":
            counts = {key: int(match.group(1)) if (match := re.search(rf"(\d+) {key}", text)) else 0 for key in ("passed", "failed", "skipped")}
        if name == "frontend" and (ROOT / ".artifacts/playwright/functional.json").exists():
            data = json.loads((ROOT / ".artifacts/playwright/functional.json").read_text(encoding="utf-8"))
            counts = data["stats"]
            (output / "playwright.json").write_text(json.dumps(data, ensure_ascii=False, indent=2).replace(str(ROOT).replace("\\", "\\\\"), "<repo>"), encoding="utf-8")
        results.append({"name": name, "command": argv, "exit_code": result.returncode, "counts": counts})
        (output / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"{name}: exit {result.returncode}; {counts}", flush=True)
        if result.returncode:
            print(str(output))
            return 1
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
