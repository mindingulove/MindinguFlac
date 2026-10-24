# Replacing SpotiFLAC with Mornye

Assessed upstream commit `297c780c3e7bcd9dffab65a65f8b1bc686da238b`
(package version 1.0.4) on 2026-10-24. This document describes the migration;
the current application still uses its pinned SpotiFLAC dependency.

Mornye's core includes metadata resolution, but no download providers or default
extension registry. A provider extension source must be selected before replacing
the existing downloader. An unconfigured replacement would remove working
Tidal/Qobuz/etc. support. Monochrome, YouTube and torrent backends are independent.

## Selected approach: embedded REST API on each device

The user selected local execution inside Mindinguflac on both desktop and
Android. Prefer upstream's versioned `/api/v1` contract for the functions it
covers, rather than monkeypatching downloader internals. This is an architecture
decision, not an implemented replacement in the current build.

Mindinguflac should own the service lifecycle, start it on an OS-assigned
loopback port, use a per-run authentication token, wait for `/api/v1/info`, and
stop it when the app exits. No separately configured server or public listener
is needed. Keep Mornye data, cache, extensions and database under Mindinguflac's
writable application directory.

| Mindinguflac operation | Mornye contract |
| --- | --- |
| Health/version check | `GET /api/v1/info` |
| Track search | `GET /api/v1/search?q=...` |
| Track/album/playlist metadata, including ISRC | `POST /api/v1/resolve` |
| Queue provider download into a job-specific local directory | `POST /api/v1/downloads` |
| Observe completion/failure | `GET /api/v1/downloads/{id}` |
| Installed provider extensions | `GET /api/v1/extensions` |

Both components run on the same device, so they can share an application-owned
job directory. After completion, Mindinguflac can validate and serve the saved
file through its existing local range/stream endpoints. Mornye's API does not
provide an audio-stream/file-transfer endpoint and deliberately omits file paths
from download history; do not infer a remote playable URL from a completed job.

The stable v1 surface currently has no artist-profile or lyrics endpoints, and
its search response contains tracks only. Keep those uncovered features behind
a small, isolated adapter using public Mornye SDK methods until upstream adds
matching REST endpoints. Do not replace them with undocumented GUI RPC calls
and then describe the whole integration as versioned REST.

Android needs real API dependencies: the existing small Pydantic stand-in is
insufficient for FastAPI. Package a matching native `pydantic-core` Android arm64
wheel with real Pydantic, FastAPI and Uvicorn, and verify service startup on
Android. Upstream's web entry point also imports pywebview: assess this desktop
GUI dependency for a headless Android entry point. JavaScript provider extensions
still require Node.js; using HTTP does not remove dependencies from the embedded
server. Python extensions remain the first Android runtime to assess.

## SDK adapter and packaging changes

- Pin the selected Mornye commit in requirements and desktop build scripts.
- Route covered metadata calls through REST. For the uncovered artist/lyrics
  features, replace old imports inside the isolated SDK adapter with Mornye
  public equivalents; retain ISRC persistence.
- Replace provider orchestration in `backend_spotiflac.py` with the REST client.
  Replace old service names with IDs of installed extensions (`ext:<id>`), and
  derive availability and fallback order from installed extensions.
- Remove old downloader metadata injection and progress monkeypatches from the
  active download path. Poll REST jobs and retain the original selection as
  provenance alongside the actual downloaded file metadata.
- Configure `MORNYE_DATA_DIR`, `MORNYE_CACHE_DIR`, `MORNYE_EXT_DIR` and the download
  directory to writable application-managed locations before importing Mornye.
  Replace the old frozen endpoint-cache runtime hook; upstream does not migrate
  previous state automatically.
- Preserve Mindinguflac's library, playlists, queue and quality-reuse policy.
  Mornye should supply metadata/provider downloads, rather than replace our app UI.
- Collect Mornye and the chosen extension runtime/dependencies in macOS and
  Windows bundles. Document the exact extension source and pinned versions.

## Android

Vendor the pinned Mornye source in place of the old SpotiFLAC package and verify
imports with the phone's actual dependency set, including our Pydantic stand-in.
A successful desktop import does not validate the Android package.

Python extensions execute in-process, making them the first runtime to assess on
Chaquopy. JavaScript extensions require a Node.js bridge; this Android app does
not currently package that runtime. Check each chosen extension's native and
browser dependencies before enabling it on Android.

## Verification before switching

1. Confirm installed extension IDs, supported qualities and fallback behavior.
2. Exercise Spotify track, album, playlist and lyrics metadata with ISRC preserved.
3. Verify a real provider transfer, cancellation, progress and file metadata.
4. Confirm equal/better saved files are reused and lower-quality files upgrade.
5. Build frozen arm64 macOS and Android packages, inspect their contents, then
   test Android buffering controls and extension downloads on a physical device.

The upstream public metadata/downloader imports and `run_async` signature were
smoke-tested from the pinned source in the current desktop environment. No
extension was installed and no Mornye provider download was claimed as tested.

References:
- https://github.com/mornyeapp/Mornye-Python/blob/main/docs/guide/migration.md
- https://github.com/mornyeapp/Mornye-Python/blob/main/docs/guide/extensions.md
- https://github.com/mornyeapp/Mornye-Python/blob/main/docs/guide/api-reference.md
- https://github.com/mornyeapp/Mornye-Python/blob/main/docs/guide/rest-api.md
