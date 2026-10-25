"""Portable playlist snapshots with revisions and deletion tombstones."""
from __future__ import annotations
import hashlib
import json
import re
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


def _track_id(track: dict) -> str:
    return str(track.get("spotify_id") or track.get("isrc") or track.get("track_key")
               or f"{str(track.get('artist', '')).casefold()}||{str(track.get('title', '')).casefold()}")


def _source_id(playlist: dict) -> str:
    """The Spotify playlist/album a playlist was imported from, if any. Two
    devices importing the same one get different local ids; this finds them."""
    match = re.search(r"open\.spotify\.com/(playlist|album)/([A-Za-z0-9]+)", str(playlist.get("spotify_url") or ""))
    return f"spotify:{match.group(1)}:{match.group(2)}" if match else ""


# Per-song clocks: clock[track_id] = [last_added, last_removed]. A song is in a
# playlist when its last add is newer than its last removal. Clocks from two
# devices merge by taking the latest of each, so additions and removals made
# on either device survive in any sync order, and absence never means removal.

def _apply_track_edits(clock: dict, old_tracks: list, new_tracks: list, now: float) -> dict:
    clock = {key: list(value) for key, value in (clock or {}).items()}
    old_ids = {_track_id(track) for track in old_tracks}
    new_ids = {_track_id(track) for track in new_tracks}
    for track_id in new_ids - old_ids:
        added, removed = clock.get(track_id, [0.0, 0.0])
        clock[track_id] = [max(now, removed + .000001), removed]
    for track_id in old_ids - new_ids:
        added, removed = clock.get(track_id, [0.0, 0.0])
        clock[track_id] = [added, max(now, added + .000001)]
    for track_id in new_ids & old_ids:
        clock.setdefault(track_id, [0.0, 0.0])
    return clock


def _merge_clocks(first: dict, second: dict) -> dict:
    merged = {}
    for track_id in set(first or {}) | set(second or {}):
        a = (first or {}).get(track_id, [0.0, 0.0])
        b = (second or {}).get(track_id, [0.0, 0.0])
        merged[track_id] = [max(float(a[0]), float(b[0])), max(float(a[1]), float(b[1]))]
    return merged


def _clock_for(playlist: dict, clock: dict) -> dict:
    """Clock covering every listed song (legacy rows have none: they count as
    added at time 0, so any recorded removal still wins over them)."""
    result = {key: list(value) for key, value in (clock or {}).items()}
    for track in playlist.get("tracks") or []:
        result.setdefault(_track_id(track), [0.0, 0.0])
    return result


def record_changes(path: Path, before: list, after: list):
    """Called under the app's playlist lock for each local edit."""
    with _LOCK:
        state = _load(_state_path(path), {})
        old = {str(row["id"]): _portable(row) for row in before}
        new = {str(row["id"]): _portable(row) for row in after}
        now = time.time()
        for key in old.keys() | new.keys():
            if old.get(key) == new.get(key):
                continue
            previous = state.get(key, {})
            clock = _apply_track_edits(previous.get("clock") or {},
                                       (old.get(key) or {}).get("tracks") or [],
                                       (new.get(key) or {}).get("tracks") or [], now)
            state[key] = {
                "revision": max(now, float(previous.get("revision") or 0) + .000001),
                "deleted": key not in new,
                "digest": _digest(new[key]) if key in new else "",
                "clock": clock,
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
            result.append({"id": key, "revision": float(meta.get("revision") or 0), "deleted": False,
                           "playlist": row, "clock": _clock_for(row, meta.get("clock") or {})})
        result.extend({"id": key, "revision": float(meta.get("revision") or 0), "deleted": True}
                      for key, meta in state.items() if meta.get("deleted"))
        return result


def _remote_wins(remote: dict, remote_revision: float, local: dict | None, local_revision: float) -> bool:
    """Newer edit decides name, artwork and order; on a tie both devices must
    pick the same copy, so break it by content digest."""
    if local is None or remote_revision != local_revision:
        return remote_revision > local_revision or local is None
    return _digest(remote) > _digest(local)


def _combine(local: dict | None, remote: dict, clock: dict, remote_first: bool) -> dict:
    """The playlist with every song whose last add beats its last removal,
    in the winning copy's order, then the other copy's songs."""
    copies = [remote] if local is None else ([remote, local] if remote_first else [local, remote])
    merged = dict(copies[0])
    if local is not None:
        merged["id"] = local["id"]
    tracks, seen = [], set()
    for copy in copies:
        for track in copy.get("tracks") or []:
            track_id = _track_id(track)
            added, removed = clock.get(track_id, [0.0, 0.0])
            if track_id in seen or removed > added:
                continue
            seen.add(track_id)
            tracks.append(track)
    merged["tracks"] = tracks
    return merged


def merge(path: Path, incoming: list) -> int:
    """Merge a paired device's playlists into the local store.

    Unmentioned local playlists are kept (absence never means deletion) and
    whole-playlist deletions travel as tombstones. Inside a playlist, songs
    added or removed on either device are combined through per-song clocks.
    The same Spotify playlist imported on both devices under different ids is
    collapsed to one: both keep the smaller id, so they converge.
    """
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
            meta = state.get(key, {})
            old_revision = float(meta.get("revision") or 0)
            if record.get("deleted"):
                if revision <= old_revision:
                    continue  # stale tombstone, or this device edited it later
                changed += key in rows
                rows.pop(key, None)
                state[key] = {"revision": revision, "deleted": True, "digest": "", "clock": {}}
                continue
            playlist = record.get("playlist")
            if not isinstance(playlist, dict) or str(playlist.get("id")) != key or not isinstance(playlist.get("tracks"), list):
                continue
            if meta.get("deleted") and revision <= old_revision:
                continue  # deleted here after the other device's last edit
            playlist = _portable(playlist)
            remote_clock = _clock_for(playlist, record.get("clock") or {})

            # Same Spotify source under another local id: one copy, smallest id.
            source = _source_id(playlist)
            twin = None
            if key not in rows and source:
                twin = next((other for other, row in rows.items() if other != key and _source_id(row) == source), None)
            if twin is not None:
                keep, drop = sorted((key, twin))
                twin_meta = state.pop(twin, {})
                local = _portable(rows.pop(twin))
                local["id"] = playlist["id"] = keep
                twin_revision = float(twin_meta.get("revision") or 0)
                clock = _merge_clocks(_clock_for(local, twin_meta.get("clock") or {}), remote_clock)
                merged = _combine(local, playlist, clock, _remote_wins(playlist, revision, local, twin_revision))
                rows[keep] = merged
                newest = max(revision, twin_revision, time.time())
                state[keep] = {"revision": newest, "deleted": False, "digest": _digest(merged), "clock": clock}
                state[drop] = {"revision": newest, "deleted": True, "digest": "", "clock": {}}
                changed += 1
                continue

            local = _portable(rows[key]) if key in rows else None
            local_clock = _clock_for(local, meta.get("clock") or {}) if local else {}
            clock = _merge_clocks(local_clock, remote_clock)
            merged = _combine(local, playlist, clock, _remote_wins(playlist, revision, local, old_revision))
            state[key] = {"revision": max(revision, old_revision), "deleted": False,
                          "digest": _digest(merged), "clock": clock}
            if local is None or _digest(merged) != _digest(local):
                rows[key] = merged
                changed += 1
        if changed:
            # Retain the pre-sync file for recovery; write both files atomically.
            backup = path.parent / "device_sync" / "playlists.before-first-sync.json"
            if not backup.exists():
                _write(backup, original)
            _write(path, list(rows.values()))
        _write(_state_path(path), state)
        return changed
