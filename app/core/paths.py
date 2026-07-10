"""Writable user-data directory, safe to use from any component.

When running as a PyInstaller frozen exe, writable files must NOT go next to
the executable (inside Program Files) because standard users have no write
permission there.  All mutable app data (settings, cache, crash log, favorites)
is stored under %APPDATA%\\OMJET LOG Analyzer on Windows and
~/.config/OMJET LOG Analyzer elsewhere.

In development mode (not frozen) the project root is used, preserving the
original behaviour.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_NAME = "OMJET LOG Analyzer"


def get_user_data_dir() -> Path:
    """Return a writable directory for user-specific app data.

    Frozen (installed): %APPDATA%\\OMJET LOG Analyzer  (Windows)
                        ~/.config/OMJET LOG Analyzer   (other)
    Development:        project root (next to main.py)
    """
    if getattr(sys, "frozen", False):
        if "APPDATA" in os.environ:
            base = Path(os.environ["APPDATA"])
        else:
            base = Path.home() / ".config"
        d = base / _APP_NAME
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(__file__).resolve().parent.parent.parent
