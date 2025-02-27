from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# from fastapi.security import OAuth2PasswordRequestForm
# from fastapi_login.exceptions import InvalidCredentialsException
from fastapi_login import LoginManager
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from urllib.parse import urlencode

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import logging
import subprocess
import queue

import os
import json


from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.base import ConflictingIdError
import atexit

from .random_names import generate_name

local_tz = ZoneInfo("America/Los_Angeles")

# Load the secrets
with open("app/secrets.json", "r") as file:
    SECRETS = json.load(file)
    print(SECRETS)


# Login Manager Setup
login_manager = LoginManager(
    SECRETS["SECRET_KEY"],
    token_url="/login",
    use_cookie=True,
    use_header=False,
    cookie_name=SECRETS["COOKIE_NAME"],
    default_expiry=timedelta(minutes=30),
)

process_dict = {}

# Global queue to store FFmpeg output
ffmpeg_output_queue = queue.Queue()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware)

session_tokens = set()


# jinja2 doesn't have easy date formatting
def format_datetime(value, format="%Y-%m-%d %H:%M:%S"):
    """Format a datetime object to a string using strftime."""
    if value is None:
        return ""
    return value.strftime(format)


# Set up the templates directory
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["datetime"] = format_datetime

# Static files are cached :|
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/dynamic/field.jpg")
def serve_image():
    file_path = "app/static/field.jpg"
    headers = {
        "Cache-Control": "no-store"  # Disable caching
        # Or use "max-age=0" for immediate revalidation:
        # "Cache-Control": "no-cache, max-age=0, must-revalidate"
    }
    return FileResponse(file_path, media_type="image/jpeg", headers=headers)

################################################################################
# Configure APScheduler with SQLite job store
jobstores = {"default": SQLAlchemyJobStore(url="sqlite:///jobs/jobs.sqlite")}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# Shutdown the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown(wait=False))

################################################################################


# Define the job function
def job_function(param1: str, param2: str):
    logging.info(f"Executing job with param1={param1}, param2={param2}")


# Pydantic models for request and response validation
class AddJobRequest(BaseModel):
    job_id: str
    run_date: datetime  # ISO 8601 format
    param1: str
    param2: str


class RemoveJobRequest(BaseModel):
    job_id: str


class JobInfo(BaseModel):
    id: str
    next_run_time: datetime = None
    args: List[str]


################################################################################
# Auth Routes


def create_redirect_content(next: str, result: str = "unsuccessful") -> str:
    return f"""
        <html><head><title>Redirecting...</title>
        <script type="text/javascript">
        setTimeout(function() {{
        window.location.href = "{next}";
        }}, 100);
        </script></head>
        <body><p>Login {result}. Try again?...</p></body>
        </html>
    """


@login_manager.user_loader()
def load_user(user_id: str):
    if user_id == "shared_user":
        return {"user_id": user_id}
    return None


@app.get("/login", response_class=HTMLResponse)
def login_form(next: Optional[str] = None):
    next_input = f'<input type="hidden" name="next" value="{next}" />' if next else ""
    return f"""
    <html>
        <body>
            <form action="/login" method="post">
                {next_input}
                <input type="password" name="password" placeholder="Password" /><br>
                <button type="submit">Login</button>
            </form>
        </body>
    </html>
    """


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, response: Response):
    cookies = request.cookies
    logging.info(f"Incoming Cookies: {cookies}")
    user_id = "shared_user"

    form = await request.form()
    password = form.get("password")
    next = form.get("next") or "/list"

    logging.info("Password check")
    if password not in SECRETS["PASSWORDS"]:
        # return InvalidCredentialsException
        return create_redirect_content(next)

    # Redirect to the original page if 'next' is provided
    next_url = next or "/list"

    response = HTMLResponse(content=create_redirect_content(next_url, "successful"))
    access_token = login_manager.create_access_token(data={"sub": user_id})
    login_manager.set_cookie(response, access_token)
    return response


# Logout route to clear the cookie
@app.get("/logout", response_class=HTMLResponse)
def logout(response: Response):
    response = RedirectResponse(url="/login")
    response.delete_cookie(login_manager.cookie_name)
    return response


## Is this still needed??
# Exception Handler for InvalidCredentialsException
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        next_url = request.url.path
        logging.info(f"Redirecting to login page with next={next_url}")

        login_url = "/login"
        if isinstance(next_url, str) and len(next_url) > 3:
            redirect_url = f"{login_url}?{urlencode({'next': next_url})}"
        else:
            redirect_url = login_url
        return RedirectResponse(url=redirect_url, status_code=302)
    else:
        # Re-raise the exception for other status codes
        raise exc


################################################################################
# Scheduler


# new_stream wrapper
def new_stream(name="", startTime=False, duration=60 * 5, key="", config={}):
    logging.info(f"New Stream: {name} {startTime} {duration} {key}")
    now = datetime.now().astimezone(local_tz)

    if not name:
        name = generate_name()
    if not startTime:
        startTime = datetime.now() + timedelta(days=365)

    endTime = startTime + timedelta(seconds=duration)

    # In Progress
    if startTime < now and endTime > now:
        startTime = now + timedelta(seconds=2)
        newDuration = endTime - now
        duration = newDuration.total_seconds()

    if not key:
        key = "sk_us-east-1_fakefake"

    try:
        scheduler.add_job(
            stream_game,
            trigger="date",
            run_date=startTime,
            id=name,
            name=name,
            kwargs={"duration": duration, "key": key, "config": config, "name": name},
        )
    except ConflictingIdError:
        logging.info(f"Job '{name}' Already Seen")
        pass
    return name


# List page (main page)
@app.get("/list", response_class=HTMLResponse)
async def list_jobs(request: Request, user=Depends(login_manager)):
    jobs = sorted(scheduler.get_jobs(), key=lambda x: x.next_run_time)
    return templates.TemplateResponse(
        "list.html.j2", {"request": request, "jobs": jobs}
    )


@app.get("/add", response_class=HTMLResponse)
def add(request: Request, user=Depends(login_manager)):
    return templates.TemplateResponse("add.html.j2", {"request": request})


# Parses data from add page
@app.post("/submit", response_class=HTMLResponse)
async def submit(
    teamName: str = Form(...),
    date: str = Form(...),
    startTime: str = Form(...),
    endTime: str = Form(...),
    streamKey: str = Form(...),
    user=Depends(login_manager),
):
    logging.info(
        f"Received form data from {user}: {teamName}, {date}, {startTime}, {endTime}, {streamKey}"
    )

    # Parse the date and time
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        logging.info(f"date {date_obj}")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Unable to understand your date, please go back and try again",
        )

    try:
        start_time_obj = datetime.strptime(startTime, "%H:%M").time()
        end_time_obj = datetime.strptime(endTime, "%H:%M").time()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Unable to understand your time fields. Please go back and try again.",
        )

    # Combine into a datetime object
    start_datetime_obj = datetime.combine(date_obj, start_time_obj).replace(
        tzinfo=local_tz
    )
    end_datetime_obj = datetime.combine(date_obj, end_time_obj).replace(tzinfo=local_tz)

    calculated_duration = end_datetime_obj - start_datetime_obj
    calculated_duration_seconds = int(calculated_duration.total_seconds())

    logging.info(f"Times received {start_datetime_obj}, {end_datetime_obj}")

    new_stream(
        teamName,
        startTime=start_datetime_obj,
        duration=calculated_duration_seconds,
        key=streamKey,
        config=SECRETS,
    )

    # Process the data (implement your logic here)
    html_content = """<html><body><p>Successful. Redirecting...</p><script>window.location.href = "/list";</script></body></html>"""
    return HTMLResponse(content=html_content)


# Route to remove a job
@app.post("/remove_job", response_class=HTMLResponse)
async def remove_job(request: Request, user=Depends(login_manager)):
    logging.info(f"Removing job: {request}")
    form = await request.form()
    logging.info(f"Form: {form}")

    name = form.get("name") or None
    if name:
        try:
            scheduler.remove_job(name)
            return RedirectResponse(url="/list", status_code=303)
        except Exception as e:
            logging.error(f"Error removing job: {e}")
            raise HTTPException(status_code=404, detail=str(e))


################################################################################
# Bash Job wrappers


def stop_subprocess(job_id):
    # Retrieve the process handle
    proc = process_dict.get(job_id)
    if proc:
        # Terminate the process
        proc.terminate()
        print(f"Stopped job {job_id}")
        # Remove the process from the dictionary
        del process_dict[job_id]


################################################################################


# Camera Bits
def input_cam_url(config):
    CAM_HOST = SECRETS["CAM_HOST"]
    CAM_USER = SECRETS["CAM_USER"]
    CAM_PASS = SECRETS["CAM_PASS"]
    INPUT_CAM = f"rtsp://{CAM_USER}:{CAM_PASS}@{CAM_HOST}:554/Streaming/channels/101/"
    return INPUT_CAM


def stream_game(duration=(60 * 4), key="", config={}, name=""):
    logging.info("Starting a stream...")
    pretty_name = name.replace(" ", "_")
    duration = int(duration)

    INPUT_CAM = input_cam_url(config)

    # Game Changer Settings
    GC_BASE = "rtmps://601c62c19c9e.global-contribute.live-video.net:443/app"
    if key == "":
        logging.error("No Destination GC Key Given")
        return
    OUTPUT_GC1 = f"{GC_BASE}/{key}"

    FFMPEG_ENV = os.environ.copy()
    FFMPEG_ENV["FFREPORT"] = f"level=32:file=logs/%p-%t-{pretty_name}.log"

    ffmpeg_command = [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stats",
        "-report",  # Logging options
        "-rtsp_transport",
        "tcp",  # RTSP Options
        "-i",
        INPUT_CAM,  # Input
        "-c:v",
        "copy",
        "-bufsize",
        "12000k",
        "-g",
        "60",  # Video options
        "-c:a",
        "aac",
        "-b:a",
        "128k",  # Audio options
        "-t",
        str(duration),  # Duration
        "-f",
        "flv",
        OUTPUT_GC1,  # Output
    ]

    process = subprocess.Popen(
        ffmpeg_command, stderr=subprocess.PIPE, universal_newlines=True, env=FFMPEG_ENV
    )

    while True:
        output = process.stderr.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            ffmpeg_output_queue.put((name, output.strip()))

    return_code = process.poll()
    return return_code
