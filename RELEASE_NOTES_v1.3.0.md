# Mindinguflac v1.3.0

## Added
- Introduce Mindinguflac for Android as a new standalone app for Android 8+ 64-bit ARM devices.
- Pair Android and desktop over the local Wi-Fi network with a fingerprint-checked, expiring QR invitation and an explicit confirmation dialog.
- Sync recently played tracks, listening statistics, and shared preferences, including tour source, tour location, and the Discogs token.
- Browse playlists, albums, and deduplicated artists in the Android library, and reorder the Android queue with touch gestures.

## Fixed
- Set the Windows unpacker window, taskbar and shortcut icons, and refresh extracted files when replacing a build of the same version.
- Check Windows browser profiles separately and try public YouTube access when browser cookies cannot be imported, instead of reporting a login requirement before contacting YouTube.
- Use combined video/audio MP4 streams on Android without requiring FFmpeg; report download failures separately from missing videos.
- Update Android to Python 3.12, CFFI 2.0.0, cryptography 50.0.2 with OpenSSL 3.5.9 LTS, and Pillow 12.3.0 to address reported dependency vulnerabilities.
- Keep AI advisor provider and model choices device-specific while syncing shared settings.
- Apply the first desktop settings snapshot on Android and use saved logical revisions for later preference changes.
- Show settings save results in a themed in-app dialog on Android.
- Renew a visible desktop pairing QR code automatically and provide a Show/Hide toggle.
- Open scanned pairing links in Android Settings and retain them until the WebView is ready.
- Correct pairing preview routing and report the scanned desktop name when verification fails.
