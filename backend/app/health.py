import logging

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import text

from app.config import Settings, read_secret
from app.database import SCHEMA_REVISION, get_engine

logger = logging.getLogger(__name__)


def check_dependencies() -> dict[str, bool]:
    result = {"database": False, "redis": False}
    try:
        with get_engine().connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            count = connection.execute(text("SELECT count(*) FROM installation")).scalar_one()
            result["database"] = revision == SCHEMA_REVISION and count == 1
    except Exception:
        logger.warning('{"event":"dependency_unavailable","dependency":"database"}')
    try:
        settings = Settings()
        with Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=read_secret(settings.redis_password_file),
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        ) as client:
            result["redis"] = bool(client.ping())
    except Exception:
        logger.warning('{"event":"dependency_unavailable","dependency":"redis"}')
    return result
