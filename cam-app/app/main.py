from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form, status
#from fastapi_proxiedheadersmiddleware import ProxiedHeadersMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
#from starlette.middleware import ProxyHeadersMiddleware


from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from fastapi.security import OAuth2PasswordRequestForm
from fastapi_login.exceptions import InvalidCredentialsException
from fastapi_login import LoginManager
from urllib.parse import urlencode

from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta
import logging
import subprocess
import json

from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.base import ConflictingIdError

import atexit

from .random_names import generate_name

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


app.mount("/static", StaticFiles(directory="app/static"), name="static")


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

def create_redirect_content(next: str) -> str:
    return f"""
        <html><head><title>Redirecting...</title>
        <script type="text/javascript">
        setTimeout(function() {{
        window.location.href = "{next}";
        }}, 100);
        </script></head>
        <body><p>Login unsuccessful. Try again?...</p></body>
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

    logging.info(f"Password check")
    if password not in SECRETS["PASSWORDS"]:
        # return InvalidCredentialsException
        return create_redirect_content(next)

    # Redirect to the original page if 'next' is provided
    next_url = next or "/list"

    html_content = f"""<html><body><p>Login successful. Redirecting...</p><script>window.location.href = "{next_url}";</script></body></html>"""
    response = HTMLResponse(content=create_redirect_content(next_url))
    access_token = login_manager.create_access_token(data={"sub": user_id})
    login_manager.set_cookie(response, access_token)
    return response


# Logout route to clear the cookie
@app.get("/logout", response_class=HTMLResponse)
def logout(response: Response):
    response = RedirectResponse(url="/login")
    response.delete_cookie(login_manager.cookie_name)
    return response

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
    now = datetime.now()

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


# Route to add a job
@app.get("/add_job", response_model=dict)
def add_job(request: Request, user=Depends(login_manager)):
    logging.info(f"Adding job {request}")
    try:
        name = new_stream()
        # scheduler.add_job(
        #     func=stream_game,
        #     trigger="date",
        #     run_date=request.run_date,
        #     args=[request.param1, request.param2],
        #     id=request.job_id,
        #     replace_existing=True,
        # )
        return {"message": f"Job {name} added successfully"}
    except Exception as e:
        logging.error(f"Error adding job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list", response_class=HTMLResponse)
async def list_jobs(request: Request, user=Depends(login_manager)):
    jobs = sorted(scheduler.get_jobs(), key=lambda x: x.next_run_time)
    return templates.TemplateResponse(
        "list.html.j2", {"request": request, "jobs": jobs}
    )

@app.get("/add", response_class=HTMLResponse)
def add(request: Request, user=Depends(login_manager)):
    return templates.TemplateResponse(
        "add.html.j2", {"request": request}
    )

@app.post("/submit", response_class=HTMLResponse)
async def submit(
    teamName: str = Form(...),
    date: str = Form(...),
    startTime: str = Form(...),
    endTime: str = Form(...),
    streamKey: str = Form(...),
):
    logging.info(f"Received form data: {teamName}, {date}, {startTime}, {endTime}, {streamKey}")

    # Parse the date and time
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Unable to understand your date, please go back and try again")

    try:
        start_time_obj = datetime.strptime(startTime, "%H:%M").time()
        end_time_obj = datetime.strptime(endTime, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Unable to understand your time fields. Please go back and try again.")

    # Combine into a datetime object
    start_datetime_obj = datetime.combine(date_obj, start_time_obj)
    end_datetime_obj = datetime.combine(date_obj, end_time_obj)

    calculated_duration = end_datetime_obj - start_datetime_obj
    calculated_duration_seconds = int(calculated_duration.total_seconds())

    new_stream(
        teamName,
        startTime=start_datetime_obj,
        duration=calculated_duration_seconds,
        key=streamKey,
        config=SECRETS,
    )

    # Process the data (implement your logic here)
    html_content = f"""<html><body><p>Successful. Redirecting...</p><script>window.location.href = "/list";</script></body></html>"""
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
            return RedirectResponse(url="/list",status_code=303)
        except Exception as e:
            logging.error(f"Error removing job: {e}")
            raise HTTPException(status_code=404, detail=str(e))



################################################################################
# Bash Job wrappers

def run_bash_command(cmd):
    logging.info(f"Starting {cmd}")

    try:
        subprocess.run(cmd, check=True, shell=True)
        logging.info("Exited")

    except subprocess.CalledProcessError as e:
        logging.error(f"Error: {e}")


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
    duration = int(duration)

    INPUT_CAM = input_cam_url(config)

    # Game Changer Settings
    GC_BASE = "rtmps://601c62c19c9e.global-contribute.live-video.net:443/app"

    if key:
        GC_KEY = key
    else:
        logging.error("No Destination GC Key Given")
        return

    OUTPUT_GC1 = f"{GC_BASE}/{GC_KEY}"

    # ffmpeg options
    LOG_OPTS = "-hide_banner -loglevel error -stats -report "
    RSTP_OPTS = "-rtsp_transport tcp "
    VIDEO_OPTS = "-c:v copy -bufsize 12000k -g 60 "
    AUDIO_OPTS = "-c:a aac -b:a 128k"

    # Single output
    OUTPUT = f'-f flv "{OUTPUT_GC1}" '

    FFMPEG_BIN="/usr/bin/ffmpeg" # OS Package
    # FFMPEG_BIN="/usr/local/bin/ffmpeg "  # local compile, not working reliably

    pretty_name = name.replace(" ", "_")
    cmd = f'FFREPORT="level=32:file=logs/%p-%t-{pretty_name}.log" {FFMPEG_BIN} '  # apt install

    cmd += f"{LOG_OPTS} -thread_queue_size 256 "
    cmd += f"{RSTP_OPTS} -i {INPUT_CAM} "
    cmd += f"{VIDEO_OPTS} {AUDIO_OPTS} -t {duration} "
    cmd += f"{OUTPUT}"

    run_bash_command(cmd)
