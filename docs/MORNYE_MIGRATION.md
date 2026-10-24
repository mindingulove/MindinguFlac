# Replacing SpotiFLAC with Mornye

Assessed upstream commit `297c780c3e7bcd9dffab65a65f8b1bc686da238b`
(package version 1.0.4) on 2026-10-24. This document describes the migration;
the current application still uses its pinned SpotiFLAC dependency.

Mornye's core includes metadata resolution, but no download providers or default
extension registry. A provider extension source must be selected before replacing
the existing downloader. An unconfigured replacement would remove working
Tidal/Qobuz/etc. support. Monochrome, YouTube and torrent backends are independent.

## Application changes

- Pin the selected Mornye commit in requirements and desktop build scripts.
- Replace `SpotiFLAC.core.spotify_metadata.SpotifyMetadataClient` imports with
  `mornye.core.spotify_metadata.SpotifyMetadataClient`. Its async metadata API
  remains available; retain our sync/async bridge and ISRC persistence.
- Adapt `backend_spotiflac.py` to `mornye.downloader.DownloadOptions` and
  `MornyeDownloader`. The `run_async(input_url)` method remains available.
  Replace old service names with IDs of installed extensions (`ext:<id>`), and
  derive availability and fallback order from installed extensions.
- Review the metadata injection and progress hooks against
  `mornye.application.download_engine`; the `mornye.downloader` module is now a
  compatibility facade. Do not assume old module monkeypatches still apply.
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
