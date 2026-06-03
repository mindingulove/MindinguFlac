# Changelog

## Mindinguflac v0.8.0

### Highlight: smarter fallbacks and safer downloads

Mindinguflac now has a much stronger fallback path when direct providers or torrent candidates are not the best answer. The new YTP-DL engine searches YouTube, scores multiple candidates, avoids weak matches, and refuses DRM-marked formats instead of blindly downloading the first result.

### YouTube / YTP-DL

- Added a dedicated `YTP-DL` download engine for best-available public YouTube audio.
- Searches the top YouTube candidates instead of accepting the first result.
- Uses fuzzy artist/title scoring, token coverage, uploader/source trust, and duration checks to pick a better match.
- Penalizes covers, karaoke, remixes, compilations, background music, gaming/sound-fx uploads, long loops, playlists, and other noisy matches.
- Rejects weak title-only archive uploads rather than downloading a likely wrong file.
- Explicitly avoids DRM-marked candidates and asks yt-dlp for non-DRM playable formats only.
- Keeps native best audio by default, with optional M4A/AAC and MP3 conversion modes.

### Torrent engine

- Improved torrent metadata reuse guards so stale or mismatched metadata is not reused for the wrong candidate.
- Tightened torrent file matching to reduce false positives from similarly named tracks, parent folders, album names, and generic short titles.
- Added stronger handling for sparse piece progress and stalled torrents, including more aggressive stalled-source detection.
- Improves source selection with live peer counts and better swarm-health scoring.

### Playback and native audio

- Fixed native output resume and device switching behavior.
- Improved stream handoff handling so pausing does not accidentally restart the same track or cancel prefetch.
- Added playback fixes around active downloads and finalized cache files.

### Assets

- `Mindinguflac-macos-arm64.zip` — macOS Apple Silicon desktop build.
- `Mindinguflac-windows.zip` — Windows x64 desktop build.

## Mindinguflac v0.7.0

### Downloads and Bypass Polish

- Added a configurable **Download retries** setting.
- Setting download retries to `0` now skips the direct attempt and routes download attempts through Tor immediately.
- The downloader iterates through providers and falls back through Tor when a provider is rate-limited or the direct attempt fails.
- Improved progress estimates, including a `6.5 MB/min` estimate for identified FLAC/lossless downloads, so the progress ring more closely reflects downloaded bytes.
- Added a separate `YTP-DL` engine for YouTube music fetches, alongside the existing SpotiFLAC, Other Providers, and Torrent engines.

### UI and UX Improvements

- The macOS app icon now uses the full transparent MINDINGUFLAC logo image without a forced square background.
- Simplified the player preparation state to display `Loading...` while a stream is being prepared.
- Track list library buttons now use an outlined download arrow until a track is saved locally, then show the filled download arrow.
- Artist pages now load the full Spotify discography instead of a small album search sample.
- Added `See all` and `See less` controls to artist-page popular track and album sections.
- Artist cards now preserve the resolved Spotify artist ID, so popular tracks and full discographies continue loading from cached discovery lists.
- Album hero pages now retain release years and load the artist portrait badge from Spotify profile imagery.
- Artist popular-track rows now resolve missing artwork and repair malformed SpotiFLAC image URLs in expanded lists.

### Playback and Queue Polish

- Fixed a bug where clicking pause while using native audio (external devices) on macOS could cause the song to restart due to premature 'ended' state detection.
- Improved native audio resume logic on macOS to preserve playback position when resuming from a stopped state.
- Manual pause now stays paused during active-download and finished-cache handoffs; the player no longer reloads the same track or cancels prefetch when pausing.
- Shuffle immediately rebuilds the active queue and refreshes the prefetched next track.
- Shuffle and repeat controls now toggle their active state immediately and highlight when enabled.
- Selecting a new track cancels active or prefetched background jobs before starting the selected track.
- Playback now ignores stale cache job records whose audio file has been deleted, and falls back to a valid library file or a new stream download.
- Tracks that already contain a Spotify ID now resolve directly to their Spotify URL for streaming and downloading.

### System

- Updated the desktop integration for SpotiFLAC `0.6.1` and enabled `Artist/Album` subfolder organization for downloads.
- Restored AppKit loading in the macOS PyInstaller bundle to prevent the PyObjC startup failure.
