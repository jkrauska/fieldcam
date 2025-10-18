"""FFmpeg streaming functionality for the fieldcam application."""

import logging
import os
import queue
import subprocess

from .config import settings

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

    while True:
        output = process.stderr.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            ffmpeg_output_queue.put((name, output.strip()))

    return_code = process.poll()
    return return_code
