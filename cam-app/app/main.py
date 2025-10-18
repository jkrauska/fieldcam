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
from .routes import (
    add_job_page,
    get_version,
    list_jobs_page,
    remove_job_route,
    serve_field_image,
    submit_job,
)

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
    """Display list of scheduled jobs."""
    return await list_jobs_page(request, user)


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


@app.get("/version")
def version():
    """Return version information about the application build."""
    return get_version()
