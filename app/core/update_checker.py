"""Background GitHub release checker.

Fetches the latest release tag from GitHub API in a worker thread and
emits update_available(tag, url) if the remote version is newer than
the running APP_VERSION.  All network errors are silently swallowed so
a missing connection never breaks startup.
"""
from __future__ import annotations

import re
import urllib.request
import json

from PySide6.QtCore import QThread, Signal

from app.core.version import APP_VERSION

_REPO = "andrewkena/OMJET-LOG-Analayzer"
_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_RELEASES_URL = f"https://github.com/{_REPO}/releases"


def _parse_version(v: str) -> tuple[int, int, int, int, int]:
    """Return (major, minor, day, month, year) for comparison.

    Accepts tags like "v0.73_13.07.2026" or "0.73_13.07.2026".
    Falls back to (0,0,0,0,0) on parse failure.
    """
    v = v.lstrip("v")
    m = re.match(r"(\d+)\.(\d+)(?:_(\d{2})\.(\d{2})\.(\d{4}))?", v)
    if not m:
        return (0, 0, 0, 0, 0)
    major, minor = int(m.group(1)), int(m.group(2))
    if m.group(3):
        day, month, year = int(m.group(3)), int(m.group(4)), int(m.group(5))
    else:
        day = month = year = 0
    return (major, minor, year, month, day)


class UpdateChecker(QThread):
    update_available = Signal(str, str)   # (remote_tag, releases_url)
    check_done = Signal()                 # emitted even when no update found

    def run(self):
        try:
            req = urllib.request.Request(
                _API_URL,
                headers={"User-Agent": "OMJET-Log-Analyzer-UpdateChecker"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            tag: str = data.get("tag_name", "")
            html_url: str = data.get("html_url", _RELEASES_URL)
            if tag and _parse_version(tag) > _parse_version(APP_VERSION):
                self.update_available.emit(tag.lstrip("v"), html_url)
        except Exception:
            pass
        finally:
            self.check_done.emit()
