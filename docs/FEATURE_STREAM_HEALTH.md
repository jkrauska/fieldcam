# Feature: Real-Time Stream Health Monitoring

## Background

`streaming.py` already captures ffmpeg's stderr output into a `queue.Queue()` (`ffmpeg_output_queue`, line 12). This is the producer half of a real-time monitoring pipeline — the consumer was never wired up.

## How ffmpeg stats work

When ffmpeg runs with `-stats` (already enabled in our command), it emits a continuously-updating progress line on stderr:

```
frame=  692 fps= 58 q=28.0 size=5376KiB time=00:00:28.77 bitrate=1530.3kbits/s speed=2.43x
```

| Field | Meaning |
|-------|---------|
| `frame` | Total video frames processed |
| `fps` | Instantaneous processing rate |
| `q` | Quantizer/quality parameter |
| `size` | Cumulative output size |
| `time` | Playback-time position |
| `bitrate` | Average output bitrate (`size / time`) |
| `speed` | Processing speed relative to real-time |

The `speed` field is critical for live streaming: below `1.0x` means the encoder is falling behind real-time (frames dropping, stream degrading).

## Current state

- **Producer (done):** `streaming.py:112-117` reads stderr lines and pushes `(name, output)` tuples into `ffmpeg_output_queue`.
- **Consumer (missing):** Nothing drains the queue. It grows unbounded during a stream.

## Implementation plan

### 1. Parse stats into structured data

Parse each stderr line into a dict:

```python
import re

def parse_ffmpeg_stats(line: str) -> dict | None:
    m = re.search(
        r'frame=\s*(\d+)\s+fps=\s*([\d.]+)\s+.*'
        r'size=\s*(\S+)\s+time=\s*(\S+)\s+'
        r'bitrate=\s*(\S+)\s+speed=\s*([\d.]+)x',
        line
    )
    if not m:
        return None
    return {
        "frame": int(m.group(1)),
        "fps": float(m.group(2)),
        "size": m.group(3),
        "time": m.group(4),
        "bitrate": m.group(5),
        "speed": float(m.group(6)),
    }
```

### 2. Expose via SSE endpoint (Datastar)

Add a `/stream-health` SSE endpoint that drains the queue and sends parsed stats as Datastar fragments. This fits naturally with the existing Datastar architecture — a `<div id="stream-health">` fragment that morphs with updated stats.

### 3. Dashboard fragment

Render a small status panel showing:
- Current fps and speed (with warning color when speed < 1.0x)
- Bitrate over time
- Stream uptime (`time` field)
- Frame count

### Alternative: use `-progress` instead of `-stats`

ffmpeg supports `-progress pipe:1` which emits clean key=value pairs on stdout:

```
frame=584
fps=52.40
bitrate=N/A
out_time=00:00:24.000000
speed=1.02x
progress=continue
```

This is easier to parse than stderr stats (no carriage-return handling needed). Would require changing the subprocess to capture stdout separately and adding `-progress pipe:1` to the ffmpeg command.

## Considerations

- The queue currently grows unbounded during a stream. Should be capped with `maxsize` or switched to only storing the latest stats dict.
- Multiple simultaneous streams each push `(name, output)` tuples — the consumer needs to demux by stream name.
- Stats lines use `\r` (carriage return) not `\n` during encoding. `universal_newlines=True` is already set which helps, but parsing should split on `\r` as well.
