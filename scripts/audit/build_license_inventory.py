"""Build an evidence-scoped license inventory; UNKNOWN entries remain explicit release gates."""
import csv
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence/A00"
sources = json.loads((EVIDENCE / "sources/index.json").read_text(encoding="utf-8"))
metadata = json.loads((EVIDENCE / "backend-dependency-metadata.json").read_text(encoding="utf-8"))
extra = json.loads((EVIDENCE / "extra-source-evidence.json").read_text(encoding="utf-8"))
inventory = json.loads((EVIDENCE / "static-inventory.json").read_text(encoding="utf-8"))
rows = []
columns = ["component", "kind", "version_or_constraint", "source_revision", "license", "evidence",
           "status", "notice_and_use_conditions", "foundation_decision", "limitations"]


def add(**values):
    rows.append({key: values.get(key, "") for key in columns})


source_license = {"XztCloud/parse_video": "MIT", "JuneYaooo/rea-video": "MIT (pyproject declaration only)",
    "Evil0ctal/Douyin_TikTok_Download_API": "Apache-2.0", "yt-dlp/yt-dlp": "Unlicense",
    "FFmpeg/FFmpeg": "LGPL-2.1-or-later / GPL variants; depends on build", "Breakthrough/PySceneDetect": "BSD-3-Clause",
    "modelscope/FunASR": "MIT", "PaddlePaddle/PaddleOCR": "Apache-2.0", "QwenLM/Qwen3-VL": "Apache-2.0",
    "vllm-project/vllm": "Apache-2.0", "volcengine/volcengine-python-sdk": "Apache-2.0"}
for src in sources:
    name = src["repository"]
    if src["kind"] == "model":
        add(component=name, kind="candidate-model-weights", version_or_constraint="audit snapshot; not deployed",
            source_revision=src.get("revision", "UNKNOWN"), license=src.get("card_license") or "UNKNOWN",
            evidence="; ".join(x["url"] for x in src.get("files", []) if x["url"].endswith("README.md")),
            status="MODEL_CARD_DECLARATION", notice_and_use_conditions="Retain applicable Apache-2.0 terms/attribution when distributing; verify selected files separately",
            foundation_decision="Candidate for A04/A05 only", limitations="No weights downloaded, no local SHA-256, no inference; auxiliary VAD/punctuation/alignment weights not selected")
        continue
    evidence = "; ".join(x["url"] for x in src.get("license_files", []))
    if name == "JuneYaooo/rea-video":
        evidence = extra["rea_pyproject.toml"]["url"] + "#L11; evidence/A00/extra-source-evidence.json"
    conditions = "Preserve copyright, license text, and applicable NOTICE; review bundled third-party files separately"
    if source_license[name] == "Unlicense":
        conditions = "Source license only; released executables and bundled dependencies require separate review"
    add(component=name, kind="candidate-source" if name != "XztCloud/parse_video" else "audited-upstream-source",
        version_or_constraint="HEAD captured on 2026-11-04; not a validated deployment version", source_revision=src.get("revision", "UNKNOWN"),
        license=source_license[name], evidence=evidence, status="DECLARATION_WITHOUT_LICENSE_TEXT" if name == "JuneYaooo/rea-video" else "SOURCE_LICENSE_READ",
        notice_and_use_conditions=conditions, foundation_decision="Reference only; no source imported" if name in ("XztCloud/parse_video", "JuneYaooo/rea-video") else "Candidate; not adopted in A00",
        limitations="Source license does not cover external services, weights, media rights, or all transitive artifacts")

for dep in metadata:
    requirement = dep["requirement"]
    license_value = dep.get("license_expression") or dep.get("license_field")
    if not license_value or str(license_value).strip().lower() in ("none", "unknown"):
        license_value = "; ".join(dep.get("license_classifiers", [])) or "UNKNOWN"
    license_value = str(license_value)
    status = "PYPI_METADATA_ONLY" if license_value != "UNKNOWN" else "BLOCKED_UNRESOLVED"
    conditions = "Metadata declaration; preserve distribution license/NOTICE and verify wheel/sdist before adopting"
    decision = "Do not inherit dependency set; select only needed packages in A01"
    if dep.get("name") == "videofetch":
        status, decision = "RESTRICTED_NONCOMMERCIAL", "Exclude from new foundation; commercial scope not authorized by this license"
        conditions = "PolyForm Noncommercial permitted purposes only; preserve license and required notices"
    elif dep.get("name") in ("mutagen", "psycopg2-binary", "func_timeout"):
        conditions = "Copyleft/exception terms require artifact-specific redistribution review; root MIT is not a blanket grant"
    add(component=dep.get("name") or re.split(r"[<>=\[]", requirement)[0],
        kind="upstream-backend-dev-dependency" if requirement in inventory["backend_dev_dependencies"] else "upstream-backend-direct-dependency",
        version_or_constraint=requirement, license=license_value, evidence=dep.get("url", "backend/pyproject.toml @ " + inventory["commit"]),
        status=status, notice_and_use_conditions=conditions, foundation_decision=decision,
        limitations="Installation did not finish; metadata is not a resolved or fully verified binary SBOM")

lock = json.loads((ROOT / ".audit-cache/parse_video/frontend/package-lock.json").read_text())
direct = {f"node_modules/{name}" for section in ("dependencies", "devDependencies") for name in inventory["frontend_package"][section]}
for path, package in sorted(lock["packages"].items()):
    if not path:
        continue
    name = path.rsplit("node_modules/", 1)[-1]
    add(component=name, kind="frontend-direct-lock-entry" if path in direct else "frontend-transitive-lock-entry",
        version_or_constraint=package.get("version", "UNKNOWN"), source_revision=package.get("integrity", ""),
        license=package.get("license") or "UNKNOWN", evidence=f"frontend/package-lock.json @ {inventory['commit']} : packages[{path}]",
        status="LOCK_METADATA_ONLY" if package.get("license") else "BLOCKED_LICENSE_MISSING",
        notice_and_use_conditions="Retain package license, attribution and NOTICE as applicable; lock metadata is not full legal text",
        foundation_decision="Reference frontend only; no node_modules copied into product",
        limitations="May include platform-optional packages not installed on this host; verify selected build SBOM in A01/A09")

for entry in extra["container_source_licenses"]:
    redis = entry["repository"] == "redis/redis"
    add(component="Redis server" if redis else "PostgreSQL server", kind="observed-container-upstream-code",
        version_or_constraint="7.4.10 (redis:7-alpine)" if redis else "15.19 (postgres:15)", source_revision=entry.get("revision", "UNKNOWN"),
        license="RSALv2 OR SSPLv1" if redis else "PostgreSQL", evidence=entry.get("url", str(entry)),
        status="SOURCE_LICENSE_READ_FOR_OBSERVED_VERSION", notice_and_use_conditions="Choose and comply with server license; distinct from redis Python client MIT" if redis else "Preserve PostgreSQL copyright and license terms",
        foundation_decision="Pin version/digest and review license in A01", limitations="Container OS/dependencies not fully inventoried; version probes are not database/queue service acceptance")
for name in ("node:20", "python:3.12-slim", "FFmpeg binary and linked codecs"):
    add(component=name, kind="container-or-binary", version_or_constraint="floating upstream declaration",
        license="MIXED / BUILD_DEPENDENT", evidence="backend/Dockerfile; frontend/Dockerfile; evidence/A00/compose-up.json; evidence/A00/image-digests.json",
        status="BLOCKED_BINARY_SBOM", foundation_decision="Lock and collect binary license/configuration in A01",
        limitations="FFmpeg -L/-buildconf unavailable; aborted backend image build; source HEAD does not identify installed binaries")
for path in ("tts_model_zh_female_mizai_uranus_bigtts.pkl", "tts_model_zh_male_guanggaojieshuo_uranus_bigtts.pkl"):
    add(component=path, kind="upstream-regression-model-artifact", source_revision=inventory["commit"], license="PROVENANCE_UNVERIFIED",
        evidence="evidence/A00/static-inventory.json; backend/app/services/predict/predict_voice_duration.py:102",
        status="BLOCKED_PROVENANCE", foundation_decision="Exclude; do not deserialize or copy",
        limitations="Root MIT is present but no artifact-specific training provenance or weight notice; not an ASR/VLM checkpoint")
add(component="backend transitive dependency closure", kind="unresolved-transitive-set", license="UNKNOWN",
    evidence="evidence/A00/backend-pip-install.json", status="BLOCKED_INSTALL_TIMEOUT",
    foundation_decision="Do not claim a complete SBOM or release clearance", limitations="Original pip resolution/install timed out; SDK brings many split packages; no full transitive licensing review")
target = ROOT / "docs/audit/licenses.csv"
with target.open("w", newline="", encoding="utf-8-sig") as stream:
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
print(f"Wrote {len(rows)} evidence-scoped entries to docs/audit/licenses.csv")
