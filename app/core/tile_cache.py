"""On-disk cache for map basemap tiles, stored next to the app so the
satellite/map imagery stays available without an internet connection
after it has been viewed once."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Callable

DEFAULT_MAX_CACHE_BYTES = 1024 * 1024 * 1024
MIN_MAX_CACHE_BYTES = 250 * 1024 * 1024
MAX_MAX_CACHE_BYTES = 5 * 1024 * 1024 * 1024

_max_cache_bytes = DEFAULT_MAX_CACHE_BYTES
_cache_cleared_callbacks: list[Callable[[], None]] = []


def get_max_cache_size_bytes() -> int:
    return _max_cache_bytes


def set_max_cache_size_bytes(value: int) -> None:
    global _max_cache_bytes
    _max_cache_bytes = value


def is_cache_over_limit() -> bool:
    return get_cache_size_bytes() > _max_cache_bytes


def register_cache_cleared_callback(callback: Callable[[], None]) -> None:
    """Register a callback invoked whenever clear_cache() runs, so other
    components tracking cache size (e.g. the tile scheme handler) can
    reset their own counters instead of re-walking the disk."""
    _cache_cleared_callbacks.append(callback)


def get_app_dir() -> Path:
    """Install directory (read-only assets).  Kept for backward compatibility."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


# Computed once at import time on the main thread — requestStarted runs on Qt IO thread
# where calling Path.resolve() / ntpath.realpath causes heap corruption on Windows.
from app.core.paths import get_user_data_dir as _get_user_data_dir  # noqa: E402
_CACHE_DIR: Path = _get_user_data_dir() / "map_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cache_dir() -> Path:
    return _CACHE_DIR


def get_cache_size_bytes() -> int:
    cache_dir = get_cache_dir()
    return sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024.0 or unit == "ГБ":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ГБ"


def clear_cache() -> None:
    cache_dir = get_cache_dir()
    for item in cache_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
    for callback in _cache_cleared_callbacks:
        callback()
