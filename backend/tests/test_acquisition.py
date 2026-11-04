import hashlib
import json
import socket
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app import acquisition as a
from app.main import create_app
from app.services.sources import media, security
from app.services.sources.adapters import MAX_BYTES, YtDlpAdapter, classify

original_enqueue = a.enqueue


@pytest.fixture
def system(monkeypatch, tmp_path):
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    a.metadata.create_all(engine)
    monkeypatch.setattr(a, "get_engine", lambda: engine)
    monkeypatch.setenv("VA_DATA_ROOT", str(tmp_path / "data"))
    for name in ("postgres", "redis"):
        secret = tmp_path / name
        secret.write_text("0123456789abcdef" * 4)
        monkeypatch.setenv(f"VA_{name.upper()}_PASSWORD_FILE", str(secret))
    queued = []
    monkeypatch.setattr(
        a, "enqueue", lambda identifier, queue, countdown=0: queued.append((identifier, queue))
    )
    from app.tasks import acquire as task

    monkeypatch.setattr(task, "get_engine", lambda: engine)
    monkeypatch.setattr(
        task, "enqueue", lambda identifier, queue, countdown=0: queued.append((identifier, queue))
    )
    client = TestClient(create_app(lambda: {"database": True, "redis": True}))
    client.headers.update({"X-Owner": "a" * 64, "X-Authorized": "true"})
    yield client, queued
    engine.dispose()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://douyin.com/video/1",
        "https://douyin.com:444/video/1",
        "https://evil@douyin.com/video/1",
        "https://douyin.com.evil.com/video/1",
        "https://127.0.0.1/video/1",
        "https://169.254.169.254/latest",
        "https://[::1]/1",
        "https://douyin.com/video/1 https://tiktok.com/2",
        "https://douyin.com/video/$(touch)",
        "https://douyin.com\\@evil.com/1",
        "https://douyin.com/video/1#secret",
    ],
)
def test_unsafe_sources(url):
    with pytest.raises(security.SourceError):
        security.extract(url)


@pytest.mark.parametrize(
    "url,platform",
    [
        ("https://v.douyin.com/AbCd/", "douyin"),
        ("https://www.tiktok.com/@user/video/123", "tiktok"),
        ("https://www.bilibili.com/video/BVabc", "bilibili"),
        ("https://youtu.be/abc", "youtube"),
    ],
)
def test_platform_identification(url, platform):
    # Trailing slash is a valid share URL; canonicalize before resource extraction.
    assert security.extract("分享 " + url)[1] == platform


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.1.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:8.8.8.8",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::a9fe:a9fe",
        "2002:7f00:1::",
        "168.63.129.16",
    ],
)
def test_dns_rejects_any_non_public_record(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, 1, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, 1, 6, "", (address, 443)),
        ],
    )
    with pytest.raises(security.SourceError):
        security.public_addresses("douyin.com", 443)


def test_numeric_connection_pins_dns_and_checks_peer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: calls.append("dns") or [(socket.AF_INET, 1, 6, "", ("8.8.8.8", 443))],
    )

    class Socket:
        def settimeout(self, value):
            pass

        def connect(self, address):
            calls.append(address)

        def getpeername(self):
            return ("8.8.8.8", 443)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *args: Socket())
    security.connect_public("douyin.com", 443)
    assert calls == ["dns", ("8.8.8.8", 443)]
    monkeypatch.setattr(Socket, "getpeername", lambda self: ("127.0.0.1", 443))
    with pytest.raises(security.SourceError):
        security.connect_public("douyin.com", 443)


def test_upload_stream_contract_and_owner(system):
    client, queued = system
    response = client.post(
        "/api/v1/assets/upload",
        content=b"fake mp4",
        headers={"Content-Type": "video/mp4", "X-Filename": "../../secret.mp4"},
    )
    assert response.status_code == 202
    payload = response.json()
    identifier = payload["job_id"]
    assert queued == [(identifier, "media")]
    assert (a.directory(identifier) / "input").read_bytes() == b"fake mp4"
    assert client.get(f"/api/v1/acquisition/jobs/{identifier}").status_code == 200
    assert (
        client.get(f"/api/v1/acquisition/jobs/{identifier}", headers={"X-Owner": "b" * 64}).status_code == 404
    )
    assert client.get(f"/api/v1/acquisition/jobs/{uuid4()}").status_code == 404
    assert (
        client.post("/api/v1/assets/upload", content=b"bad", headers={"X-Authorized": "false"}).status_code
        == 400
    )


def test_resolve_acquire_idempotent_no_sensitive_source(system):
    client, queued = system
    response = client.post(
        "/api/v1/assets/resolve",
        json={"text": "https://www.youtube.com/watch?v=abc&token=secret", "authorized": True},
    )
    assert response.status_code == 200
    identifier = response.json()["source_id"]
    assert a.lookup(identifier)["url"] == "https://www.youtube.com/watch?v=abc"
    for _ in range(2):
        assert client.post(f"/api/v1/assets/{identifier}/acquire").status_code == 202
    assert queued == [(identifier, "download")]
    assert "secret" not in response.text
    assert (
        client.post(
            "/api/v1/assets/resolve", json={"text": "https://youtu.be/a", "authorized": False}
        ).status_code
        == 422
    )


def test_upload_size_and_mismatched_length(system):
    client, queued = system
    for content, headers, status in [
        (b"", {}, 400),
        (b"x", {"Content-Length": str(MAX_BYTES + 1)}, 413),
        (b"ab", {"Content-Length": "1"}, 413),
        (b"a", {"Content-Length": "3"}, 400),
    ]:
        assert client.post("/api/v1/assets/upload", content=content, headers=headers).status_code == status
    assert not queued
    assert not list(a.root().glob("staging/*"))


@pytest.mark.parametrize(
    "message,code,retryable",
    [
        ("HTTP 429 cookie=secret", "SOURCE_RATE_LIMITED", True),
        ("timeout", "SOURCE_TIMEOUT", True),
        ("login cookies", "SOURCE_AUTH_REQUIRED", False),
        ("403 captcha", "SOURCE_ACCESS_DENIED", False),
        ("404 not found", "SOURCE_EXPIRED", False),
        ("requested format", "SOURCE_UNSUPPORTED", False),
        ("unknown secret", "SOURCE_CHANGED", False),
    ],
)
def test_classification_redacts(message, code, retryable):
    exc = classify(message)
    assert (exc.code, exc.retryable) == (code, retryable)
    assert "secret" not in str(exc)


def test_media_fake_signature_never_invokes_tool(monkeypatch, tmp_path):
    path = tmp_path / "file.mp4"
    path.write_bytes(b"<html>not a video</html>")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("must reject before tool"))
    with pytest.raises(security.SourceError, match="MEDIA_INVALID"):
        media.validate(path)


def test_media_argv_and_full_decode(monkeypatch, tmp_path):
    path = tmp_path / "quote;$(shell).mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"0" * 32)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "format": {"duration": "1", "format_name": "mov,mp4"},
                    "streams": [{"codec_type": "video", "width": 16, "height": 16}],
                }
            ).encode(),
        )

    monkeypatch.setattr(subprocess, "run", run)
    info = media.validate(path)
    assert info["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(calls) == 2 and all(not options.get("shell") for _, options in calls)
    assert str(path) in calls[1][0] and calls[1][0][calls[1][0].index("-protocol_whitelist") + 1] == "file"


def test_adapter_argv_and_no_credentials(monkeypatch, tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        Path(argv[argv.index("--output") + 1]).write_bytes(b"video")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    YtDlpAdapter().acquire("https://douyin.com/video/123", tmp_path / "input")
    argv, options = calls[0]
    assert "--proxy" in argv and "--ignore-config" in argv and "--no-geo-bypass" in argv
    assert not options.get("shell") and "COOKIE" not in str(options["env"])


def test_failure_cleanup_and_bounded_retry(system, monkeypatch):
    client, _ = system
    from app.tasks import acquire as task

    identifier = client.post(
        "/api/v1/assets/resolve", json={"text": "https://douyin.com/video/123", "authorized": True}
    ).json()["source_id"]
    a.update(identifier, status="PENDING")
    attempts = []

    class Broken:
        def acquire(self, url, dest):
            attempts.append(1)
            dest.write_bytes(b"partial")
            raise security.SourceError("SOURCE_RATE_LIMITED", True)

    monkeypatch.setattr(task, "adapter_for", lambda platform: Broken())
    monkeypatch.setattr(task, "enqueue", lambda *args, **kwargs: None)
    task.download.run(identifier)
    assert a.lookup(identifier)["attempts"] == 1
    task.download.run(identifier)
    row = a.lookup(identifier)
    assert row["status"] == "FAILED_PERMANENT" and row["attempts"] == 2
    assert len(attempts) == 2 and not a.directory(identifier).exists()
    task.download.run(identifier)
    assert len(attempts) == 2


def test_media_failure_cleanup(system):
    client, _ = system
    from app.tasks.acquire import media as task

    identifier = client.post("/api/v1/assets/upload", content=b"pretend mp4").json()["job_id"]
    task.run(identifier)
    assert a.lookup(identifier)["code"] == "MEDIA_INVALID"
    assert not a.directory(identifier).exists()
    assert not a.directory(identifier, "original").exists()


@pytest.mark.parametrize(
    "duration,format_name,streams",
    [
        ("1", "mov,mp4", []),
        ("nan", "mov,mp4", []),
        ("1", "mpegts", [{"codec_type": "video", "width": 16, "height": 16}]),
        ("181", "mov,mp4", [{"codec_type": "video", "width": 16, "height": 16}]),
        ("1", "mov,mp4", [{"codec_type": "video", "width": 8192, "height": 16}]),
    ],
)
def test_media_probe_limits(monkeypatch, tmp_path, duration, format_name, streams):
    path = tmp_path / "input"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom")
    data = {"format": {"duration": duration, "format_name": format_name}, "streams": streams}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, json.dumps(data).encode()),
    )
    with pytest.raises(security.SourceError):
        media.validate(path)


def test_adapter_timeout_safe(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["secret"], 160)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(security.SourceError, match="SOURCE_TIMEOUT"):
        YtDlpAdapter().acquire("https://youtu.be/a", tmp_path / "input")


def test_download_media_handoff_is_idempotent_controlled_adapter(system, monkeypatch):
    client, queued = system
    from app.tasks import acquire as task

    class Controlled:
        def acquire(self, url, dest):
            dest.write_bytes(b"synthetic controlled adapter bytes")

    monkeypatch.setattr(task, "adapter_for", lambda platform: Controlled())
    monkeypatch.setattr(
        task,
        "validate",
        lambda path: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size},
    )
    identifier = client.post(
        "/api/v1/assets/resolve", json={"text": "https://youtu.be/A02Synthetic", "authorized": True}
    ).json()["source_id"]
    client.post(f"/api/v1/assets/{identifier}/acquire")
    task.download.run(identifier)
    assert a.lookup(identifier)["phase"] == "media"
    task.download.run(identifier)
    assert a.lookup(identifier)["attempts"] == 1
    task.media.run(identifier)
    assert a.lookup(identifier)["status"] == "SUCCEEDED"
    contents = (a.directory(identifier, "original") / "source.mp4").read_bytes()
    task.media.run(identifier)
    assert (a.directory(identifier, "original") / "source.mp4").read_bytes() == contents
    assert queued[-1] == (identifier, "media")


def test_queue_failure_is_terminal_and_cleans(system, monkeypatch):
    from app.tasks.worker import celery_app

    identifier = a.create("owner", "upload", "file_upload")
    a.directory(identifier).mkdir(parents=True)

    def broken(*args, **kwargs):
        raise RuntimeError("redis://secret")

    monkeypatch.setattr(celery_app, "send_task", broken)
    with pytest.raises(security.SourceError, match="QUEUE_UNAVAILABLE"):
        original_enqueue(identifier, "media")
    assert a.lookup(identifier)["code"] == "QUEUE_UNAVAILABLE"
    assert not a.directory(identifier).exists()


def test_pinned_redirect_limit_and_next_target_validation(monkeypatch):
    from app.services.sources.download_cli import RedirectHandler

    assert RedirectHandler.max_redirections == 5 and RedirectHandler.max_repeats == 2

    def unexpected(*args, **kwargs):
        pytest.fail("must reject domain/port before DNS")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected)
    for host, port in [("localhost", 443), ("169.254.169.254", 443), ("evil.test", 443), ("douyin.com", 80)]:
        with pytest.raises(security.SourceError):
            security.public_addresses(host, port)


def test_capacity_and_stale_job(system):
    client, _ = system
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/assets/resolve", json={"text": "https://youtu.be/A02Synthetic", "authorized": True}
            ).status_code
            == 200
        )
    assert (
        client.post(
            "/api/v1/assets/resolve", json={"text": "https://youtu.be/A02Synthetic", "authorized": True}
        ).json()["code"]
        == "ACQUISITION_BUSY"
    )
    identifier = a.create("other-owner", "upload", "file_upload")
    a.update(identifier, created=0, status="PENDING")
    from app.tasks.acquire import media as task

    task.run(identifier)
    assert a.lookup(identifier)["code"] == "SOURCE_TIMEOUT"


def test_oversized_json_is_rejected_before_parsing(system):
    client, _ = system
    response = client.post(
        "/api/v1/assets/resolve", content=b"x" * 9000, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_late_download_cannot_resurrect_expired_task(system, monkeypatch):
    client, queued = system
    from app.tasks import acquire as task

    identifier = client.post(
        "/api/v1/assets/resolve", json={"text": "https://youtu.be/A02Synthetic", "authorized": True}
    ).json()["source_id"]
    client.post(f"/api/v1/assets/{identifier}/acquire")

    class Late:
        def acquire(self, url, dest):
            a.update(identifier, status="FAILED_PERMANENT", code="SOURCE_TIMEOUT")
            dest.write_bytes(b"late-data")

    monkeypatch.setattr(task, "adapter_for", lambda platform: Late())
    task.download.run(identifier)
    assert a.lookup(identifier)["status"] == "FAILED_PERMANENT"
    assert queued == [(identifier, "download")]
    assert not a.directory(identifier).exists()
