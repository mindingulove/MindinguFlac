# Mindinguflac v1.1.2

## Highlights
- Upgraded the packaged SpotiFLAC integration to the `v1.1.8` module line.
- Artist Popular Tracks improved and fixed a bug with Spotify's artist overview data by Spotify artist ID before falling back to text search.
- Added proxy-aware async HTTP client patching for newer SpotiFLAC network paths.

## Bug Fixes
- Fixed artist pages falling back to generic search results for top songs even when a Spotify artist ID was available.
- Fixed the Duran Duran popular-track path to resolve the live Spotify artist identity and return ID-backed top tracks.
- Fixed the in-app footer and backend user-agent version strings to report `1.1.2`.
- Added a settings gear tooltip and removed the redundant settings page hero title.
