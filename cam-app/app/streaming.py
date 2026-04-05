"""FFmpeg streaming functionality for the fieldcam application."""

import logging
import os
import subprocess
import threading

import httpx

from .config import settings
from .database import add_active_stream, update_stream_status
from .event_bus import clear_stream_stats, update_stream_stats

RTMP_BASES = {
    "gamechanger": settings.rtmp_gamechanger,
    "youtube": settings.rtmp_youtube,
}

# Registry of live ffmpeg subprocesses so we can terminate them on shutdown.
_active_processes: dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()


def terminate_all_streams(timeout: int = 5):
    """SIGTERM all tracked ffmpeg processes, wait, then SIGKILL any survivors."""
    with _process_lock:
        procs = dict(_active_processes)
    if not procs:
        return
    logging.info("Terminating %d active ffmpeg process(es)…", len(procs))
    for name, proc in procs.items():
        try:
            proc.terminate()
            logging.info("Sent SIGTERM to stream %s (PID %d)", name, proc.pid)
        except OSError:
            pass
    for name, proc in procs.items():
        try:
            proc.wait(timeout=timeout)
            logging.info("Stream %s exited", name)
        except subprocess.TimeoutExpired:
            logging.warning("Stream %s did not exit in %ds, sending SIGKILL", name, timeout)
            proc.kill()


def input_cam_url(config):
    """Generate the RTSP camera input URL (main stream, channel 101)."""
    return f"rtsp://{settings.cam_user}:{settings.cam_pass}@{settings.cam_host}:554/Streaming/channels/101/"


def snapshot_field_image():
    """Grab a JPEG snapshot from the Hikvision ISAPI endpoint (sub-stream, channel 102)."""
    url = f"http://{settings.cam_host}/ISAPI/Streaming/channels/102/picture"
    auth = httpx.DigestAuth(settings.cam_user, settings.cam_pass)
    output = settings.field_image_path
    tmp = output + ".tmp"
    try:
        resp = httpx.get(url, auth=auth, timeout=10)
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            f.write(resp.content)
        os.replace(tmp, output)
    except httpx.TimeoutException:
        logging.warning("Field snapshot timed out")
    except httpx.HTTPStatusError as e:
        logging.warning("Field snapshot HTTP error: %s", e)
    except Exception as e:
        logging.warning("Field snapshot error: %s", e)


def _build_output_url(key: str, destination: str = "gamechanger", custom_url: str = "") -> str:
    """Build the RTMP output URL for the given destination."""
    if destination == "custom" and custom_url:
        return f"{custom_url.rstrip('/')}/{key}"
    base = RTMP_BASES.get(destination, RTMP_BASES["gamechanger"])
    return f"{base}/{key}"


def _parse_progress(block: dict[str, str]) -> dict:
    """Parse an ffmpeg -progress block into structured stats."""
    speed_raw = block.get("speed", "0x").rstrip("x").strip()
    try:
        speed = float(speed_raw)
    except ValueError:
        speed = 0.0

    try:
        fps = float(block.get("fps", "0"))
    except ValueError:
        fps = 0.0

    # out_time comes as HH:MM:SS.microseconds — truncate to HH:MM:SS
    out_time = block.get("out_time", "00:00:00.000000")
    if "." in out_time:
        out_time = out_time.split(".")[0]

    return {
        "frame": int(block.get("frame", "0") or "0"),
        "fps": fps,
        "bitrate": block.get("bitrate", "N/A"),
        "out_time": out_time,
        "speed": speed,
        "total_size": int(block.get("total_size", "0") or "0"),
        "drop_frames": int(block.get("drop_frames", "0") or "0"),
    }


def stream_game(duration=(60 * 4), key="", config=None, name="", destination="gamechanger", custom_url=""):
    """
    Stream a game from the camera to an RTMP destination.

    Args:
        duration: Duration in seconds for the stream
        key: Stream key appended to the destination base URL
        config: Configuration dictionary (not currently used)
        name: Name of the stream for logging purposes
        destination: Target service — "gamechanger", "youtube", or "custom"
        custom_url: Full RTMP base URL when destination is "custom"

    Returns:
        Return code from FFmpeg process
    """
    if config is None:
        config = {}

    logging.info(f"Starting stream to {destination}...")
    pretty_name = name.replace(" ", "_")
    duration = int(duration)

    input_cam = input_cam_url(config)

    if not key:
        logging.error("No stream key given")
        return
    output_url = _build_output_url(key, destination, custom_url)

    os.makedirs("logs", exist_ok=True)
    ffmpeg_env = os.environ.copy()
    ffmpeg_env["FFREPORT"] = f"level=32:file=logs/%p-%t-{pretty_name}.log"

    ffmpeg_command = [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",  # Clean key=value progress on stdout
        "-report",  # Detailed log to file
        "-rtsp_transport",
        "tcp",  # RTSP Options
        "-i",
        input_cam,  # Input
        "-c:v",
        "copy",  # Video passthrough
        "-c:a",
        "copy",  # Audio passthrough
        "-t",
        str(duration),  # Duration
        "-f",
        "flv",
        output_url,
    ]

    process = subprocess.Popen(
        ffmpeg_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=ffmpeg_env,
    )

    with _process_lock:
        _active_processes[name] = process

    # Register stream in database immediately after starting
    try:
        add_active_stream(
            job_name=name,
            pid=process.pid,
            duration=duration,
            stream_key=key,
            destination=destination,
        )
    except Exception as e:
        logging.error(f"Failed to register stream in database: {e}")

    # Drain stderr in a background thread to prevent pipe deadlock.
    # With -loglevel error, only actual errors appear here.
    error_lines: list[str] = []

    def _drain_stderr():
        for line in process.stderr:
            line = line.strip()
            if line:
                error_lines.append(line)
                logging.error(f"ffmpeg [{name}]: {line}")

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    try:
        # Read -progress output from stdout (key=value pairs).
        # Each block ends with a "progress=continue" or "progress=end" line.
        progress_block: dict[str, str] = {}
        while True:
            line = process.stdout.readline()
            if line == "" and process.poll() is not None:
                break
            line = line.strip()
            if not line:
                continue
            if "=" in line:
                k, _, value = line.partition("=")
                progress_block[k] = value
                if k == "progress":
                    # End of a progress block — parse and publish
                    stats = _parse_progress(progress_block)
                    update_stream_stats(name, stats)
                    progress_block = {}

        stderr_thread.join(timeout=5)
        return_code = process.poll()

        # Update stream status based on return code
        if return_code == 0:
            update_stream_status(name, "completed")
            logging.info(f"Stream {name} completed successfully")
        else:
            error_msg = error_lines[-1] if error_lines else f"exit code {return_code}"
            update_stream_status(name, "failed", f"FFmpeg: {error_msg}")
            logging.error(f"Stream {name} failed with exit code {return_code}")

        return return_code

    except Exception as e:
        logging.error(f"Error during stream {name}: {e}")
        update_stream_status(name, "failed", str(e))
        raise
    finally:
        with _process_lock:
            _active_processes.pop(name, None)
        clear_stream_stats(name)
