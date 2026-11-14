"""Record license metadata and packaged notices from the built Linux image."""

import json
import subprocess
import sys
from pathlib import Path

IMAGE = "video-analyzer-backend:0.1.0"
PROGRAM = r'''
import hashlib, importlib.metadata as m, json
names = ["scenedetect", "opencv-python-headless", "numpy", "click", "platformdirs", "tqdm"]
result = {}
for name in names:
    dist = m.distribution(name)
    entries = []
    for item in dist.files or []:
        path = str(item)
        if ".dist-info/" not in path or not any(x in path.upper() for x in ("LICENSE", "LICENCE", "NOTICE")):
            continue
        source = dist.locate_file(item)
        if source.is_file():
            data = source.read_bytes()
            entries.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                            "text": data.decode("utf-8", "replace")})
    meta = dist.metadata
    result[name] = {"version": dist.version, "license_expression": meta.get("License-Expression"),
                    "license_declaration_first_line": (meta.get("License") or "").splitlines()[:1],
                    "files": entries}
print(json.dumps(result, ensure_ascii=False))
'''


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/collect_a03_licenses.py <new-output-file>")
        return 2
    target = Path(sys.argv[1])
    if target.exists():
        raise FileExistsError("Refusing to overwrite evidence")
    result = subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "python",
                             IMAGE, "-c", PROGRAM], check=True, capture_output=True, timeout=60)
    data = json.loads(result.stdout)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(data)} package metadata and license records in {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
