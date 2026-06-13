# Mindinguflac v1.0.3

A small patch release focused on search reliability and recovery.

## Highlights

### Search Recovery
- **Stale Search Recovery:** Search suggestions and full-text search now recover after a transient Spotify client failure instead of staying broken until the app is restarted.
- **Safer Search Caching:** Empty search results are no longer cached, so one bad response cannot poison later searches.
- **ID-First Fetching:** Fixed a bug where not every request was fetched via ID first.

### Validation
- **Regression Coverage:** Added tests for the empty-result cache case and the retry-after-failure path.

## Notes
- This release builds on v1.0.2 and does not change playback semantics.
