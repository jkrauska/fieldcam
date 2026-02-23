# FieldCam Plans

## 1. Datastar Best Practices Audit — DONE

We're on Datastar RC7 (`datastar@1.0.0-RC.7`). Several patterns in the codebase bypassed Datastar in favor of manual JS/DOM manipulation.

### 1.1 Manual `fetch()` / DOM manipulation — DONE

| Location | What changed |
|---|---|
| `base_shell.html.j2` (logout) | Replaced `fetch('/logout').then(...)` JS with a plain `<a href="/logout">` link. No JS needed — the server deletes the cookie and redirects. |
| `base_shell.html.j2` (people count) | Removed the entire 28-line `setInterval` / `fetch` / manual DOM polling IIFE. People count is now loaded declaratively via `data-on:load="@get('/fragment/people_count')"` on the `#people-count` div in `_list_content.html.j2`. New backend endpoint `GET /fragment/people_count` returns an HTML fragment that Datastar morphs in. |
| `_list_content.html.j2` (copy buttons) | Replaced bare `onclick="copyToClipboard(..., this)"` with `data-on:click="copyToClipboard(..., el)"` (2 instances: active streams + scheduled jobs). |
| `add.html.j2` / `_add_form_body.html.j2` (auto-set end time) | Replaced `addEventListener('input', ...)` script blocks with `data-on:input="autoEndTime(el.value, 'endId')"`. Extracted the shared `autoEndTime()` helper into `base_shell.html.j2` (for SPA/modal) and `add.html.j2` (standalone fallback). Removed ~38 lines of IIFE/script blocks total. |

### 1.2 Hardcoded HTML strings — DONE

| Location | What changed |
|---|---|
| `routes.py` `submit_job()` | Replaced 5-line hardcoded HTML string with `templates.env.get_template("_submit_success.html.j2").render()`. New template: `_submit_success.html.j2`. |

### 1.3 Full-page reloads still present (deferred to section 2)

| Location | Status |
|---|---|
| `list.html.j2` `<meta http-equiv="refresh" content="900">` | Will be removed when SSE is implemented (section 2). |
| `auth.py` `create_redirect_content()` | Kept as non-SPA fallback. |

### 1.4 Navigation handling (unchanged)

The SPA navigation currently works via manual `history.pushState()` calls inside each nav link's `data-on:click`. The `spa-router.js` file bridges `popstate` events back to Datastar via a custom `datastar-navigate` event. This works but is fragile.

**Potential improvement:** Consolidate navigation into a single helper or evaluate whether Datastar's built-in mechanisms can replace the manual `pushState` + custom event pattern.

### 1.5 No SSE endpoints (deferred to section 2)

Datastar's reactive model is built around SSE (Server-Sent Events) for server-push updates. We currently have **zero** SSE endpoints. Every update requires either a user action or a one-shot `data-on:load` fetch. Adding SSE is the single biggest remaining improvement (details in section 2).

---

## 2. Auto-Updating List View for All Viewers — DONE

### What was implemented

**Event bus** (`event_bus.py`): A thread-safe version counter. Any code path that changes jobs or streams calls `notify_list_changed()` to bump the counter. SSE generators poll it every 2 seconds.

**SSE endpoint** (`GET /sse/list`): Returns `text/event-stream`. On connect it sends the current `_list_content.html.j2` as a `datastar-patch-elements` event targeting `#list-content` with `inner` mode. When the version counter changes, it re-renders and pushes the updated fragment. Sends `: keepalive` comments every 30 seconds to prevent proxy/browser timeouts.

**Notification hooks**: `notify_list_changed()` is called from:
- `routes.py`: `submit_job()`, `remove_job_route()`, `cancel_stream_route()`
- `database.py`: `add_active_stream()`, `update_stream_status()`, `cleanup_stale_streams()`

This means all viewers see updates within ~2 seconds when:
- A job is scheduled or removed
- A stream starts, completes, fails, or is cancelled
- The periodic cleanup detects a dead process

**People count**: Now rendered server-side with 60-second caching via `_get_people_count_text()`. Included in the template context as `{{ people_count }}`. No more client-side fetch — the count is part of the SSE-pushed content.

**Frontend**: The `#list-content` wrapper div has `data-on:load="@get('/sse/list')"` (added in `_render_list_content_fragment()` and `list.html.j2`). Datastar's `@get()` handles SSE responses natively — it keeps the connection open, processes `datastar-patch-elements` events, and auto-reconnects on errors with exponential backoff.

**Removed**: `<meta http-equiv="refresh" content="900">` from `list.html.j2` — no longer needed.

---

## 3. Current Streams UI

### Problem

The active streams tracking system exists in the database (`ActiveStream` model) but the UI around it has gaps:

1. **No real-time status indication.** A stream might be running, but the UI only shows what was last fetched. There's no visual indicator of stream health (is FFmpeg still alive? how long has it been running? how much time remains?).

2. **No progress/elapsed time.** We store `start_time` and `duration` but don't show a countdown or progress bar.

3. **No stream output/logs.** FFmpeg output goes to a `queue.Queue()` (`ffmpeg_output_queue`) but nothing ever reads from it for the UI. The queue just accumulates.

4. **Stale stream detection is background-only.** `cleanup_stale_streams()` runs every 5 minutes — a user could be looking at a "running" stream that actually crashed 4 minutes ago.

### Improvements

#### 3.1 Stream Status Cards

Replace the current simple table row with richer stream cards showing:
- Stream name and target (GameChanger key, partially masked)
- Status badge (running/pending/completed/failed/cancelled) with color coding
- Elapsed time / remaining time (calculated from `start_time` + `duration`)
- A progress bar (percentage of duration elapsed)
- Cancel button (already exists)

#### 3.2 Live Status via SSE

Tie into the SSE endpoint from section 2. When a stream starts, transitions, or ends, push an updated fragment. This means:
- When `stream_game()` calls `add_active_stream()`, trigger an SSE push.
- When `update_stream_status()` is called (completed/failed), trigger an SSE push.
- When `cancel_active_stream()` is called, trigger an SSE push.

#### 3.3 FFmpeg Output Viewer (stretch)

Optionally expose a simple log viewer that reads from the `ffmpeg_output_queue` or the log files in `logs/`. This could be an SSE-fed `<pre>` block on a detail page — useful for debugging stream issues live.

#### 3.4 Process Health Check on Demand

Add a lightweight endpoint (or include in the SSE loop) that checks `os.kill(pid, 0)` and reports actual process liveness, rather than waiting for the 5-minute cleanup cycle.

---

## 4. YouTube Streaming as an Alternative to GameChanger — **DONE**

### What Was Done

**4.1 Data Model** — Added `destination` column (TEXT, default `"gamechanger"`) to `ActiveStream` in `database.py`. Included an `ALTER TABLE` migration in `init_db()` so existing SQLite databases get the column automatically.

**4.2 RTMP Routing** — Replaced the hardcoded GameChanger RTMP URL in `streaming.py` with a `RTMP_BASES` dictionary mapping `"gamechanger"` and `"youtube"` to their respective ingest URLs. A `_build_output_url()` helper builds the final URL from the destination + key. The `"custom"` destination uses a user-provided base URL.

**4.3 Scheduler Plumbing** — Updated `new_stream()` in `scheduler.py` to accept `destination` and `custom_url` parameters and pass them through to `stream_game()` via APScheduler kwargs.

**4.4 Route / Form Handling** — Added `destination` and `customUrl` form fields to `submit_job()` in `routes.py`. These are forwarded to `new_stream()`. Default remains `"gamechanger"` for backward compatibility.

**4.5 Add Form UI** — Updated both `_add_form_body.html.j2` (SPA modal) and `add.html.j2` (standalone page) with:
- A destination `<select>` (GameChanger / YouTube / Custom RTMP)
- Datastar `data-show` to conditionally reveal the Custom RTMP URL field
- Context-sensitive stream key hints: GameChanger logo + `sk_us-east-1_` hint for GC, YouTube Studio instructions for YT
- GameChanger "How to Get Your Key" link only shown when GC is selected

**4.6 List View** — Added a "Dest" column to all three tables:
- Active streams table (`_list_content.html.j2`) — reads `stream.destination`
- Scheduled jobs table (`_list_content.html.j2`) — reads `job.kwargs.destination`
- Stream history table (`_list_all_content.html.j2`) — reads `stream.destination`
- Badges: **GC** (dark), **YT** (red), **Custom** (grey)

### Not Yet Implemented (future enhancements)

- YouTube Live event scheduling via YouTube API (users manually create events and paste keys)
- Simultaneous multi-destination streaming (FFmpeg tee muxer)
- Per-destination encoding presets (transcoding for YouTube resolution requirements)

---

## Priority Order

1. ~~**Datastar best practices cleanup** (section 1) — remove manual JS, use Datastar idioms consistently~~ **DONE**
2. ~~**SSE endpoint for live list updates** (sections 2 + 3.2) — highest impact, enables real-time UI for all viewers~~ **DONE**
3. **Stream status UI improvements** (section 3) — better cards, progress, elapsed time
4. ~~**YouTube destination support** (section 4) — new feature, moderate effort~~ **DONE**
