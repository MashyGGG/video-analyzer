"""Validate A00 provenance/deliverable integrity, not product or model acceptance."""
import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence/A00"
UPSTREAM = ROOT / ".audit-cache/parse_video"
EXPECTED_SHA = "adc13afb47a112f0def0435231e691a5307e5b49"
checks = []


def check(name, condition, details=""):
    checks.append(dict(name=name, status="PASS" if condition else "FAIL", details=details))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


documents = [ROOT / "docs/audit/baseline.md", ROOT / "docs/audit/licenses.csv", ROOT / "docs/decisions/ADR-001-foundation.md"]
check("three_requested_deliverables", all(p.is_file() and p.stat().st_size for p in documents))
check("plan_and_reproduction_entrypoints", all((ROOT / p).is_file() for p in ("docs/audit/A00-plan.md", "scripts/audit/reproduce.ps1", "scripts/audit/run_probe.py")))
inventory = read_json(EVIDENCE / "static-inventory.json")
sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=UPSTREAM, text=True).strip()
check("pinned_upstream_revision", sha == EXPECTED_SHA == inventory["commit"])
state = subprocess.check_output(["git", "status", "--porcelain"], cwd=UPSTREAM, text=True).strip()
check("upstream_worktree_unchanged", state == "", state)
hash_errors = [r["path"] for r in inventory["files"] if hashlib.sha256((UPSTREAM / r["path"]).read_bytes()).hexdigest() != r["sha256"]]
check("tracked_source_hashes", not hash_errors, f"{len(inventory['files'])} files; mismatches: {hash_errors}")
rows = list(csv.DictReader(documents[1].open(encoding="utf-8-sig", newline="")))
check("license_csv_parses_and_has_provenance", len(rows) == 563 and all(r["component"] and r["license"] and r["evidence"] and r["status"] for r in rows), f"{len(rows)} entries")
check("all_direct_backend_declarations_listed", sum(r["kind"].startswith("upstream-backend-") for r in rows) == len(inventory["backend_dependencies"]) + len(inventory["backend_dev_dependencies"]))
check("frontend_lock_entries_covered", sum(r["kind"].startswith("frontend-") for r in rows) == inventory["frontend_lock"]["package_count"] - 1)
sources = read_json(EVIDENCE / "sources/index.json")
check("candidate_revisions_are_exact", len(sources) == 15 and all(re.fullmatch(r"[0-9a-f]{40}", r.get("revision", "")) and r["status"] == "FETCHED" for r in sources))
model_rows = [r for r in sources if r["kind"] == "model"]
check("models_not_misrepresented_as_tested", len(model_rows) == 4 and all(r["weights_downloaded"] is False and r["inference_tested"] is False for r in model_rows))
license_errors = []
for src in sources:
    for file in src.get("license_files", []) + src.get("files", []):
        if hashlib.sha256((ROOT / file["file"]).read_bytes()).hexdigest() != file["sha256"]:
            license_errors.append(file["file"])
check("public_license_and_card_hashes", not license_errors, str(license_errors))
reference_errors = []
for path in (documents[0], documents[2], ROOT / "docs/audit/A00-plan.md"):
    text = path.read_text(encoding="utf-8")
    for relative, line in re.findall(r"up:([A-Za-z0-9_./-]+):(\d+)", text):
        source = UPSTREAM / relative
        if not source.is_file() or int(line) > len(source.read_text(encoding="utf-8-sig").splitlines()):
            reference_errors.append(f"{relative}:{line}")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if target.startswith(("https://", "http://", "#")):
            continue
        if not (path.parent / target.split("#")[0]).resolve().exists():
            reference_errors.append(target)
check("source_line_and_local_link_targets_exist", not reference_errors, str(reference_errors))
url_result = read_json(EVIDENCE / "url-validator.json")
check("negative_probe_counts_preserved", (url_result["passed"], url_result["failed"], url_result["skipped"]) == (3, 4, 0) and len(url_result["results"]) == 7)
pytest_result = read_json(EVIDENCE / "pytest-original.json")
check("original_pytest_blocker_preserved", pytest_result["exit_code"] == 4 and "No module named 'httpx'" in pytest_result["stderr"])
expected_codes = {"frontend-build.json": 0, "frontend-typecheck.json": 0, "frontend-lint.json": 1, "backend-install.json": 1, "backend-pip-install.json": 124, "compose-up.json": 124, "compose-config-prepared.json": 0}
check("reported_command_exit_codes_match", all(read_json(EVIDENCE / name)["exit_code"] == code for name, code in expected_codes.items()))
artifact_files = [p for base in (ROOT / "docs/audit", ROOT / "docs/decisions", ROOT / "scripts/audit", EVIDENCE) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
forbidden = [str(p.relative_to(ROOT)) for p in artifact_files if p.name == ".env" or p.suffix.lower() in (".mp4", ".mov", ".pkl", ".pt", ".safetensors", ".bin", ".pem", ".key")]
check("no_private_media_weights_or_secret_files", not forbidden, str(forbidden))
secrets = []
for line in (UPSTREAM / ".env").read_text(encoding="utf-8").splitlines():
    key, _, value = line.partition("=")
    if ("PASSWORD" in key or key == "SECRET_KEY") and len(value) > 16:
        secrets.append(value)
leaks = [str(p.relative_to(ROOT)) for p in artifact_files if any(secret in p.read_text(encoding="utf-8-sig", errors="replace") for secret in secrets)]
check("temporary_local_credentials_not_in_deliverables", not leaks, str(leaks))
syntax_errors = []
for script in (ROOT / "scripts/audit").glob("*.py"):
    try:
        ast.parse(script.read_text(encoding="utf-8"))
    except SyntaxError:
        syntax_errors.append(script.name)
check("audit_python_syntax", not syntax_errors, str(syntax_errors))
baseline = documents[0].read_text(encoding="utf-8")
adr = documents[2].read_text(encoding="utf-8")
check("unmet_gates_and_unapproved_decision_explicit", "结论：BLOCKED" in baseline and "Proposed / 待人类审阅" in adr and "不是抓包结果" in baseline)
result = dict(scope="A00 deliverable integrity only; not upstream, model, platform, or product acceptance", checks=checks,
              passed=sum(c["status"] == "PASS" for c in checks), failed=sum(c["status"] == "FAIL" for c in checks), skipped=0)
(EVIDENCE / "deliverable-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(1 if result["failed"] else 0)
