"""Job scheduling functionality for the fieldcam application."""

import logging
import threading
from datetime import datetime, timedelta

from apscheduler.jobstores.base import ConflictingIdError, JobLookupError

from .config import LOCAL_TZ, camera_configured, missing_camera_fields, scheduler
from .database import cancel_active_stream, cleanup_stale_streams
from .metrics import prune_old_samples, sample_metrics
from .random_names import generate_name
from .streaming import snapshot_field_image, stream_game

# Job IDs that depend on the camera being configured. Centralized so the
# auto-stop logic in start_cleanup_task can both refuse to schedule and remove
# any stale entries left behind by a previous run that had credentials.
_CAMERA_JOB_IDS: tuple[str, ...] = ("HIDDEN_snapshot_field",)


def new_stream(
    name="",
    start_time=False,
    duration=60 * 5,
    key="",
    destination="gamechanger",
    custom_url="",
    streamer_name="",
):
    """
    Schedule a new stream job.

    Args:
        name: Name for the stream job (auto-generated if not provided)
        start_time: When to start the stream (defaults to far future)
        duration: Duration in seconds (default 5 minutes)
        key: Stream key for the destination service
        destination: Target service — "gamechanger", "youtube", or "custom"
        custom_url: Full RTMP base URL when destination is "custom"
        streamer_name: Optional contact name for the person operating the stream

    Returns:
        The name of the scheduled job
    """

    logging.info(f"New Stream: {name} {start_time} {duration} {key} -> {destination} (streamer={streamer_name or '-'})")
    now = datetime.now().astimezone(LOCAL_TZ)

    if not name:
        name = generate_name()
    if not start_time:
        start_time = datetime.now() + timedelta(days=365)

    end_time = start_time + timedelta(seconds=duration)

    if start_time < now and end_time > now:
        start_time = now + timedelta(seconds=2)
        new_duration = end_time - now
        duration = new_duration.total_seconds()

    if not key:
        raise ValueError("Stream key is required")

    if not camera_configured():
        missing = ", ".join(missing_camera_fields())
        raise ValueError(f"Camera is not configured (missing: {missing}). Set camera credentials in the Settings page before scheduling streams.")

    kwargs = {
        "duration": duration,
        "key": key,
        "name": name,
        "destination": destination,
        "streamer_name": streamer_name,
    }
    if destination == "custom" and custom_url:
        kwargs["custom_url"] = custom_url

    # If the name already exists, append _1, _2, ... until unique
    job_name = name
    suffix = 0
    while True:
        try:
            kwargs["name"] = job_name
            scheduler.add_job(
                stream_game,
                trigger="date",
                run_date=start_time,
                id=job_name,
                name=job_name,
                kwargs=kwargs,
            )
            break
        except ConflictingIdError:
            suffix += 1
            job_name = f"{name}_{suffix}"
            logging.info(f"Job '{name}' already exists, trying '{job_name}'")

    return job_name


def get_scheduled_jobs():
    """Get all scheduled jobs sorted by next run time."""
    return sorted(scheduler.get_jobs(), key=lambda x: x.next_run_time)


def remove_job(job_id: str):
    """
    Remove a scheduled job by ID.

    Args:
        job_id: The ID of the job to remove

    Raises:
        Exception: If job removal fails
    """
    scheduler.remove_job(job_id)


def _remove_camera_jobs(reason: str) -> None:
    """Remove any persisted camera-dependent jobs. Idempotent."""
    for job_id in _CAMERA_JOB_IDS:
        try:
            scheduler.remove_job(job_id)
            logging.warning("Removed stale job %s (%s)", job_id, reason)
        except JobLookupError:
            pass


def start_cleanup_task():
    """
    Start periodic background tasks.

    Always-on tasks (do not require camera credentials):
      - stale-stream cleanup
      - metric sampling (CPU temp + a fresh YOLO detection + camera ping)
      - metric retention pruning

    Camera-dependent tasks (only scheduled when camera credentials are set):
      - field snapshot grab (every 60s)
      - initial YOLO detection cache warm-up

    When the camera is NOT configured, camera-dependent jobs are explicitly
    REMOVED from the persistent jobstore so a previous run's snapshot job
    doesn't keep running silently. This is the auto-stop condition: a
    misconfigured deployment will log a clear error instead of pretending
    the snapshot job is "executed successfully" every minute.
    """
    try:
        scheduler.add_job(
            cleanup_stale_streams,
            trigger="interval",
            minutes=5,
            id="HIDDEN_cleanup_stale_streams",
            name="HIDDEN_cleanup_stale_streams",
        )
        logging.info("Started periodic cleanup task for stale streams")
    except ConflictingIdError:
        logging.info("Cleanup task already running")

    if camera_configured():
        scheduler.add_job(
            snapshot_field_image,
            trigger="interval",
            seconds=60,
            id="HIDDEN_snapshot_field",
            name="HIDDEN_snapshot_field",
            replace_existing=True,
        )
        logging.info("Started field snapshot task (every 60s)")

        def _initial_snapshot():
            try:
                snapshot_field_image()
            except Exception as exc:
                logging.warning("Initial field snapshot failed (will retry every 60s): %s", exc)

        threading.Thread(target=_initial_snapshot, daemon=True, name="initial-snapshot").start()
        logging.info("Kicked off background initial field snapshot")

        from .routes import _refresh_detection_cache

        threading.Thread(target=_refresh_detection_cache, daemon=True, name="detection-warmup").start()
        logging.info("Kicked off background detection cache warm-up")
    else:
        missing = ", ".join(missing_camera_fields())
        logging.error(
            "Camera not configured (missing: %s) — field snapshot job NOT scheduled. "
            "Streams cannot be recorded until camera credentials are set in the Settings page.",
            missing,
        )
        _remove_camera_jobs("camera not configured")

    # Sample CPU temp + detection counts into the metric_samples table every 60s.
    # Runs regardless of camera config so we still capture CPU temp.
    scheduler.add_job(
        sample_metrics,
        trigger="interval",
        seconds=60,
        id="HIDDEN_sample_metrics",
        name="HIDDEN_sample_metrics",
        replace_existing=True,
    )
    logging.info("Started metric sampler (every 60s)")

    # Prune raw samples older than 30 days, daily
    scheduler.add_job(
        prune_old_samples,
        trigger="interval",
        hours=24,
        id="HIDDEN_prune_metrics",
        name="HIDDEN_prune_metrics",
        kwargs={"days": 30},
        replace_existing=True,
    )
    logging.info("Started metric retention task (daily, keep 30 days)")


def cancel_stream(job_name: str):
    """
    Cancel an actively running stream.

    Args:
        job_name: Name of the stream to cancel

    Returns:
        True if successfully cancelled, False otherwise
    """
    return cancel_active_stream(job_name)
