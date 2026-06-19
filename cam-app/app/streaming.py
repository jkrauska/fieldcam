"""FFmpeg streaming functionality for the fieldcam application."""

import logging
import os
import shlex
import subprocess
import tempfile
import threading
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from .config import camera_configured, missing_camera_fields, settings
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


def input_cam_url() -> str:
    """Generate the RTSP camera input URL (main stream, channel 101)."""
    return f"rtsp://{settings.camera_user}:{settings.camera_pass}@{settings.camera_ip}:554/Streaming/channels/101/"


def snapshot_field_image():
    """Grab a JPEG snapshot from the Hikvision ISAPI endpoint (sub-stream, channel 102).

    Raises:
        RuntimeError: when the camera is not configured, or when the HTTP
            request / file write fails. Raising on failure is what makes
            APScheduler log the job as failed (with traceback) instead of
            the misleading "executed successfully" — otherwise the operator
            sees a clean log while the UI is silently stuck on the
            "Waiting for snapshot" placeholder because no file was written.
    """
    if not camera_configured():
        missing = ", ".join(missing_camera_fields())
        raise RuntimeError(f"Cannot snapshot field image — camera not configured (missing: {missing})")
    url = f"http://{settings.camera_ip}/ISAPI/Streaming/channels/102/picture"
    auth = httpx.DigestAuth(settings.camera_user, settings.camera_pass)
    output = settings.field_image_path

    try:
        resp = httpx.get(url, auth=auth, timeout=10)
        resp.raise_for_status()
    except httpx.ConnectError as e:
        raise RuntimeError(f"Field snapshot connect error to {settings.camera_ip}: {e}") from e
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Field snapshot timed out connecting to {url}") from e
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Field snapshot HTTP {e.response.status_code} from {url}") from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"Field snapshot HTTP error from {url}: {e}") from e

    # Per-call random suffix avoids two concurrent snapshot jobs racing on the
    # same .tmp path (see PLANS-2026-05 §3.4).
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=os.path.dirname(output) or ".",
            prefix=os.path.basename(output) + ".",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
        os.replace(tmp_path, output)
        tmp_path = None
    except OSError as e:
        raise RuntimeError(f"Field snapshot write failed ({output}): {e}") from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _parse_ffmpeg_options(options: str) -> list[str]:
    """Split env-configured ffmpeg option string into argv tokens."""
    options = options.strip()
    if not options:
        return []
    return shlex.split(options)


def _ensure_srt_latency(url: str, latency_ms: int) -> str:
    """Append SRT latency (ms) to a caller URL if not already set."""
    if latency_ms <= 0:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(name.lower() == "latency" for name in query):
        return url
    query["latency"] = [str(latency_ms)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _build_output_url(key: str, destination: str = "gamechanger", custom_url: str = "") -> str:
    """Build the output URL for the given destination."""
    if destination == "custom" and custom_url:
        custom_url = custom_url.rstrip("/")
        if custom_url.lower().startswith("srt://"):
            if key and "streamid=" not in custom_url.lower():
                sep = "&" if "?" in custom_url else "?"
                custom_url = f"{custom_url}{sep}streamid={key}"
            return _ensure_srt_latency(custom_url, settings.srt_latency_ms)
        return f"{custom_url}/{key}"
    base = RTMP_BASES.get(destination, RTMP_BASES["gamechanger"])
    return f"{base}/{key}"


def _output_format(destination: str, custom_url: str = "") -> str:
    """Return ffmpeg muxer format for the destination."""
    if destination == "custom" and custom_url.lower().startswith("srt://"):
        return "mpegts"
    return "flv"


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


def stream_game(duration=(60 * 4), key="", name="", destination="gamechanger", custom_url="", streamer_name=""):
    """
    Stream a game from the camera to an RTMP destination.

    Args:
        duration: Duration in seconds for the stream
        key: Stream key appended to the destination base URL
        name: Name of the stream for logging purposes
        destination: Target service — "gamechanger", "youtube", or "custom"
        custom_url: RTMP/RTMPS base URL or SRT caller URL when destination is "custom"
        streamer_name: Optional contact name for the person operating the stream

    Returns:
        Return code from FFmpeg process
    """
    logging.info(f"Starting stream to {destination} (streamer={streamer_name or '-'})...")
    pretty_name = name.replace(" ", "_")
    duration = int(duration)

    if not camera_configured():
        missing = ", ".join(missing_camera_fields())
        logging.error("Camera not configured (missing: %s); cannot start stream", missing)
        return

    input_cam = input_cam_url()

    if not key:
        logging.error("No stream key given")
        return
    output_url = _build_output_url(key, destination, custom_url)
    output_format = _output_format(destination, custom_url)

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
        *_parse_ffmpeg_options(settings.video_options),
        *_parse_ffmpeg_options(settings.audio_options),
        "-t",
        str(duration),  # Duration
        "-f",
        output_format,
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
            streamer_name=streamer_name,
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
