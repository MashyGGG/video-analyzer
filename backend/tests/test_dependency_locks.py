import ast
import json
import re
import tomllib
from pathlib import Path

from app.database import SCHEMA_REVISION

ROOT = Path(__file__).resolve().parents[2]


def test_python_direct_versions_match_complete_lock_and_runtime_export():
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text())
    versions = {p["name"]: p.get("version") for p in lock["package"]}
    exported = (ROOT / "backend/requirements.lock").read_text()
    for declaration in project["project"]["dependencies"] + project["dependency-groups"]["dev"]:
        name, version = declaration.split("==")
        name = re.sub(r"\[.*\]", "", name).lower()
        assert versions[name] == version
    for declaration in project["project"]["dependencies"]:
        name, version = declaration.split("==")
        name = re.sub(r"\[.*\]", "", name).lower()
        assert f"{name}=={version}" in exported
    assert "--hash=sha256:" in exported
    assert "videofetch" not in versions and "openai" not in versions


def test_frontend_exact_versions_match_lock():
    project = json.loads((ROOT / "frontend/package.json").read_text())
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    for group in ("dependencies", "devDependencies"):
        for name, version in project[group].items():
            assert re.fullmatch(r"\d+\.\d+\.\d+", version)
            assert lock["packages"]["node_modules/" + name]["version"] == version
            assert lock["packages"][""]["" + group][name] == version


def test_readiness_schema_revision_matches_only_migration_head():
    files = list((ROOT / "backend/migrations/versions").glob("*.py"))
    assert len(files) == 2
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(next(p for p in files if p.name.startswith("0002")).read_text()).body
        if isinstance(node, ast.Assign)
    }
    assert assignments["revision"] == SCHEMA_REVISION
    assert assignments["down_revision"] == "0001_installation"
