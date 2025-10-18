"""FFmpeg streaming functionality for the fieldcam application."""
import logging
import os
import subprocess
import queue

from .config import SECRETS

# Global queue to store FFmpeg output
ffmpeg_output_queue = queue.Queue()


def input_cam_url(config):
    """Generate the RTSP camera input URL."""
    CAM_HOST = SECRETS["CAM_HOST"]
    CAM_USER = SECRETS["CAM_USER"]
    CAM_PASS = SECRETS["CAM_PASS"]
    INPUT_CAM = f"rtsp://{CAM_USER}:{CAM_PASS}@{CAM_HOST}:554/Streaming/channels/101/"
    return INPUT_CAM


def stream_game(duration=(60 * 4), key="", config={}, name=""):
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
    logging.info("Starting a stream...")
    pretty_name = name.replace(" ", "_")
    duration = int(duration)

    INPUT_CAM = input_cam_url(config)

    # Game Changer Settings
    GC_BASE = "rtmps://601c62c19c9e.global-contribute.live-video.net:443/app"
    if key == "":
        logging.error("No Destination GC Key Given")
        return
    OUTPUT_GC1 = f"{GC_BASE}/{key}"

    FFMPEG_ENV = os.environ.copy()
    FFMPEG_ENV["FFREPORT"] = f"level=32:file=logs/%p-%t-{pretty_name}.log"

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
        INPUT_CAM,  # Input
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
        OUTPUT_GC1,  # Output
    ]

    process = subprocess.Popen(
        ffmpeg_command, stderr=subprocess.PIPE, universal_newlines=True, env=FFMPEG_ENV
    )

    while True:
        output = process.stderr.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            ffmpeg_output_queue.put((name, output.strip()))

    return_code = process.poll()
    return return_code
