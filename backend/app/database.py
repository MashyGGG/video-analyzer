from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.config import Settings

SCHEMA_REVISION = "0002_acquisition"


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        Settings().database_url,
        pool_size=2,
        max_overflow=1,
        pool_pre_ping=True,
        pool_timeout=2,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"},
    )
