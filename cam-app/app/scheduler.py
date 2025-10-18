"""Job scheduling functionality for the fieldcam application."""
import logging
from datetime import datetime, timedelta

from apscheduler.jobstores.base import ConflictingIdError

from .config import scheduler, LOCAL_TZ
from .streaming import stream_game
from .random_names import generate_name


def new_stream(name="", startTime=False, duration=60 * 5, key="", config={}):
    """
    Schedule a new stream job.
    
    Args:
        name: Name for the stream job (auto-generated if not provided)
        startTime: When to start the stream (defaults to far future)
        duration: Duration in seconds (default 5 minutes)
        key: GameChanger stream key
        config: Configuration dictionary
        
    Returns:
        The name of the scheduled job
    """
    logging.info(f"New Stream: {name} {startTime} {duration} {key}")
    now = datetime.now().astimezone(LOCAL_TZ)

    if not name:
        name = generate_name()
    if not startTime:
        startTime = datetime.now() + timedelta(days=365)

    endTime = startTime + timedelta(seconds=duration)

    # In Progress - adjust if stream should already be running
    if startTime < now and endTime > now:
        startTime = now + timedelta(seconds=2)
        newDuration = endTime - now
        duration = newDuration.total_seconds()

    if not key:
        key = "sk_us-east-1_fakefake"

    try:
        scheduler.add_job(
            stream_game,
            trigger="date",
            run_date=startTime,
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
