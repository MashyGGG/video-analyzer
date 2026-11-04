"""Inspect official PyPI metadata for declared exact versions; never silently resolve open ranges."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

root = Path(__file__).resolve().parents[2]
inventory = json.loads((root / "evidence/A00/static-inventory.json").read_text(encoding="utf-8"))


def inspect(requirement):
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^,;]+)", requirement)
    result = {"requirement": requirement, "scope": "upstream-direct-backend-declaration"}
    if not match:
        result.update(status="UNRESOLVED_RANGE_OR_INVALID", license="UNKNOWN")
        return result
    name, version = match.groups()
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    result.update(name=name, version=version, url=url)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            info = json.load(response)["info"]
        result.update(status="METADATA_FETCHED", license_expression=info.get("license_expression"),
                      license_field=info.get("license"),
                      license_classifiers=[x for x in info.get("classifiers", []) if x.startswith("License ::")],
                      requires_dist=info.get("requires_dist"), project_urls=info.get("project_urls"))
    except Exception as exc:
        result.update(status="BLOCKED", license="UNKNOWN", error=f"{type(exc).__name__}: {exc}")
    return result


with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(inspect, inventory["backend_dependencies"] + inventory["backend_dev_dependencies"]))
(root / "evidence/A00/backend-dependency-metadata.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for r in results:
    print(r["requirement"], r["status"], r.get("license_expression") or "; ".join(r.get("license_classifiers", [])) or str(r.get("license_field", "UNKNOWN"))[:70])
