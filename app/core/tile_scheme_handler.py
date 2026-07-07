"""Custom 'tilecache://' URL scheme: serves Google basemap tiles from a local
disk cache (app/core/tile_cache.py), fetching from Google only on first
request and saving the result, so tiles stay available offline afterwards.
"""
from __future__ import annotations

import threading
import urllib.request

from PySide6.QtCore import QBuffer, QByteArray, Signal
from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler

from app.core.tile_cache import (get_cache_dir, get_cache_size_bytes,
                                  get_max_cache_size_bytes,
                                  register_cache_cleared_callback)

SCHEME = b"tilecache"
_VALID_LAYERS = ("s", "y", "m", "p")
_SUBDOMAINS = ("mt0", "mt1", "mt2", "mt3")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124"
)


def register_tile_scheme():
    """Must be called before QApplication is constructed."""
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
    )
    QWebEngineUrlScheme.registerScheme(scheme)


class TileCacheSchemeHandler(QWebEngineUrlSchemeHandler):
    """Handles tilecache://tile/<lyrs>/<z>/<x>/<y> requests."""

    cache_limit_exceeded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_bytes = get_cache_size_bytes()
        self._limit_warning_shown = self._cached_bytes > get_max_cache_size_bytes()
        register_cache_cleared_callback(self._on_cache_cleared)

    def requestStarted(self, job: QWebEngineUrlRequestJob):
        # Called on Qt WebEngine IO thread. ANY pathlib / os call here causes
        # STATUS_HEAP_CORRUPTION (0xc0000374) on Windows. Dispatch all I/O to
        # a plain Python thread which is safe.
        url = job.requestUrl()
        parts = [p for p in url.path().split("/") if p]
        if len(parts) != 4:
            job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
            return
        lyrs, z, x, y = parts
        if lyrs not in _VALID_LAYERS:
            job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
            return
        try:
            zi, xi, yi = int(z), int(x), int(y)
        except ValueError:
            job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
            return

        threading.Thread(
            target=self._serve_tile,
            args=(job, lyrs, z, x, y, zi, xi, yi),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------ #
    # Everything below runs on a plain Python thread — safe on Windows.   #
    # ------------------------------------------------------------------ #

    def _serve_tile(self, job, lyrs, z, x, y, zi, xi, yi):
        tile_path = get_cache_dir() / lyrs / z / x / f"{y}.png"
        if tile_path.exists():
            try:
                data = tile_path.read_bytes()
            except OSError:
                job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
                return
            self._reply_with_bytes(job, data)
            return

        # Not cached — fetch from Google
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        subdomain = _SUBDOMAINS[(xi + yi) % len(_SUBDOMAINS)]
        remote = f"https://{subdomain}.google.com/vt/lyrs={lyrs}&x={xi}&y={yi}&z={zi}"
        try:
            req = urllib.request.Request(remote, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
        except Exception:
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return

        try:
            tile_path.write_bytes(data)
            self._cached_bytes += len(data)
            self._check_cache_limit()
        except OSError:
            pass

        self._reply_with_bytes(job, data)

    def _check_cache_limit(self):
        if self._limit_warning_shown:
            return
        if self._cached_bytes > get_max_cache_size_bytes():
            self._limit_warning_shown = True
            self.cache_limit_exceeded.emit()

    def _on_cache_cleared(self):
        self._cached_bytes = 0
        self._limit_warning_shown = False

    def recheck_cache_limit(self):
        if self._cached_bytes <= get_max_cache_size_bytes():
            self._limit_warning_shown = False
        else:
            self._check_cache_limit()

    @staticmethod
    def _reply_with_bytes(job: QWebEngineUrlRequestJob, data: bytes):
        buf = QBuffer(job)
        buf.setData(QByteArray(data))
        buf.open(QBuffer.OpenModeFlag.ReadOnly)
        job.reply(b"image/png", buf)
