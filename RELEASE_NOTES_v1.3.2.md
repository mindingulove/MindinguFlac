# Mindinguflac v1.3.2

## Fixed
- Desktop torrent first pass now uses a focused set of album, track, and lossless searches across every selected tracker. This reduces duplicate provider/detail requests that could hide healthy high-seed results.
- Android and desktop keep the best live torrent candidates in one seed/peer-ranked list, reject zero-seed live results, and reuse a verified album magnet for queued tracks from that album.
- Torrent playback downloads only the selected track, retries other candidates after a source stalls, and continues YouTube audio fallback while FLAC candidates are tested.
- Start prefetching upcoming queue tracks during current playback, with separate concurrency controls for playback and background prefetch plus an adjustable metadata timeout.
- Fix a cache-job crash caused by an album search variable being read before assignment.
- Keep playlist synchronization and playback settings aligned across devices.
- Settings, backend user-agent, macOS bundle, and Android now report version **1.3.2**. Android versionCode is **11**.

## Android download
Download **Mindinguflac-android-arm64-v1.3.2-build11.apk** below. Requires Android 8.0 or newer and a 64-bit ARM device (`arm64-v8a`). The `.apk.sha256` file contains its SHA-256 checksum. The APK is signed with the same certificate as previous Android releases so it can update an existing installation in place.
