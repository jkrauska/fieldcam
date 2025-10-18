"""Job scheduling functionality for the fieldcam application."""

import logging
from datetime import datetime, timedelta

from apscheduler.jobstores.base import ConflictingIdError

from .config import LOCAL_TZ, scheduler
from .random_names import generate_name
from .streaming import stream_game


def new_stream(name="", start_time=False, duration=60 * 5, key="", config=None):
    """
    Schedule a new stream job.

    Args:
        name: Name for the stream job (auto-generated if not provided)
        start_time: When to start the stream (defaults to far future)
        duration: Duration in seconds (default 5 minutes)
        key: GameChanger stream key
        config: Configuration dictionary

    Returns:
        The name of the scheduled job
    """
    if config is None:
        config = {}

    logging.info(f"New Stream: {name} {start_time} {duration} {key}")
    now = datetime.now().astimezone(LOCAL_TZ)

    if not name:
        name = generate_name()
    if not start_time:
        start_time = datetime.now() + timedelta(days=365)

    end_time = start_time + timedelta(seconds=duration)

    # In Progress - adjust if stream should already be running
    if start_time < now and end_time > now:
        start_time = now + timedelta(seconds=2)
        new_duration = end_time - now
        duration = new_duration.total_seconds()

    if not key:
        key = "sk_us-east-1_fakefake"

    try:
        scheduler.add_job(
            stream_game,
            trigger="date",
            run_date=start_time,
            id=name,
            name=name,
            kwargs={"duration": duration, "key": key, "config": config, "name": name},
        )
    except ConflictingIdError:
        logging.info(f"Job '{name}' Already Seen")
        pass
    return name


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
