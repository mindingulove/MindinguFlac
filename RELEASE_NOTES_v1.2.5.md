# Mindinguflac v1.2.5

This release updates the SpotiFLAC download engine to 1.6.0 and fixes the sidebar **Related music** card, which never finished loading.

- Fixes the **Related music** card staying empty until you skip to the next track and back. The artist top-tracks endpoint returned a server error whenever the card asked about a track whose Spotify artist ID had not been resolved yet — the normal state when a song first starts. The card removes itself when a request fails and only rebuilds when the track changes, so it stayed missing for the rest of that song.
- Fixes the same card getting stuck on `Loading related music...` and then vanishing. The endpoint was running per-track play-count enrichment sequentially, taking 30–80 seconds for artists with large catalogues, while the interface gives up on that request after 20 seconds. The endpoint now skips that enrichment, since the card only shows artwork and titles — a cold Michael Jackson request drops from 79.5s to 5.1s.
- Artist pages still enrich and sort by play counts exactly as before.
- Updates the SpotiFLAC download module from 1.5.2 to 1.6.0, which closes provider connection pools when a download batch finishes and makes the concurrent-download limit configurable.
- Bundles the `pydoll` dependency that SpotiFLAC 1.6.0 requires at import time. Upstream lists it only in its requirements file rather than its package dependencies, so without this the packaged app fails to start.
- macOS (Apple Silicon and Intel) desktop builds are included.
