from alembic import context
from sqlalchemy import create_engine, pool

from app.config import Settings


def run_migrations() -> None:
    # Never inject a password into Config or logs, and never auto-create tables.
    engine = create_engine(
        Settings().database_url, poolclass=pool.NullPool, connect_args={"connect_timeout": 5}
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
