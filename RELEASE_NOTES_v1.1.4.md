# Mindinguflac v1.1.4

### Fixed
- Artist popular tracks now load through the async SpotiFLAC client path.
- Saved SpotiFLAC provider selections are honored before inherited defaults.
- Finalized cache playback now clears stale red error status icons left by earlier failed stream attempts.

### Updated
- SpotiFLAC → 1.2.8.
- Download requests now pass SpotiFLAC 1.2.8 options directly.
- ytp-dl and torrent searches now use a metadata-driven classical search path for classical genre/style tracks, with catalog-number safeguards so normal music searches keep the existing stricter behavior.
- ytp-dl and torrent stream jobs now enrich missing genre metadata before search-profile selection using Spotify/ISRC and MusicBrainz genre/tag lookup, so classical tracks can enter the classical search path even when the frontend payload is sparse.
- Recently Played and other `track_key`-only playback entries now recover Spotify/ISRC identifiers before download metadata enrichment.
- ytp-dl now falls back to title-only searches when sparse queue/recent items have no artist metadata, without penalizing otherwise strong title matches.
- Visible Settings footer, backend user-agent, and macOS About/bundle versions now report `1.1.4`.

