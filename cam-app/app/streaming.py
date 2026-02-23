"""FFmpeg streaming functionality for the fieldcam application."""

import logging
import os
import queue
import subprocess

from .config import settings
from .database import add_active_stream, update_stream_status

# Global queue to store FFmpeg output
ffmpeg_output_queue = queue.Queue()

RTMP_BASES = {
    "gamechanger": "rtmps://601c62c19c9e.global-contribute.live-video.net:443/app",
    "youtube": "rtmp://a.rtmp.youtube.com/live2",
}


def input_cam_url(config):
    """Generate the RTSP camera input URL."""
    input_cam = f"rtsp://{settings.cam_user}:{settings.cam_pass}@{settings.cam_host}:554/Streaming/channels/101/"
    return input_cam


def _build_output_url(key: str, destination: str = "gamechanger", custom_url: str = "") -> str:
    """Build the RTMP output URL for the given destination."""
    if destination == "custom" and custom_url:
        return f"{custom_url.rstrip('/')}/{key}"
    base = RTMP_BASES.get(destination, RTMP_BASES["gamechanger"])
    return f"{base}/{key}"


def stream_game(
    duration=(60 * 4), key="", config=None, name="", destination="gamechanger", custom_url=""
):
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

    ffmpeg_env = os.environ.copy()
    ffmpeg_env["FFREPORT"] = f"level=32:file=logs/%p-%t-{pretty_name}.log"

    ffmpeg_command = [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stats",
        "-report",  # Logging options
        "-rtsp_transport",
        "tcp",  # RTSP Options
        "-i",
        input_cam,  # Input
        "-c:v",
        "copy",
        "-bufsize",
        "12000k",
        "-g",
        "60",  # Video options
        "-c:a",
        "aac",
        "-b:a",
        "128k",  # Audio options
        "-t",
        str(duration),  # Duration
        "-f",
        "flv",
        output_url,
    ]

    process = subprocess.Popen(
        ffmpeg_command, stderr=subprocess.PIPE, universal_newlines=True, env=ffmpeg_env
    )

    # Register stream in database immediately after starting
    try:
        add_active_stream(
            job_name=name, pid=process.pid, duration=duration,
            stream_key=key, destination=destination,
        )
    except Exception as e:
        logging.error(f"Failed to register stream in database: {e}")
        # Continue anyway, but log the error

    try:
        # Monitor FFmpeg output
        while True:
            output = process.stderr.readline()
            if output == "" and process.poll() is not None:
                break
            if output:
                ffmpeg_output_queue.put((name, output.strip()))

        return_code = process.poll()

        # Update stream status based on return code
        if return_code == 0:
            update_stream_status(name, "completed")
            logging.info(f"Stream {name} completed successfully")
        else:
            update_stream_status(name, "failed", f"FFmpeg exit code: {return_code}")
            logging.error(f"Stream {name} failed with exit code {return_code}")

        return return_code

    except Exception as e:
        # Handle any unexpected errors
        logging.error(f"Error during stream {name}: {e}")
        update_stream_status(name, "failed", str(e))
        raise
