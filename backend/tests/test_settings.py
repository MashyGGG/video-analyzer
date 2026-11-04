from pathlib import Path

import pytest
from app.config import Settings, read_secret


@pytest.mark.parametrize("value", ["", "password", "a" * 64, "ab" * 32 + "\nextra", "x" * 64])
def test_rejects_empty_weak_or_malformed_secret(tmp_path, value):
    file = tmp_path / "secret"
    file.write_text(value)
    with pytest.raises(ValueError, match="Invalid local secret"):
        read_secret(file)


def test_missing_secret_has_no_silent_default(tmp_path):
    with pytest.raises(ValueError, match="Missing local secret"):
        read_secret(tmp_path / "missing")


def test_secret_file_and_urls_do_not_depend_on_cloud_keys(tmp_path, monkeypatch):
    file = tmp_path / "secret"
    value = "0123456789abcdef" * 4
    file.write_text(value + "\n")
    settings = Settings(postgres_password_file=Path(file), redis_password_file=Path(file))
    assert settings.database_url.password == value
    assert value not in str(settings.database_url)
    assert settings.redis_url(0).endswith("@redis:6379/0")
    monkeypatch.setenv("LLM_API_KEY", "ignored-value")
    assert Settings(postgres_password_file=file).database_url == settings.database_url
