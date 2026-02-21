"""Web routes for the fieldcam application."""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .config import LOCAL_TZ, login_manager, settings
from .database import get_active_streams, get_all_streams
from .scheduler import cancel_stream, get_scheduled_jobs, new_stream, remove_job


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


def _list_context(request: Request):
    """Build context for list page / list-content fragment (jobs, active_streams, field_name)."""
    jobs = get_scheduled_jobs()
    active_streams = get_active_streams()
    for stream in active_streams:
        if stream.start_time:
            utc_time = datetime.fromisoformat(stream.start_time.replace("Z", "+00:00"))
            local_time = utc_time.replace(tzinfo=None).astimezone(LOCAL_TZ)
            stream.start_time_local = local_time
    return {
        "request": request,
        "jobs": jobs,
        "active_streams": active_streams,
        "field_name": settings.location,
    }


def _render_list_content_fragment(request: Request):
    """Render the list-content fragment for Data-Star patch (single div#list-content)."""
    ctx = _list_context(request)
    content = templates.env.get_template("_list_content.html.j2").render(**ctx)
    return f'<div id="list-content">\n{content}\n</div>'


async def list_jobs_page(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Display the list of scheduled jobs and active streams."""
    ctx = _list_context(request)
    ctx["request"] = request
    return templates.TemplateResponse(
        "list.html.j2",
        ctx,
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

    # Data-Star: return fragment to patch add-form-container; fallback for non-JS is same fragment as full response
    html_content = (
        '<div id="add-form-container">'
        '<p class="alert alert-success">Stream scheduled successfully.</p>'
        '<p><a href="/list" class="btn btn-primary">Back to list</a></p>'
        "</div>"
    )
    return HTMLResponse(content=html_content)


async def remove_job_route(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Handle job removal. Returns HTML fragment for Data-Star to morph into #list-content."""
    logging.info(f"Removing job: {request}")
    form = await request.form()
    logging.info(f"Form: {form}")

    name = form.get("name") or None
    if name:
        try:
            remove_job(name)
            html = _render_list_content_fragment(request)
            return HTMLResponse(content=html)
        except Exception as e:
            logging.error(f"Error removing job: {e}")
            raise HTTPException(status_code=404, detail=str(e)) from e


async def cancel_stream_route(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Handle canceling an active stream. Returns HTML fragment for Data-Star to morph into #list-content."""
    logging.info(f"Canceling stream: {request}")
    form = await request.form()
    logging.info(f"Form: {form}")

    name = form.get("name") or None
    if name:
        try:
            success = cancel_stream(name)
            if success:
                logging.info(f"Successfully cancelled stream: {name}")
            else:
                logging.warning(f"Failed to cancel stream: {name}")
            html = _render_list_content_fragment(request)
            return HTMLResponse(content=html)
        except Exception as e:
            logging.error(f"Error canceling stream: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e


async def list_all_streams_page(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Display complete stream history."""
    all_streams = get_all_streams()

    # Convert UTC timestamps to local timezone for display
    for stream in all_streams:
        if stream.start_time:
            # Parse ISO format UTC timestamp
            utc_time = datetime.fromisoformat(stream.start_time.replace("Z", "+00:00"))
            # Convert to local timezone
            local_time = utc_time.replace(tzinfo=None).astimezone(LOCAL_TZ)
            stream.start_time_local = local_time

    return templates.TemplateResponse(
        "list_all.html.j2",
        {
            "request": request,
            "streams": all_streams,
            "field_name": settings.location,
        },
    )


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
