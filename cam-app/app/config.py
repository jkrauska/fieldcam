"""Configuration management for the fieldcam application."""

import atexit
import hashlib
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi_login import LoginManager
from pydantic import AliasChoices, Field, ValidationError
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

    # Camera configuration.
    # Accept legacy CAM_HOST/CAM_USER/CAM_PASS aliases in addition to the
    # current CAMERA_IP/CAMERA_USER/CAMERA_PASS names. Legacy names emit a
    # deprecation warning at startup (see log_observed_config).
    camera_ip: str = Field(
        default="",
        validation_alias=AliasChoices("camera_ip", "cam_host"),
    )
    camera_user: str = Field(
        default="",
        validation_alias=AliasChoices("camera_user", "cam_user"),
    )
    camera_pass: str = Field(
        default="",
        validation_alias=AliasChoices("camera_pass", "cam_pass"),
    )

    # Application settings
    location: str = "Tepper"

    # When true, dump the resolved configuration to the log at startup.
    # Off by default to keep production logs quiet. Enable via DEBUG=1
    # (or true/yes/on) in the process environment / .env file.
    debug: bool = False

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

    # FFmpeg stream encode options (space-separated args, inserted after -i).
    # Tune via .env / settings UI without changing Python.
    video_options: str = "-c:v copy"
    audio_options: str = "-af pan=mono|c0=c0 -c:a aac -ar 48000 -b:a 64k"

    # Optional settings
    timezone: str = "America/Los_Angeles"
    token_expiry_minutes: int = 30
    jobs_db_path: str = "sqlite:///jobs/jobs.sqlite"
    # Path to field camera snapshot (cron/ffmpeg writes here; default /tmp so any user can read)
    field_image_path: str = "/tmp/field.jpg"
    # YOLOv8 ONNX model shipped in the image (regenerate via `uv run --extra export`)
    yolo_model: str = "app/models/yolov8n.onnx"

    model_config = SettingsConfigDict(**_SETTINGS_KW)

    @property
    def passwords_list(self) -> list[str]:
        """Return passwords as a list."""
        if not self.passwords:
            return []
        return [p.strip() for p in self.passwords.split(",")]


# Initialize settings
try:
    settings = Settings()
except ValidationError as exc:
    missing = [e["loc"][0] for e in exc.errors() if e["type"] == "missing"]
    if missing:
        env_hint = f"  cp {_ENV_FILE.with_suffix('.example').relative_to(_PROJECT_ROOT.parent)} {_ENV_FILE.relative_to(_PROJECT_ROOT.parent)}"
        print(
            "\n*** Missing required configuration ***\n"
            f"  The following settings have no value: {', '.join(missing)}\n\n"
            f"  Create a .env file from the template and fill in the values:\n"
            f"    {env_hint}\n",
            file=sys.stderr,
        )
    else:
        print(f"\n*** Configuration error ***\n{exc}\n", file=sys.stderr)
    sys.exit(1)


# Fields whose values should never be logged in plaintext.
_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "secret_key",
        "camera_pass",
        "auth_hash_sfll",
        "passwords",
        "admin_password",
    }
)


# Legacy env var names -> current canonical names. Listed for backward
# compatibility with older .env files. Detected at startup and warned about
# in log_observed_config().
_LEGACY_ENV_ALIASES: dict[str, str] = {
    "CAM_HOST": "CAMERA_IP",
    "CAM_USER": "CAMERA_USER",
    "CAM_PASS": "CAMERA_PASS",
}


def _env_file_keys() -> set[str]:
    """Return the set of upper-cased keys present in the .env file (if any)."""
    keys: set[str] = set()
    if not _ENV_FILE.is_file():
        return keys
    try:
        for raw in _ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            keys.add(line.partition("=")[0].strip().upper())
    except OSError:
        pass
    return keys


def _detect_legacy_env_aliases() -> dict[str, str]:
    """Return {legacy_name: canonical_name} for any deprecated env vars in use."""
    file_keys = _env_file_keys()
    found: dict[str, str] = {}
    for legacy, canonical in _LEGACY_ENV_ALIASES.items():
        if legacy in os.environ or legacy in file_keys:
            found[legacy] = canonical
    return found


def camera_configured() -> bool:
    """True only when all required camera credentials are set."""
    return bool(settings.camera_ip and settings.camera_user and settings.camera_pass)


def missing_camera_fields() -> list[str]:
    """Return the names of any unset required camera settings."""
    return [name for name in ("camera_ip", "camera_user", "camera_pass") if not getattr(settings, name)]


def _redact(name: str, value: object) -> str:
    """Return a log-safe representation of a setting value."""
    if name in _SENSITIVE_FIELDS:
        if value in (None, ""):
            return "<empty>"
        text = str(value)
        # Show only length + a short fingerprint so we can tell if the value changed.
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        return f"<set, len={len(text)}, sha256[:8]={digest}>"
    if value == "":
        return "<empty>"
    return repr(value)


def log_observed_config(log: logging.Logger | None = None) -> None:
    """Log resolved Settings plus which env vars the process actually sees.

    Sensitive values are redacted. Useful at startup to verify whether
    environment variables / .env are being picked up.
    """
    log = log or logging.getLogger(__name__)

    log.info("Config: project root = %s", _PROJECT_ROOT)
    if _ENV_FILE.is_file():
        log.info("Config: .env loaded from %s", _ENV_FILE)
    else:
        log.info("Config: no .env file at %s (using process env only)", _ENV_FILE)

    log.info("Config: resolved Settings (sensitive values redacted):")
    for name in sorted(settings.model_fields):
        value = getattr(settings, name)
        log.info("  settings.%s = %s", name, _redact(name, value))

    # Also report which matching env vars are present in the process. This
    # helps diagnose cases where the process didn't actually receive the env
    # vars you expect (e.g. wrong shell, missing docker --env-file, etc.).
    log.info("Config: matching environment variables seen in process:")
    any_env = False
    for name in sorted(settings.model_fields):
        env_key = name.upper()
        if env_key in os.environ:
            any_env = True
            log.info("  %s = %s", env_key, _redact(name, os.environ[env_key]))
    if not any_env:
        log.info("  (none — no matching env vars set in this process)")

    # Warn about any deprecated env var names still in use. We still honor
    # them via Settings AliasChoices, but they should be renamed.
    for legacy, canonical in _detect_legacy_env_aliases().items():
        log.warning(
            "DEPRECATED env var %s detected — please rename to %s in %s. Legacy name is still accepted but will be removed in a future release.",
            legacy,
            canonical,
            _ENV_FILE,
        )


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
