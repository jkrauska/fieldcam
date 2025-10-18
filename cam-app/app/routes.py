"""Web routes for the fieldcam application."""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import LOCAL_TZ, login_manager, settings
from .scheduler import get_scheduled_jobs, new_stream, remove_job


def format_datetime(value, format="%Y-%m-%d %H:%M:%S"):
    """Format a datetime object to a string using strftime."""
    if value is None:
        return ""
    return value.strftime(format)


# Set up the templates directory
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["datetime"] = format_datetime


def serve_field_image():
    """Serve the field camera image with no-cache headers."""
    file_path = "app/static/field.jpg"
    headers = {
        "Cache-Control": "no-store"  # Disable caching
    }
    return FileResponse(file_path, media_type="image/jpeg", headers=headers)


async def list_jobs_page(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Display the list of scheduled jobs."""
    jobs = get_scheduled_jobs()
    return templates.TemplateResponse(
        "list.html.j2", {"request": request, "jobs": jobs, "field_name": settings.location}
    )


def add_job_page(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Display the add job form."""
    return templates.TemplateResponse("add.html.j2", {"request": request})


async def submit_job(
    team_name: str = Form(..., alias="teamName"),
    date: str = Form(...),
    start_time: str = Form(..., alias="startTime"),
    end_time: str = Form(..., alias="endTime"),
    stream_key: str = Form(..., alias="streamKey"),
    user=Depends(login_manager),  # noqa: B008
):
    """
    Handle job submission from the add form.

    Parses and validates the form data, then schedules a new stream job.
    """
    logging.info(
        f"Received form data from {user}: {team_name}, {date}, {start_time}, "
        f"{end_time}, {stream_key}"
    )

    # Parse the date and time
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        logging.info(f"date {date_obj}")
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail="Unable to understand your date, please go back and try again",
        ) from e

    try:
        start_time_obj = datetime.strptime(start_time, "%H:%M").time()
        end_time_obj = datetime.strptime(end_time, "%H:%M").time()
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail="Unable to understand your time fields. Please go back and try again.",
        ) from e

    # Combine into a datetime object
    start_datetime_obj = datetime.combine(date_obj, start_time_obj).replace(tzinfo=LOCAL_TZ)
    end_datetime_obj = datetime.combine(date_obj, end_time_obj).replace(tzinfo=LOCAL_TZ)

    calculated_duration = end_datetime_obj - start_datetime_obj
    calculated_duration_seconds = int(calculated_duration.total_seconds())

    logging.info(f"Times received {start_datetime_obj}, {end_datetime_obj}")

    new_stream(
        team_name,
        start_time=start_datetime_obj,
        duration=calculated_duration_seconds,
        key=stream_key,
        config={},
    )

    # Redirect to list page
    html_content = (
        "<html><body><p>Successful. Redirecting...</p>"
        '<script>window.location.href = "/list";</script></body></html>'
    )
    return HTMLResponse(content=html_content)


async def remove_job_route(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Handle job removal."""
    logging.info(f"Removing job: {request}")
    form = await request.form()
    logging.info(f"Form: {form}")

    name = form.get("name") or None
    if name:
        try:
            remove_job(name)
            return RedirectResponse(url="/list", status_code=303)
        except Exception as e:
            logging.error(f"Error removing job: {e}")
            raise HTTPException(status_code=404, detail=str(e)) from e


def get_version():
    """
    Return version information including git commit, branch, and build time.

    Returns a JSON response with:
    - git_commit: Full git commit hash
    - git_commit_short: Abbreviated 7-character commit hash
    - git_branch: Git branch name
    - build_time: ISO 8601 formatted build timestamp
    """
    version_file = Path("app/version.json")

    try:
        if version_file.exists():
            with open(version_file) as f:
                version_data = json.load(f)

            # Add short commit hash
            git_commit = version_data.get("git_commit", "unknown")
            version_data["git_commit_short"] = (
                git_commit[:7] if git_commit != "unknown" else "unknown"
            )

            return JSONResponse(content=version_data)
        else:
            return JSONResponse(
                content={
                    "git_commit": "unknown",
                    "git_commit_short": "unknown",
                    "git_branch": "unknown",
                    "build_time": "unknown",
                    "error": "version.json not found",
                }
            )
    except Exception as e:
        logging.error(f"Error reading version file: {e}")
        return JSONResponse(
            content={
                "git_commit": "unknown",
                "git_commit_short": "unknown",
                "git_branch": "unknown",
                "build_time": "unknown",
                "error": str(e),
            },
            status_code=500,
        )
