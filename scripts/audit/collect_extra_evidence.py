"""Read public source/package license details; no package code is executed."""
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evidence/A00"
SOURCES = OUT / "sources"


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "video-analyzer-A00-audit"}), timeout=40) as response:
        return response.read()


def repo_metadata(name):
    return json.loads((SOURCES / name.replace("/", "__") / "metadata.json").read_text(encoding="utf-8"))


result = {}
rea = repo_metadata("JuneYaooo/rea-video")
url = f"https://api.github.com/repos/JuneYaooo/rea-video/git/trees/{rea['revision']}?recursive=1"
tree = json.loads(fetch(url))
result["rea_license_search"] = dict(url=url, truncated=tree.get("truncated"),
    matches=[e["path"] for e in tree["tree"] if re.search(r"(^|/)(license|licence|notice|copying)", e["path"], re.I)])
for name in ("pyproject.toml", "README.md"):
    url = f"https://raw.githubusercontent.com/JuneYaooo/rea-video/{rea['revision']}/{name}"
    text = fetch(url).decode("utf-8")
    result[f"rea_{name}"] = dict(url=url, sha256=hashlib.sha256(text.encode()).hexdigest(),
        licensing_lines=[dict(line=i, text=line) for i, line in enumerate(text.splitlines(), 1) if re.search(r"license|licence|copyright|许可|授权", line, re.I)])

sdk = repo_metadata("volcengine/volcengine-python-sdk")
result["sdk_endpoints"] = []
for name in ("volcenginesdkcore/configuration.py", "volcenginesdkcore/endpoint/providers/default_provider.py", "volcenginesdkcore/endpoint/providers/standard_provider.py", "volcenginesdkspeechsaasprod/api/speech_saas_prod_api.py"):
    url = f"https://raw.githubusercontent.com/volcengine/volcengine-python-sdk/{sdk['revision']}/{name}"
    entry = dict(url=url)
    try:
        text = fetch(url).decode("utf-8")
        entry.update(sha256=hashlib.sha256(text.encode()).hexdigest(),
                     lines=[dict(line=i, text=line.strip()) for i, line in enumerate(text.splitlines(), 1) if re.search(r"volcengineapi|host =|ListSpeakers|list_speakers|endpoint|service_name|service=|resource_path|http_method|api_version", line)])
    except Exception as exc:
        entry["error"] = str(exc)
    result["sdk_endpoints"].append(entry)

result["package_licenses"] = []
for package, version in (("videofetch", "0.9.1"), ("responses-validator", "0.3.0")):
    info = json.loads(fetch(f"https://pypi.org/pypi/{package}/{version}/json"))
    wheels = [u for u in info["urls"] if u["filename"].endswith(".whl")]
    entry = dict(package=package, version=version, metadata_license=info["info"].get("license"))
    if wheels:
        wheel = wheels[0]
        raw = fetch(wheel["url"])
        digest = hashlib.sha256(raw).hexdigest()
        if digest != wheel["digests"]["sha256"]:
            raise ValueError("Package digest mismatch")
        entry.update(url=wheel["url"], sha256=digest, files=[])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entry["top_level_modules"] = sorted({n.split("/")[0] for n in archive.namelist() if "/" in n and ".dist-info" not in n.split("/")[0]})
            for name in archive.namelist():
                if name.endswith("/") or not re.search(r"(^|/)(license|licence|notice|copying)", name, re.I):
                    continue
                data = archive.read(name)
                target = SOURCES / f"pypi__{package}__{version}" / Path(name).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                entry["files"].append(dict(package_path=name, file=str(target.relative_to(ROOT)).replace("\\", "/"), sha256=hashlib.sha256(data).hexdigest()))
    result["package_licenses"].append(entry)
result["container_source_licenses"] = []
for repo, ref, name in (("redis/redis", "7.4.10", "LICENSE.txt"), ("postgres/postgres", "REL_15_19", "COPYRIGHT")):
    entry = dict(repository=repo, ref=ref)
    try:
        commit = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/{ref}"))["sha"]
        url = f"https://raw.githubusercontent.com/{repo}/{commit}/{name}"
        raw = fetch(url)
        target = SOURCES / (repo.replace("/", "__") + "__" + ref) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        entry.update(revision=commit, url=url, file=str(target.relative_to(ROOT)).replace("\\", "/"), sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        entry["error"] = str(exc)
    result["container_source_licenses"].append(entry)
(OUT / "extra-source-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
