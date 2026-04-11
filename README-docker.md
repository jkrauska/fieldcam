# Docker Deployment

The cam-app container image is automatically built and pushed to GitHub Container Registry (GHCR) on every push to `main` that changes files under `cam-app/`.

## Pull the image

```bash
docker pull ghcr.io/jkrauska/fieldcam/camapp:latest
```

The image is built for `linux/arm64` (Raspberry Pi / Apple Silicon). If you need x86, update the `platforms` field in `.github/workflows/build-camapp.yml`.

## Environment file

Create a `.env` file (see `cam-app/.env.example` for reference):

```bash
cp cam-app/.env.example cam-app/.env
```

Required variables:


| Variable         | Description                                     |
| ---------------- | ----------------------------------------------- |
| `SECRET_KEY`     | Random string for session signing               |
| `CAMERA_IP`      | IP address of the RTSP camera                   |
| `CAMERA_USER`    | Camera username                                 |
| `CAMERA_PASS`    | Camera password                                 |
| `PASSWORDS`      | Comma-separated list of allowed login passwords |
| `ADMIN_PASSWORD` | Password that unlocks the settings page         |


Optional variables:


| Variable               | Default                      | Description                    |
| ---------------------- | ---------------------------- | ------------------------------ |
| `TIMEZONE`             | `America/Los_Angeles`        | Timezone for scheduling        |
| `COOKIE_NAME`          | `stream411_login`            | Login cookie name              |
| `TOKEN_EXPIRY_MINUTES` | `30`                         | Login session duration         |
| `LOCATION`             | `Tepper`                     | Location name shown in UI      |
| `BLACKOUT_SEASON`      | —                            | Shown in schedule form warning |
| `BLACKOUT_TEAMS`       | —                            | Shown in schedule form warning |
| `RTMP_GAMECHANGER`     | —                            | RTMP base URL for GameChanger  |
| `RTMP_YOUTUBE`         | —                            | RTMP base URL for YouTube      |
| `JOBS_DB_PATH`         | `sqlite:///jobs/jobs.sqlite` | SQLite database path           |


## Run with Docker Compose

The `docker-compose.yml` at the repo root is the recommended way to run:

```bash
docker compose up -d
```

This:

- Pulls `camapp:latest` (update `image` to the GHCR path below if not building locally)
- Exposes port 9090
- Loads env vars from `cam-app/.env`
- Mounts persistent volumes for the database, logs, static assets, and YOLO models

To use the GHCR image, update `docker-compose.yml`:

```yaml
services:
  camapp:
    image: "ghcr.io/jkrauska/fieldcam/camapp:latest"
    # ... rest stays the same
```

### Volume mounts


| Host path              | Container path                   | Purpose                      |
| ---------------------- | -------------------------------- | ---------------------------- |
| `./cam-app/app/static` | `/code/app/static`               | Static assets (field images) |
| `./jobs`               | `/code/jobs`                     | SQLite database              |
| `./logs`               | `/code/logs`                     | FFmpeg log files             |
| `./cam-app/models`     | `/code/models` (read-only)       | YOLO model weights           |
| `/sys/class/thermal`   | `/sys/class/thermal` (read-only) | CPU temperature              |


## Run standalone

```bash
docker run -d \
  --name camapp \
  --restart always \
  -p 9090:9090 \
  --env-file cam-app/.env \
  -v ./jobs:/code/jobs \
  -v ./logs:/code/logs \
  ghcr.io/jkrauska/fieldcam/camapp:latest
```

## View logs

```bash
docker logs -f camapp
```

## Rebuild locally

If you want to build the image locally instead of pulling from GHCR:

```bash
cd cam-app
docker build -t camapp:latest .
```

Or for multi-arch (arm64) from a non-arm host:

```bash
cd cam-app
./buildx.sh
```

