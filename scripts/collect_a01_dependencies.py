"""Record locked package declarations/licenses; preserve local installed notices, no weights."""

import csv
import hashlib
import json
import re
import shutil
import tomllib
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/A01"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    distributions = {re.sub("[-_.]+", "-", d.metadata["Name"]).lower(): d for d in metadata.distributions()}
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text())
    notices = []
    for package in lock["package"]:
        if "version" not in package or package["name"] == "video-analyzer-backend":
            continue
        name, version = package["name"], package["version"]
        dist = distributions.get(name)
        license_name, evidence = "UNKNOWN", "not installed on this platform"
        if dist is not None and dist.version == version:
            meta = dist.metadata
            license_name = (
                meta.get("License-Expression")
                or meta.get("License")
                or "; ".join(
                    v.removeprefix("License :: ")
                    for v in meta.get_all("Classifier", [])
                    if v.startswith("License :: ")
                )
                or "UNKNOWN"
            )
            # Avoid embedding full license bodies in a CSV cell; saved below verbatim.
            if len(license_name) > 300:
                license_name = "See installed license notices"
            evidence = f"installed METADATA {name}=={version}"
            for file in dist.files or []:
                if ".dist-info/" not in str(file).replace("\\", "/"):
                    continue
                if not any(k in str(file).lower() for k in ("license", "copying", "notice")):
                    continue
                source = Path(dist.locate_file(file))
                if source.is_file():
                    relative = Path(str(file).replace("\\", "/"))
                    target = OUT / "licenses" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    notices.append(
                        {
                            "file": target.relative_to(ROOT).as_posix(),
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        }
                    )
        rows.append(
            dict(
                ecosystem="pypi",
                name=name,
                version=version,
                license=license_name,
                evidence=evidence,
                scope="uv.lock, runtime + dev + conditional platform alternatives",
            )
        )
    npm = json.loads((ROOT / "frontend/package-lock.json").read_text())
    for path, package in npm["packages"].items():
        if not path:
            continue
        rows.append(
            dict(
                ecosystem="npm",
                name=package.get("name") or path.split("node_modules/")[-1],
                version=package["version"],
                license=package.get("license", "UNKNOWN"),
                evidence=f"frontend/package-lock.json:{path}",
                scope="runtime + dev + optional platform alternatives",
            )
        )
    # Official source tag proves the selected Redis server branch is BSD; not the Python redis client license.
    sources = [
        ("redis-7.2.13", "https://raw.githubusercontent.com/redis/redis/7.2.13/COPYING"),
        ("postgres-17.11", "https://raw.githubusercontent.com/postgres/postgres/REL_17_11/COPYRIGHT"),
    ]
    for name, url in sources:
        target = OUT / "licenses" / (name + ".txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = urllib.request.urlopen(url, timeout=25).read()
        target.write_bytes(data)
        notices.append(
            dict(
                file=target.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(data).hexdigest(), source=url
            )
        )
        rows.append(
            dict(
                ecosystem="server",
                name=name,
                version=name.split("-", 1)[1],
                license="BSD-3-Clause" if name.startswith("redis") else "PostgreSQL",
                evidence=target.relative_to(ROOT).as_posix(),
                scope="server source; not a complete container OS SBOM",
            )
        )
    destination = ROOT / "docs/audit/A01-licenses.csv"
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "license-notices.json").write_text(
        json.dumps(notices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "entries": len(rows),
                "unknown": [r["name"] for r in rows if r["license"] == "UNKNOWN"],
                "notice_files": len(notices),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
