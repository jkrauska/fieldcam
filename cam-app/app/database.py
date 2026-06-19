"""Database models and functions for tracking active streams."""

import logging
import os
import signal
from datetime import UTC, datetime

from sqlalchemy import Column, Float, Index, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import JOBS_DB_URL
from .event_bus import notify_list_changed

Base = declarative_base()


class ActiveStream(Base):
    """Model for tracking active streaming processes."""

    __tablename__ = "active_streams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String, nullable=False)
    pid = Column(Integer, nullable=False)
    start_time = Column(String, nullable=False)  # ISO format timestamp
    duration = Column(Integer, nullable=False)
    stream_key = Column(String)
    destination = Column(String, default="gamechanger")
    streamer_name = Column(String)  # Person operating the stream (optional contact info)
    status = Column(String, default="running")  # running, completed, cancelled, failed
    error_message = Column(Text)
    hidden_from_history = Column(Integer, default=0)  # 1 = hidden from history UI
    created_at = Column(String, default=lambda: datetime.now(UTC).isoformat())
    updated_at = Column(String, default=lambda: datetime.now(UTC).isoformat())


class MetricSample(Base):
    """Append-only time-series samples for host + detection metrics.

    Wide format keeps storage compact and queries trivial for the small,
    fixed set of metrics we record (one row per sampling interval).
    """

    __tablename__ = "metric_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(Integer, nullable=False)  # unix epoch seconds, UTC
    cpu_temp_c = Column(Float)  # nullable: sensor may be unavailable
    person_count = Column(Integer)  # nullable: detection not yet warm
    bird_count = Column(Integer)
    total_count = Column(Integer)
    camera_ping_ms = Column(Float)  # nullable: None = camera unreachable / not configured

    __table_args__ = (Index("ix_metric_samples_ts", "ts"),)


# Create engine and session (same resolved path as APScheduler in config)
engine = create_engine(JOBS_DB_URL)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Initialize database and create tables if they don't exist."""
    Base.metadata.create_all(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("active_streams")}
    if "destination" not in columns:
        try:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE active_streams ADD COLUMN destination TEXT DEFAULT 'gamechanger'"))
                conn.commit()
            logging.info("Migration: added 'destination' column to active_streams")
        except Exception:
            logging.warning("Migration failed: could not add 'destination' column", exc_info=True)
    if "streamer_name" not in columns:
        try:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE active_streams ADD COLUMN streamer_name TEXT"))
                conn.commit()
            logging.info("Migration: added 'streamer_name' column to active_streams")
        except Exception:
            logging.warning("Migration failed: could not add 'streamer_name' column", exc_info=True)
    if "hidden_from_history" not in columns:
        try:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE active_streams ADD COLUMN hidden_from_history INTEGER DEFAULT 0 NOT NULL"))
                conn.commit()
            logging.info("Migration: added 'hidden_from_history' column to active_streams")
        except Exception:
            logging.warning("Migration failed: could not add 'hidden_from_history' column", exc_info=True)

    # metric_samples migrations: add new columns to pre-existing databases.
    try:
        metric_cols = {c["name"] for c in inspect(engine).get_columns("metric_samples")}
    except Exception:
        metric_cols = set()
    if metric_cols and "camera_ping_ms" not in metric_cols:
        try:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE metric_samples ADD COLUMN camera_ping_ms FLOAT"))
                conn.commit()
            logging.info("Migration: added 'camera_ping_ms' column to metric_samples")
        except Exception:
            logging.warning("Migration failed: could not add 'camera_ping_ms' column", exc_info=True)

    logging.info("Database initialized - active_streams table ready")


def add_active_stream(
    job_name: str,
    pid: int,
    duration: int,
    stream_key: str = "",
    destination: str = "gamechanger",
    streamer_name: str = "",
):
    """Register a new active stream in the database."""
    session = SessionLocal()
    try:
        stream = ActiveStream(
            job_name=job_name,
            pid=pid,
            start_time=datetime.now(UTC).isoformat(),
            duration=duration,
            stream_key=stream_key,
            destination=destination,
            streamer_name=streamer_name or None,
            status="running",
        )
        session.add(stream)
        session.commit()
        notify_list_changed()
        logging.info(f"Added active stream: {job_name} (PID: {pid})")
    except Exception as e:
        session.rollback()
        logging.error(f"Error adding active stream: {e}")
        raise
    finally:
        session.close()


def get_active_streams():
    """
    Get all currently active or pending streams.

    Returns:
        List of ActiveStream objects with status 'running' or 'pending'
    """
    session = SessionLocal()
    try:
        streams = session.query(ActiveStream).filter(ActiveStream.status.in_(["running", "pending"])).all()
        # Detach from session to avoid issues after session closes
        session.expunge_all()
        return streams
    finally:
        session.close()


def get_all_streams():
    """
    Get complete stream history.

    Returns:
        List of all ActiveStream objects, ordered by creation time (newest first)
    """
    session = SessionLocal()
    try:
        streams = (
            session.query(ActiveStream)
            .filter((ActiveStream.hidden_from_history == 0) | (ActiveStream.hidden_from_history.is_(None)))
            .order_by(ActiveStream.start_time.desc())
            .all()
        )
        session.expunge_all()
        return streams
    finally:
        session.close()


def get_stream_by_name(job_name: str):
    """
    Get a specific stream by job name.

    Args:
        job_name: Name of the stream job

    Returns:
        ActiveStream object or None if not found
    """
    session = SessionLocal()
    try:
        stream = session.query(ActiveStream).filter(ActiveStream.job_name == job_name).first()
        if stream:
            session.expunge(stream)
        return stream
    finally:
        session.close()


def update_stream_status(job_name: str, status: str, error_message: str = None):
    """
    Update the status of a stream.

    Args:
        job_name: Name of the stream job
        status: New status (completed, failed, cancelled)
        error_message: Optional error message if failed
    """
    session = SessionLocal()
    try:
        stream = session.query(ActiveStream).filter(ActiveStream.job_name == job_name).first()
        if stream:
            stream.status = status
            stream.updated_at = datetime.now(UTC).isoformat()
            if error_message:
                stream.error_message = error_message
            session.commit()
            notify_list_changed()
            logging.info(f"Updated stream {job_name} status to {status}")
        else:
            logging.warning(f"Stream {job_name} not found in database")
    except Exception as e:
        session.rollback()
        logging.error(f"Error updating stream status: {e}")
        raise
    finally:
        session.close()


def remove_stream(job_name: str):
    """
    Remove a stream record from the database.

    Note: This should rarely be used as we want to keep history.

    Args:
        job_name: Name of the stream job
    """
    session = SessionLocal()
    try:
        stream = session.query(ActiveStream).filter(ActiveStream.job_name == job_name).first()
        if stream:
            session.delete(stream)
            session.commit()
            logging.info(f"Removed stream: {job_name}")
    except Exception as e:
        session.rollback()
        logging.error(f"Error removing stream: {e}")
        raise
    finally:
        session.close()


def hide_stream_by_id(stream_id: int) -> bool:
    """Mark a stream history entry as hidden (soft-remove from history UI).

    Returns True if a row was updated, False if not found.
    """
    session = SessionLocal()
    try:
        stream = session.query(ActiveStream).filter(ActiveStream.id == stream_id).first()
        if not stream:
            return False
        stream.hidden_from_history = 1
        stream.updated_at = datetime.now(UTC).isoformat()
        session.commit()
        logging.info(f"Hidden stream history entry id={stream_id} ({stream.job_name})")
        return True
    except Exception as e:
        session.rollback()
        logging.error(f"Error hiding stream id={stream_id}: {e}")
        raise
    finally:
        session.close()


def delete_stream_by_id(stream_id: int) -> bool:
    """Delete a single stream history entry by its primary key.

    Returns True if a row was deleted, False if not found.
    """
    session = SessionLocal()
    try:
        stream = session.query(ActiveStream).filter(ActiveStream.id == stream_id).first()
        if not stream:
            return False
        session.delete(stream)
        session.commit()
        logging.info(f"Deleted stream history entry id={stream_id} ({stream.job_name})")
        return True
    except Exception as e:
        session.rollback()
        logging.error(f"Error deleting stream id={stream_id}: {e}")
        raise
    finally:
        session.close()


def cleanup_stale_streams():
    """
    Check all running streams and update status if process is dead.

    This function should be called periodically (e.g., every 5 minutes).
    """
    session = SessionLocal()
    try:
        running_streams = session.query(ActiveStream).filter(ActiveStream.status == "running").all()

        for stream in running_streams:
            try:
                # Check if process is still alive
                # Sending signal 0 doesn't actually send a signal, just checks if process exists
                os.kill(stream.pid, 0)
            except OSError:
                # Process is dead
                stream.status = "failed"
                stream.error_message = "Process died unexpectedly"
                stream.updated_at = datetime.now(UTC).isoformat()
                logging.warning(f"Stream {stream.job_name} (PID {stream.pid}) found dead, marked as failed")

        session.commit()
        notify_list_changed()
    except Exception as e:
        session.rollback()
        logging.error(f"Error during cleanup: {e}")
    finally:
        session.close()


def cancel_active_stream(job_name: str):
    """
    Cancel a running stream by killing its process.

    Args:
        job_name: Name of the stream job to cancel

    Returns:
        True if successfully cancelled, False otherwise
    """
    # Get the most recent RUNNING stream with this name
    session = SessionLocal()
    try:
        stream = (
            session.query(ActiveStream)
            .filter(ActiveStream.job_name == job_name, ActiveStream.status == "running")
            .order_by(ActiveStream.created_at.desc())
            .first()
        )

        if not stream:
            logging.warning(f"No running stream found with name {job_name}")
            session.close()
            return False

        # Detach from session
        session.expunge(stream)
        session.close()

        try:
            # Try to terminate the process gracefully first
            os.kill(stream.pid, signal.SIGTERM)
            update_stream_status(job_name, "cancelled")
            logging.info(f"Cancelled stream {job_name} (PID {stream.pid})")
            return True
        except ProcessLookupError:
            # Process already dead
            update_stream_status(job_name, "failed", "Process not found")
            logging.warning(f"Stream {job_name} process not found (PID {stream.pid})")
            return False
        except Exception as e:
            logging.error(f"Error cancelling stream {job_name}: {e}")
            return False
    except Exception as e:
        session.close()
        logging.error(f"Database error while cancelling stream {job_name}: {e}")
        return False
