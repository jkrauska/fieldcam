"""Lightweight time-series metrics: sampler, retention, and query helpers.

Stores CPU temperature and YOLO detection counts in a single SQLite table
(`metric_samples`) sampled once per minute. Designed as a modern, embedded
replacement for an RRD at this scale (~1 row/minute, ~500k rows/year).
"""

import logging
import time

from sqlalchemy import delete, select

from .database import MetricSample, SessionLocal


def _read_cpu_temp_c() -> float | None:
    """Return CPU temperature in degrees Celsius, or None if unavailable."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _read_detection_counts() -> tuple[int | None, int | None, int | None]:
    """Read the last-known YOLO counts from the in-memory cache in routes.py.

    Returns (person_count, bird_count, total_count). Any value may be None if
    the cache hasn't been populated yet (e.g. immediately after startup).
    """
    # Local import to avoid a circular import (routes.py -> metrics is fine,
    # but routes imports plenty itself).
    try:
        from . import routes
    except Exception:
        return (None, None, None)

    cache = getattr(routes, "_detection_cache", None)
    if not isinstance(cache, dict):
        return (None, None, None)

    counts = cache.get("counts")
    if not isinstance(counts, dict):
        return (None, None, None)

    person = counts.get("person")
    bird = counts.get("bird")
    if person is None and bird is None:
        return (None, None, None)
    total = (person or 0) + (bird or 0)
    return (person, bird, total)


def sample_metrics() -> None:
    """Take one sample of CPU temp and detection counts and persist it."""
    cpu_temp = _read_cpu_temp_c()
    person, bird, total = _read_detection_counts()

    if cpu_temp is None and person is None and bird is None:
        logging.debug("sample_metrics: no metrics available, skipping insert")
        return

    session = SessionLocal()
    try:
        sample = MetricSample(
            ts=int(time.time()),
            cpu_temp_c=cpu_temp,
            person_count=person,
            bird_count=bird,
            total_count=total,
        )
        session.add(sample)
        session.commit()
    except Exception:
        session.rollback()
        logging.exception("sample_metrics: failed to insert sample")
    finally:
        session.close()


def prune_old_samples(days: int = 30) -> int:
    """Delete samples older than `days`. Returns number of rows removed."""
    cutoff = int(time.time()) - days * 86400
    session = SessionLocal()
    try:
        result = session.execute(delete(MetricSample).where(MetricSample.ts < cutoff))
        session.commit()
        removed = int(result.rowcount or 0)
        if removed:
            logging.info(f"prune_old_samples: removed {removed} samples older than {days} days")
        return removed
    except Exception:
        session.rollback()
        logging.exception("prune_old_samples: failed")
        return 0
    finally:
        session.close()


# Supported chart ranges -> seconds
RANGE_SECONDS: dict[str, int] = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}


def query_samples(range_key: str = "24h", max_points: int = 500) -> dict:
    """Query samples for a time range, bucket-averaging if needed.

    Returns:
        {
            "range": "24h",
            "ts":            [int, ...],         # unix epoch seconds (UTC)
            "cpu_temp_c":    [float|None, ...],
            "person":        [float|None, ...],
            "bird":          [float|None, ...],
            "total":         [float|None, ...],
        }
    """
    if range_key not in RANGE_SECONDS:
        range_key = "24h"
    span = RANGE_SECONDS[range_key]
    now = int(time.time())
    cutoff = now - span

    session = SessionLocal()
    try:
        rows = session.execute(
            select(
                MetricSample.ts,
                MetricSample.cpu_temp_c,
                MetricSample.person_count,
                MetricSample.bird_count,
                MetricSample.total_count,
            )
            .where(MetricSample.ts >= cutoff)
            .order_by(MetricSample.ts.asc())
        ).all()
    finally:
        session.close()

    ts_out: list[int] = []
    cpu_out: list[float | None] = []
    person_out: list[float | None] = []
    bird_out: list[float | None] = []
    total_out: list[float | None] = []

    if not rows:
        return {
            "range": range_key,
            "ts": ts_out,
            "cpu_temp_c": cpu_out,
            "person": person_out,
            "bird": bird_out,
            "total": total_out,
        }

    if len(rows) <= max_points:
        for ts, cpu, person, bird, total in rows:
            ts_out.append(ts)
            cpu_out.append(cpu)
            person_out.append(float(person) if person is not None else None)
            bird_out.append(float(bird) if bird is not None else None)
            total_out.append(float(total) if total is not None else None)
        return {
            "range": range_key,
            "ts": ts_out,
            "cpu_temp_c": cpu_out,
            "person": person_out,
            "bird": bird_out,
            "total": total_out,
        }

    # Downsample: bucket-average so the chart stays smooth and fast on long ranges.
    bucket = max(1, span // max_points)
    cur_bucket = rows[0][0] // bucket
    buf_cpu: list[float] = []
    buf_p: list[int] = []
    buf_b: list[int] = []
    buf_t: list[int] = []

    def flush(bucket_idx: int) -> None:
        ts_out.append(bucket_idx * bucket + bucket // 2)
        cpu_out.append(sum(buf_cpu) / len(buf_cpu) if buf_cpu else None)
        person_out.append(sum(buf_p) / len(buf_p) if buf_p else None)
        bird_out.append(sum(buf_b) / len(buf_b) if buf_b else None)
        total_out.append(sum(buf_t) / len(buf_t) if buf_t else None)

    for ts, cpu, person, bird, total in rows:
        b = ts // bucket
        if b != cur_bucket:
            flush(cur_bucket)
            buf_cpu.clear()
            buf_p.clear()
            buf_b.clear()
            buf_t.clear()
            cur_bucket = b
        if cpu is not None:
            buf_cpu.append(cpu)
        if person is not None:
            buf_p.append(person)
        if bird is not None:
            buf_b.append(bird)
        if total is not None:
            buf_t.append(total)

    flush(cur_bucket)

    return {
        "range": range_key,
        "ts": ts_out,
        "cpu_temp_c": cpu_out,
        "person": person_out,
        "bird": bird_out,
        "total": total_out,
    }
