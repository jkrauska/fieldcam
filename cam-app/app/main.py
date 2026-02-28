"""Main entry point for the fieldcam application."""

import json
import logging

from datastar_py.fastapi import DatastarResponse
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Import route handlers
from .auth import (
    handle_login,
    handle_logout,
    http_exception_handler,
)

# Import configuration and setup
from .config import login_manager
from .database import init_db
from .routes import (
    add_job_page,
    cancel_stream_route,
    get_version,
    history_fragment,
    list_jobs_page,
    detection_api,
    detection_fragment,
    remove_job_route,
    save_settings,
    serve_field_image,
    settings_fragment,
    signal_shutdown,
    sse_list,
    submit_job,
)
from .scheduler import start_cleanup_task

# Configure logging - apply consistent format to all loggers including uvicorn
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATEFMT,
)

# Override uvicorn's loggers to use the same format
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    _logger = logging.getLogger(_name)
    _logger.handlers.clear()
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
    _logger.addHandler(_handler)
    _logger.propagate = False

# Initialize FastAPI app
app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware)

from .csrf import CSRFMiddleware  # noqa: E402
app.add_middleware(CSRFMiddleware)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register exception handler
app.add_exception_handler(HTTPException, http_exception_handler)


# Startup event handler
@app.on_event("startup")
async def startup_event():
    """Initialize database and start background tasks on application startup."""
    init_db()
    start_cleanup_task()
    logging.info("Application startup complete - database and cleanup task initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """Signal SSE generators to exit so uvicorn can close connections quickly."""
    signal_shutdown()
    logging.info("Shutdown signal sent")


# Authentication routes
@app.get("/login")
def login_form(next: str = None):
    """Redirect to SPA shell, which shows the login form via the 401 handler."""
    return RedirectResponse(url=next or "/", status_code=302)


@app.post("/login")
async def login(request: Request, response: Response):
    """Handle login submission via Datastar SSE or plain form POST."""
    resp, success, next_url = await handle_login(request, response)
    is_datastar = request.headers.get("datastar-request") == "true"

    if success:
        if is_datastar:
            out = Response(
                content=f"window.location.href = {json.dumps(next_url)};",
                media_type="text/javascript",
            )
        else:
            out = RedirectResponse(url=next_url, status_code=302)
        if resp and "set-cookie" in resp.headers:
            out.headers["set-cookie"] = resp.headers["set-cookie"]
        return out

    if is_datastar:
        from .routes import _make_toast_event
        return DatastarResponse(_make_toast_event("Incorrect password", "bg-danger"))

    from .routes import render_shell_with_login
    return render_shell_with_login(request, next_url, error="Incorrect password.")


@app.get("/logout", response_class=HTMLResponse)
def logout(response: Response):
    """Handle logout."""
    return handle_logout(response)


# Application routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Main page: list of scheduled jobs and active streams (SPA entry)."""
    return await list_jobs_page(request, user)


@app.get("/dynamic/field.jpg")
def dynamic_field_image(user=Depends(login_manager)):  # noqa: B008
    """Serve field camera image without caching (auth required)."""
    return serve_field_image()


@app.get("/add", response_class=HTMLResponse)
def add(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Return add-job form fragment (used by Datastar to reset the modal form)."""
    return add_job_page(request, user)


# Use the submit_job function directly from routes.py
app.post("/submit", response_class=HTMLResponse)(submit_job)


@app.post("/remove_job", response_class=HTMLResponse)
async def remove_job(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Handle job removal."""
    return await remove_job_route(request, user)


@app.post("/cancel_stream", response_class=HTMLResponse)
async def cancel_stream(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Handle canceling an active stream."""
    return await cancel_stream_route(request, user)


@app.get("/version")
def version():
    """Return version information about the application build."""
    return get_version()


app.get("/api/detections")(detection_api)
app.get("/fragment/detections", response_class=HTMLResponse)(detection_fragment)
app.get("/fragment/history", response_class=HTMLResponse)(history_fragment)
app.get("/fragment/settings", response_class=HTMLResponse)(settings_fragment)
app.post("/settings/save", response_class=HTMLResponse)(save_settings)
app.get("/sse/list")(sse_list)
