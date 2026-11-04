import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "init_local", Path(__file__).resolve().parents[2] / "scripts/init_local.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_init_is_idempotent_and_does_not_print_secrets(tmp_path, capsys):
    module.initialize(tmp_path)
    files = sorted((tmp_path / ".secrets").glob("*"))
    assert len(files) == 2
    first = {f.name: f.read_bytes() for f in files}
    module.initialize(tmp_path)
    assert first == {f.name: f.read_bytes() for f in files}
    assert all(v.decode().strip() not in capsys.readouterr().out for v in first.values())


@pytest.mark.parametrize("corruption", ["missing", "empty"])
def test_partial_or_broken_secrets_refuse_implicit_rotation(tmp_path, corruption):
    module.initialize(tmp_path)
    file = tmp_path / ".secrets/redis_password"
    if corruption == "missing":
        file.unlink()
    else:
        file.write_text("")
    before = (tmp_path / ".secrets/postgres_password").read_bytes()
    with pytest.raises(ValueError):
        module.initialize(tmp_path)
    assert (tmp_path / ".secrets/postgres_password").read_bytes() == before
