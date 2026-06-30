"""Custom 'tilecache://' URL scheme: serves Google basemap tiles from a local
disk cache (app/core/tile_cache.py), fetching from Google only on first
request and saving the result, so tiles stay available offline afterwards.
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler

from app.core.tile_cache import get_cache_dir

SCHEME = b"tilecache"
_VALID_LAYERS = ("s", "y", "m", "p")
_SUBDOMAINS = ("mt0", "mt1", "mt2", "mt3")


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)

    def requestStarted(self, job: QWebEngineUrlRequestJob):
        url: QUrl = job.requestUrl()
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

        tile_path = get_cache_dir() / lyrs / z / x / f"{y}.png"
        if tile_path.exists():
            data = tile_path.read_bytes()
            self._reply_with_bytes(job, data)
            return

        tile_path.parent.mkdir(parents=True, exist_ok=True)
        subdomain = _SUBDOMAINS[(xi + yi) % len(_SUBDOMAINS)]
        remote_url = QUrl(
            f"https://{subdomain}.google.com/vt/lyrs={lyrs}&x={xi}&y={yi}&z={zi}"
        )
        reply = self._manager.get(QNetworkRequest(remote_url))

        def on_finished():
            if reply.error() != QNetworkReply.NetworkError.NoError:
                job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
                return
            data = bytes(reply.readAll())
            try:
                tile_path.write_bytes(data)
            except OSError:
                pass
            self._reply_with_bytes(job, data)

        reply.finished.connect(on_finished)
        job.destroyed.connect(reply.abort)

    @staticmethod
    def _reply_with_bytes(job: QWebEngineUrlRequestJob, data: bytes):
        buf = QBuffer(job)
        buf.setData(QByteArray(data))
        buf.open(QBuffer.OpenModeFlag.ReadOnly)
        job.reply(b"image/png", buf)
