# Mindinguflac v1.4

## Added
- Add On this device and side-by-side, divided “This phone” and “Connected device” tabs to Offline, so the phone can browse and play the computer's completed downloads without copying its audio or exposing private file paths.
- Paired-computer playback in the Android Devices list over the existing pinned Wi-Fi connection. Forward song selection, queue and transport actions to the receiving desktop, show Listening on / Controlled by banners, and clear sessions on exit, timeout or pairing removal.
- Match the desktop and mobile album toolbar order, add the desktop overflow menu and persistent List/Compact views, and remove the extra Available offline header label. Android album sharing previews a customizable artwork card and opens the system image share sheet.
- Album header Play and Download All controls on desktop and Android. Download All queues the existing song action in order with the selected engine and quality, skips equal-or-better saved tracks, and shows remaining tracks in its progress ring. Queues survive navigation and resume when the app reopens.
- Show the computer's lyrics on a controlling phone, timed by the alignment the computer measured against the audio it is playing; lyric nudges on the phone adjust the computer.
- Play the music video on a controlling phone: it downloads the clip the computer matched in the background and plays it muted, following the computer's clock and video offset. Switch to video/audio mirrors between the two devices.
- Swipe left or right to move between the This phone and Connected device tabs in Offline.
- An automatic Offline playlist on desktop and Android, containing music downloaded on that device, with a four-cover artwork grid. It cannot be deleted and disappears when the device has no downloaded music.

## Changed
- Replace the retired SpotiFLAC dependency with embedded Mornye. Use its versioned REST API where supported and its artist-profile and lyrics functions for those features.
- Retain local artist-profile and lyrics implementations as compatibility fallbacks, and preserve already installed local provider extensions during migration.

## Fixed
- Suppress browser tap highlights and accidental text selection on player controls while retaining selectable text fields.
- Keep Android video controls visible after finger-up and allow a quick second tap to switch video mode.
- Start cached desktop audio on the system output when a saved Bluetooth device has disconnected, retaining volume and playback position.
- Check small video storyboard previews before downloading music clips, skip static album artwork, and show No video available when matching uploads contain only artwork. Check existing video files before offering the video switch, and keep failed preview checks retryable.
- Hide video/audio controls after three seconds without pointer or touch activity, including when the pointer stays over the artwork.
- Let Monochrome downloads reuse the selected playback source and shared transfer, allow slow catalog responses, and save audio without keeping a video track.
- Find the bundled Node.js and media tools for Mornye providers when the desktop app starts from Finder.
- Run Mornye's JavaScript provider extensions on Android with a bundled standalone Node.js and FFmpeg 8.1 (`ffmpeg`/`ffprobe` built from source with the NDK), bundle the provider extensions in the APK, and pass their signed-session challenge in a Chrome Custom Tab, as Mornye's own app does: the real browser usually clears Cloudflare without a tap (a WebView is challenged harder), and the grant returns through the `mornye://session-grant` deep link (the Zarz page redirects only to Mornye's or SpotiFLAC's scheme), which brings the app back. A song the user plays clears Mornye's pause after a failed check, the signed request waits long enough for a check to finish, and extension warnings now reach the log. While the app is in the background, a "Tap to verify" notification opens it. The phone downloads with the selected provider only, so one download asks for at most one verification. Node 18-era file reads no longer trip Mornye's extension write guard.
- Show an animated remote-volume indicator with the connected device name and percentage on Android, and keep the remote session active in the background.
- Renew connected-device sessions from Android's native playback foreground service instead of relying on WebView background timers; hold a CPU wake lock only while remote control is active.
- Route Android hardware volume buttons and media-session volume controls to the selected computer only while connected; restore local phone volume when the remote session ends.
- Resolve artwork and metadata through each device's own backend and cache during remote playback; keep audio/video playback, downloads and prefetch on the receiving device.
- Mirror the receiving player's real loading state, progress, quality and queue title on the controller.
- Keep the seekbar moving for Monochrome streams whose length is not in the track metadata, using the matched recording's length; the remote seekbar no longer stays at 0:00 on both devices.
- Report the live playback clock to the phone after it selects a song on a computer that restored a paused track at launch; seeks from the phone are no longer ignored there.
- Follow the remote position in the Android collapsed player's progress line, and never freeze the remote clock after a tap on the seekbar.
- Keep the Devices and Queue panels clear of the remote-control banner on desktop.
- Play the macOS side video smoothly: never restart a seek that is still loading, and correct drift with occasional seeks instead of speed changes, which stepped the video frame by frame.
- Keep the remote seek thumb stable while dragging and send one seek when released, so both devices land at the same playback position.
- Left-align the remote playback banner and open Devices when it is tapped, without an extra local-device button.
- Reserve the measured banner and player-control heights in the desktop and mobile layouts, including full-screen playback.
- Allow downward swipes to dismiss Android album share cards.
- Acknowledge library jobs before metadata lookups, persist resolved identifiers from the worker, and recover accepted downloads after a lost acknowledgement so album queues remain sequential.
- Show download errors with a visible retry state, retry punctuation-sensitive Monochrome searches without weakening recording matching, and prevent saved album siblings from supplying another track's progress or completion file.
- Retry a timed-out stream or library-download request once after two seconds, recovering the accepted job first so the retry does not duplicate work.
- Explain when Monochrome search finds only a live or alternate take and safely skips it; the stream then continues on YouTube instead of failing. Explicit Monochrome downloads still report the miss.
- Android offline downloads from Monochrome use the same OkHttp client as playback, so they are no longer refused with HTTP 403.
- The side-video motion check decodes YouTube's storyboard previews on Android too. They are WebP, which the phone's Pillow cannot read, so it failed with `UnidentifiedImageError`.
- Adding several playlist recommendations in quick succession no longer shows an insertBefore error or leaves added songs listed under Recommended.
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
- Update Settings, backend user agents, macOS bundle metadata and Android to version **1.4**. Android versionCode is **36**.

Mornye provider downloads require an installed provider extension. Monochrome, YouTube and torrent backends remain independent.
