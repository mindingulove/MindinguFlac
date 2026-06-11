# Mindinguflac v1.0.2

A reliability-focused patch release addressing critical metadata discovery bugs and cache corruption issues.

## Highlights

### Artist and Album Discovery
- **Chronological Sorting:** The artist profile page now correctly prioritizes main studio albums over singles, compilations, and EPs. This ensures that an artist's core discography is always visible in the top 8 positions, instead of being buried by posthumous releases or modern digital singles.
- **Improved Falling Search:** Updated the fallback artist/album search logic to use exact-match quoted queries. This fixes issues where artists with multi-word names (like Jimi Hendrix) or albums with special characters would fail to resolve when the primary discography API was unavailable.
- **Recursion Guard:** Fixed a critical bug where certain live albums (e.g. Jimi Hendrix Experience 1967/1969) could cause an infinite backend recursion loop during fallback resolution, resulting in empty tracklists.

### Cache Reliability
- **Self-Healing SQLite Storage:** Improved the persistent metadata cache to automatically identify and ignore "poisoned" entries. If a previous fetch attempt failed and cached an empty tracklist, the app now automatically detects the corruption, bypasses the cache, and re-fetches the correct data.
- **Safe Caching:** The backend now strictly refuses to cache empty results into the persistent database, preventing transient API timeouts from becoming permanent failures.

## Desktop Packages
- `Mindinguflac-macos-arm64.zip` - macOS Apple Silicon desktop build.
- `Mindinguflac-windows.zip` - Windows x64 desktop build.

## Previous
See the v1.0.1 release notes for the major SpotiFLAC 1.0 engine upgrade this builds on.
