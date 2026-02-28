# FieldCam Plans

## 1. Security

### 1.1 Plain-text password comparison
**`auth.py:37`, `config.py:46,58-62`**
Passwords are stored and compared as plain text. `config.py` even defines an unused `auth_hash_sfll` field that suggests hashing was planned but never wired up.
- Replace with `bcrypt` or `argon2` hashing
- Wire up or remove the unused `auth_hash_sfll` config field

---

## 2. Error Handling

### 2.1 Silent migration failure
**`database.py:44-50`**
The `ALTER TABLE` migration catches all exceptions with a bare `pass`. If it fails for a reason other than "column already exists," the error is swallowed.
- Log the exception or use `IF NOT EXISTS` logic

### 2.2 Generic exception detail leaked to client
**`routes.py:274-276, 298-300`**
`raise HTTPException(status_code=404, detail=str(e))` passes internal error strings to the browser.
- Log the full traceback server-side; return a generic user-facing message

---

## 3. Dead Code / Cleanup

### 3.1 Unused `ffmpeg_output_queue`
**`streaming.py:11-12`**
A global `queue.Queue()` is populated (line 117) but never consumed.
- Remove or wire up to a log/monitoring endpoint (see 4.3)

### 3.2 Repeated session boilerplate
**`database.py` (throughout)**
Every function manually opens/closes a session with try/finally.
- Refactor to a context-manager helper or use FastAPI's `Depends(get_db)` pattern

---

## 4. Current Streams UI

### Problem

The active streams tracking system exists in the database (`ActiveStream` model) but the UI around it has gaps:

1. **No real-time status indication.** A stream might be running, but the UI only shows what was last fetched. There's no visual indicator of stream health (is FFmpeg still alive? how long has it been running? how much time remains?).
2. **No progress/elapsed time.** We store `start_time` and `duration` but don't show a countdown or progress bar.
3. **No stream output/logs.** FFmpeg output goes to a `queue.Queue()` (`ffmpeg_output_queue`) but nothing ever reads from it for the UI.
4. **Stale stream detection is background-only.** `cleanup_stale_streams()` runs every 5 minutes — a user could be looking at a "running" stream that actually crashed 4 minutes ago.

### 4.1 Stream Status Cards

Replace the current simple table row with richer stream cards showing:
- Stream name and target (GameChanger key, partially masked)
- Status badge (running/pending/completed/failed/cancelled) with color coding
- Elapsed time / remaining time (calculated from `start_time` + `duration`)
- A progress bar (percentage of duration elapsed)
- Cancel button (already exists)

### 4.2 Process Health Check on Demand

Add a lightweight endpoint (or include in the SSE loop) that checks `os.kill(pid, 0)` and reports actual process liveness, rather than waiting for the 5-minute cleanup cycle.

### 4.3 FFmpeg Output Viewer (stretch)

Optionally expose a simple log viewer that reads from the `ffmpeg_output_queue` or the log files in `logs/`. This could be an SSE-fed `<pre>` block on a detail page — useful for debugging stream issues live.

---

## 5. Navigation Improvements

### 5.1 SPA navigation consolidation

The SPA navigation currently works via manual `history.pushState()` calls inside each nav link's `data-on:click`. The `spa-router.js` file bridges `popstate` events back to Datastar via a custom `datastar-navigate` event. This works but is fragile.

- Consolidate navigation into a single helper or evaluate whether Datastar's built-in mechanisms can replace the manual `pushState` + custom event pattern.

---

## 6. YouTube Enhancements (future)

- YouTube Live event scheduling via YouTube API (users manually create events and paste keys)
- Simultaneous multi-destination streaming (FFmpeg tee muxer)
- Per-destination encoding presets (transcoding for YouTube resolution requirements)

---

## Priority Order

1. **Security** (section 1) — password hashing
2. **Error handling** (section 2) — silent failures, leaked details
3. **Stream status UI** (section 4) — better cards, progress, health checks
4. **Dead code / cleanup** (section 3) — remove unused code, DRY up database layer
5. **Navigation** (section 5) — consolidate SPA routing
6. **YouTube enhancements** (section 6) — future features
