# Mindinguflac v1.0.2

A reliability-focused patch release addressing critical metadata discovery bugs, cache corruption issues, and stricter artist matching.

## Highlights

### Artist and Album Discovery
- **Chronological Sorting:** The artist profile page now correctly prioritizes main studio albums over singles, compilations, and EPs.
- **Reliable Artist Links:** Fixed a bug where clicking multi-word artists (like Jimi Hendrix) would sometimes load an empty profile. Uses exact-match quoted queries for better resolution.
- **Improved Fallback Search:** Updated fallback search logic to handle special characters and multi-word names reliably.
- **Recursion Guard:** Fixed a critical bug where certain live albums could cause an infinite backend recursion loop.
- **Extended Discovery Timeout:** Increased discovery timeout to 30s to ensure deep discography lookups complete successfully.

### Stricter Audio Matching
- **Cover/Tribute Penalties:** Added explicit penalties for "Tribute", "Cover", "Reimagined", and "Karaoke" versions to prevent picking cover versions when original artists are requested.
- **Artist Path Verification:** The torrent engine now strictly verifies that the requested artist name appears in the file path or torrent title.
- **Torrent Engine Stability:** Fixed a bug where an undefined variable would cause torrent metadata probes to fail.
- **Cleaner SpotiFLAC Fallbacks:** Prioritizes high-fidelity official streaming providers and avoids low-quality user-uploaded covers.

### Playlist and UI Fixes
- **Auto-Formatting Durations:** Fixed an issue where tracks in imported playlists would show empty durations. Now automatically formats `duration_ms` if needed.
- **Self-Healing SQLite Storage:** Automatically identifies and bypasses "poisoned" 0-track cache entries.
- **Safe Caching:** Backend now strictly refuses to cache empty results into the persistent database.

## Desktop Packages
- `Mindinguflac-macos-arm64.zip` - macOS Apple Silicon desktop build.
- `Mindinguflac-windows.zip` - Windows x64 desktop build.

## Previous
See the v1.0.1 release notes for the major SpotiFLAC 1.0 engine upgrade this builds on.
