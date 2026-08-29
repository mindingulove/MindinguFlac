# Changelog

All notable changes to Mindinguflac are documented here.

---

## [1.2.6] — 2026-08-29

### Updated
- SpotiFLAC download module updated from `1.6.0` to `3.7.0` at upstream commit `902bf67`. Mindinguflac now uses the relocated `SpotiFLAC.core.spotify_metadata` API, supports the downloader's resumable-stream argument, and keeps the frozen-app endpoint cache redirect compatible with the cache's move into `SpotiFLAC.core`.
- SpotiFLAC 3.7.0 is extension-first: the built-in provider package has been removed. Existing provider names remain supported as aliases for installed extensions (`tidal-web`, `qobuz-web`, `amazon`, `deezer`, `soundcloud`, and `ytmusic-spotiflac`). A SpotiFLAC provider extension must be installed in `~/.spotiflac/extensions` for downloads to work.
- The complete reviewed SpotiFLAC extension registry set is installed locally: Spotify Web, Amazon Music, Apple Music, SoundCloud, YouTube Music, Deezer, Pandora, Qobuz Web, and Tidal Web.
- YouTube authentication now uses `browser_cookie3` discovery instead of a hardcoded browser list. Supported local cookie stores are checked fresh for every job; only YouTube-domain cookies are exported to a permission-restricted temporary job file, and that file is deleted when the job ends.
- Settings now offers Codex with GPT-5.4 Mini as a third AI advisor. Selecting it starts a browser-based PKCE login through `codex-auth`; credentials remain in that package's permission-restricted token store and are refreshed by the authentication client.
- The obsolete optional Qobuz user-token setting and persistence logic have been removed. Qobuz remains available through its SpotiFLAC provider extension without that legacy field.
- Duck.ai and Gemini now share one browser-worker lifecycle manager, and all download backends use the same normalized advisor settings. Dead browser-side chat helpers and unauthenticated debug chat endpoints were removed.
- AI requests stay with the provider explicitly selected in Settings instead of silently falling through to another provider. Video lookup now receives the saved provider/model settings correctly.
- Visible Settings footer, HTTP server header, backend user-agent, release helper, and macOS About/bundle versions now report `1.2.6`.

### Fixed
- Music search now recovers from an expired or transiently failing SpotiFLAC session and parses Spotify's current `tracksV2` fallback response instead of silently returning zero results.
- Artist popular-track titles and album names are normalized at the metadata boundary, preventing Python regex objects from appearing in the interface while preserving Spotify IDs used by downloads and Torrent matching.
- Artist biographies once again include Spotify's **Where people listen** cities and listener counts when those statistics are available.
- YouTube jobs with missing or expired signed-in browser cookies now show an actionable macOS/Windows notification. The action opens YouTube in the system default browser and retries the same failed track automatically when the user returns to Mindinguflac.
- YouTube login failures now also use the operating system notification service. macOS requests notification permission when the app first opens, making Mindinguflac available in System Settings before a download fails; clicking the native banner opens YouTube in the default browser, while the in-app action remains available if permission is denied.
- Desktop side-effect endpoints now reject cross-site browser origins, while preserving native and same-port loopback requests. Codex tokens are never returned by the local status or login APIs.
- Album pages and saved/favorite album rows now recover missing original release years through MusicBrainz, including old saved entries without album IDs. The year appears beside the artist, track count, duration, and sidebar album label; same-named singles no longer override the album year.
- Duck.ai's first readiness check now retries after Playwright's one-time Chromium installation, preventing a false unavailable status when the newly installed worker is already usable.
- The macOS Dock command now reads the actual native-or-browser audio state: it says **Pause** while music is playing and **Play** while playback is paused or stopped.
- Relaunching Mindinguflac restores the last selected song and its saved playback timestamp. The song opens paused at that position and resumes from there when Play is pressed.
- Spotify track, album, artist, ISRC, and cross-service identifiers remain unchanged through the SpotiFLAC metadata migration. Torrent remains an independent engine with its source selection and shared-session behavior unchanged.

## [1.2.5] — 2026-08-07

### Fixed
- The sidebar **Related music** card no longer stays empty until you skip to another track and back. `/api/artist/top_tracks` returned HTTP 500 (`'NoneType' object has no attribute 'strip'`) whenever the card sent `artist_id: null`, which is the normal state for a track whose Spotify artist ID has not been resolved yet. The card's error handler removes itself on failure, and since the sidebar only rebuilds when the track key changes, it never retried — so the card stayed gone for the whole track. `spotify_artist_top_tracks()` now coerces a missing artist name or ID instead of raising.
- The same card no longer hangs on `Loading related music...` before disappearing. `/api/artist/top_tracks` ran per-track play-count enrichment sequentially, taking 30–80s for artists with large catalogues, while the frontend aborts that request after 20s — so the card never populated. The endpoint now skips enrichment (its only consumer renders artwork and title, never play counts), cutting a cold Michael Jackson response from 79.5s to 5.1s. Artist-page sorting still enriches play counts as before.

### Updated
- SpotiFLAC download module updated from `1.5.2` to `1.6.0`, bringing its provider-pool cleanup on batch completion and a configurable concurrent-download limit.
- macOS and Windows PyInstaller specs now bundle `pydoll`. SpotiFLAC 1.6.0 imports it at package-import time (`core/solver.py` and `core/signed_session_mono.py`, reached via `providers/amazon.py`), and upstream declares it only in its `requirements.txt` rather than its package dependencies — without this, `import SpotiFLAC` fails at startup in a frozen build.
- Visible Settings footer, backend user-agent, release helper, and macOS About/bundle versions now report `1.2.5`.

---

## [1.2.4] — 2026-07-25

### Fixed
- YouTube fallback now detects a signed-in local browser session when YouTube requires bot verification, trying Safari then Chrome on macOS and Edge then Chrome on Windows.
- Browser selection skips profiles without YouTube login cookies and reports the selected browser in the cache log.

### Updated
- Visible Settings footer, backend user-agent, release helper, and macOS About/bundle versions now report `1.2.4`.
- SpotiFLAC download module updated to version `1.5.2`.

---

## [1.2.3] — 2026-07-22

### Fixed
- Download engines now explicitly request uncompressed HTTP responses, avoiding `incorrect header check` failures from proxies that mislabel response encoding across YouTube, Torrent, and SpotiFLAC downloads.
- SpotiFLAC provider attempts now use a fresh async HTTP client per event loop, preventing a successful first provider from leaving Deezer, Apple, or Tidal bound to its closed loop.

### Updated
- SpotiFLAC → 1.5.2, bringing its current async download orchestration and provider updates.
- Desktop builds now include the `nodriver` dependency required by SpotiFLAC's browser-backed provider fallback.

---

## [1.2.2] — 2026-07-14

### Fixed
- Prevented duplicate Mindinguflac app instances from opening a second desktop window on macOS startup/relaunch.
- Connected Bluetooth devices in the Connect panel now try to activate the matching audio output instead of remaining a dead no-op row.
- When a saved or selected Bluetooth output is not reachable, playback now falls back to `This computer` instead of staying stuck on an unavailable device.
- Native Bluetooth mute on macOS now honors an explicit `0` volume request instead of snapping back to full volume through the native-audio API path.
- Side video playback now stays in sync when audio is playing through the native output path, including tracks launched from Recently Played.
- Artist pages now render a fast initial Popular Tracks section immediately, then stream enriched playcounts in place instead of blocking the whole discovery view.
- Artist page albums and related artists now load in parallel with the slower top-track enrichment pass, so those sections appear without waiting for every playcount lookup to finish.
- Artist page top-track headers now use the compact single-height layout instead of leaving an oversized blank gap above the row labels.
- Artist page Popular Tracks headers no longer show a transient `Updating plays...` label while the background enrichment pass is still running.
- Missing Spotify playcounts on artist-page overflow tracks are now backfilled with per-track Spotify stats, so fallback tracks such as compilation or non-top10 rows still show populated plays.
- Listening Stats now fall back to period-filtered raw listening events for top artists, top albums, and top genres whenever the newer aggregate tables are incomplete, keeping those sections populated and aligned with the selected period.

---

## [1.2.1] — 2026-07-08

### Fixed
- SpotiFLAC provider HTTP clients now request identity encoding, preventing broken compressed API responses from crashing cache jobs with `incorrect header check`.
- Provider decompression failures are now captured as provider failures, allowing the controlled fallback chain to continue instead of surfacing a raw cache-job error.
- Apple Music is now included in the SpotiFLAC fallback order shown by Settings, with Apple lossless/Atmos quality values mapped to `ALAC` and `ATMOS`.
- Deezer/provider downloads mislabeled as `.flac` are repaired to their actual audio container before validation and metadata embedding.
- YouTube downloads now discover explicit `cookies.txt` files and retry without auth options when cookie-based attempts fail.
- Packaged macOS builds now redirect SpotiFLAC's internal provider endpoint cache (`SpotiFLAC/core/.endpoints_cache.txt`) to app data; the bundled copy is only used as a read-only seed, so endpoint refreshes no longer mutate the signed `.app` bundle.

### Updated
- Visible Settings footer, backend user-agent, release helper, and macOS About/bundle versions now report `1.2.1`.

---

## [1.2.0] — 2026-07-05

### Added
- Expanded synced lyrics support.
- Music video playback: the backend searches eight torrent providers (apibay, knaben, SolidTorrents, 1337x, KickAss, limetorrents, torlock, torrentdownloads) in parallel with a YouTube lookup; whichever returns a valid clip first is used, with YouTube as the automatic fallback when no torrent clip is found. An AI advisor (Duck.ai or Gemini) reranks torrent candidates in parallel before download begins.

### Updated
- SpotiFLAC → 1.3.1.
- Visible Settings footer, backend user-agent, and macOS About/bundle versions now report `1.2.0`.
- Windows build now ships as a single launcher exe. First run shows a native setup window (follows system light/dark theme) with an Unpack button; files are extracted to `%LOCALAPPDATA%\Mindinguflac\app\<version>\` and reused on every subsequent launch. Updating to a new version re-extracts automatically. Desktop and Start Menu shortcuts are offered during setup.

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
- ytp-dl now falls back to title-only searches when sparse queue/recent items have no artist metadata, without penalizing otherwise strong title matches.
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
