# Embedded Mornye integration

Mindinguflac vendors Mornye-Python 1.0.4 at commit
`297c780c3e7bcd9dffab65a65f8b1bc686da238b` under `vendor/mornye-python`.
The retired SpotiFLAC repository is not needed for installation, packaging or
runtime. The upstream source and MIT license are retained together.

## Routing

| Feature | Primary implementation |
| --- | --- |
| Track search | Mornye `GET /api/v1/search` |
| Track/album/playlist tracks with ISRC | Mornye `POST /api/v1/resolve` |
| Provider downloads, progress and cancellation | Mornye `/api/v1/downloads` jobs |
| Installed extension health | Mornye `GET /api/v1/extensions` |
| Artist profile | Mornye `SpotifyMetadataClient.get_artist_profile_async` |
| Lyrics | Mornye `core.lyrics.fetch_lyrics_async` |
| Uncovered artist/album search, discography and play counts | Isolated Mornye SDK adapter |

Mornye has artist-profile and lyrics functions, so they are the primary route.
`local_metadata` retains the SpotiFLAC implementations as a compatibility fallback
only when the corresponding Mornye function is missing. It carries the original
MIT license and provenance. An upstream network error does not silently select a
different implementation. Existing Mindinguflac endpoints and lyric caches remain.

`mornye_bridge.py` isolates SDK use. No downloader monkeypatches, GUI RPC methods,
or imports of the retired SpotiFLAC package are used. The old `spotiflac` engine
setting is retained as a compatibility ID; the visible engine is Mornye.

## Service lifecycle

`mornye_runtime.py` lazily starts the official upstream FastAPI application on an
OS-assigned `127.0.0.1` port with a random per-run token, verifies `/api/v1/info`,
and stops the service with Mindinguflac. It runs inside the same app on desktop
and Android, without a companion server. All Mornye state is under Mindinguflac's
writable data directory. Upstream GUI installers and subscription schedulers are
not started by this embedded service.

The components share device-local storage. Jobs receive a local output directory;
Mindinguflac validates and plays resulting files through its own existing range
endpoints. A successful API job is not treated as a remote audio-stream URL.

Android packages real Pydantic, a verified Android arm64 `pydantic-core` wheel,
FastAPI and Uvicorn. A headless `webview` import adapter prevents Mornye from
opening a second GUI. The old Pydantic stand-in and SpotiFLAC package are removed.

## Providers and verification limits

Mornye ships no default provider extensions or registry. Already installed local
Mornye/SpotiFLAC extensions are copied once into the app data directory, without
overwriting newer app copies or contacting an extension registry. Only installed extensions
are submitted to its API. Android exposes the provider engine only when a Python
extension, or an extension with a usable runtime, is present. JavaScript
extensions still require Node.js, which the Android package does not contain.
Monochrome, YouTube and torrent backends remain independent.

Contract tests exercise the actual authenticated REST server, resolution, service
shutdown/restart, primary SDK artist/lyrics routing, fallback selection and
provider-job request/cancellation mapping. Live desktop checks resolved the
Hungry Like the Wolf Spotify track with its ISRC, fetched Duran Duran's artist
profile and obtained synced lyrics through Mornye. No third-party provider
extension transfer or physical Android runtime test is claimed.

Sources:
- https://github.com/mornyeapp/Mornye-Python/blob/main/docs/guide/rest-api.md
- https://github.com/mornyeapp/Mornye-Python/blob/main/docs/guide/extensions.md
- https://github.com/mornyeapp/Mornye-Python/blob/main/docs/guide/migration.md

The native desktop log writer is not a terminal. The embedded Uvicorn service
uses the app's logging configuration; using Uvicorn's default formatter prevented
startup through an `isatty` call and made search appear empty. A real API startup
test with file-only logging covers that regression.

Focused migration/playback tests pass (223 tests plus 7 subtests, and the two
JavaScript suites). The legacy `test_music_metadata.py` suite also has existing
fixture/cache failures reproduced against the pre-migration module; these are
not included in the passing focused count. `test_spotify_web_metadata.py` already
refers to a module absent from the checkout and cannot be collected.

Final frozen macOS verification: the rebuilt arm64 app returned 60 results for
`pink floyd` (20 tracks, 20 artists, 20 albums). The native UI search, Artists tab
and Albums tab were exercised. Packaged code and UI match source, and deep strict
code-signature verification passes. Android APK signature/content checks pass;
physical Android execution remains untested.
