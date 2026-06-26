"""Shared MM:SS time formatting used across graphs, timeline, tables and map."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def format_mmss(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


_utc_offset_hours = 0.0


def set_utc_offset_hours(offset_hours: float) -> None:
    """Set the UTC offset (in hours) applied by format_gps_time, e.g. +3 for Moscow."""
    global _utc_offset_hours
    _utc_offset_hours = offset_hours


def get_utc_offset_hours() -> float:
    return _utc_offset_hours


def format_gps_time(epoch_seconds: float) -> str:
    """Wall-clock time of day for an absolute log timestamp, shifted by the configured UTC offset."""
    try:
        tz = timezone(timedelta(hours=_utc_offset_hours))
        return datetime.fromtimestamp(epoch_seconds, tz=tz).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "--:--:--"
