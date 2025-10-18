"""FFmpeg streaming functionality for the fieldcam application."""

import logging
import os
import queue
import subprocess

from .config import settings
from .database import add_active_stream, update_stream_status

# Global queue to store FFmpeg output
ffmpeg_output_queue = queue.Queue()


def input_cam_url(config):
    """Generate the RTSP camera input URL."""
    input_cam = f"rtsp://{settings.cam_user}:{settings.cam_pass}@{settings.cam_host}:554/Streaming/channels/101/"
    return input_cam


def stream_game(duration=(60 * 4), key="", config=None, name=""):
    """
    Stream a game from the camera to GameChanger.

    Args:
        duration: Duration in seconds for the stream
        key: GameChanger stream key
        config: Configuration dictionary (not currently used)
        name: Name of the stream for logging purposes

    Returns:
        Return code from FFmpeg process
    """
    if config is None:
        config = {}

    logging.info("Starting a stream...")
    pretty_name = name.replace(" ", "_")
    duration = int(duration)

    input_cam = input_cam_url(config)

    # Game Changer Settings
    gc_base = "rtmps://601c62c19c9e.global-contribute.live-video.net:443/app"
    if key == "":
        logging.error("No Destination GC Key Given")
        return
    output_gc1 = f"{gc_base}/{key}"

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
        output_gc1,  # Output
    ]

    process = subprocess.Popen(
        ffmpeg_command, stderr=subprocess.PIPE, universal_newlines=True, env=ffmpeg_env
    )

    # Register stream in database immediately after starting
    try:
        add_active_stream(job_name=name, pid=process.pid, duration=duration, stream_key=key)
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
