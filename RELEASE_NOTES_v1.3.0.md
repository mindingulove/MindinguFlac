# Mindinguflac v1.3.0

## Added
- Pair Android and desktop over the local Wi-Fi network with a fingerprint-checked, expiring QR invitation and an explicit confirmation dialog.
- Sync recently played tracks, listening statistics, and shared preferences, including tour source, tour location, and the Discogs token.
- Browse playlists, albums, and deduplicated artists in the Android library, and reorder the Android queue with touch gestures.

## Fixed
- Keep AI advisor provider and model choices device-specific while syncing shared settings.
- Apply the first desktop settings snapshot on Android and use saved logical revisions for later preference changes.
- Show settings save results in a themed in-app dialog on Android.
- Renew a visible desktop pairing QR code automatically and provide a Show/Hide toggle.
- Open scanned pairing links in Android Settings and retain them until the WebView is ready.
- Correct pairing preview routing and report the scanned desktop name when verification fails.
