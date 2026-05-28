# FieldCam

A FastAPI-based web application for scheduling and managing live camera streams for ball field events. FieldCam allows users to schedule streaming sessions, automatically capturing and serving field camera images for scheduled games and practices.

## Features

- **Live Field Camera Integration** - Capture and serve real-time field images
- **Job Scheduling** - Schedule streaming sessions with start/end times
- **User Authentication** - Secure login system with session management
- **Automated Streaming** - Automatically start/stop streams based on schedule
- **Docker Support** - Single published container, runs anywhere Docker does
- **Job Management** - Web interface for adding, listing, and removing scheduled jobs

## Run with the published Docker image

The `camapp` container image is automatically built and pushed to GitHub Container Registry (GHCR) on every push to `main` that changes files under `cam-app/`. The published image is the recommended way to run FieldCam.

### Prerequisites

- Docker (24+)
- A directory on the host for runtime state (`jobs/`, `logs/`)
- An RTSP-capable IP camera (only required for the camera capture cron, not for the app to start)

### 1. Pull the image

```bash
docker pull ghcr.io/jkrauska/fieldcam/camapp:latest
```

The image is currently built for `linux/arm64` (Raspberry Pi / Apple Silicon). If you need `linux/amd64`, update `platforms` in `.github/workflows/build-camapp.yml` and rebuild.

### 2. Create an `.env` file

Create a working directory and a `.env` file inside it (see `cam-app/.env.example` in the repo for a template you can copy if you cloned it):

```bash
mkdir -p ~/fieldcam && cd ~/fieldcam
mkdir -p jobs logs
touch .env
```

Minimum required variables:

| Variable         | Description                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| `SECRET_KEY`     | Random string for session signing — generate with `openssl rand -hex 32` |
| `PASSWORDS`      | Comma-separated list of allowed login passwords                          |
| `ADMIN_PASSWORD` | Password that unlocks the settings page                                  |
| `CAMERA_IP`      | IP address of the RTSP camera                                            |
| `CAMERA_USER`    | Camera username                                                          |
| `CAMERA_PASS`    | Camera password                                                          |

Optional variables:

| Variable               | Default                           | Description                                 |
| ---------------------- | --------------------------------- | ------------------------------------------- |
| `TIMEZONE`             | `America/Los_Angeles`             | Timezone for scheduling                     |
| `COOKIE_NAME`          | `stream411_login`                 | Login cookie name                           |
| `TOKEN_EXPIRY_MINUTES` | `30`                              | Login session duration in minutes           |
| `LOCATION`             | `Tepper`                          | Location name shown in UI                   |
| `BLACKOUT_SEASON`      | —                                 | Shown in schedule form warning              |
| `BLACKOUT_TEAMS`       | —                                 | Shown in schedule form warning              |
| `RTMP_GAMECHANGER`     | (preset)                          | RTMP base URL for GameChanger               |
| `RTMP_YOUTUBE`         | `rtmp://a.rtmp.youtube.com/live2` | RTMP base URL for YouTube                   |
| `JOBS_DB_PATH`         | `sqlite:///jobs/jobs.sqlite`      | SQLite database path (inside the container) |
| `FIELD_IMAGE_PATH`     | `/tmp/field.jpg`                  | Path the app reads the field snapshot from  |

Example `.env`:

```bash
SECRET_KEY=replace-with-openssl-rand-hex-32
PASSWORDS=changeme1,changeme2
ADMIN_PASSWORD=changeme-admin
CAMERA_IP=192.168.1.50
CAMERA_USER=admin
CAMERA_PASS=supersecret
TIMEZONE=America/Los_Angeles
LOCATION=Tepper
RTMP_YOUTUBE=rtmp://a.rtmp.youtube.com/live2
```

### 3. Start the container

```bash
docker run -d \
  --name camapp \
  --restart unless-stopped \
  -p 9090:9090 \
  -v "$(pwd)/.env:/code/.env" \
  -v "$(pwd)/jobs:/code/jobs" \
  -v "$(pwd)/logs:/code/logs" \
  -v /tmp/field.jpg:/tmp/field.jpg:ro \
  ghcr.io/jkrauska/fieldcam/camapp:latest
```

The app is now available at `http://localhost:9090`. Health check: `GET /health`.

Notes on the volumes:

- `.env` — bind-mounted so the in-app **Settings** page (admin only) can persist edits back to the host file. On save it rewrites `.env` and SIGTERMs the process; the `--restart unless-stopped` policy then brings the container back with the new values. Without this mount, settings edits are silently discarded on restart. (You can substitute `--env-file .env` if you don't need the in-app editor — values will still load at boot — but writes from the Settings page won't survive.)
- `jobs/` — SQLite job/state database (must persist across restarts).
- `logs/` — FFmpeg / app log files.
- `/tmp/field.jpg` — read-only bind so the container can serve the snapshot the host writes (see step 4). Pre-create the file with `touch /tmp/field.jpg` before starting the container, otherwise Docker will create a directory at that path instead. Skip this mount entirely if you don't yet have a cron capture set up — the app starts fine without it.

Optional mounts:

- `-v /sys/class/thermal:/sys/class/thermal:ro` — exposes Pi CPU temperature to the data page.

### 4. (Optional) Capture a field snapshot via cron

The app serves the file at `FIELD_IMAGE_PATH` (default `/tmp/field.jpg`) at `/dynamic/field.jpg`. The simplest way to populate it is a host-side cron job using `ffmpeg`:

```bash
crontab -e
```

```cron
* * * * * /usr/bin/ffmpeg -hide_banner -loglevel error -y \
  -i rtsp://USERNAME:PASSWORD@IPADDRESS:554/Streaming/channels/102/ \
  -frames:v 1 -q:v 2 /tmp/field.jpg
```

Using `/tmp` keeps the file world-readable so any user (and the bind-mounted container) can read it.

### 5. Common operations

```bash
docker logs -f camapp                    # tail logs
docker restart camapp                    # restart in place
docker pull ghcr.io/jkrauska/fieldcam/camapp:latest \
  && docker rm -f camapp \
  && docker run -d ... (same flags as above)   # update to latest image
```

## API Endpoints

### Public Endpoints

- `GET /login` — Login form
- `POST /login` — Handle login submission
- `GET /health` — Health check (for Docker / orchestrator probes)

### Authenticated Endpoints

- `GET /` — Main SPA shell (list of scheduled jobs)
- `GET /dynamic/field.jpg` — Serve current field image (no cache)
- `GET /add` — Add new streaming job form
- `POST /submit` — Submit new streaming job
- `POST /remove_job` — Remove a scheduled job
- `POST /cancel_stream` — Cancel an active stream
- `GET /data` — Data / metrics page
- `GET /logout` — Log out current user
- `GET /version` — Application version information

## Usage

### Adding a Streaming Job

1. Navigate to `http://localhost:9090/`
2. Log in with one of the passwords from `PASSWORDS` (or `ADMIN_PASSWORD` for admin features)
3. Click **Add Job**
4. Fill in the form:
   - **Team Name** — Name of the team or event
   - **Date** — Date of the game (YYYY-MM-DD)
   - **Start Time** — Stream start time (HH:MM)
   - **End Time** — Stream end time (HH:MM)
   - **Stream Key** — (Optional) Custom stream key or auto-generated
5. Click **Submit**

### Managing Jobs

- View all scheduled jobs on the main page.
- Remove jobs with the remove button next to each job.
- Jobs are automatically executed based on their scheduled time.

### Viewing the Field Camera

Access the live field image at `/dynamic/field.jpg` (requires authentication).

## Development

### Local Development Setup

#### Install uv

Install [uv](https://github.com/astral-sh/uv) — a fast Python package installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

#### Setting up the environment

```bash
cd cam-app
uv sync --all-extras
pre-commit install
```

#### Running the app locally

```bash
cd cam-app
uv run uvicorn app.main:app --reload --port 9090
```

The app loads its config from `cam-app/.env` if present (resolved relative to the `cam-app/` project root, not the current working directory).

### Code Quality

This project uses [Ruff](https://github.com/astral-sh/ruff) for linting and formatting. Always run the following from `cam-app/` before committing:

```bash
uv run ruff check . && uv run ruff format .
```

Pre-commit hooks (`pre-commit install`) run these automatically on commit. GitHub Actions also runs ruff checks on every PR — see `.github/workflows/lint.yml`.

### Building the Docker image locally

The published image is the canonical build, but you can build locally:

```bash
cd cam-app
docker build -t camapp:latest .
```

For an iterative rebuild loop (Linux only, requires `inotify-tools`):

```bash
cd cam-app
./build.sh now
```

This watches `app/` for changes and rebuilds the image after a 60s debounce. Restart the running container manually after each rebuild (`docker rm -f camapp && docker run ...`).

#### A note on YOLO detection

Detection runs on **ONNX Runtime** against pre-exported models committed under `cam-app/app/models/` — no `torch` or `ultralytics` in the image, no model download at runtime. This keeps the image small and fast on a Raspberry Pi (ONNX is ~2× faster than PyTorch there). The app still degrades gracefully: if `onnxruntime` or the model file is missing, detection routes return an error and the rest of the UI keeps working.

Two models ship in the image; select via the `YOLO_MODEL` setting (env var or settings page):

| Model | `YOLO_MODEL` value | Notes |
|-------|--------------------|-------|
| Nano (default) | `app/models/yolov8n.onnx` | ~12 MB, fastest (~130 ms/img on Pi 5) |
| Medium | `app/models/yolov8m.onnx` | ~50 MB, more accurate at distance, ~3–4× slower |

`YOLO_MODEL` must point at an `.onnx` file — a stale `.pt` value (from the old torch path) will return a clear error.

To regenerate or add a model (e.g. `yolov8s`), use the `export` extra — it pulls in `ultralytics` + `torch` locally only:

```bash
cd cam-app
uv run --extra export python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', imgsz=640, opset=12)"
mv yolov8n.onnx app/models/yolov8n.onnx
```

### Technology Stack

- **FastAPI** — Modern Python web framework
- **Uvicorn** — ASGI server
- **APScheduler** — Job scheduling
- **SQLAlchemy** — Database ORM
- **Jinja2** — Template engine
- **FastAPI-Login** — Authentication
- **Datastar** — Lightweight hypermedia frontend (CDN script, no npm); backend-driven UI with HTML patch responses
- **Docker** — Containerization

### Datastar integration

The list and add pages use [Datastar](https://data-star.dev/) so that actions (remove job, cancel stream, submit new stream) update the page via **HTML morphing** instead of full reloads:

- **List page** (`/`): Remove and Cancel buttons submit via `@post(..., {contentType: 'form'})`. The server returns an HTML fragment for `#list-content`, which Datastar morphs into the DOM.
- **Add page** (`/add`): The form uses `data-on:submit="@post('/submit', {contentType: 'form'})"`. On success the server returns a fragment for `#add-form-container` (success message + link back to list).

No frontend build step or Datastar SDK is required; the client loads the Datastar script from the CDN, and the backend returns plain HTML fragments with the expected element IDs.

## Troubleshooting

### Container

```bash
docker logs -f camapp                  # follow logs
docker restart camapp                  # restart
docker exec -it camapp /bin/sh         # shell into the container
```

### Field image not updating

Check the host cron job is running:

```bash
crontab -l
```

Verify FFmpeg can talk to the camera:

```bash
ffmpeg -i rtsp://USERNAME:PASSWORD@IPADDRESS:554/Streaming/channels/102/ -frames:v 1 test.jpg
```

### Login issues

Verify your `.env` file is being read by the container:

```bash
docker exec camapp env | grep -E "SECRET_KEY|CAMERA_IP|PASSWORDS"
```

If those are empty, the `--env-file` path is wrong or the variables are missing from the file.

### Configuration

If the container exits immediately with a "Missing required configuration" message, one of the required variables (`SECRET_KEY`, etc.) is missing or empty. Re-check the `.env` file against the table above.

## Contributing

Contributions are welcome — please open a pull request.

## License

See [LICENSE](LICENSE) file for details.

## Support

For issues, questions, or contributions, please visit the [GitHub repository](https://github.com/jkrauska/fieldcam).
