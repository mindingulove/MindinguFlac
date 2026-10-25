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

## Compilation identity and recording editions (v1.4)

Mornye v1 TrackOut does not carry album IDs or artist IDs. The bridge restores
those uncovered fields from the corresponding public SDK track object, reusing
search results where available. Metadata caches use exact Spotify track IDs,
so a compilation edit cannot overwrite the artist-album edition of the song.
Saved album URLs/IDs remain authoritative; album navigation does not infer an
album from the performing artist when an exact release is available.

Various Artists album owners are kept separate from individual performers.
Album responses and saved/imported tracks retain the album ID and album artist.
The same song can belong to both saved albums without merging their links.

For an unavailable unlabelled compilation edit, a Monochrome studio-album
fallback requires matching performer, musical-work relationship, provider vs
MusicBrainz duration, and a non-compilation, non-live album release. Live takes,
remixes and unverified title matches remain excluded. Requested and source ISRCs
are retained separately; using original audio does not replace the selected
compilation album or artwork.

Live case: Spotify track `4xCvkEWkK08p00riIBu1QO` belongs to album
`7AecHhPbyoban69HXHUL7a` (Hits Of The 90s, Various Artists, 16 tracks),
ISRC `USPR39507368`. Its edit and the Relish album recording share MusicBrainz
work `2c48f418-73f4-3380-a136-c81b4969e860`. The selected Monochrome album take
uses `USPR39500200`; a ranged request returned HTTP 206 with a FLAC header.

Alternate catalog ISRCs can resolve to one MusicBrainz recording ID. The matcher
accepts this stronger identity only with the same performer, base title and
compatible source/provider durations. Unicode dash variants are normalized
before performer comparison. This also covers single/7-inch labels without
song-specific mappings. The reported Save Tonight compilation ISRC
`GBAKW0201563` and provider `USSM10027246` share recording
`d8a837d1-886d-44e4-aa72-d19e61180b3b`; the resolver selects the provider recording
and retains the requested compilation identity.

Browser Monochrome playback now uses a restricted loopback range proxy backed
by the existing native shared fetch. Video sync reads those same cached bytes,
with no second provider request for matching. Android native playback continues
to use its captured stream prefix. Incomplete prefixes are retried; offsets and
manual nudges are keyed by audio source and matcher version, so an edit cannot
reuse an original-album offset or a stale failure. Matching also searches
negative offsets for videos which omit album intros, retaining the confidence
and ambiguity rejection checks. Different edits with incompatible soundtracks
still report unmatched rather than guessing.

Lyrics now follow `source_recording` after resolution, while selected compilation
album identity stays intact. The payload uses the actual title, duration and
ISRC, and excludes a compilation Spotify ID when fallback audio is selected.
Changing recording invalidates the in-flight UI lyrics identity. Mornye remains
the provider implementation: parallel public `fetch_lyrics_async` calls with
individual provider lists let the application prefer timed answers over plain
ones without modifying upstream internals. The app cache generation changes to
avoid reusing prior plain-only decisions, and plain lyrics are labelled untimed.

Final v1.4 verification: 230 focused Python tests plus 7 subtests passed;
JavaScript album identity, lyrics source handoff, offline playlist and transport
lock checks passed. The frozen desktop app resolved Save Tonight to catalog ISRC
`USSM10027246`, then requested lyrics as `Save Tonight`, 239 seconds, without the
compilation Spotify ID. Its runtime cache contains synced LRCLIB lyrics (47 timed
lines). Comparing the already-buffered audio with the cached video matched at
+0.116 seconds (confidence 19.4, margin 10.03), without another audio download.
Both final ARM64 packages match the source/UI; macOS deep strict signing and
Android v2 debug signing pass. Android hardware execution remains untested.
