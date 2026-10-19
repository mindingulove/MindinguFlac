"""Portable playlist snapshots with revisions and deletion tombstones."""
from __future__ import annotations
import hashlib
import json
import threading
import time
from pathlib import Path

_LOCK = threading.RLock()
_LOCAL_KEYS = {"library_path", "output_dir", "cache_path", "active_audio_path", "local_path", "file_path", "path"}


def _portable(value):
    if isinstance(value, dict):
        return {key: _portable(item) for key, item in value.items() if key not in _LOCAL_KEYS}
    if isinstance(value, list):
        return [_portable(item) for item in value]
    return value


def _load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text("utf-8"))


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), "utf-8")
    temp.replace(path)


def _state_path(path):
    return path.parent / "device_sync" / "playlists.json"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_changes(path: Path, before: list, after: list):
    """Called under the app's playlist lock for each local edit."""
    with _LOCK:
        state = _load(_state_path(path), {})
        old = {str(row["id"]): _portable(row) for row in before}
        new = {str(row["id"]): _portable(row) for row in after}
        for key in old.keys() | new.keys():
            if old.get(key) == new.get(key):
                continue
            previous = state.get(key, {})
            state[key] = {
                "revision": max(time.time(), float(previous.get("revision") or 0) + .000001),
                "deleted": key not in new,
                "digest": _digest(new[key]) if key in new else "",
            }
        _write(_state_path(path), state)


def export(path: Path) -> list[dict]:
    with _LOCK:
        rows = _load(path, [])
        if not isinstance(rows, list):
            raise ValueError("Playlist store is not a list")
        state = _load(_state_path(path), {})
        result = []
        for row in rows:
            row = _portable(row)
            key = str(row["id"])
            meta = state.get(key, {})
            result.append({"id": key, "revision": float(meta.get("revision") or 0), "deleted": False, "playlist": row})
        result.extend({"id": key, "revision": float(meta.get("revision") or 0), "deleted": True}
                      for key, meta in state.items() if meta.get("deleted"))
        return result


def merge(path: Path, incoming: list) -> int:
    """Keep unmentioned local playlists; absence never means remote deletion."""
    if not isinstance(incoming, list):
        raise ValueError("Invalid playlist snapshot")
    with _LOCK:
        original = _load(path, [])
        if not isinstance(original, list):
            raise ValueError("Playlist store is not a list")
        rows = {str(row["id"]): row for row in original}
        state = _load(_state_path(path), {})
        changed = 0
        for record in incoming:
            if not isinstance(record, dict):
                continue
            key = str(record.get("id") or "")
            if not key or len(key) > 512:
                continue
            revision = float(record.get("revision") or 0)
            old_revision = float(state.get(key, {}).get("revision") or 0)
            deleted = bool(record.get("deleted"))
            if revision < old_revision:
                continue
            if deleted:
                if revision <= old_revision:
                    continue
                rows.pop(key, None)
                state[key] = {"revision": revision, "deleted": True, "digest": ""}
                changed += 1
                continue
            playlist = record.get("playlist")
            if not isinstance(playlist, dict) or str(playlist.get("id")) != key or not isinstance(playlist.get("tracks"), list):
                continue
            playlist = _portable(playlist)
            local = _portable(rows[key]) if key in rows else None
            if state.get(key, {}).get("deleted") and revision <= old_revision:
                continue
            if local is not None and revision == old_revision:
                if _digest(local) == _digest(playlist):
                    continue
                # Legacy copies have no revision. Preserve the union on first
                # contact so initial sync cannot silently drop either track list.
                if revision == 0:
                    merged = dict(max((local, playlist), key=_digest))
                    tracks = {}
                    ordered_copies = sorted((local, playlist), key=_digest, reverse=True)
                    for track in ordered_copies[0]["tracks"] + ordered_copies[1]["tracks"]:
                        identity = str(track.get("track_key") or track.get("spotify_id") or f"{track.get('artist', '').casefold()}||{track.get('title', '').casefold()}")
                        previous = tracks.get(identity)
                        tracks[identity] = max((previous, track), key=_digest) if previous else track
                    merged["tracks"] = list(tracks.values())
                    playlist = merged
                elif _digest(local) > _digest(playlist):
                    continue
            if local == playlist:
                # Still accept its revision to prevent older edits overwriting it.
                state[key] = {"revision": revision, "deleted": False, "digest": _digest(playlist)}
                continue
            rows[key] = playlist
            state[key] = {"revision": revision, "deleted": False, "digest": _digest(playlist)}
            changed += 1
        if changed:
            # Retain the pre-sync file for recovery; write both files atomically.
            backup = path.parent / "device_sync" / "playlists.before-first-sync.json"
            if not backup.exists():
                _write(backup, original)
            _write(path, list(rows.values()))
        _write(_state_path(path), state)
        return changed
