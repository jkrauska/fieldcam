"""Web routes for the fieldcam application."""
import logging
from datetime import datetime

from fastapi import Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from .config import login_manager, SECRETS, LOCAL_TZ
from .scheduler import new_stream, get_scheduled_jobs, remove_job


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


async def list_jobs_page(request: Request, user=Depends(login_manager)):
    """Display the list of scheduled jobs."""
    jobs = get_scheduled_jobs()
    return templates.TemplateResponse(
        "list.html.j2", 
        {
            "request": request, 
            "jobs": jobs, 
            "field_name": SECRETS["LOCATION"]
        }
    )


def add_job_page(request: Request, user=Depends(login_manager)):
    """Display the add job form."""
    return templates.TemplateResponse("add.html.j2", {"request": request})


async def submit_job(
    teamName: str = Form(...),
    date: str = Form(...),
    startTime: str = Form(...),
    endTime: str = Form(...),
    streamKey: str = Form(...),
    user=Depends(login_manager),
):
    """
    Handle job submission from the add form.
    
    Parses and validates the form data, then schedules a new stream job.
    """
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
        tzinfo=LOCAL_TZ
    )
    end_datetime_obj = datetime.combine(date_obj, end_time_obj).replace(tzinfo=LOCAL_TZ)

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

    # Redirect to list page
    html_content = """<html><body><p>Successful. Redirecting...</p><script>window.location.href = "/list";</script></body></html>"""
    return HTMLResponse(content=html_content)


async def remove_job_route(request: Request, user=Depends(login_manager)):
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
            raise HTTPException(status_code=404, detail=str(e))
