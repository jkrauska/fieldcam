# Active Streams Tracking Implementation

## Overview

This implementation adds SQLite-based tracking for active streaming processes, allowing real-time monitoring and control of FFmpeg streams.

## Database Schema

### New Table: `active_streams`

```sql
CREATE TABLE active_streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT UNIQUE NOT NULL,
    pid INTEGER NOT NULL,
    start_time TEXT NOT NULL,  -- ISO format timestamp
    duration INTEGER NOT NULL,
    stream_key TEXT,
    status TEXT DEFAULT 'running',  -- 'running', 'completed', 'cancelled', 'failed'
    error_message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
```

## Files Modified/Created

### 1. **New File: `app/database.py`**
- SQLAlchemy model for `active_streams` table
- Database initialization function `init_db()`
- CRUD functions:
  - `add_active_stream()` - Register new stream when it starts
  - `get_active_streams()` - Get running/pending streams for main display
  - `get_all_streams()` - Get complete stream history
  - `get_stream_by_name()` - Get specific stream details
  - `update_stream_status()` - Update stream status (completed/failed/cancelled)
  - `cleanup_stale_streams()` - Check PIDs and mark dead processes
  - `cancel_active_stream()` - Kill process by PID and update status

### 2. **Modified: `app/streaming.py`**
- Added import: `from .database import add_active_stream, update_stream_status`
- Modified `stream_game()` function:
  - Registers stream in database immediately after starting FFmpeg process
  - Stores PID for process management
  - Updates status to 'completed' or 'failed' based on return code
  - Handles exceptions and updates status accordingly

### 3. **Modified: `app/scheduler.py`**
- Added import: `from .database import cancel_active_stream, cleanup_stale_streams`
- New functions:
  - `start_cleanup_task()` - Schedules periodic cleanup every 5 minutes
  - `cancel_stream()` - Wrapper for canceling active streams

### 4. **Modified: `app/routes.py`**
- Added imports: `from .database import get_active_streams, get_all_streams`
- Modified `list_jobs_page()` to include active streams in context
- New route handlers:
  - `cancel_stream_route()` - POST endpoint to cancel active streams
  - `list_all_streams_page()` - GET endpoint for complete history

### 5. **Modified: `app/templates/list.html.j2`**
- Added "Live Streams" section showing active streams with:
  - Red badge indicating LIVE status
  - Start time and duration
  - Stop button to cancel stream
- Updated "Scheduled Streams" section header
- Added "View History" button linking to `/list_all`

### 6. **New File: `app/templates/list_all.html.j2`**
- Complete stream history page
- Color-coded status badges:
  - 🔴 Running (red)
  - ✅ Completed (green)
  - ⚠️ Failed (yellow)
  - ⛔ Cancelled (gray)
- Shows all stream details including PID and error messages
- Tooltips for errors and stream keys

### 7. **Modified: `app/main.py`**
- Added imports for database and scheduler functions
- New startup event handler:
  - Calls `init_db()` to create tables
  - Calls `start_cleanup_task()` to start periodic cleanup
- Registered new routes:
  - `GET /list_all` - Stream history page
  - `POST /cancel_stream` - Cancel active stream endpoint

## Features

### Real-time Stream Monitoring
- Live streams appear in red-highlighted section on main `/list` page
- Shows stream status, start time, duration, and stream key
- Automatic updates every 15 minutes (page auto-refresh)

### Process Management
- Click stop button to cancel any running stream
- Process is terminated with SIGTERM signal
- Status updated to 'cancelled' in database

### History Tracking
- All streams are permanently stored (never deleted)
- Complete history accessible via `/list_all` page
- View past streams with status, duration, and any error messages

### Automatic Cleanup
- Background task runs every 5 minutes
- Checks if stream processes are still alive
- Marks dead processes as 'failed' automatically

## Data Flow

1. **Stream Start:**
   - User schedules a stream (or scheduled job triggers)
   - `stream_game()` starts FFmpeg process
   - PID captured and stored in database with status 'running'

2. **During Stream:**
   - Stream appears in "Live Streams" section on `/list` page
   - User can cancel via stop button if needed
   - Cleanup task periodically verifies process is alive

3. **Stream End:**
   - FFmpeg process completes or fails
   - Status updated to 'completed' or 'failed' with error details
   - Stream removed from "Live Streams" section
   - Record remains in database for history

## Benefits

✅ **Persistence** - Survives application restarts  
✅ **Audit Trail** - Complete history of all streams  
✅ **Process Control** - Cancel streams from UI  
✅ **Automatic Cleanup** - Dead processes detected and marked  
✅ **Debugging** - Error messages stored for troubleshooting  
✅ **Architecture** - Uses existing SQLite database  

## Usage

### Main Page (`/list`)
- View scheduled streams (blue section)
- View active streams (red section)
- Cancel running streams with stop button
- Schedule new streams with "Schedule A Stream" button
- Access history with "View History" button

### History Page (`/list_all`)
- View all streams ever run
- Filter by status (running, completed, failed, cancelled)
- See error details on failed streams
- Return to main page with "Back to Live View" button

## Testing Recommendations

1. **Test Stream Tracking:**
   - Schedule a stream
   - Verify it appears in "Live Streams" when running
   - Check that PID is captured in database

2. **Test Cancellation:**
   - Start a stream
   - Click stop button
   - Verify process terminates
   - Check status updated to 'cancelled'

3. **Test History:**
   - Run several streams to completion
   - Visit `/list_all`
   - Verify all streams appear with correct status

4. **Test Cleanup:**
   - Manually kill an FFmpeg process
   - Wait 5 minutes
   - Verify cleanup task marks it as 'failed'

## Database Location

Same as APScheduler jobs: `jobs/jobs.sqlite`

This keeps all job and stream data in one database file.
