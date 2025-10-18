"""Configuration management for the fieldcam application."""
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import atexit

# Timezone configuration
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Load the secrets
with open("app/secrets.json", "r") as file:
    SECRETS = json.load(file)

# Login Manager Setup
login_manager = LoginManager(
    SECRETS["SECRET_KEY"],
    token_url="/login",
    use_cookie=True,
    use_header=False,
    cookie_name=SECRETS["COOKIE_NAME"],
    default_expiry=timedelta(minutes=30),
)

# Configure APScheduler with SQLite job store
jobstores = {"default": SQLAlchemyJobStore(url="sqlite:///jobs/jobs.sqlite")}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# Shutdown the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown(wait=False))
