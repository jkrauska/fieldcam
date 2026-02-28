# Hikvision Camera Settings for GameChanger Streaming

Recommended settings for streaming via ffmpeg with `-c:v copy -c:a copy` to Amazon IVS (GameChanger).

Since we use video and audio passthrough (no transcoding), the camera settings **are** the final encode. Getting these right is critical.

## Video Settings

| Setting | Recommended | Notes |
|---|---|---|
| **Stream Type** | Main Stream (Normal) | |
| **Video Type** | Video & Audio | Must include audio for GameChanger |
| **Resolution** | 1280x720 (720p) | GC viewers are on phones; 1080p doubles bandwidth for no visible benefit |
| **Video Encoding** | **H.264** | **Critical.** H.265 cannot be muxed into FLV and IVS won't accept it via RTMPS |
| **H.264+** | **OFF** | Hikvision's "smart" codec causes wild bitrate swings — bad for live streaming |
| **Profile** | High Profile | Best compression efficiency at a given bitrate |
| **Frame Rate** | 30 fps | Smooth for sports action |
| **Bitrate Type** | Constant (CBR) | Prevents bitrate spikes that could exceed upload and cause buffering |
| **Max Bitrate** | 3500–4500 Kbps | Sweet spot for 720p30 sports. Adjust down if upload is tight |
| **I Frame Interval** | 60 | = 2 seconds at 30fps. IVS standard. Lets viewers join quickly and recovers fast from glitches |
| **Video Quality** | Higher or Highest | With CBR, this tells the encoder to try harder within the bitrate cap |
| **SVC** | OFF | Not useful for single-quality live output |
| **Smoothing** | Lean toward Smooth | Reduces frame-to-frame bitrate spikes, easier on upload pipe |

## Audio Settings

| Setting | Recommended | Notes |
|---|---|---|
| **Audio Encoding** | **AAC** | **Critical.** Required for `-c:a copy` into FLV. G.711/G.726 cannot be muxed into FLV |
| **Sampling Rate** | 48kHz | Highest quality available |
| **Audio Stream Bitrate** | 64kbps | Highest available; still negligible bandwidth vs video |
| **Audio Input** | MicIn or LineIn | Depends on your hardware setup |
| **Environmental Noise Filter** | Try ON | Worth enabling for outdoor fields |

## Why These Settings Matter

With `-c:v copy -c:a copy`, ffmpeg does **zero transcoding** — it just remuxes the camera's encoded stream into FLV for RTMPS delivery. This means:

- **Zero CPU cost** on the Pi for encoding
- Camera settings directly determine stream quality and compatibility
- Wrong codec choices (H.265, G.711) will cause ffmpeg to error out immediately

## Common Pitfalls

1. **H.265 selected** — ffmpeg will fail: `Could not write header for output file: Invalid argument`. H.265/HEVC cannot go into FLV container.
2. **H.264+ enabled** — Stream will work but viewers may experience buffering due to extreme bitrate variation.
3. **Audio left on G.711 (default)** — ffmpeg will fail because G.711 (u-law/a-law) is not supported in FLV. Must be AAC.
4. **Resolution too high** — 4K/1080p wastes bandwidth. Most GameChanger viewers watch on phones where 720p looks identical.
5. **I Frame Interval too large** — Viewers will see a long black screen when joining mid-stream. Keep at 2 seconds (60 frames at 30fps).
