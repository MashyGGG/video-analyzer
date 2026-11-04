"""A02 persisted acquisition contract. Owner is an unguessable session capability."""

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.database import get_engine
from app.services.sources.adapters import MAX_BYTES, VERSION
from app.services.sources.security import SourceError, extract

metadata = sa.MetaData()
assets = sa.Table(
    "acquisition",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("owner", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(10), nullable=False),
    sa.Column("platform", sa.String(20), nullable=False),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("resource", sa.String(200), nullable=False),
    sa.Column("adapter_version", sa.String(80), nullable=False),
    sa.Column("status", sa.String(30), nullable=False),
    sa.Column("phase", sa.String(10), nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False),
    sa.Column("code", sa.String(40), nullable=True),
    sa.Column("info", sa.Text, nullable=False),
    sa.Column("created", sa.BigInteger, nullable=False),
)
State = Literal["RESOLVED", "PENDING", "ACQUIRING", "PROBING", "SUCCEEDED", "FAILED_PERMANENT"]


class ErrorBody(BaseModel):
    code: str
    message: str = "采集未完成，请上传获授权的 MP4/MOV 文件。"
    retryable: bool = False
    details: dict[str, str] = Field(default_factory=lambda: {"fallback": "upload"})


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4096)
    authorized: Literal[True]


class Job(BaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_id: UUID
    asset_id: UUID
    job_id: UUID
    platform: str
    state: State
    attempts: int
    error: ErrorBody | None = None
    validation: dict[str, str | int] = Field(default_factory=dict)
    fallback: Literal["upload"] = "upload"


def root() -> Path:
    return Settings().data_root


def directory(identifier: str, area: str = "staging") -> Path:
    identifier = str(UUID(identifier))
    base = root().resolve()
    path = base / area / identifier
    if path.is_symlink() or not path.resolve().is_relative_to(base):
        raise SourceError("STORAGE_UNAVAILABLE")
    return path


def update(identifier: str, **values: object) -> None:
    with get_engine().begin() as connection:
        connection.execute(assets.update().where(assets.c.id == identifier).values(**values))


def advance(identifier: str, before: str, **values: object) -> bool:
    with get_engine().begin() as connection:
        result = connection.execute(
            assets.update()
            .where(
                assets.c.id == identifier,
                assets.c.status == before,
            )
            .values(**values)
        )
        return result.rowcount == 1


def lookup(identifier: str, owner: str | None = None) -> dict:
    query = sa.select(assets).where(assets.c.id == str(UUID(identifier)))
    if owner is not None:
        query = query.where(assets.c.owner == owner)
    with get_engine().connect() as connection:
        row = connection.execute(query).mappings().first()
    if row is None:
        raise SourceError("NOT_FOUND")
    return dict(row)


def fail(identifier: str, error: SourceError) -> None:
    try:
        update(identifier, status="FAILED_PERMANENT", code=error.code)
    finally:
        shutil.rmtree(directory(identifier), ignore_errors=True)


def claim(identifier: str, before: str, after: str, phase: str | None = None) -> bool:
    with get_engine().begin() as connection:
        condition = assets.c.phase == phase if phase else sa.true()
        result = connection.execute(
            assets.update()
            .where(
                assets.c.id == identifier,
                assets.c.status == before,
                condition,
            )
            .values(status=after)
        )
        return result.rowcount == 1


def enqueue(identifier: str, queue: str, countdown: int = 0) -> None:
    from app.tasks.worker import celery_app

    try:
        celery_app.send_task(
            f"acquisition.{queue}", args=[identifier], queue=queue, retry=False, countdown=countdown
        )
    except Exception:
        fail(identifier, SourceError("QUEUE_UNAVAILABLE"))
        raise SourceError("QUEUE_UNAVAILABLE") from None


def create(owner: str, kind: str, platform: str, url: str = "", resource: str = "") -> str:
    identifier = str(uuid4())
    with get_engine().begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(747202)"))
        active = (
            sa.select(sa.func.count())
            .select_from(assets)
            .where(
                assets.c.status.not_in(("SUCCEEDED", "FAILED_PERMANENT")),
            )
        )
        if (connection.scalar(active) or 0) >= 20 or (
            connection.scalar(active.where(assets.c.owner == owner)) or 0
        ) >= 5:
            raise SourceError("ACQUISITION_BUSY")
        connection.execute(
            assets.insert().values(
                id=identifier,
                owner=owner,
                kind=kind,
                platform=platform,
                url=url,
                resource=resource,
                adapter_version=VERSION if kind == "link" else "upload:a02.1",
                status="RESOLVED",
                phase="download" if kind == "link" else "media",
                attempts=0,
                info="{}",
                created=int(time.time()),
            )
        )
    return identifier


def job(row: dict) -> Job:
    return Job(
        source_id=row["id"],
        asset_id=row["id"],
        job_id=row["id"],
        platform=row["platform"],
        state=row["status"],
        attempts=row["attempts"],
        validation=json.loads(row["info"]),
        error=ErrorBody(code=row["code"]) if row["code"] else None,
    )


def owner(x_owner: str = Header(default="")) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", x_owner):
        raise SourceError("AUTH_REQUIRED")
    return hashlib.sha256(x_owner.encode()).hexdigest()


router = APIRouter(
    prefix="/api/v1",
    responses={
        400: {"model": ErrorBody},
        404: {"model": ErrorBody},
        413: {"model": ErrorBody},
        503: {"model": ErrorBody},
    },
)


@router.post("/assets/resolve", response_model=Job)
def resolve(payload: ResolveRequest, user: str = Depends(owner)) -> Job:
    url, platform, resource = extract(payload.text)
    return job(lookup(create(user, "link", platform, url, resource), user))


@router.post("/assets/{source_id}/acquire", response_model=Job, status_code=202)
def acquire(source_id: UUID, user: str = Depends(owner)) -> Job:
    identifier = str(source_id)
    lookup(identifier, user)
    if claim(identifier, "RESOLVED", "PENDING"):
        enqueue(identifier, "download")
    return job(lookup(identifier, user))


@router.post(
    "/assets/upload",
    response_model=Job,
    status_code=202,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload(request: Request, user: str = Depends(owner), x_authorized: str = Header(default="")) -> Job:
    if x_authorized != "true":
        raise SourceError("SOURCE_AUTH_REQUIRED")
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise SourceError("MEDIA_INVALID") from None
    if length <= 0:
        raise SourceError("MEDIA_INVALID")
    if length > MAX_BYTES:
        raise SourceError("MEDIA_TOO_LARGE")
    identifier = create(user, "upload", "file_upload")
    path = directory(identifier)
    try:
        path.mkdir(parents=True, exist_ok=False)
        received = 0
        # Total upload deadline, including a stalled client stream.
        import asyncio

        async with asyncio.timeout(180):
            with (path / "input").open("xb") as target:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > MAX_BYTES or received > length:
                        raise SourceError("MEDIA_TOO_LARGE")
                    target.write(chunk)
        if received != length:
            raise SourceError("MEDIA_INVALID")
        update(identifier, status="PENDING")
        enqueue(identifier, "media")
    except SourceError as exc:
        fail(identifier, exc)
        raise
    except OSError:
        fail(identifier, SourceError("STORAGE_UNAVAILABLE"))
        raise SourceError("STORAGE_UNAVAILABLE") from None
    except BaseException:
        fail(identifier, SourceError("UPLOAD_INTERRUPTED"))
        raise SourceError("UPLOAD_INTERRUPTED") from None
    return job(lookup(identifier, user))


@router.get("/acquisition/jobs/{job_id}", response_model=Job)
def status(job_id: UUID, user: str = Depends(owner)) -> Job:
    row = lookup(str(job_id), user)
    if row["status"] in ("PENDING", "ACQUIRING", "PROBING") and time.time() - row["created"] > 600:
        # Do not delete active work while a process could still own it. Maintenance cleans stale work.
        advance(str(job_id), row["status"], status="FAILED_PERMANENT", code="SOURCE_TIMEOUT")
        row = lookup(str(job_id), user)
    return job(row)


def error_response(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, SourceError)
    exc = error
    code = (
        404
        if exc.code == "NOT_FOUND"
        else 401
        if exc.code == "AUTH_REQUIRED"
        else (
            413
            if exc.code == "MEDIA_TOO_LARGE"
            else 503
            if exc.code in ("QUEUE_UNAVAILABLE", "STORAGE_UNAVAILABLE")
            else 400
        )
    )
    return JSONResponse(ErrorBody(code=exc.code, retryable=exc.retryable).model_dump(), status_code=code)
