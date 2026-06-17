# FFmpeg streaming notes

Gotchas and corrections for RTSP → FLV/RTMP streaming (YouTube, GameChanger, etc.).

## Production host: Debian Trixie, FFmpeg 7

Stream control hosts and the cam-app Docker image (`python:3.11-slim-trixie`) run **Debian Trixie** with **FFmpeg 7**. That is well past the Enhanced FLV threshold, so **HEVC/H.265 passthrough** (`-c:v copy -f flv`) to YouTube works without the old “H.265 can't go in FLV” failure mode.

```bash
ffmpeg -version | head -1
```

Do not assume every machine in the fleet matches — older Bookworm/`5.1.x` installs only support legacy FLV (H.264 video).

## HEVC (H.265) in FLV (FFmpeg 6+)

**Do not repeat the old rule:** “HEVC/H.265 cannot be muxed into FLV.”

That was true for **legacy FLV**, which only carried H.264. Since **FFmpeg 6.1+**, FFmpeg supports **Enhanced FLV** / **Enhanced RTMP**:

- HEVC is muxed with fourcc `hvc1` (not the legacy H.264 codec id).
- AV1 and VP9 are also supported in the same extended format.
- YouTube ingest accepts Enhanced RTMP with HEVC; passthrough with `-c:v copy -f flv` is valid when the camera already outputs HEVC.

References: [FFmpeg 6.1 release notes](https://ffmpeg.org/) (“Support HEVC, VP9, AV1 codec in enhanced flv format”), [Enhanced RTMP spec](https://github.com/veovera/enhanced-rtmp).

`README-HikVision.md` still recommends H.264 for GameChanger/IVS and lowest CPU use; HEVC + Enhanced FLV is mainly relevant for YouTube when the camera is already on H.265.

## Audio: mono downmix (what the app does)

Hikvision main stream often reports:

```
Audio: aac (LC), 48000 Hz, stereo
```

ffprobe may show **stereo** while the mic is effectively **mono on one channel** (signal on left, silence on right). Viewers then hear audio in **one ear / one speaker** only. Re-encoding with `-ac 2` does not fix that.

**`cam-app/app/streaming.py`** downmixes L+R to mono before AAC encode:

```bash
-af "pan=mono|c0=0.5*c0+0.5*c1" -c:a aac -ar 48000 -b:a 64k
```

- Combines both channels so a single hot channel is heard on all speakers.
- Keeps **48 kHz** (camera native); do not force 44100.
- Small CPU cost vs `-c:a copy`, but fixes the one-channel feed issue.

**Alternatives** (not used by default):

- **`-c:a copy`** — no CPU, but preserves one silent channel if the camera sends it that way.
- **Duplicate one channel** (when you know which side has audio): `-af "pan=stereo|c0=c0|c1=c0"`.

Check the source with:

```bash
ffprobe -rtsp_transport tcp -i "rtsp://USER:PASS@CAMERA_IP:554/Streaming/channels/101/"
```

## Reference command (matches `stream_game`)

```bash
ffmpeg -hide_banner -loglevel error -progress pipe:1 -report \
  -rtsp_transport tcp \
  -i "rtsp://USER:PASS@CAMERA_IP:554/Streaming/channels/101/" \
  -c:v copy \
  -af "pan=mono|c0=0.5*c0+0.5*c1" -c:a aac -ar 48000 -b:a 64k \
  -f flv \
  "rtmp://DEST/STREAM_KEY"
```

Application code: `cam-app/app/streaming.py` (`stream_game`).
