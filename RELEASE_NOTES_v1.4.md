# Mindinguflac v1.4

## Added
- An automatic Offline playlist on desktop and Android, containing music downloaded on that device, with a four-cover artwork grid. It cannot be deleted and disappears when the device has no downloaded music.

## Changed
- Replace the retired SpotiFLAC dependency with embedded Mornye. Use its versioned REST API where supported and its artist-profile and lyrics functions for those features.
- Retain local artist-profile and lyrics implementations as compatibility fallbacks, and preserve already installed local provider extensions during migration.

## Fixed
- Restore desktop music search when file-based logging prevented the embedded Mornye API from starting.
- Keep Android playback controls locked during native startup and Monochrome buffering, and unlock them after a failed start so playback can be retried.
- Allow verified original-album recordings when a compilation edition is unavailable, while preserving the requested and resolved ISRCs.
- Keep compilation album IDs and album artists distinct from track performers, preserve each saved release in title links, and prevent exact album requests from opening a different album by name.
- Verify shortened compilation edits against the same performer, musical work and studio-album release before using the available original recording.
- Reload lyrics using the actual streaming recording’s title, ISRC and duration, prefer timed lyrics over plain text, and label untimed lyrics clearly.
- Match alternate catalog ISRCs through shared recording identities and normalize Unicode punctuation in performer names.
- Match streaming audio to video through the shared playback buffer, retry incomplete prefixes, and keep offsets separate for each audio source. Allow videos which omit a long album intro.
- Preserve explicitly selected deluxe/remaster album links even when Spotify reuses a track ID.
- Reuse equal-or-better saved audio across engines; identify lossy YouTube files by their actual format and distinguish lossless ALAC from AAC in M4A files.

## Security and version
- Upgrade Pillow to 13.0.0, including the bundled native Android decoder.
- Update Settings, backend user agents, macOS bundle metadata and Android to version **1.4**. Android versionCode is **19**.

Mornye provider downloads require an installed provider extension. Monochrome, YouTube and torrent backends remain independent.
