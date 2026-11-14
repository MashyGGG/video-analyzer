import hashlib
import json

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app import acquisition, timeline_jobs
from app.main import create_app
from tests.test_media_timeline import make_video


@pytest.fixture
def system(monkeypatch, tmp_path):
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    acquisition.metadata.create_all(engine)
    timeline_jobs.metadata.create_all(engine)
    monkeypatch.setattr(acquisition, "get_engine", lambda: engine)
    monkeypatch.setattr(timeline_jobs, "get_engine", lambda: engine)
    monkeypatch.setenv("VA_DATA_ROOT", str(tmp_path / "data"))
    for name in ("postgres", "redis"):
        secret = tmp_path / name
        secret.write_text("0123456789abcdef" * 4)
        monkeypatch.setenv(f"VA_{name.upper()}_PASSWORD_FILE", str(secret))
    from app.tasks import timeline, worker

    monkeypatch.setattr(timeline, "get_engine", lambda: engine)
    queued = []
    monkeypatch.setattr(worker.celery_app, "send_task", lambda name, args, **kwargs: queued.append(args))
    client = TestClient(create_app(lambda: {"database": True, "redis": True}))
    client.headers.update({"X-Owner": "a" * 64})
    owner_hash = hashlib.sha256(("a" * 64).encode()).hexdigest()
    identifier = acquisition.create(owner_hash, "upload", "file_upload")
    path = acquisition.directory(identifier, "original")
    path.mkdir(parents=True)
    make_video(path / "source.mp4", "color=red:s=160x90:r=10:d=1")
    digest = hashlib.sha256((path / "source.mp4").read_bytes()).hexdigest()
    acquisition.update(identifier, status="SUCCEEDED", info=json.dumps({"sha256": digest}))
    yield client, identifier, queued, timeline
    engine.dispose()


def test_owner_queue_result_and_reference(system):
    client, identifier, queued, timeline = system
    url = f"/api/v1/assets/{identifier}/timeline"
    assert client.post(url).json()["state"] == "PENDING"
    assert client.post(url).json()["state"] == "PENDING"
    assert len(queued) == 1
    timeline.run_timeline.run(*queued[0])
    assert client.get(url).json()["state"] == "SUCCEEDED"
    result = client.get(url + "/result").json()
    name = result["shots"][0]["reference"]["file"]
    assert client.get(url + "/frames/" + name).content.startswith(b"\xff\xd8")
    client.headers["X-Owner"] = "b" * 64
    assert client.get(url).status_code == 404
    assert client.get(url + "/result").status_code == 404
    assert client.get(url + "/frames/" + name).status_code == 404


def test_hash_failure_can_be_retried(system):
    client, identifier, queued, timeline = system
    url = f"/api/v1/assets/{identifier}/timeline"
    acquisition.update(identifier, info=json.dumps({"sha256": "0" * 64}))
    assert client.post(url).status_code == 202
    timeline.run_timeline.run(*queued[0])
    assert client.get(url).json()["error"] == "MEDIA_HASH_MISMATCH"
    assert client.get(url + "/result").status_code == 400
    assert client.post(url).json()["state"] == "PENDING"
    assert len(queued) == 2 and queued[0][1] != queued[1][1]


def test_stale_attempt_cannot_overwrite_new_attempt(system):
    client, identifier, queued, timeline = system
    url = f"/api/v1/assets/{identifier}/timeline"
    assert client.post(url).status_code == 202
    with timeline_jobs.get_engine().begin() as connection:
        connection.execute(timeline_jobs.timelines.update().where(
            timeline_jobs.timelines.c.asset_id == identifier).values(updated=0))
    assert client.get(url).json()["error"] == "MEDIA_TIMEOUT"
    assert client.post(url).json()["state"] == "PENDING"
    timeline.run_timeline.run(*queued[0])
    assert client.get(url).json()["state"] == "PENDING"
    timeline.run_timeline.run(*queued[1])
    assert client.get(url).json()["state"] == "SUCCEEDED"


def test_queue_error_is_not_success(system, monkeypatch):
    client, identifier, _, _ = system
    from app.tasks.worker import celery_app

    def fail(*args, **kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(celery_app, "send_task", fail)
    url = f"/api/v1/assets/{identifier}/timeline"
    assert client.post(url).status_code == 503
    status = client.get(url).json()
    assert status["state"] == "FAILED" and status["error"] == "QUEUE_UNAVAILABLE"


def test_unready_and_other_owner_cannot_start(system):
    client, identifier, queued, _ = system
    url = f"/api/v1/assets/{identifier}/timeline"
    client.headers["X-Owner"] = "b" * 64
    assert client.post(url).status_code == 404
    client.headers["X-Owner"] = "a" * 64
    acquisition.update(identifier, status="PENDING")
    assert client.post(url).status_code == 400
    assert queued == []
