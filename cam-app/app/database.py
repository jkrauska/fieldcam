"""Database models and functions for tracking active streams."""

import logging
import os
import signal
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, create_engine, text
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
    status = Column(String, default="running")  # running, completed, cancelled, failed
    error_message = Column(Text)
    created_at = Column(String, default=datetime.utcnow().isoformat())
    updated_at = Column(String, default=datetime.utcnow().isoformat())


# Create engine and session (same resolved path as APScheduler in config)
engine = create_engine(JOBS_DB_URL)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Initialize database and create tables if they don't exist."""
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        try:
            conn.execute(
                text("ALTER TABLE active_streams ADD COLUMN destination TEXT DEFAULT 'gamechanger'")
            )
            conn.commit()
        except Exception:
            pass
    logging.info("Database initialized - active_streams table ready")


def add_active_stream(
    job_name: str, pid: int, duration: int, stream_key: str = "", destination: str = "gamechanger"
):
    """Register a new active stream in the database."""
    session = SessionLocal()
    try:
        stream = ActiveStream(
            job_name=job_name,
            pid=pid,
            start_time=datetime.utcnow().isoformat(),
            duration=duration,
            stream_key=stream_key,
            destination=destination,
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
        streams = (
            session.query(ActiveStream)
            .filter(ActiveStream.status.in_(["running", "pending"]))
            .all()
        )
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
        streams = session.query(ActiveStream).order_by(ActiveStream.start_time.desc()).all()
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
            stream.updated_at = datetime.utcnow().isoformat()
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
                stream.updated_at = datetime.utcnow().isoformat()
                logging.warning(
                    f"Stream {stream.job_name} (PID {stream.pid}) found dead, marked as failed"
                )

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
