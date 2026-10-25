# Mindinguflac v1.4

## Added
- Add On this device and side-by-side, divided “This phone” and “Connected device” tabs to Offline, so the phone can browse and play the computer's completed downloads without copying its audio or exposing private file paths.
- Paired-computer playback in the Android Devices list over the existing pinned Wi-Fi connection. Forward song selection, queue and transport actions to the receiving desktop, show Listening on / Controlled by banners, and clear sessions on exit, timeout or pairing removal.
- Match the desktop and mobile album toolbar order, add the desktop overflow menu and persistent List/Compact views, and remove the extra Available offline header label. Android album sharing previews a customizable artwork card and opens the system image share sheet.
- Album header Play and Download All controls on desktop and Android. Download All queues the existing song action in order with the selected engine and quality, skips equal-or-better saved tracks, and shows remaining tracks in its progress ring. Queues survive navigation and resume when the app reopens.
- An automatic Offline playlist on desktop and Android, containing music downloaded on that device, with a four-cover artwork grid. It cannot be deleted and disappears when the device has no downloaded music.

## Changed
- Replace the retired SpotiFLAC dependency with embedded Mornye. Use its versioned REST API where supported and its artist-profile and lyrics functions for those features.
- Retain local artist-profile and lyrics implementations as compatibility fallbacks, and preserve already installed local provider extensions during migration.

## Fixed
- Show an animated remote-volume indicator with the connected device name and percentage on Android, and keep the remote session active in the background.
- Renew connected-device sessions from Android's native playback foreground service instead of relying on WebView background timers; hold a CPU wake lock only while remote control is active.
- Route Android hardware volume buttons and media-session volume controls to the selected computer only while connected; restore local phone volume when the remote session ends.
- Resolve artwork and metadata through each device's own backend and cache during remote playback; keep audio/video playback, downloads and prefetch on the receiving device.
- Mirror the receiving player's real loading state, progress, quality and queue title on the controller.
- Left-align the remote playback banner and open Devices when it is tapped, without an extra local-device button.
- Reserve the measured banner and player-control heights in the desktop and mobile layouts, including full-screen playback.
- Allow downward swipes to dismiss Android album share cards.
- Acknowledge library jobs before metadata lookups, persist resolved identifiers from the worker, and recover accepted downloads after a lost acknowledgement so album queues remain sequential.
- Show download errors with a visible retry state, retry punctuation-sensitive Monochrome searches without weakening recording matching, and prevent saved album siblings from supplying another track's progress or completion file.
- Retry a timed-out stream or library-download request once after two seconds, recovering the accepted job first so the retry does not duplicate work.
- Explain when Monochrome search finds only a live or alternate take and safely skips it.
- Filter playlist recommendations against the saved playlist by recording identity, exclude incomplete artist/album catalog entries, and retain Spotify/ISRC identifiers on playable recommendations.
- Resolve artist artwork for the Android Your Library artist list using the local metadata backend.
- Restore desktop music search when file-based logging prevented the embedded Mornye API from starting.
- Keep Android playback controls locked during native startup and Monochrome buffering, and unlock them after a failed start so playback can be retried.
- Allow verified original-album recordings when a compilation edition is unavailable, while preserving the requested and resolved ISRCs.
- Keep compilation album IDs and album artists distinct from track performers, preserve each saved release in title links, and prevent exact album requests from opening a different album by name.
- Verify shortened compilation edits against the same performer, musical work and studio-album release before using the available original recording.
- Reload lyrics using the actual streaming recording’s title, ISRC and duration, prefer timed lyrics over plain text, and label untimed lyrics clearly.
- Align lyrics against independently recognized buffered vocals on desktop and Android. Apply a measured offset only when multiple phrases agree; retain manual adjustments per recording and lyric version, and use the audible native playback clock.
- Match alternate catalog ISRCs through shared recording identities and normalize Unicode punctuation in performer names.
- Match streaming audio to video through the shared playback buffer, retry incomplete prefixes, and keep offsets separate for each audio source. Allow videos which omit a long album intro.
- Preserve explicitly selected deluxe/remaster album links even when Spotify reuses a track ID.
- Reuse equal-or-better saved audio across engines; identify lossy YouTube files by their actual format and distinguish lossless ALAC from AAC in M4A files.

## Security and version
- Upgrade Pillow to 13.0.0, including the bundled native Android decoder.
- Update Settings, backend user agents, macOS bundle metadata and Android to version **1.4**. Android versionCode is **24**.

Mornye provider downloads require an installed provider extension. Monochrome, YouTube and torrent backends remain independent.
