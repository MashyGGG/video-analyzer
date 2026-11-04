import json
import logging
import shutil
import time

from app.acquisition import advance, assets, claim, directory, enqueue, fail, lookup, update
from app.database import get_engine
from app.services.sources.adapters import adapter_for
from app.services.sources.media import validate
from app.services.sources.security import SourceError
from app.tasks.worker import celery_app


@celery_app.task(name="acquisition.download", soft_time_limit=175, time_limit=185)
def download(identifier: str) -> None:
    if not claim(identifier, "PENDING", "ACQUIRING", phase="download"):
        return
    row = lookup(identifier)
    path = directory(identifier)
    try:
        if time.time() - row["created"] > 600:
            raise SourceError("SOURCE_TIMEOUT")
        path.mkdir(parents=True, exist_ok=False)
        attempt = row["attempts"] + 1
        update(identifier, attempts=attempt)
        try:
            adapter_for(row["platform"]).acquire(row["url"], path / "input")
        except SourceError as exc:
            if not exc.retryable or attempt >= 2:
                raise
            shutil.rmtree(path)
            if not advance(identifier, "ACQUIRING", status="PENDING"):
                return
            enqueue(identifier, "download", countdown=2)
            return
        (path / "tool.log").unlink(missing_ok=True)
        if not advance(identifier, "ACQUIRING", status="PENDING", phase="media"):
            shutil.rmtree(path, ignore_errors=True)
            return
        enqueue(identifier, "media")
    except SourceError as exc:
        fail(identifier, exc)
    except Exception:
        fail(identifier, SourceError("SOURCE_CHANGED"))
    logging.getLogger(__name__).warning("acquisition_download_finished job=%s", identifier)


@celery_app.task(name="acquisition.media", soft_time_limit=75, time_limit=85)
def media(identifier: str) -> None:
    if not claim(identifier, "PENDING", "PROBING", phase="media"):
        return
    path = directory(identifier)
    try:
        if time.time() - lookup(identifier)["created"] > 600:
            raise SourceError("SOURCE_TIMEOUT")
        info = validate(path / "input")
        info["acquired_at_ms"] = int(time.time() * 1000)
        destination = directory(identifier, "original")
        destination.mkdir(parents=True, exist_ok=False)
        # Exclusive target, no overwrite; per-owner asset IDs avoid cross-owner cache disclosure.
        with (destination / "source.mp4").open("xb") as target, (path / "input").open("rb") as source:
            shutil.copyfileobj(source, target)
        with get_engine().begin() as connection:
            result = connection.execute(
                assets.update()
                .where(
                    assets.c.id == identifier,
                    assets.c.status == "PROBING",
                )
                .values(status="SUCCEEDED", info=json.dumps(info), code=None)
            )
            if result.rowcount != 1:
                raise SourceError("SOURCE_TIMEOUT")
    except SourceError as exc:
        shutil.rmtree(directory(identifier, "original"), ignore_errors=True)
        fail(identifier, exc)
    except Exception:
        shutil.rmtree(directory(identifier, "original"), ignore_errors=True)
        fail(identifier, SourceError("STORAGE_UNAVAILABLE"))
    finally:
        shutil.rmtree(path, ignore_errors=True)
    logging.getLogger(__name__).warning("acquisition_validation_finished job=%s", identifier)
