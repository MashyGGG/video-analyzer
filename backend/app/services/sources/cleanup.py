"""Administrator-only stale staging cleanup, after task hard deadlines have elapsed."""

import shutil
import time

import sqlalchemy as sa

from app.acquisition import assets, directory, update
from app.database import get_engine


def cleanup() -> int:
    with get_engine().connect() as connection:
        rows = list(
            connection.execute(
                sa.select(assets.c.id).where(
                    assets.c.created < int(time.time()) - 3600,
                    assets.c.status != "SUCCEEDED",
                )
            ).scalars()
        )
    for identifier in rows:
        update(identifier, status="FAILED_PERMANENT", code="SOURCE_TIMEOUT")
        shutil.rmtree(directory(identifier), ignore_errors=True)
        shutil.rmtree(directory(identifier, "original"), ignore_errors=True)
    return len(rows)


if __name__ == "__main__":
    print(f"stale_acquisitions_cleaned={cleanup()}")
