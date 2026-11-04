import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


def read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise ValueError("Missing local secret; run scripts/init_local.py") from None
    if not re.fullmatch(r"[0-9a-f]{64}", value) or len(set(value)) < 8:
        raise ValueError("Invalid local secret; use the local initializer")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VA_", extra="ignore")
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "video_analyzer"
    postgres_user: str = "video_analyzer"
    postgres_password_file: Path = Path("/run/secrets/postgres_password")
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password_file: Path = Path("/run/secrets/redis_password")

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=read_secret(self.postgres_password_file),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    def redis_url(self, database: int) -> str:
        # Secret is constrained to hex; no user supplied URL or query parameters.
        return (
            f"redis://:{read_secret(self.redis_password_file)}@{self.redis_host}:{self.redis_port}/{database}"
        )
