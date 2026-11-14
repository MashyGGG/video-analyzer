"""A03 processing, isolated on the existing media worker."""

import json
import logging
import shutil
import time

from app.acquisition import directory, lookup
from app.database import get_engine
from app.services.media.timeline import MediaError, analyze
from app.tasks.worker import celery_app
from app.timeline_jobs import TimelineResult, result_dir, timelines


@celery_app.task(name="timeline.analyze", soft_time_limit=570, time_limit=600)
def run_timeline(identifier: str, attempt: str) -> None:
    with get_engine().begin() as connection:
        claimed = connection.execute(timelines.update().where(timelines.c.asset_id == identifier,
            timelines.c.attempt == attempt, timelines.c.status == "PENDING").values(
                status="RUNNING", updated=int(time.time())))
        if claimed.rowcount != 1:
            return
    output = None
    published = False
    try:
        output = result_dir(identifier, attempt)
        asset = lookup(identifier)
        source = directory(identifier, "original") / "source.mp4"
        expected = json.loads(asset["info"])["sha256"]
        result = analyze(source, output)
        TimelineResult.model_validate(result)
        if result["metadata"]["sha256"] != expected:
            raise MediaError("MEDIA_HASH_MISMATCH")
        with get_engine().begin() as connection:
            changed = connection.execute(timelines.update().where(timelines.c.asset_id == identifier,
                timelines.c.attempt == attempt, timelines.c.status == "RUNNING").values(
                    status="SUCCEEDED", code=None, updated=int(time.time())))
            published = changed.rowcount == 1
    except Exception as exc:
        code = str(exc) if isinstance(exc, MediaError) and str(exc).startswith("MEDIA_") else "MEDIA_PROCESS_FAILED"
        with get_engine().begin() as connection:
            connection.execute(timelines.update().where(timelines.c.asset_id == identifier,
                timelines.c.attempt == attempt, timelines.c.status == "RUNNING").values(
                    status="FAILED", code=code, updated=int(time.time())))
    finally:
        if output is not None and not published:
            shutil.rmtree(output, ignore_errors=True)
    logging.getLogger(__name__).warning("timeline_finished asset=%s", identifier)
