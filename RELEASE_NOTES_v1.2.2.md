# Mindinguflac v1.2.2

This release focuses on macOS desktop stability, Bluetooth output recovery, video playback behavior, and artist-page metadata delivery.

## Fixed

- Prevented duplicate Mindinguflac app instances from opening a second desktop window on macOS startup or relaunch.
- Connected Bluetooth devices in the Connect panel now actively try to switch to the matching audio output instead of showing a dead connected row.
- Saved or selected Bluetooth outputs now fall back to `This computer` when the device is connected but not reachable as an audio output.
- Native Bluetooth mute on macOS now respects a real zero-volume request instead of bouncing back to full volume through the native output endpoint.
- Side video playback now keeps playing when audio is routed through native output, including tracks started from Recently Played.
- Artist pages now render Popular Tracks immediately from the fast Spotify overview payload, then stream in the fully enriched track list afterward instead of hanging on discovery loading.
- Artist page albums and related artists now load in parallel with the slow playcount enrichment pass.
- Artist page overflow tracks now backfill missing Spotify plays with per-track Spotify stats, so non-top10 rows and compilation tracks still show populated play counts.
- Artist page Popular Tracks headers now use a tighter single-height layout.
- Artist page Popular Tracks headers no longer show a temporary `Updating plays...` label during the background enrichment pass.
- Listening Stats now fall back to period-filtered raw listening events for top artists, top albums, and top genres whenever the newer aggregate tables are incomplete, keeping those sections populated and matched to the selected period.

## Updated

- Visible Settings footer, backend user-agent, release helper, and macOS About/bundle metadata now report `1.2.2`.
