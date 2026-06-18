# Mindinguflac v1.1.1

## Highlights
- Artist pages now recover Duran Duran's top tracks from the live Spotify artist identity again.
- Top-track lookup falls back to the live Spotify client when the direct artist endpoint is empty.
- Artist identity resolution prefers the live Spotify search path and only uses cached discovery data as a last resort.

## Bug Fixes
- Fixed artist pages returning empty popular-track sections for artists whose cached identity or endpoint response had drifted.
- Fixed the macOS bundle version metadata to match the new `1.1.1` release.
