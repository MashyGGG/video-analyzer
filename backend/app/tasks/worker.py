from celery import Celery

from app.config import Settings

settings = Settings()
celery_app = Celery("video_analyzer", broker=settings.redis_url(0), backend=settings.redis_url(1))
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue="infrastructure",
    task_track_started=True,
    result_expires=300,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=5,
    broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2, "visibility_timeout": 60},
    redis_socket_connect_timeout=2,
    redis_socket_timeout=2,
    task_soft_time_limit=10,
    task_time_limit=15,
    worker_hijack_root_logger=False,
    imports=("app.tasks.acquire",),
)


@celery_app.task(name="infrastructure.ping")
def ping(token: str) -> dict[str, str]:
    """Internal acceptance probe, never represents video/model processing."""
    return {"token": token, "service": "worker", "version": "0.1.0"}
