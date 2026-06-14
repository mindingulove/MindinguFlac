# Mindinguflac v1.1.0

## Highlights
- Added local taste profiles driven by actual listening and manual feedback.
- Added playlist recommendations that can continue manual playlists dynamically.
- Stored playlist origin explicitly so album-derived playlists remain separate from user-created playlists.
- Improved taste-aware ranking across search, artist views, and playlist recommendations.

## Playlist Recommendations
- Recommendation panel now appears below the track list on user-created playlists.
- Recommendations are seeded from the playlist's artists, albums, genres, and decade profile.
- Tracks already in the playlist, queue, or previously shown this session are excluded.
- Add a recommendation directly to the playlist with the + button; a replacement is fetched automatically.
- Dismiss a recommendation to blacklist it from future suggestions for that playlist.
- Results are cached in SQLite for 24 hours and served instantly on return visits.
- Track-key prefix normalization ensures playlist tracks are correctly excluded from the suggestion pool.
- Artwork loads lazily via JS Image preload — expired CDN URLs are silently ignored instead of causing browser errors.

## Stats & UI
- Stats period month picker rebuilt as a proper dropdown overlay using a portal pattern, escaping overflow-clipping ancestors.
- Home nav pill now shows a house icon instead of text.

## Bug Fixes
- Fixed SQLite "database is locked" storms caused by background migration threads spawning additional migration threads on each new connection. Sentinel is now committed before the background thread starts.
- Background listen-stats and genre-affinity backfill jobs now commit every 50 rows instead of holding a single write transaction for the entire backfill, preventing other writes from timing out.
- Server suspended (Ctrl+Z) state no longer silently blocks all recommendations — connection state is now properly cleared on restart.
