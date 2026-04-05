"""Configuration management for the fieldcam application."""

import atexit
import hashlib
import os
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi_login import LoginManager
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to project root (cam-app), so it works regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
# Only pass env_file if it exists (avoid errors when .env is missing)
_SETTINGS_KW: dict = {
    "env_file_encoding": "utf-8",
    "case_sensitive": False,
    "env_prefix": "",
    "extra": "ignore",
}
if _ENV_FILE.is_file():
    _SETTINGS_KW["env_file"] = _ENV_FILE


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Security settings
    secret_key: str
    cookie_name: str = "stream411_login"

    # Camera configuration
    cam_host: str
    cam_user: str
    cam_pass: str

    # Application settings
    location: str = "Tepper"

    # Authentication
    auth_hash_sfll: str = ""
    passwords: str = ""  # Comma-separated list
    admin_password: str = ""  # Admin password unlocks settings page

    # Blackout info (shown in schedule form)
    blackout_season: str = ""
    blackout_teams: str = "TBD"

    # RTMP base URLs per destination (key appended at stream time)
    rtmp_gamechanger: str = "rtmps://601c62c19c9e.global-contribute.live-video.net:443/app"
    rtmp_youtube: str = "rtmp://a.rtmp.youtube.com/live2"

    # Optional settings
    timezone: str = "America/Los_Angeles"
    token_expiry_minutes: int = 30
    jobs_db_path: str = "sqlite:///jobs/jobs.sqlite"
    # Path to field camera snapshot (cron/ffmpeg writes here; default /tmp so any user can read)
    field_image_path: str = "/tmp/field.jpg"
    # YOLO model variant (e.g. yolov8n.pt, yolov8s.pt)
    yolo_model: str = "models/yolov8n.pt"

    model_config = SettingsConfigDict(**_SETTINGS_KW)

    @property
    def passwords_list(self) -> list[str]:
        """Return passwords as a list."""
        if not self.passwords:
            return []
        return [p.strip() for p in self.passwords.split(",")]


# Initialize settings
settings = Settings()


def _resolve_jobs_db_url(url: str) -> str:
    """Resolve relative SQLite paths against project root and ensure directory exists."""
    if not url.startswith("sqlite:///"):
        return url
    path_part = url.replace("sqlite:///", "")
    if os.path.isabs(path_part):
        return url
    full_path = _PROJECT_ROOT / path_part
    full_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{full_path}"


# Resolved DB URL so jobs/ exists under project root when path is relative
JOBS_DB_URL = _resolve_jobs_db_url(settings.jobs_db_path)

# Timezone configuration
LOCAL_TZ = ZoneInfo(settings.timezone)

# Derive a 32-byte key so PyJWT doesn't warn about short HMAC keys
_jwt_secret = hashlib.sha256(settings.secret_key.encode()).hexdigest()

# Login Manager Setup
login_manager = LoginManager(
    _jwt_secret,
    token_url="/login",
    use_cookie=True,
    use_header=False,
    cookie_name=settings.cookie_name,
    default_expiry=timedelta(minutes=settings.token_expiry_minutes),
)

# Configure APScheduler with SQLite job store (use resolved path)
jobstores = {"default": SQLAlchemyJobStore(url=JOBS_DB_URL)}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# Shutdown the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown(wait=False))
