# FieldCam Improvement Ideas

A fresh-eyes review of the codebase. Organized from quick wins to larger efforts.

---

## 1. Security

### 1.1 Hash passwords
**`auth.py:61`, `config.py:46`**
Passwords are compared as plain text (`password not in settings.passwords_list`). The `auth_hash_sfll` field in config was clearly meant for hashing but is unused.
- Store bcrypt/argon2 hashes in the env var, compare with `bcrypt.checkpw()`
- Remove or wire up `auth_hash_sfll`

### 1.2 Camera credentials in RTSP URL
**`streaming.py:23`**
`input_cam_url()` interpolates `cam_user` and `cam_pass` directly into the URL string. This URL ends up in FFmpeg's command-line arguments, which are visible via `ps aux` on the host.
- Use FFmpeg's `-headers` option or pipe credentials via stdin
- At minimum, avoid logging the full URL (currently `logging.info` may expose it)

### 1.3 Cookie missing `Secure` flag
**`auth.py:83-88`**
`set_cookie()` doesn't set `secure=True`. If the app ever runs behind HTTPS (likely in production), the cookie should be marked secure to prevent transmission over plain HTTP.
- Add `secure=True` when not in a development/debug mode

### 1.4 CSRF middleware allows missing headers
**`csrf.py:43-46`**
When neither Origin nor Referer is present, the request is allowed through. The comment says SameSite=Lax is the backstop, but this weakens the CSRF defense.
- Consider rejecting POST requests with no Origin/Referer, or at least logging a warning

---

## 2. Reliability & Error Handling

### 2.1 Silent `ALTER TABLE` failure
**`database.py:44-50`**
The migration catches all exceptions with bare `pass`. If it fails for a non-"column exists" reason, the error is silently swallowed.
- Check the specific exception message or use `IF NOT EXISTS` (via raw SQL for SQLite: `PRAGMA table_info` check)
- At minimum, log the exception at `DEBUG` level

### 2.2 Exception details leaked to client
**`routes.py:326, 350`**
`raise HTTPException(detail=str(e))` sends internal error strings to the browser.
- Log the full traceback server-side, return a generic message to the client

### 2.3 `created_at`/`updated_at` use class-level defaults
**`database.py:31-32`**
```python
created_at = Column(String, default=datetime.utcnow().isoformat())
```
This evaluates once at import time, so every row gets the same timestamp (the time the module was loaded). Should be:
```python
created_at = Column(String, default=lambda: datetime.utcnow().isoformat())
```

### 2.4 No graceful FFmpeg shutdown on app exit
**`streaming.py`**
When the app shuts down, `signal_shutdown()` breaks SSE loops but does nothing about running FFmpeg subprocesses. Orphaned FFmpeg processes will keep streaming until their duration expires.
- Track child PIDs and `SIGTERM` them on shutdown
- Or use `process.terminate()` in a cleanup handler

### 2.5 `input_cam_url()` accepts unused `config` param
**`streaming.py:21-24`**
The `config` parameter is accepted but never used. Same for `config` in `stream_game()`.
- Remove dead parameters or document what they're intended for

---

## 3. Code Quality

### 3.1 Repeated session boilerplate
**`database.py` (throughout)**
Every function manually opens/closes a session with try/finally. This is 6+ repetitions of the same pattern.
- Use a context manager: `@contextmanager def get_session(): ...`
- Or use FastAPI's `Depends(get_db)` pattern for route-level injection

### 3.2 Unused `ffmpeg_output_queue`
**`streaming.py:13`**
A global `queue.Queue()` is populated on every FFmpeg stderr line but nothing ever reads from it. It will grow unbounded for long streams.
- Either wire it up to the planned stream health UI, or remove it
- If keeping it, add a `maxsize` to prevent memory growth

### 3.3 Duplicate time-zone conversion logic
**`routes.py:86-90` and `routes.py:357-360`**
The same UTC-to-local conversion code appears in both `_list_context()` and `history_fragment()`.
- Extract to a helper: `def localize_stream_times(streams): ...`

### 3.4 Duplicate detection text formatting
**`routes.py:66-79` and `routes.py:383-389`**
`_get_detection_text()` and `detection_fragment()` both format YOLO counts into the same string pattern independently.
- Share the formatting logic

### 3.5 Mixed route registration styles
**`main.py`**
Some routes use `@app.get` decorators, others use `app.post("/submit")(submit_job)` — the two styles are mixed inconsistently.
- Pick one style and use it consistently

### 3.6 f-string logging
Throughout the codebase, logging uses f-strings: `logging.info(f"...")`. This evaluates the string even when the log level is disabled.
- Use lazy formatting: `logging.info("Starting stream to %s", destination)`

---

## 4. UX Improvements

### 4.1 Stream progress / elapsed time
The database has `start_time` and `duration` but the UI doesn't show how much time remains or a progress indicator. Users see "LIVE" with no sense of whether the stream just started or is about to end.
- Add elapsed/remaining time to stream rows (calculated client-side from `start_time` + `duration`)
- Optionally show a progress bar

### 4.2 Confirmation before destructive actions
Cancel-stream and remove-job buttons fire immediately with no confirmation.
- Add a "Are you sure?" step — even a simple inline confirm toggle

### 4.3 Field image staleness indicator
The field image updates "every 5 minutes" (via cron). If cron fails, the user sees a stale image with no warning.
- Show the file's `mtime` as "Last updated X minutes ago"
- Highlight in red if older than 10 minutes

### 4.4 Mobile responsiveness
The stream table uses `table-responsive` but stream key truncation (`{{ stream.stream_key[13:][:6] }}...`) hardcodes character offsets that assume key format. On narrow screens, column widths can still be awkward.
- Consider a card layout on mobile breakpoints instead of a table
- Use CSS `text-overflow: ellipsis` instead of template-level truncation

### 4.5 Toast auto-dismiss is CSS-only
**`routes.py:397-401`**
The toast uses a CSS `animation: toast-fade 2s` to disappear. It stays in the DOM (just invisible). If multiple toasts fire quickly, they stack invisibly.
- Remove the toast DOM element after the animation ends, or use a proper toast queue

### 4.6 Empty state on the main page
When there are no streams or scheduled jobs, the page shows just the field image and two big buttons. There's no messaging to orient a new user.
- Add a brief "No streams scheduled. Click Schedule to get started." message

---

## 5. Performance

### 5.1 YOLO detection runs synchronously (cached)
**`routes.py:66-79`**
`_get_detection_text()` is called on every list render. The 60-second cache helps, but when it expires, the next SSE push blocks on YOLO inference in the event loop thread (it's not `await`ed — it's a plain function call inside `_list_context()`).
- Run detection in a background task on a timer instead of lazily on request
- Or wrap it with `asyncio.to_thread` like `detection_fragment()` does

### 5.2 SSE re-renders the full list on every change
**`routes.py:424`**
Every time `event_bus` bumps, the entire list template is re-rendered and pushed to all SSE clients — even if only one field changed.
- For a small app this is fine, but if the list grows, consider sending only the changed fragment

### 5.3 Field image served through Python
**`routes.py:51-59`**
Every image request goes through FastAPI's `FileResponse`. Since this is a static file that cron writes to disk, it could be served directly by a reverse proxy (nginx, Caddy).
- Add a note in deployment docs, or configure the Docker setup with nginx in front

---

## 6. Testing

### 6.1 No test suite exists
There are zero automated tests. The CI only runs Ruff (linting).
- Add pytest with basic tests for:
  - `new_stream()` scheduling logic (edge cases: past start time, duplicate names)
  - `_build_output_url()` for each destination type
  - CSRF middleware (allowed/blocked scenarios)
  - Login backoff timing
  - `cleanup_stale_streams()` with mocked PIDs

### 6.2 No integration/E2E tests
- A basic test that boots the FastAPI app (`TestClient`) and exercises the submit/list/cancel flow would catch regressions in the SPA fragment rendering

---

## 7. Infrastructure & DevOps

### 7.1 Bootstrap loaded from CDN
**`base_shell.html.j2:7-8`**
Bootstrap CSS is loaded from `cdn.jsdelivr.net` in the template, but local copies also exist in `static/`. The CDN version wins (it's in `<head>` first).
- Pick one: either use the local copies for offline resilience, or remove the local copies to reduce repo size

### 7.2 Datastar loaded from CDN
**`base_shell.html.j2:114`**
Same issue — Datastar JS is loaded from CDN but a local copy exists in `static/datastar.js`.
- Decide on local-only (for air-gapped/offline field deployments) or CDN-only

### 7.3 Docker Compose volume for static mounts app code
**`docker-compose.yml:14`**
`./cam-app/app/static:/code/app/static` mounts the host's static directory into the container. This means container-baked static files are overridden by whatever's on the host. If the host directory is stale, the app serves old assets.
- Consider mounting only the specific file (field.jpg) instead of the entire static directory

### 7.4 No health check endpoint
There's no `/health` or `/readyz` for Docker/orchestrator health checks.
- Add a lightweight endpoint that returns 200 (and optionally checks DB connectivity)

### 7.5 Log rotation
FFmpeg writes log files to `logs/` with PID-based names. There's no rotation or cleanup.
- Add logrotate config or a periodic cleanup job for old log files

---

## 8. Architecture Considerations

### 8.1 Module-level side effects
**`config.py:111-114`**
`scheduler.start()` runs at import time. This means importing `config` in tests or scripts immediately starts the APScheduler background thread.
- Move `scheduler.start()` into the FastAPI startup event
- Same for `atexit.register` — move to shutdown event (which already exists)

### 8.2 Global mutable state
`routes.py` has module-level mutable state (`_shutting_down`, `_detection_cache`). `event_bus.py` has a global `_list_version`. `auth.py` has global `_fail_counts`/`_last_fail`. This works for a single-process deployment but would break with multiple workers.
- Document that the app must run with a single Uvicorn worker (which it does now)
- If multi-worker is ever needed, move shared state to Redis or the database

### 8.3 `datetime.utcnow()` is deprecated
**`database.py:31-32, 63, 152, 211`**
`datetime.utcnow()` is deprecated since Python 3.12. Use `datetime.now(timezone.utc)` instead.

### 8.4 Inconsistent time handling
Start times are stored as ISO strings in the database, then parsed back with string manipulation (`replace("Z", "+00:00")`) in routes. The `start_time_local` attribute is monkey-patched onto ORM objects.
- Store times as proper `DateTime` columns in SQLAlchemy
- Or at least standardize the ISO format (always include timezone info)

---

## Priority Suggestion

| Priority | Section | Effort | Impact |
|----------|---------|--------|--------|
| 1 | 2.3 Fix `created_at` default bug | 5 min | Correctness bug |
| 2 | 1.1 Hash passwords | 1 hr | Security |
| 3 | 2.2 Stop leaking exceptions | 15 min | Security |
| 4 | 3.2 Fix unbounded queue | 10 min | Memory safety |
| 5 | 8.3 Replace `utcnow()` | 15 min | Future-proofing |
| 6 | 7.4 Add health endpoint | 15 min | Operations |
| 7 | 3.1 Session context manager | 30 min | Code quality |
| 8 | 6.1 Add basic tests | 2-4 hr | Reliability |
| 9 | 4.1 Stream progress UI | 2-3 hr | UX |
| 10 | 8.1 Remove import side effects | 1 hr | Testability |
