"""Job scheduling functionality for the fieldcam application."""

import logging
from datetime import datetime, timedelta

from apscheduler.jobstores.base import ConflictingIdError

from .config import LOCAL_TZ, scheduler
from .database import cancel_active_stream, cleanup_stale_streams
from .random_names import generate_name
from .streaming import snapshot_field_image, stream_game


def new_stream(
    name="", start_time=False, duration=60 * 5, key="", config=None,
    destination="gamechanger", custom_url="",
):
    """
    Schedule a new stream job.

    Args:
        name: Name for the stream job (auto-generated if not provided)
        start_time: When to start the stream (defaults to far future)
        duration: Duration in seconds (default 5 minutes)
        key: Stream key for the destination service
        config: Configuration dictionary
        destination: Target service — "gamechanger", "youtube", or "custom"
        custom_url: Full RTMP base URL when destination is "custom"

    Returns:
        The name of the scheduled job
    """
    if config is None:
        config = {}

    logging.info(f"New Stream: {name} {start_time} {duration} {key} -> {destination}")
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

    kwargs = {
        "duration": duration,
        "key": key,
        "config": config,
        "name": name,
        "destination": destination,
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


def start_cleanup_task():
    """
    Start periodic cleanup task to check for dead stream processes.

    Runs every 5 minutes to verify running streams are still active.
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

    # Grab a field camera snapshot every 60 seconds
    scheduler.add_job(
        snapshot_field_image,
        trigger="interval",
        seconds=60,
        id="HIDDEN_snapshot_field",
        name="HIDDEN_snapshot_field",
        replace_existing=True,
    )
    # Take one immediately at startup, then warm the detection cache
    snapshot_field_image()
    logging.info("Started field snapshot task (every 60s)")

    import threading

    from .routes import _refresh_detection_cache
    threading.Thread(target=_refresh_detection_cache, daemon=True).start()
    logging.info("Kicked off background detection cache warm-up")


def cancel_stream(job_name: str):
    """
    Cancel an actively running stream.

    Args:
        job_name: Name of the stream to cancel

    Returns:
        True if successfully cancelled, False otherwise
    """
    return cancel_active_stream(job_name)
