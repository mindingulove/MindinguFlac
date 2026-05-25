# Changelog

## What's New

### Downloads and Bypass Polish

- Added a configurable **Download retries** setting.
- Setting download retries to `0` now skips the direct attempt and routes download attempts through Tor immediately.
- The downloader iterates through providers and falls back through Tor when a provider is rate-limited or the direct attempt fails.
- Improved progress estimates, including a `6.5 MB/min` estimate for identified FLAC/lossless downloads, so the progress ring more closely reflects downloaded bytes.

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

- Shuffle immediately rebuilds the active queue and refreshes the prefetched next track.
- Shuffle and repeat controls now toggle their active state immediately and highlight when enabled.
- Selecting a new track cancels active or prefetched background jobs before starting the selected track.
- Playback now ignores stale cache job records whose audio file has been deleted, and falls back to a valid library file or a new stream download.
- Tracks that already contain a Spotify ID now resolve directly to their Spotify URL for streaming and downloading.

### System

- Updated the desktop integration for SpotiFLAC `0.6.1` and enabled `Artist/Album` subfolder organization for downloads.
- Restored AppKit loading in the macOS PyInstaller bundle to prevent the PyObjC startup failure.
