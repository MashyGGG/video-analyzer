"""Static inventory only: never import upstream modules or deserialize model artifacts."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".audit-cache/parse_video"
OUT = ROOT / "evidence/A00"


def main():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=SOURCE).decode().split("\0")
    tracked = [p for p in tracked if p]
    data = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE).decode().strip(),
            "files": [], "imports": {}, "network_calls": [], "literal_urls": [],
            "tables": [], "migrations": [], "test_functions": [], "routes": [], "syntax_errors": []}
    imports = {}
    for relative in tracked:
        path = SOURCE / relative
        raw = path.read_bytes()
        data["files"].append(dict(path=relative, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        if path.suffix != ".py":
            continue
        text = raw.decode("utf-8-sig")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            data["syntax_errors"].append(dict(path=relative, line=exc.lineno, message=exc.msg))
            continue
        for node in ast.walk(tree):
            loc = dict(path=relative, line=getattr(node, "lineno", 0))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [n.name.split(".")[0] for n in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
                for name in names:
                    if name:
                        imports.setdefault(name, set()).add(relative)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for url in re.findall(r"(?:https?|wss?)://[^\s\"'<>`]+", node.value):
                    data["literal_urls"].append(dict(**loc, url=url))
            if isinstance(node, ast.Call):
                func = ast.unparse(node.func)
                if (re.search(r"(?:^|\.)(?:requests|httpx|session|client|websocket|websockets|ydl|video_client|self\._client|self\._download_client)\.(get|post|put|delete|request|stream|connect|extract_info|parsefromurl|download)$", func)
                        or re.search(r"\.(invoke|ainvoke|list_speakers)$", func)
                        or func.endswith(("ChatOpenAI", "init_chat_model", "VideoClient", "YoutubeDL"))):
                    # Arguments may contain user content or secrets: retain target expression, never values.
                    data["network_calls"].append(dict(**loc, function=func,
                        first_argument=ast.unparse(node.args[0])[:180] if node.args and not isinstance(node.args[0], ast.Dict) else None))
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "__tablename__" in names and isinstance(node.value, ast.Constant):
                    data["tables"].append(dict(**loc, name=node.value.value))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    data["test_functions"].append(dict(**loc, name=node.name))
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in ("get", "post", "patch", "put", "delete"):
                        data["routes"].append(dict(**loc, method=decorator.func.attr.upper(),
                            path_fragment=ast.literal_eval(decorator.args[0]) if decorator.args else "", function=node.name))
        if "/alembic/versions/" in relative:
            values = {}
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    if isinstance(target, ast.Name) and target.id in ("revision", "down_revision"):
                        values[target.id] = ast.literal_eval(node.value)
            values.update(path=relative, downgrade_defined=any(isinstance(n, ast.FunctionDef) and n.name == "downgrade" for n in tree.body))
            data["migrations"].append(values)
    data["imports"] = {k: sorted(v) for k, v in sorted(imports.items()) if k not in sys.stdlib_module_names and k not in ("app", "tests", "")}
    config = tomllib.loads((SOURCE / "backend/pyproject.toml").read_text(encoding="utf-8"))
    data["backend_dependencies"] = config["project"]["dependencies"]
    data["backend_dev_dependencies"] = config["dependency-groups"]["dev"]
    data["frontend_package"] = json.loads((SOURCE / "frontend/package.json").read_text())
    lock = json.loads((SOURCE / "frontend/package-lock.json").read_text())
    data["frontend_lock"] = dict(lockfileVersion=lock["lockfileVersion"], package_count=len(lock["packages"]),
        direct_packages={name: lock["packages"].get(f"node_modules/{name}", {}) for section in ("dependencies", "devDependencies") for name in data["frontend_package"][section]})
    data["license_notice_paths"] = [p for p in tracked if re.search(r"(^|/)(license|licence|notice|copying)", p, re.I)]
    (OUT / "static-inventory.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: len(data[k]) for k in ("files", "tables", "migrations", "test_functions", "network_calls", "literal_urls", "syntax_errors")}, indent=2))


if __name__ == "__main__":
    main()
