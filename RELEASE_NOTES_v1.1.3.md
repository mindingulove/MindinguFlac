# Mindinguflac v1.1.3

## Highlights
- **SpotiFLAC → 1.2.1**: Upgraded the internal backend core to SpotiFLAC 1.2.1, supporting updated Deezer, Tidal, and Amazon services, alongside a Phase 1 asyncio migration and FLAC verification improvements.
- **Spotify Web Auth Fixes**: Fixed the Artist About and Related Artists sections (monthly listeners, biography, image gallery, fans-also-like) that were silently failing due to Spotify removing inline TOTP secret declarations. Both sections now authenticate using `SpotifyWebClient` query structures with community-supplied fallback queries.

## Bug Fixes and Stability
- **Torrent Session Leak & Stalling**: Fixed a critical bug where unsuccessful torrent candidates in a race were left active, exhausting connection limits and stalling subsequent downloads. Stalled candidate handles are now cleanly unregistered and removed.
- **Cache Clean-Up Reliability**: Fixed a file handle lock that prevented the "Empty Cache" function from executing. The app now closes and unregisters torrent resources before purging the cache directory with safe retry loops.
- **Accurate Download Progress**: Fixed the sparse preallocated file size illusion that caused the progress bar to prematurely jump to 95% on torrent downloads. Progress is now calculated strictly from active libtorrent progress bytes.
- **Audio Playback Buffering**: Fixed an issue where WebKit `<audio>` would buffer indefinitely when trying to stream a previously fully-downloaded FLAC torrent candidate by checking file status and correctly routing it via the content-length range path.
