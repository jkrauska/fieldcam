"""Web routes for the fieldcam application."""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.consts import ElementPatchMode
from datastar_py.fastapi import DatastarResponse
from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import LOCAL_TZ, login_manager, settings
from .database import get_active_streams, get_all_streams
from .event_bus import get_list_version, notify_list_changed
from .scheduler import cancel_stream, get_scheduled_jobs, new_stream, remove_job
from .yolo_check import detect_objects

# Shutdown flag — set by the FastAPI shutdown event so SSE generators exit promptly
_shutting_down = False


def signal_shutdown():
    """Called by the app shutdown event to break SSE loops."""
    global _shutting_down
    _shutting_down = True


def format_datetime(value, format="%Y-%m-%d %H:%M:%S"):
    """Format a datetime object to a string using strftime."""
    if value is None:
        return ""
    return value.strftime(format)


def clean_job_name(value):
    """Normalize legacy job names for display."""
    return value.replace("SFLL ", "").replace("Pirates Majors", "Majors Pirates")


# Set up the templates directory
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["datetime"] = format_datetime
templates.env.filters["clean_name"] = clean_job_name


def serve_field_image():
    """Serve the field camera image with no-cache headers (reads from field_image_path, e.g. /tmp/field.jpg)."""
    file_path = Path(settings.field_image_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Field image not available")
    headers = {
        "Cache-Control": "no-store"  # Disable caching
    }
    return FileResponse(str(file_path), media_type="image/jpeg", headers=headers)


_detection_cache: dict = {"text": "\u2014", "expires": 0.0}
_DETECTION_TTL = 60


def _get_detection_text() -> str:
    """Return object detection summary as display text, cached for 60 seconds."""
    now = time.time()
    if now > _detection_cache["expires"]:
        result = detect_objects(image_path=settings.field_image_path)
        counts = result.get("counts")
        if counts:
            parts = [f"{n} {name}{'s' if n != 1 else ''}"
                     for name, n in counts.items() if n > 0]
            _detection_cache["text"] = ", ".join(parts) if parts else "0"
        else:
            _detection_cache["text"] = "\u2014"
        _detection_cache["expires"] = now + _DETECTION_TTL
    return _detection_cache["text"]


def _list_context(request: Request):
    """Build context for list page / list-content fragment."""
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
        "detection_text": _get_detection_text(),
    }


def _render_list_inner(request: Request) -> str:
    """Render just the list-content template HTML (no wrapper div)."""
    ctx = _list_context(request)
    return templates.env.get_template("_list_content.html.j2").render(**ctx)


def _render_list_content_fragment(request: Request):
    """Render the list-content fragment with the SSE-connected wrapper div.

    The wrapper div opens an SSE connection so all viewers get live updates.
    """
    content = _render_list_inner(request)
    return f'<div id="list-content" data-init="@get(\'/sse/list\')">\n{content}\n</div>'


def _is_fragment_request(request: Request) -> bool:
    """True when client wants only the main content fragment (SPA navigation)."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.headers.get("Datastar-Request") == "true"
    )


def _fragment_response(content: str, selector: str = "#app-content", mode: str = "inner"):
    """Return HTMLResponse with Datastar patch headers for SPA fragment."""
    return HTMLResponse(
        content=content,
        headers={"datastar-selector": selector, "datastar-mode": mode},
    )


def _render_add_fragment(request: Request) -> str:
    """Render the add-job form fragment for SPA."""
    now = datetime.now(tz=LOCAL_TZ)
    blackout = [t.strip() for t in settings.blackout_teams.split(",") if t.strip()]
    return templates.env.get_template("_add_content.html.j2").render(
        request=request,
        default_date=now.strftime("%Y-%m-%d"),
        default_time=now.strftime("%H:%M"),
        blackout_season=settings.blackout_season,
        blackout_teams=blackout,
    )


def _render_list_all_fragment(request: Request, streams, field_name: str) -> str:
    """Render the list_all content fragment for SPA."""
    return templates.env.get_template("_list_all_content.html.j2").render(
        request=request,
        streams=streams,
        field_name=field_name,
    )


def _render_shell(
    request: Request,
    page_content: str,
    page_title: str = "Live Stream",
    user=None,
):
    """Render the SPA shell with the given main content."""
    now = datetime.now(tz=LOCAL_TZ)
    blackout = [t.strip() for t in settings.blackout_teams.split(",") if t.strip()]
    return templates.TemplateResponse(
        "base_shell.html.j2",
        {
            "request": request,
            "page_content": page_content,
            "page_title": page_title,
            "user": user,
            "default_date": now.strftime("%Y-%m-%d"),
            "default_time": now.strftime("%H:%M"),
            "blackout_season": settings.blackout_season,
            "blackout_teams": blackout,
        },
    )


def _render_login_fragment(request: Request, next_url: str, error: str | None = None) -> str:
    """Render login form fragment for in-shell or patch (SPA login)."""
    return templates.env.get_template("_login_content.html.j2").render(
        request=request,
        next_url=next_url,
        error=error,
    )


def render_shell_with_login(request: Request, next_url: str, error: str | None = None):
    """Return SPA shell with login form as main content (no redirect, URL stays /)."""
    content = _render_login_fragment(request, next_url, error)
    return _render_shell(
        request,
        content,
        page_title="FieldCam",
        user=None,
    )


async def list_jobs_page(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Display the list of scheduled jobs and active streams."""
    if _is_fragment_request(request):
        return _fragment_response(_render_list_content_fragment(request))
    page_content = _render_list_content_fragment(request)
    return _render_shell(request, page_content, page_title="Live Stream", user=user)


def add_job_page(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Display the add job form (fragment for modal); full GET /add redirects to list."""
    if _is_fragment_request(request):
        return _fragment_response(
            _render_add_fragment(request),
            selector="#add-form-container",
            mode="outer",
        )
    return RedirectResponse(url="/", status_code=302)


async def submit_job(
    request: Request,
    team_name: str = Form(..., alias="teamName"),
    date: str = Form(...),
    start_time: str = Form(..., alias="startTime"),
    duration_hours: int = Form(2, alias="durationHours"),
    duration_minutes: int = Form(30, alias="durationMinutes"),
    stream_key: str = Form(..., alias="streamKey"),
    destination: str = Form("gamechanger"),
    custom_url: str = Form("", alias="customUrl"),
    user=Depends(login_manager),  # noqa: B008
):
    """
    Handle job submission from the add form.

    Parses and validates the form data, then schedules a new stream job.
    """
    logging.info(
        f"Received form data from {user}: {team_name}, {date}, {start_time}, "
        f"duration={duration_hours}h{duration_minutes}m, {stream_key}, destination={destination}"
    )

    # --- Input validation ---
    duration_hours = max(0, min(duration_hours, 6))
    duration_minutes = max(0, min(duration_minutes, 55))
    if duration_hours == 0 and duration_minutes == 0:
        raise HTTPException(status_code=400, detail="Duration must be greater than zero.")

    stream_key = stream_key.strip()
    if not stream_key:
        raise HTTPException(status_code=400, detail="Stream key is required.")

    if destination not in ("gamechanger", "youtube", "custom"):
        raise HTTPException(status_code=400, detail="Invalid destination.")

    if destination == "custom":
        custom_url = custom_url.strip()
        if not custom_url:
            raise HTTPException(status_code=400, detail="Custom RTMP URL is required for custom destinations.")
        if not custom_url.startswith(("rtmp://", "rtmps://")):
            raise HTTPException(status_code=400, detail="Custom URL must start with rtmp:// or rtmps://")

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
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail="Unable to understand your start time. Please go back and try again.",
        ) from e

    start_datetime_obj = datetime.combine(date_obj, start_time_obj).replace(tzinfo=LOCAL_TZ)
    calculated_duration_seconds = (duration_hours * 3600) + (duration_minutes * 60)

    # Warn if the stream would end entirely in the past
    now = datetime.now(tz=LOCAL_TZ)
    end_datetime = start_datetime_obj + timedelta(seconds=calculated_duration_seconds)
    if end_datetime < now:
        raise HTTPException(
            status_code=400,
            detail="This stream's end time is in the past. Please pick a later date or time.",
        )

    logging.info(f"Start {start_datetime_obj}, duration {calculated_duration_seconds}s")

    new_stream(
        team_name,
        start_time=start_datetime_obj,
        duration=calculated_duration_seconds,
        key=stream_key,
        config={},
        destination=destination,
        custom_url=custom_url,
    )
    notify_list_changed()

    list_html = _render_list_inner(request)
    form_html = _render_add_fragment(request)
    return DatastarResponse([
        SSE.patch_elements(list_html, selector="#list-content", mode=ElementPatchMode.INNER),
        SSE.patch_elements(form_html, selector="#add-form-container", mode=ElementPatchMode.INNER),
        _make_toast_event("Stream scheduled"),
    ])


async def remove_job_route(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Handle job removal. Returns HTML fragment for Data-Star to morph into #list-content."""
    logging.info(f"Removing job: {request}")
    form = await request.form()
    logging.info(f"Form: {form}")

    name = form.get("name") or None
    if name:
        try:
            remove_job(name)
            notify_list_changed()
            html = _render_list_inner(request)
            return DatastarResponse(
                SSE.patch_elements(html, selector="#list-content", mode=ElementPatchMode.INNER)
            )
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
            notify_list_changed()
            html = _render_list_inner(request)
            return DatastarResponse(
                SSE.patch_elements(html, selector="#list-content", mode=ElementPatchMode.INNER)
            )
        except Exception as e:
            logging.error(f"Error canceling stream: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e


async def history_fragment(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Return stream history table as a fragment for the history modal."""
    all_streams = get_all_streams()
    for stream in all_streams:
        if stream.start_time:
            utc_time = datetime.fromisoformat(stream.start_time.replace("Z", "+00:00"))
            local_time = utc_time.replace(tzinfo=None).astimezone(LOCAL_TZ)
            stream.start_time_local = local_time
    html = _render_list_all_fragment(request, all_streams, settings.location)
    return _fragment_response(html, selector="#history-modal-body", mode="inner")


async def detection_api(user=Depends(login_manager)):  # noqa: B008
    """
    Run YOLO on the current field image and return detected object counts.

    Returns JSON with counts per class, total, details, etc.
    """
    result = await asyncio.to_thread(detect_objects, image_path=settings.field_image_path)
    if result.get("error") and result.get("counts") is None:
        raise HTTPException(
            status_code=503 if "not installed" in result.get("error", "") else 404,
            detail=result["error"],
        )
    return JSONResponse(content=result)


async def detection_fragment(user=Depends(login_manager)):  # noqa: B008
    """Return detection counts as an HTML fragment for Datastar to morph into #detections."""
    result = await asyncio.to_thread(detect_objects, image_path=settings.field_image_path)
    counts = result.get("counts")
    if counts:
        parts = [f"{n} {name}{'s' if n != 1 else ''}"
                 for name, n in counts.items() if n > 0]
        text = ", ".join(parts) if parts else "0"
    else:
        text = "\u2014"
    html = f'Detections: <span aria-live="polite">{text}</span>'
    return _fragment_response(html, selector="#detections", mode="inner")


def _make_toast_event(message: str, bg: str = "bg-success") -> str:
    """Build an SSE event that patches a Bootstrap toast into #toast-area."""
    toast = (
        f'<div class="toast show align-items-center text-white {bg} border-0"'
        ' role="alert" style="animation:toast-fade 2s ease-in forwards">'
        f'<div class="toast-body text-center">{message}</div></div>'
    )
    return SSE.patch_elements(toast, selector="#toast-area", mode=ElementPatchMode.INNER)


async def sse_list(request: Request, user=Depends(login_manager)):  # noqa: B008
    """SSE endpoint: streams list content updates to all connected viewers.

    Polls the event bus version counter every 2 seconds.  When a change is
    detected the list-content fragment is re-rendered and pushed.  A keepalive
    comment is sent every 30 seconds to prevent proxy/browser timeouts.
    """

    async def event_generator():
        # Start at the current version so we don't immediately re-push the
        # same content the server already rendered into the initial page.
        last_version = get_list_version()
        last_send = time.time()
        try:
            while not _shutting_down and not await request.is_disconnected():
                current_version = get_list_version()
                now = time.time()

                if current_version != last_version:
                    last_version = current_version
                    content = _render_list_inner(request)
                    yield SSE.patch_elements(
                        content, selector="#list-content", mode=ElementPatchMode.INNER
                    )
                    last_send = now
                elif now - last_send > 30:
                    yield ": keepalive\n\n"
                    last_send = now

                # Short sleep so we notice _shutting_down quickly
                for _ in range(10):
                    if _shutting_down:
                        return
                    await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass

    return DatastarResponse(event_generator())


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
