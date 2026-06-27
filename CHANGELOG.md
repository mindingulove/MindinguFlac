# Changelog

All notable changes to Mindinguflac are documented here.

---

## [1.1.4] — 2026-06-27

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
- Visible Settings footer, backend user-agent, and macOS About/bundle versions now report `1.1.4`.

---

## [1.1.3] — 2026-06-21

### Fixed
- **Artist About section** — was silently failing to load (monthly listeners, biography, gallery) because Spotify removed the inline TOTP secret format (`let eU=[{secret:…}]`) from their web player JS bundle, causing every auth attempt to raise internally and return empty data.
- **Related Artists section** — same root cause; "Fans also like" tiles were never populated on the artist page.
- Both sections now use SpotiFLAC's `SpotifyWebClient` for authentication (TOTP via community secrets repo + required `Client-Token` header), with the live `queryArtistOverview` hash pulled dynamically from Spotify's JS bundle and a known fallback hash if scraping fails.

### Updated
- **SpotiFLAC → 1.2.1** — includes Deezer, Tidal, Amazon, and base provider updates; Phase 1 asyncio migration; FLAC validation for additional providers.
- Updated `stream_to_file` monkey-patch to accept the new `stop_event` parameter added in SpotiFLAC 1.2.1.

---

## [1.1.2] — 2026-06-14

### Fixed
- Artist top tracks failing to load after SpotiFLAC 1.1.8 upgrade.
- Typo in artist page section highlight.
- Windows CI artifact upload path.
- Visible version strings not updated on previous release.

### Updated
- SpotiFLAC → 1.1.8.

---

## [1.1.1] — 2026-06-12

### Fixed
- Prefetch handoff race condition causing the wrong track to play after fast skipping.
- macOS Now Playing widget: disappearing after sleep, duplicate widget on resume, artwork not updating.
- macOS Now Playing helper startup reliability and UI search dropdown z-index bleed.
- Play loop resolution after Now Playing interactions.
- All remaining `backend.*` import paths broken by the SpotiFLAC 1.1.0 package rename.

---

## [1.1.0] — 2026-06-11

### Added
- **Playlist recommendations** streamed progressively as they resolve.
- **Remove from playlist** context menu action.
- **ID-first routing** — direct navigation to artist/album/track by Spotify ID.
- Taste backfill v2 to seed tracks added after the v1 sentinel.
- Pill scroll arrows for overflow tabs.

### Fixed
- Artist queue seeding order.
- Listening metadata persistence.
- Settings navigation rendering.
- SpotiFLAC 1.1.0 import compatibility and frozen app bundling (macOS + Windows).

### Updated
- SpotiFLAC → 1.1.0 (package renamed from `backend` to `SpotiFLAC`).
- yt-dlp bundled explicitly in both macOS and Windows specs.

---

## [1.0.3] — 2026-06-10

### Fixed
- Artist page album discovery and sorting (studio albums prioritised over singles/compilations, newest first).

---

## [1.0.2] — 2026-06-10

### Added
- **Artist page "Fans also like"** section — Spotify related artists tiles.
- **Sidebar "Related music" carousel** — scrollable related artist cards.
- **"On Tour" section** on artist page with tile grid and Duck.ai / Gemini live date lookup.
- Wikipedia bio fallback with inline article links and page image preserved.
- Next-in-queue card shown immediately on first track selection and refreshed on queue mutations.
- Context menu overhaul: album context menu, boundary clamping, dynamic z-index, share links, MusicBrainz / YouTube ID detection.
- Album "Add to Queue" and "Share" actions.
- Queue wrap-around support.

### Fixed
- Artist ID re-resolution when a supplied ID returns no Spotify stats.
- Cached poisoned artist IDs scrubbed on startup.
- Context menu positioning (fixed, flip logic, long header wrapping).
- Duplicate tracks appearing in queue when playing from Home.
- Album-to-playlist batch addition.

### Updated
- SpotiFLAC → 1.0.0.
- Removed dead musicdl / backend_other engine code.

---

## [1.0.1] — earlier

### Added
- Per-service quality options in settings.
- Player pie progress ring (static before download starts, animated during).
- 2-second prefetch trigger for next track.
- Volume persistence across restarts.
- Playlist feature with Spotify import.
- macOS desktop app (PyInstaller .app bundle).
- Windows single-executable build.

### Fixed
- Artists/Albums nav both highlighting simultaneously.
- Spotify playlist metadata not auto-refreshing more than once per open.

---

## [1.0.0] — initial release

- Initial public release of Mindinguflac.
- SpotiFLAC, Torrent, and YTP-DL download engines.
- 5-track parallel prefetch with job reuse.
- Persistent SQLite storage for sources, blacklist, and metadata cache.
- macOS native audio output routing via NSSound.
- Duck.ai AI reranker for torrent candidate selection.
- HI-RES / HQ quality pills in the sidebar.
- Safari Audio error 4 auto-retry.
