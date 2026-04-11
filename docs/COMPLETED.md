# Completed Work

Items from prior planning docs that have been implemented.

---

## Code Refactoring (from REFACTORING_SUMMARY)

- **Modular structure:** Monolithic `main.py` split into `config.py`, `auth.py`, `scheduler.py`, `streaming.py`, `routes.py`
- **Removed leaked secrets:** `print(SECRETS)` removed from main.py
- **Dead code cleanup:** Removed unused imports, globals (`process_dict`, `session_tokens`), unused functions (`job_function`, `stop_subprocess`), unused Pydantic models
- **Configuration moved to environment variables** via `pydantic-settings` (replaced `secrets.json`)
- **`pyproject.toml` + uv** replaces bare `requirements.txt`

## Security

- **CSRF middleware** (`csrf.py`) — wired into FastAPI via `app.add_middleware(CSRFMiddleware)`
- **Exception details no longer leaked** — cancel/remove routes return opaque `error_id` instead of `str(e)`

## Reliability

- **Graceful FFmpeg shutdown** — `terminate_all_streams()` sends SIGTERM/SIGKILL to all FFmpeg subprocesses on app exit

## Active Streams & Database (from ACTIVE_STREAMS_IMPLEMENTATION)

- **`ActiveStream` SQLAlchemy model** with full CRUD in `database.py`
- **Process tracking** — FFmpeg PID stored, checked for liveness
- **Stream cancellation from UI** — `POST /cancel_stream` sends SIGTERM
- **Automatic stale stream cleanup** — background task every 5 minutes
- **Stream history** — `GET /fragment/history` with status badges, error details
- **Admin history delete** — `POST /delete_history` (admin-only)

## Stream Health (from FEATURE_STREAM_HEALTH)

- **`ffmpeg_output_queue` removed** — replaced with `-progress pipe:1` parsing in `streaming.py`
- **SSE stream health endpoint** — `GET /sse/stream-health` pushes real-time ffmpeg stats (fps, speed, bitrate) to connected clients via Datastar
- **Stats parsing** — structured extraction of ffmpeg progress fields

## SPA & Datastar Migration

- **SPA shell** (`base_shell.html.j2`) with Datastar-powered partial fragment updates
- **Fragment routes:** `_list_content`, `_add_form_body`, `_settings_content`, `_login_content`, etc.
- **Event bus** (`event_bus.py`) for live SSE push of list changes and stream stats
- **SSE list updates** — `GET /sse/list` streams list content to all connected viewers
- **Toast notifications** via SSE fragment patching

## YOLO Object Detection

- **`yolo_check.py`** — ultralytics-based person/object detection on field snapshots
- **Detection API** (`GET /api/detection`) and **fragment** (`GET /fragment/detection`)
- **Background cache warm-up** thread for detection results

## UI & UX

- **Field image serving** — `GET /dynamic/field.jpg` with cache headers
- **CPU temperature display** in footer (reads `/sys/class/thermal`)
- **Bootstrap CSS/icons bundled locally** in `static/` (though CDN refs remain in template)
- **Sorted history** by timestamp
- **Placeholder field image** when no snapshot exists

## Infrastructure

- **Health check endpoint** — `GET /health` returns `{"status": "ok"}` for Docker/orchestrator probes
- **Multi-arch Docker build** support (`buildx.sh`)
- **GitHub Actions CI** — ruff lint + format checks (`lint.yml`), container build (`build-camapp.yml`)
- **`.dockerignore`** added
- **Pre-commit hooks** configured (`.pre-commit-config.yaml`)
- **Ruff configuration** consolidated into `cam-app/pyproject.toml`
