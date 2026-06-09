# Mindinguflac v1.0.1

A patch release on top of v1.0.0, focused on a major SpotiFLAC engine upgrade, a real "related music" / "fans also like" discovery experience, richer artist pages, and several metadata and queue reliability fixes.

## Highlights

### SpotiFLAC Engine
- Upgraded the SpotiFLAC engine to **1.0.0** (the module was refactored to expose its core logic through the `backend` package). Downloads, parallel-run patching, metadata search, artist top-tracks, and album/playlist lookups were all re-validated end-to-end against the new version.

### Discovery & Artist Pages
- **Related music**: the sidebar "Related music" card is now a Spotify-style horizontal carousel of the playing artist's top tracks.
- **Fans also like**: artist pages now show a related-artists section (Spotify "fans also like", with a MusicBrainz relationship fallback), with circular artist tiles and a "Show all" grid.
- **On Tour**: artist pages now include an "On Tour" section with a tile grid and a "View all upcoming concerts" link.

### Artist Info & Bios
- **Reliable artist info**: when a track carries a wrong or non-Spotify artist id, the sidebar now re-resolves the artist by name instead of falling back to the album cover with 0 listeners.
- **Cache scrub**: a one-time cleanup removes previously cached wrong/non-Spotify artist ids so they re-resolve correctly.
- **Wikipedia bios**: when Spotify has no data, the fallback Wikipedia biography now keeps its inline article links and uses the Wikipedia page image.

### Queue
- The **Next in queue** card now appears immediately on the first track selection and updates live when the queue is reordered, shuffled, or has tracks added/removed.

### Cleanup
- Removed dead `musicdl` / `backend_other` engine code and the vestigial UI it left behind.

## Assets

- `Mindinguflac-macos-arm64.zip` - macOS Apple Silicon desktop build.
- `Mindinguflac-windows.zip` - Windows x64 desktop build.

## Previous

See the v1.0.0 release notes for the first stable release this builds on.
