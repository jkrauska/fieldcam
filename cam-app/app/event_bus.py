"""Thread-safe event notification for SSE subscribers.

Uses a simple version counter that's safe to increment from any thread
(CPython GIL guarantees atomic int increment). SSE generators poll the
counter and re-render when it changes.
"""

import threading

# --- List change notifications ---

_list_version = 0


def notify_list_changed():
    """Bump the version so SSE generators know to push an update."""
    global _list_version
    _list_version += 1


def get_list_version() -> int:
    return _list_version


# --- Real-time stream stats ---

_stream_stats: dict[str, dict] = {}
_stream_stats_lock = threading.Lock()
_stats_version = 0


def update_stream_stats(name: str, stats: dict):
    """Store the latest ffmpeg progress stats for a stream."""
    global _stats_version
    with _stream_stats_lock:
        _stream_stats[name] = stats
        _stats_version += 1


def get_stream_stats() -> dict[str, dict]:
    """Return a snapshot of stats for all active streams."""
    with _stream_stats_lock:
        return dict(_stream_stats)


def get_stats_version() -> int:
    return _stats_version


def clear_stream_stats(name: str):
    """Remove stats for a stream that has ended."""
    global _stats_version
    with _stream_stats_lock:
        _stream_stats.pop(name, None)
        _stats_version += 1
