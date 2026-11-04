"""Internal A01 acceptance commands; no public write API, models or media."""

import argparse
import json
import re
import subprocess
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from redis import Redis
from sqlalchemy import text

from app.config import Settings, read_secret
from app.database import get_engine


def connection(database: str) -> psycopg.Connection:
    settings = Settings()
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=read_secret(settings.postgres_password_file),
        dbname=database,
        autocommit=True,
        connect_timeout=3,
    )


def marker(action: str, token: str) -> dict[str, str | bool]:
    if not re.fullmatch("[0-9a-f]{32}", token):
        raise ValueError("Invalid probe marker")
    settings = Settings()
    key = f"a01:probe:{token}"
    path = Path("/data") / key.replace(":", "_")
    client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=read_secret(settings.redis_password_file),
        socket_timeout=3,
    )
    with get_engine().connect() as db:
        installation = str(db.execute(text("SELECT id FROM installation")).scalar_one())
    try:
        if action == "write":
            client.set(key, token, ex=3600)
            path.write_text(token)
            client.execute_command("SAVE")
        if action == "clean":
            client.delete(key)
            path.unlink(missing_ok=True)
            return {"cleaned": True}
        return {
            "installation": installation,
            "redis_persisted": client.get(key) == token.encode(),
            "file_persisted": path.read_text() == token,
        }
    finally:
        client.close()


def migrate_replay() -> dict[str, bool]:
    name = "a01_accept_" + uuid.uuid4().hex
    with connection("postgres") as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            import os

            env = {**os.environ, "VA_POSTGRES_DB": name}

            def migrate(target: str, direction: str = "upgrade") -> None:
                result = subprocess.run(
                    ["alembic", direction, target], env=env, capture_output=True, timeout=30, check=False
                )
                if result.returncode:
                    raise RuntimeError("Migration replay failed (credential-free error)")

            migrate("head")
            with connection(name) as db:
                row = db.execute("SELECT id FROM installation").fetchone()
                assert row is not None
                first = row[0]
            migrate("head")
            with connection(name) as db:
                row = db.execute("SELECT id FROM installation").fetchone()
                assert row is not None and row[0] == first
            migrate("base", "downgrade")
            with connection(name) as db:
                row = db.execute("SELECT to_regclass('installation')").fetchone()
                assert row is not None and row[0] is None
            migrate("head")
            with connection(name) as db:
                row = db.execute("SELECT count(*) FROM installation").fetchone()
                assert row is not None and row[0] == 1
            return {"empty_upgrade": True, "idempotent_upgrade": True, "downgrade": True, "reupgrade": True}
        finally:
            # Only this generated scratch database is ever dropped.
            if not re.fullmatch(r"a01_accept_[0-9a-f]{32}", name):
                raise ValueError("Refusing database cleanup")
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["queue", "write", "read", "clean", "migrations"])
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    output: object
    if args.action == "queue":
        from app.tasks.worker import celery_app

        token = uuid.uuid4().hex
        result = celery_app.send_task("infrastructure.ping", args=[token])
        try:
            payload = result.get(timeout=15)
            assert payload["token"] == token and payload["service"] == "worker"
            output = {"real_queue_roundtrip": True}
        finally:
            result.forget()
    elif args.action == "migrations":
        output = migrate_replay()
    else:
        output = marker(args.action, args.token)
    print(json.dumps(output))


if __name__ == "__main__":
    main()
