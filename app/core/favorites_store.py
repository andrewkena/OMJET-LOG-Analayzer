"""Persists the user's starred (favorite) log fields across app restarts."""
from __future__ import annotations

import json

from app.core.tile_cache import get_app_dir

_FAVORITES_FILENAME = "favorites.json"
_RENAMES_FILENAME = "renames.json"


def _get_path():
    return get_app_dir() / _FAVORITES_FILENAME


def _get_renames_path():
    return get_app_dir() / _RENAMES_FILENAME


def load_favorites() -> set[tuple[str, str]]:
    path = _get_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {(msg_type, fname) for msg_type, fname in data}
    except (OSError, ValueError, TypeError):
        return set()


def save_favorites(favorites: set[tuple[str, str]]):
    path = _get_path()
    try:
        path.write_text(json.dumps(sorted(favorites)), encoding="utf-8")
    except OSError:
        pass


def load_renames() -> dict[tuple[str, str], str]:
    path = _get_renames_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {(msg_type, fname): new_name for msg_type, fname, new_name in data}
    except (OSError, ValueError, TypeError):
        return {}


def save_renames(renames: dict[tuple[str, str], str]):
    path = _get_renames_path()
    try:
        rows = sorted((msg_type, fname, new_name) for (msg_type, fname), new_name in renames.items())
        path.write_text(json.dumps(rows), encoding="utf-8")
    except OSError:
        pass
