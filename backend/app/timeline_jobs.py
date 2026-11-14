"""Owner-scoped timeline requests and result access."""

import json
import re
import time
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from app.acquisition import directory, lookup, owner
from app.database import get_engine
from app.services.sources.security import SourceError

metadata = sa.MetaData()
timelines = sa.Table(
    "media_timeline", metadata,
    sa.Column("asset_id", sa.String(36), primary_key=True),
    sa.Column("attempt", sa.String(36), nullable=False),
    sa.Column("status", sa.String(20), nullable=False),
    sa.Column("code", sa.String(40)),
    sa.Column("updated", sa.BigInteger, nullable=False),
)
router = APIRouter(prefix="/api/v1")


class TimelineStatus(BaseModel):
    asset_id: UUID
    state: str
    error: str | None = None


class FrameReference(BaseModel):
    pts: int
    timestamp_ms: int = Field(ge=0)
    file: str = Field(pattern=r"^frame_\d{4}\.jpg$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Shot(BaseModel):
    shot_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    transition: str
    review_flags: list[str]
    thumbnail: str = Field(pattern=r"^thumb_\d{4}\.jpg$")
    reference: FrameReference


class MediaMetadata(BaseModel):
    duration_ms: int = Field(gt=0, le=180000)
    duration_basis: str
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)
    container: str
    video_codec: str
    rotation: int
    video_stream_index: int = Field(ge=0)
    audio_stream_indices: list[int]
    audio_present: bool
    time_base: str
    avg_frame_rate: str
    variable_frame_rate: bool
    source_start_pts: int
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TimelineResult(BaseModel):
    schema_version: str
    algorithm: str
    metadata: MediaMetadata
    shots: list[Shot] = Field(min_length=1, max_length=200)
    semantic_segments: list[dict]

    @model_validator(mode="after")
    def valid_timeline(self) -> "TimelineResult":
        previous = 0
        for shot in self.shots:
            if shot.start_ms != previous or not shot.start_ms <= shot.reference.timestamp_ms < shot.end_ms:
                raise ValueError("Invalid physical timeline")
            previous = shot.end_ms
        if previous != self.metadata.duration_ms:
            raise ValueError("Timeline does not cover video")
        return self


def result_dir(asset_id: str, attempt: str) -> Path:
    path = directory(asset_id, "timelines") / str(UUID(attempt))
    if path.is_symlink() or not path.resolve().is_relative_to(directory(asset_id, "timelines").resolve()):
        raise SourceError("STORAGE_UNAVAILABLE")
    return path


def get_row(asset_id: str) -> dict:
    with get_engine().connect() as connection:
        row = connection.execute(sa.select(timelines).where(timelines.c.asset_id == asset_id)).mappings().first()
    if row is None:
        raise SourceError("NOT_FOUND")
    return dict(row)


def public(row: dict) -> TimelineStatus:
    return TimelineStatus(asset_id=row["asset_id"], state=row["status"], error=row["code"])


@router.post("/assets/{asset_id}/timeline", response_model=TimelineStatus, status_code=202)
def request_timeline(asset_id: UUID, user: str = Depends(owner)) -> TimelineStatus:
    identifier = str(asset_id)
    asset = lookup(identifier, user)
    if asset["status"] != "SUCCEEDED":
        raise SourceError("MEDIA_NOT_READY")
    now = int(time.time())
    attempt = str(uuid4())
    with get_engine().begin() as connection:
        # A database lock serializes concurrent requests for the same asset.
        if connection.dialect.name == "postgresql":
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))"), {"id": identifier})
        row = connection.execute(sa.select(timelines).where(timelines.c.asset_id == identifier)).mappings().first()
        if row and (row["status"] == "SUCCEEDED" or (row["status"] in ("PENDING", "RUNNING") and now - row["updated"] < 900)):
            return public(dict(row))
        values = dict(attempt=attempt, status="PENDING", code=None, updated=now)
        if row:
            connection.execute(timelines.update().where(timelines.c.asset_id == identifier).values(**values))
        else:
            connection.execute(timelines.insert().values(asset_id=identifier, **values))
    from app.tasks.worker import celery_app

    try:
        celery_app.send_task("timeline.analyze", args=[identifier, attempt], queue="media", retry=False)
    except Exception:
        with get_engine().begin() as connection:
            connection.execute(timelines.update().where(timelines.c.asset_id == identifier,
                timelines.c.attempt == attempt, timelines.c.status == "PENDING").values(
                    status="FAILED", code="QUEUE_UNAVAILABLE", updated=int(time.time())))
        raise SourceError("QUEUE_UNAVAILABLE") from None
    return public(get_row(identifier))


@router.get("/assets/{asset_id}/timeline", response_model=TimelineStatus)
def timeline_status(asset_id: UUID, user: str = Depends(owner)) -> TimelineStatus:
    identifier = str(asset_id)
    lookup(identifier, user)
    row = get_row(identifier)
    if row["status"] in ("PENDING", "RUNNING") and int(time.time()) - row["updated"] >= 900:
        with get_engine().begin() as connection:
            connection.execute(timelines.update().where(timelines.c.asset_id == identifier,
                timelines.c.attempt == row["attempt"], timelines.c.status == row["status"]).values(
                    status="FAILED", code="MEDIA_TIMEOUT", updated=int(time.time())))
        row = get_row(identifier)
    return public(row)


def completed(identifier: str, user: str) -> Path:
    lookup(identifier, user)
    row = get_row(identifier)
    if row["status"] != "SUCCEEDED":
        raise SourceError("MEDIA_NOT_READY")
    return result_dir(identifier, row["attempt"])


@router.get("/assets/{asset_id}/timeline/result", response_model=TimelineResult)
def timeline_result(asset_id: UUID, user: str = Depends(owner)) -> TimelineResult:
    path = completed(str(asset_id), user) / "timeline.json"
    try:
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise SourceError("STORAGE_UNAVAILABLE")
        data = json.loads(path.read_text(encoding="utf-8"))
        return TimelineResult.model_validate(data)
    except (OSError, ValueError):
        raise SourceError("STORAGE_UNAVAILABLE") from None


@router.get("/assets/{asset_id}/timeline/frames/{name}")
def timeline_frame(asset_id: UUID, name: str, user: str = Depends(owner)) -> FileResponse:
    base = completed(str(asset_id), user)
    if not re.fullmatch(r"(?:frame|thumb)_\d{4}\.jpg", name):
        raise SourceError("NOT_FOUND")
    path = base / name
    if path.is_symlink() or not path.is_file():
        raise SourceError("NOT_FOUND")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
