"""Configuration management for the fieldcam application."""

import atexit
from datetime import timedelta
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi_login import LoginManager
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    long_string: str = ""

    # Authentication
    auth_hash_sfll: str = ""
    passwords: str = ""  # Comma-separated list

    # Optional settings
    timezone: str = "America/Los_Angeles"
    token_expiry_minutes: int = 30
    jobs_db_path: str = "sqlite:///jobs/jobs.sqlite"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Map environment variables to fields
        env_prefix="",
        extra="ignore",
    )

    @property
    def passwords_list(self) -> list[str]:
        """Return passwords as a list."""
        if not self.passwords:
            return []
        return [p.strip() for p in self.passwords.split(",")]


# Initialize settings
settings = Settings()

# Timezone configuration
LOCAL_TZ = ZoneInfo(settings.timezone)

# Login Manager Setup
login_manager = LoginManager(
    settings.secret_key,
    token_url="/login",
    use_cookie=True,
    use_header=False,
    cookie_name=settings.cookie_name,
    default_expiry=timedelta(minutes=settings.token_expiry_minutes),
)

# Configure APScheduler with SQLite job store
jobstores = {"default": SQLAlchemyJobStore(url=settings.jobs_db_path)}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# Shutdown the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown(wait=False))
