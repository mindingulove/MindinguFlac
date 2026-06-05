# Changelog

## Mindinguflac v0.9.2

### Highlight: Automatic Playwright browser setup and real-time quality badges

This release automates the Chromium browser installation for the Duck.ai advisor and introduces real-time HI-RES/HQ badges in the player sidebar.

### Duck.ai Advisor
- **Automatic Browser Setup**: The app now automatically detects missing Chromium binaries and installs them via Playwright on the first run, removing the need for manual setup.

### UI and UX Improvements
- **Visual Quality Indicators**: Real-time **HI-RES** and **HQ** badges in the player sidebar now indicate the actual audio fidelity being streamed, based on the resolved audio source and metadata.
- **Enhanced Detection**: Improved quality detection to support a wider range of file extensions (including YouTube's `.webm` and `.opus`) and metadata keywords (`SQ`, `320`, `LOSSLESS`, etc.).

## Mindinguflac v0.9.1

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

## Mindinguflac v0.9.0

### Highlight: app-only output fixes and stronger AI-assisted torrent selection

Mindinguflac now handles selected output devices more reliably on macOS, improves how torrent candidates are ranked and raced, and replaces the fragile Duck.ai direct-request bypass with a persistent browser worker that lets Duck.ai's own frontend handle its challenge flow.

### Torrent engine

- Passes magnet metadata into the AI reranker so candidate display names and trackers can be considered.
- Added local SQLite-backed adult/video vocabulary filtering for torrent results and internal torrent file paths.
- Added torrent source racing where clean matched candidates compete and the first real byte progress wins.
- Improved torrent racing so candidates are sorted by measured live peer count and the fastest source by real byte progress wins, instead of whichever candidate happens to appear first.
- Added an optional parallel AI advisor for clean torrent candidate reranking. The advisor is non-blocking and cannot override adult/video filters, metadata checks, or libtorrent byte-progress validation.
- Replaced the brittle Duck.ai direct-request bypass with a long-running Playwright browser worker that uses Duck.ai's real frontend for AI advisor requests.
- Fixed the AI advisor opt-in gate: installing Duck.ai packages no longer auto-enables Duck requests unless `MINDINGUFLAC_AI_RERANK_PROVIDER` is explicitly configured.
- Fixed cross-job file deletion: when a same-album prefetch and the active track share one magnet/handle, cleaning up one job no longer deletes the shared `_race` files out from under the other's live download (was surfacing as false "no byte progress" / "stalled during streaming").
- Throttled concurrent prefetch torrent jobs (`MINDINGUFLAC_PREFETCH_TORRENT_SLOTS`, default 2) so 5-track parallel prefetch can no longer flood the shared libtorrent session and starve the actively-playing track's metadata probe (was surfacing as every source going "unresponsive during metadata probe"). Active playback jobs are never gated.
- Fixed the metadata probe dropping the whole swarm: it set every file's priority to 0 while scoring, which makes libtorrent disconnect all peers (rate-based choker + inactivity timeout), so the race then started at 0 peers and a live FLAC never downloaded ("Race has no byte progress yet (0p)"). The probe now keeps the matched file at low priority to hold the swarm warm; the race resumes from there. A/B verified: zero-then-race stalled where target-priority-during-probe downloads.
- Fixed a winning download being deleted instead of finishing: when a race winner that had already downloaded real bytes hit a transient stall, `stream_to_completion` returned `None` ("keep as fallback to resume later") but every caller then deleted the partial (`delete_files=True`) and abandoned it. A winning source with progress now re-announces to wake the swarm and resumes from its partial in place (up to 4 cycles) before giving up, so slow/bursty FLAC swarms download to completion.

### Search & metadata

- Fixed text search crashing with "Search failed: unhashable type: 'AppConfig'": `search_music` was decorated with `@lru_cache` and took the unhashable `AppConfig` dataclass as its first argument, so every typed search raised before returning. The config does not affect search results, so the cache now keys on the query alone.

### Playback and native audio

- Fixed native app-only output handoff while a torrent is still caching: selecting a native device now stops default-output browser playback, remembers the current position, and starts native playback from that position when the cache file is ready.
- Added a macOS best-effort auto-unmute helper for selected native output devices, including zero-volume recovery, so app-only playback is not silent just because the target device was left muted.
- Fixed playback dying when the selected app-audio output device disconnects (e.g. EDIFIER over Bluetooth dropping): instead of sitting silently paused, the app now listens for the browser `devicechange` event, detects the device leaving the CoreAudio list, and falls back to the default output ("This computer"), resuming from the same position.
- Restored the downloaded-file duration check (`downloaded_track_matches_request`), which had become dead code that always returned a match. A multi-file album/discography torrent could bind a job's `library_path` to the wrong sibling track; native output (which resolves files by track identity, unlike the browser which streams by job-id) then played the wrong song. Job finalization now picks the audio file whose duration matches the requested track (±10s) instead of the first file in the folder.
- Changed the player status icon behavior so a ready track opens the playlist picker, while download/error states still open the progress log.

### Packaging

- Added Playwright and `playwright-stealth` requirements for the Duck.ai browser worker.
- Updated macOS and Windows PyInstaller specs so packaged apps include the Duck.ai worker and Playwright Python package data.
- Added a frozen-app `--ddg-worker` entry point so the packaged desktop app can launch the Duck.ai browser worker without recursively opening the GUI.

### Assets

- `Mindinguflac-macos-arm64.zip` — macOS Apple Silicon desktop build.
- `Mindinguflac-windows.zip` — Windows x64 desktop build.

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
