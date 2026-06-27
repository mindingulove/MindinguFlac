# Mindinguflac v1.1.4

## Highlights
- **SpotiFLAC → 1.2.8**: Upgraded the bundled SpotiFLAC integration and now passes the 1.2.8 download options directly.
- **Provider Selection Reliability**: Saved SpotiFLAC provider selections now take precedence before inherited defaults, so the chosen service is respected consistently.

## Bug Fixes and Stability
- Fixed artist popular tracks by routing them through the async SpotiFLAC client path.
- Updated the visible Settings footer, backend user-agent, and macOS About/bundle version metadata to `1.1.4`.
