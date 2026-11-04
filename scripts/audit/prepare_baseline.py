"""Prepare disposable A00 runtime config; never copy user credentials or alter tracked source."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[2]
cache = root / ".audit-cache"
upstream = cache / "parse_video"
env_file = upstream / ".env"
if env_file.exists():
    raise SystemExit("Refusing to overwrite an existing audit .env; inspect it locally first")
env = {
    "POSTGRES_SERVER": "127.0.0.1", "POSTGRES_PORT": "15433", "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24), "POSTGRES_DB": "parse_video",
    "SECRET_KEY": secrets.token_urlsafe(48), "SUPER_ADMINI_EMAIL": "audit@example.invalid",
    "SUPER_ADMINI_PASSWORD": secrets.token_urlsafe(24),
    "COMFY_URL": "http://127.0.0.1:9", "COMFY_USER": "", "COMFY_PASSWORD": "",
    "LLM_NAME": "audit-unavailable", "LLM_BASE_URL": "http://127.0.0.1:9/v1", "LLM_API_KEY": "",
    "IMAGE_MODEL_BASE_URL": "http://127.0.0.1:9", "IMAGE_MODEL_NAME": "audit-unavailable",
    "IMAGE_MODEL_API_KEY": "", "BYTEDANCE_APP_ID": "", "BYTEDANCE_TOKEN": "",
    "BYTEDANCE_AK": "", "BYTEDANCE_SK": "", "BYTEDANCE_API_KEY": "", "RUNNINGHUB_API_KEY": "",
    "LOG_LEVEL": "INFO", "LOG_ENABLED": "False", "LOG_DIR": "./LOGS", "BACKEND_HOST": "0.0.0.0",
    "FRONTEND_HOST": "http://127.0.0.1:13000", "REDIS_URL": "redis://127.0.0.1:16380/0",
    "FRONTEND_BIND": "127.0.0.1:13000", "RUN_ENV": "DEV", "DOUYIN_COOKIES_FILE": "",
}
env_file.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n", encoding="utf-8")
(cache / "compose.audit.yaml").write_text('''services:
  backend:
    ports: !override
      - "127.0.0.1:18000:8000"
  frontend:
    ports: !override
      - "127.0.0.1:13000:3000"
  postgres:
    ports: !override
      - "127.0.0.1:15433:5432"
  redis:
    ports: !override
      - "127.0.0.1:16380:6379"
''', encoding="utf-8")
print("Prepared disposable .env (no cloud credentials) and loopback-only port override. No tracked source changed.")
