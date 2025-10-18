"""Main entry point for the fieldcam application."""

import logging

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Import route handlers
from .auth import (
    get_login_form,
    handle_login,
    handle_logout,
    http_exception_handler,
)

# Import configuration and setup
from .database import init_db
from .routes import (
    add_job_page,
    cancel_stream_route,
    get_version,
    list_all_streams_page,
    list_jobs_page,
    remove_job_route,
    serve_field_image,
    submit_job,
)
from .scheduler import start_cleanup_task

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Initialize FastAPI app
app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware)

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


# Authentication routes
@app.get("/login", response_class=HTMLResponse)
def login_form(next: str = None):
    """Display login form."""
    return get_login_form(next)


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, response: Response):
    """Handle login submission."""
    return await handle_login(request, response)


@app.get("/logout", response_class=HTMLResponse)
def logout(response: Response):
    """Handle logout."""
    return handle_logout(response)


# Application routes
@app.get("/dynamic/field.jpg")
def dynamic_field_image():
    """Serve field camera image without caching."""
    return serve_field_image()


@app.get("/list", response_class=HTMLResponse)
async def list_jobs(request: Request, user=None):
    """Display list of scheduled jobs and active streams."""
    return await list_jobs_page(request, user)


@app.get("/list_all", response_class=HTMLResponse)
async def list_all(request: Request, user=None):
    """Display complete stream history."""
    return await list_all_streams_page(request, user)


@app.get("/add", response_class=HTMLResponse)
def add(request: Request, user=None):
    """Display add job form."""
    return add_job_page(request, user)


# Use the submit_job function directly from routes.py
app.post("/submit", response_class=HTMLResponse)(submit_job)


@app.post("/remove_job", response_class=HTMLResponse)
async def remove_job(request: Request, user=None):
    """Handle job removal."""
    return await remove_job_route(request, user)


@app.post("/cancel_stream", response_class=HTMLResponse)
async def cancel_stream(request: Request, user=None):
    """Handle canceling an active stream."""
    return await cancel_stream_route(request, user)


@app.get("/version")
def version():
    """Return version information about the application build."""
    return get_version()
