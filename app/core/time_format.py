"""Shared MM:SS time formatting used across graphs, timeline, tables and map."""
from __future__ import annotations

from datetime import datetime, timezone


def format_mmss(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def format_gps_time(epoch_seconds: float) -> str:
    """Wall-clock time of day (UTC) for an absolute log timestamp."""
    try:
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "--:--:--"
