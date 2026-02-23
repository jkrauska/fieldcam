"""Thread-safe event notification for SSE subscribers.

Uses a simple version counter that's safe to increment from any thread
(CPython GIL guarantees atomic int increment). SSE generators poll the
counter and re-render when it changes.
"""

_list_version = 0


def notify_list_changed():
    """Bump the version so SSE generators know to push an update."""
    global _list_version
    _list_version += 1


def get_list_version() -> int:
    return _list_version
