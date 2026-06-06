# Mindinguflac v0.9.0

## Highlight: app-only output fixes and stronger AI-assisted torrent selection

Mindinguflac now handles selected output devices more reliably on macOS, improves how torrent candidates are ranked and raced, and replaces the fragile Duck.ai direct-request bypass with a persistent browser worker that lets Duck.ai's own frontend handle its challenge flow.

## Torrent Engine

- Passes magnet metadata into the AI reranker so candidate display names and trackers can be considered.
- Improves torrent racing by sorting candidates with measured live peer counts, then selecting the fastest source by real byte progress instead of first candidate order.
- Keeps the AI advisor non-blocking: it can guide clean candidate ordering, but it cannot override adult/video filters, metadata checks, or libtorrent byte-progress validation.
- Replaces the brittle Duck.ai direct-request bypass with a long-running Playwright browser worker that uses Duck.ai's real frontend.
- Preserves shared torrent files across active playback and same-album prefetch jobs so one job cannot delete another job's live `_race` files.
- Throttles concurrent prefetch torrent jobs so 5-track prefetch does not starve the actively-playing track's metadata probe.
- Keeps the matched torrent file prioritized during metadata probing so the swarm remains warm before the race starts.
- Resumes winning sources with real progress through transient stalls instead of deleting useful partial downloads.

## Playback and Native Audio

- Adds a macOS best-effort auto-unmute helper for selected native output devices, including zero-volume recovery.
- Fixes native app-only output handoff while a torrent is still caching: selecting a native device stops default-output browser playback, remembers position, and starts native playback when the cache file is ready.
- Falls back to "This computer" and resumes from the same position if the selected app-audio output device disconnects.
- Restores downloaded-file duration matching so multi-file album/discography torrents bind playback to the requested track instead of a wrong sibling file.
- Changes the player status icon so ready tracks open the playlist picker, while download/error states still open the progress log.

## Search and Metadata

- Fixes text search crashes caused by caching with an unhashable `AppConfig`.

## Packaging

- Adds Playwright and `playwright-stealth` requirements for the Duck.ai browser worker.
- Updates macOS and Windows PyInstaller specs to include the Duck.ai worker and Playwright package data.
- Adds a frozen-app `--ddg-worker` entry point so packaged desktop apps can launch the Duck.ai worker without recursively opening the GUI.
- Updates visible app and bundle versions to `0.9.0`.

## Assets

- `Mindinguflac-macos-arm64.zip` - macOS Apple Silicon desktop build.
- `Mindinguflac-windows.zip` - Windows x64 desktop build.
