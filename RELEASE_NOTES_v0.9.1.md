# Mindinguflac v0.9.1

Patch release for the v0.9 line. This keeps the v0.9.0 fallback/racing work and adds fixes for collaborative Spotify metadata, torrent finalization, and cache maintenance.

## v0.9.1 changes

### Metadata and Matching

- Fixed Spotify track payloads that could keep a stale artist from the previous playback context.
- Added Spotify ID canonicalization before download matching, so collaborative tracks use the actual artist list from Spotify metadata.
- Added a Spotify embed fallback for track metadata when the normal Spotify client does not return a full track object.
- Verified the Rod Stewart / Amy Belle track case now enriches from a poisoned `Michael Jackson` payload to `Rod Stewart, Amy Belle` before torrent and AI candidate scoring.

### Torrent Engine

- Fixed a torrent finalization edge case where libtorrent could underreport `file_progress()` even after the target audio file was fully materialized on disk.
- Keeps sparse-file protection by requiring a valid audio header before accepting an underreported completed file.

### Cache Maintenance

- Added a new cache cleanup option: `On every close or restart`.
- Desktop shutdown now applies the close/restart cache cleanup mode before the local server exits.

### Playback and macOS Audio

- Keeps the macOS auto-unmute helper from v0.9.0 work so muted selected output devices are unmuted before native playback starts.

## v0.9.0 baseline

Highlight: smarter fallbacks and safer downloads. Mindinguflac gained a stronger fallback path when direct providers or torrent candidates are not the best answer. The YTP-DL engine searches YouTube, scores multiple candidates, avoids weak matches, and refuses DRM-marked formats instead of blindly downloading the first result.

### YouTube / YTP-DL

- Added a dedicated YTP-DL download engine for best-available public YouTube audio.
- Searches the top YouTube candidates instead of accepting the first result.
- Uses fuzzy artist/title scoring, token coverage, uploader/source trust, and duration checks.
- Penalizes covers, karaoke, remixes, compilations, background music, gaming/sound-fx uploads, loops, playlists, and other noisy matches.
- Rejects weak title-only archive uploads rather than downloading likely wrong files.
- Explicitly avoids DRM-marked candidates and asks yt-dlp for non-DRM playable formats only.
- Keeps native best audio by default, with optional M4A/AAC and MP3 modes.

### Torrent Engine

- Improved torrent metadata reuse guards.
- Tightened torrent file matching to reduce false positives from similar titles, parent folders, album names, and generic short titles.
- Improved sparse-piece progress handling, stalled-source detection, live peer scoring, and swarm-health selection.
- Added a Duck.ai advisor that runs in parallel with the existing fuzzy torrent logic. The advisor reranks clean candidates, while the local fuzzy matcher still probes and rejects bad files, so AI guidance improves ordering without replacing deterministic safety checks.

### Playback and Native Audio

- Fixed native output resume and device switching behavior.
- Improved stream handoff handling so pausing does not restart the same track or cancel prefetch.
- Added playback fixes around active downloads and finalized cache files.
- Added best-effort macOS output auto-unmute before native playback starts.

### Assets

- `Mindinguflac-macos-arm64.zip` - macOS Apple Silicon desktop build.
- `Mindinguflac-windows.zip` - Windows x64 desktop build.
