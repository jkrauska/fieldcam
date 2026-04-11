"""Web routes for the fieldcam application."""

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from datastar_py import ServerSentEventGenerator as SSE  # noqa: N814
from datastar_py.consts import ElementPatchMode
from datastar_py.fastapi import DatastarResponse
from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import _ENV_FILE, LOCAL_TZ, login_manager, settings
from .database import delete_stream_by_id, get_active_streams, get_all_streams
from .event_bus import get_list_version, get_stats_version, get_stream_stats, notify_list_changed
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


# Load build version once at import time
_version_file = Path("app/version.json")
try:
    _v = json.loads(_version_file.read_text()) if _version_file.exists() else {}
    _build_time = _v.get("build_time", "")
    _build_date = _build_time[:10].replace("-", "") if _build_time else "?"
    APP_VERSION = f"Version: {_v.get('git_branch', '?')}@{_v.get('git_commit', '?')[:7]} ({_build_date})"
except Exception:
    APP_VERSION = "dev"

_START_TIME = time.time()


def _localize_stream_times(streams):
    """Convert UTC start_time strings to local timezone on each stream object."""
    for stream in streams:
        if stream.start_time:
            utc_time = datetime.fromisoformat(stream.start_time.replace("Z", "+00:00"))
            stream.start_time_local = utc_time.replace(tzinfo=None).astimezone(LOCAL_TZ)


def _format_detection_counts(counts: dict) -> str:
    """Format YOLO detection counts dict into a human-readable string."""
    if not counts:
        return "\u2014"
    parts = [f"{n} {name}{'s' if n != 1 else ''}" for name, n in counts.items() if n > 0]
    return ", ".join(parts) if parts else "0"


def _cpu_temp() -> str:
    """Return CPU temperature in °C, or '—' if unavailable."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read().strip()) / 1000:.1f}°C"
    except OSError:
        return "—"


def _uptime_text() -> str:
    """Return human-readable uptime like '3 days' or '45 minutes'."""
    secs = int(time.time() - _START_TIME)
    if secs >= 86400:
        return f"{secs // 86400} day{'s' if secs >= 172800 else ''}"
    if secs >= 3600:
        return f"{secs // 3600} hour{'s' if secs >= 7200 else ''}"
    return f"{max(secs // 60, 1)} minute{'s' if secs >= 120 else ''}"


# Set up the templates directory
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["datetime"] = format_datetime
templates.env.filters["clean_name"] = clean_job_name


_PLACEHOLDER_IMAGE = Path(__file__).resolve().parent / "static" / "placeholder_field.jpg"


def serve_field_image():
    """Serve the field camera image, falling back to a placeholder if missing/corrupt."""
    file_path = Path(settings.field_image_path)
    if file_path.is_file() and file_path.stat().st_size > 0:
        return FileResponse(
            str(file_path),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    return FileResponse(
        str(_PLACEHOLDER_IMAGE),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


_detection_cache: dict = {"text": "\u2014", "expires": 0.0}
_DETECTION_TTL = 60
_detection_refresh_lock = threading.Lock()


def _refresh_detection_cache():
    """Run YOLO detection and update the cache (called from a background thread)."""
    try:
        result = detect_objects(image_path=settings.field_image_path, model_name=settings.yolo_model)
        _detection_cache["text"] = _format_detection_counts(result.get("counts"))
        _detection_cache["expires"] = time.time() + _DETECTION_TTL
    except Exception:
        logging.exception("Background detection refresh failed")


def _get_detection_text() -> str:
    """Return cached detection text, never blocking the request.

    When the cache is stale, a background thread is spawned to refresh it.
    The first call ever returns the default placeholder until the background
    refresh completes.
    """
    if time.time() > _detection_cache["expires"]:
        if _detection_refresh_lock.acquire(blocking=False):
            try:
                threading.Thread(target=_do_detection_refresh, daemon=True).start()
            except Exception:
                _detection_refresh_lock.release()
    return _detection_cache["text"]


def _do_detection_refresh():
    """Thread target: refresh cache then release the lock."""
    try:
        _refresh_detection_cache()
    finally:
        _detection_refresh_lock.release()


def _list_context(request: Request):
    """Build context for list page / list-content fragment."""
    jobs = get_scheduled_jobs()
    active_streams = get_active_streams()
    _localize_stream_times(active_streams)
    return {
        "request": request,
        "jobs": jobs,
        "active_streams": active_streams,
        "field_name": settings.location,
        "detection_text": _get_detection_text(),
        "cache_bust": int(time.time()),
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
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.headers.get("Datastar-Request") == "true"


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


def _render_list_all_fragment(request: Request, streams, field_name: str, user=None) -> str:
    """Render the list_all content fragment for SPA."""
    return templates.env.get_template("_list_all_content.html.j2").render(
        request=request,
        streams=streams,
        field_name=field_name,
        is_admin=user and user.get("is_admin", False),
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
            "app_version": APP_VERSION,
            "app_uptime": _uptime_text(),
            "cpu_temp": _cpu_temp(),
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
    return DatastarResponse(
        [
            SSE.patch_elements(list_html, selector="#list-content", mode=ElementPatchMode.INNER),
            SSE.patch_elements(form_html, selector="#add-form-container", mode=ElementPatchMode.INNER),
            _make_toast_event("Stream scheduled"),
        ]
    )


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
            return DatastarResponse(SSE.patch_elements(html, selector="#list-content", mode=ElementPatchMode.INNER))
        except Exception as e:
            error_id = uuid.uuid4().hex[:8].upper()
            logging.error("Error removing job [%s]: %s", error_id, e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Please send support this message: ERROR: {error_id}") from e


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
            return DatastarResponse(SSE.patch_elements(html, selector="#list-content", mode=ElementPatchMode.INNER))
        except Exception as e:
            error_id = uuid.uuid4().hex[:8].upper()
            logging.error("Error canceling stream [%s]: %s", error_id, e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Please send support this message: ERROR: {error_id}") from e


async def history_fragment(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Return stream history table as a fragment for the history modal."""
    all_streams = get_all_streams()
    _localize_stream_times(all_streams)
    html = _render_list_all_fragment(request, all_streams, settings.location, user=user)
    return _fragment_response(html, selector="#history-modal-body", mode="inner")


async def delete_history_entry(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Delete a single stream history entry (admin only)."""
    _require_admin(user)
    form = await request.form()
    stream_id = form.get("id")
    if not stream_id:
        raise HTTPException(status_code=400, detail="Missing stream id")

    try:
        deleted = delete_stream_by_id(int(stream_id))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail="Invalid stream id") from e

    if not deleted:
        raise HTTPException(status_code=404, detail="Stream entry not found")

    all_streams = get_all_streams()
    _localize_stream_times(all_streams)
    html = _render_list_all_fragment(request, all_streams, settings.location, user=user)
    return DatastarResponse(
        [
            SSE.patch_elements(html, selector="#history-modal-body", mode=ElementPatchMode.INNER),
            _make_toast_event("History entry removed"),
        ]
    )


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
    text = _format_detection_counts(result.get("counts"))
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
                    yield SSE.patch_elements(content, selector="#list-content", mode=ElementPatchMode.INNER)
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


def _format_bitrate_short(bitrate: str) -> str:
    """Convert e.g. '4040.9kbits/s' to '4Mb/s'."""
    if not bitrate or bitrate == "N/A":
        return ""
    bitrate = bitrate.strip()
    try:
        if "kbits/s" in bitrate:
            kbits = float(bitrate.replace("kbits/s", ""))
            if kbits >= 1000:
                return f"{kbits / 1000:.0f}Mb/s"
            return f"{kbits:.0f}kb/s"
    except ValueError:
        pass
    return bitrate


def _format_elapsed_of_total(out_time: str, duration_secs: int) -> str:
    """Format 'MM:SS of MM:SSm' from out_time HH:MM:SS and total duration seconds."""
    # Parse out_time
    parts = out_time.split(":")
    try:
        elapsed_s = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        elapsed_s = 0
    em, es = divmod(elapsed_s, 60)
    tm, ts = divmod(duration_secs, 60)
    return f"{em:02d}:{es:02d} of {tm:02d}:{ts:02d}"


def _render_stream_health_patches(stats: dict[str, dict], active_streams) -> list[tuple[str, str, str]]:
    """Return list of (selector, html, mode) tuples for patching stream table cells."""
    # Build a lookup of duration by job_name from active_streams
    durations = {}
    for stream in active_streams:
        durations[stream.job_name] = stream.duration

    patches = []
    for name, s in stats.items():
        bitrate = _format_bitrate_short(s.get("bitrate", "N/A"))
        out_time = s.get("out_time", "00:00:00")
        duration = durations.get(name, 0)

        # Status cell: "LIVE 4Mb/s"
        rate_text = f" {bitrate}" if bitrate else ""
        status_html = f'<span class="badge bg-success"><i class="bi bi-broadcast-pin"></i> LIVE{rate_text}</span>'
        patches.append((f"#stream-status-{name.replace(' ', '_')}", status_html))

        # Duration cell: "01:23 of 60:00"
        duration_html = _format_elapsed_of_total(out_time, duration)
        patches.append((f"#stream-duration-{name.replace(' ', '_')}", duration_html))

    return patches


async def sse_stream_health(request: Request, user=Depends(login_manager)):  # noqa: B008
    """SSE endpoint: pushes real-time ffmpeg stats into stream table cells.

    Polls the stats version counter every second. When new stats arrive,
    individual Status and Duration cells are patched via Datastar.
    """

    async def event_generator():
        last_version = get_stats_version()
        last_send = time.time()
        try:
            while not _shutting_down and not await request.is_disconnected():
                current_version = get_stats_version()
                now = time.time()

                if current_version != last_version:
                    last_version = current_version
                    stats = get_stream_stats()
                    active = get_active_streams()
                    patches = _render_stream_health_patches(stats, active)
                    for selector, html in patches:
                        yield SSE.patch_elements(html, selector=selector, mode=ElementPatchMode.INNER)
                    last_send = now
                elif now - last_send > 30:
                    yield ": keepalive\n\n"
                    last_send = now

                # Poll every second for responsive stats updates
                for _ in range(5):
                    if _shutting_down:
                        return
                    await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass

    return DatastarResponse(event_generator())


def _require_admin(user):
    """Raise 403 if user is not an admin."""
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")


# --- Editable .env settings definition ---
# Each group: (label, caution, [(env_key, display_label, input_type)])
_SETTINGS_GROUPS = [
    (
        "Application",
        False,
        [
            ("LOCATION", "Location name", "text"),
            ("BLACKOUT_SEASON", "Blackout season", "text"),
            ("BLACKOUT_TEAMS", "Blackout teams (comma-separated)", "text"),
            ("TIMEZONE", "Timezone", "text"),
            ("TOKEN_EXPIRY_MINUTES", "Token expiry (minutes)", "number"),
        ],
    ),
    (
        "Authentication",
        False,
        [
            ("PASSWORDS", "Passwords (comma-separated)", "text"),
            ("ADMIN_PASSWORD", "Admin password", "text"),
        ],
    ),
    (
        "Camera",
        True,
        [
            ("CAMERA_IP", "Camera IP", "text"),
            ("CAMERA_USER", "Camera username", "text"),
            ("CAMERA_PASS", "Camera password", "text"),
        ],
    ),
    (
        "Streaming",
        False,
        [
            ("RTMP_GAMECHANGER", "RTMP GameChanger URL", "text"),
            ("RTMP_YOUTUBE", "RTMP YouTube URL", "text"),
        ],
    ),
    (
        "Security",
        True,
        [
            ("SECRET_KEY", "Secret key", "text"),
            ("COOKIE_NAME", "Cookie name", "text"),
        ],
    ),
    (
        "Advanced",
        False,
        [
            ("JOBS_DB_PATH", "Jobs DB path", "text"),
            ("FIELD_IMAGE_PATH", "Field image path", "text"),
            ("YOLO_MODEL", "YOLO model", "text"),
        ],
    ),
]


def _read_env_values() -> dict[str, str]:
    """Read current .env file into a dict (raw key=value pairs)."""
    values = {}
    if _ENV_FILE.is_file():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    return values


def _write_env_values(values: dict[str, str]):
    """Rewrite the .env file preserving comments and updating/adding values."""
    lines = []
    written_keys: set[str] = set()
    if _ENV_FILE.is_file():
        for line in _ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key in values:
                    lines.append(f"{key}={values[key]}")
                    written_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)
    # Append any new keys not already in the file
    for key, val in values.items():
        if key not in written_keys:
            lines.append(f"{key}={val}")
    _ENV_FILE.write_text("\n".join(lines) + "\n")


async def settings_fragment(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Return settings form as HTML fragment (admin only)."""
    _require_admin(user)
    env_values = _read_env_values()
    html = templates.env.get_template("_settings_content.html.j2").render(
        request=request,
        groups=_SETTINGS_GROUPS,
        values=env_values,
    )
    return _fragment_response(html, selector="#settings-modal-body", mode="inner")


async def save_settings(request: Request, user=Depends(login_manager)):  # noqa: B008
    """Save settings to .env and restart the application (admin only)."""
    _require_admin(user)
    form = await request.form()
    env_values = _read_env_values()

    # Update only keys that are in our editable groups
    editable_keys = {key for _, _, fields in _SETTINGS_GROUPS for key, _, _ in fields}
    for key in editable_keys:
        form_val = form.get(key)
        if form_val is not None:
            env_values[key] = form_val

    _write_env_values(env_values)
    logging.info("Settings saved to .env — restarting application")

    # Touch this file so uvicorn's file watcher triggers a reload
    Path(__file__).touch()

    # Close modal, show toast, and reload page after server has restarted
    return DatastarResponse(
        [
            SSE.patch_signals({"showSettingsModal": False}),
            _make_toast_event("Settings saved — restarting...", "bg-success"),
            SSE.execute_script("setTimeout(() => window.location.reload(), 5000)"),
        ]
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
            version_data["git_commit_short"] = git_commit[:7] if git_commit != "unknown" else "unknown"

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
