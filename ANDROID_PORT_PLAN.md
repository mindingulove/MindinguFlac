# Mindinguflac Android Port Plan

Status: active implementation. The Android port is not complete until every
required runtime below is present in the APK and the device verification gates
pass. A successful Gradle compile by itself is not completion.

Last verification pass: 2026-10-09 on a macOS arm64 host with **no Android
device attached**. Everything that can be proved without hardware is now
proved and ticked; everything that needs an arm64 phone is still open and is
listed under "Outstanding" at the end. See `android-app/README.md` for the
reproducible commands and the recorded results.

## Product requirements

- Keep the phone interface Spotify-like: Home, Search, Your Library, artist,
  album/playlist, now-playing, lyrics, related music, events, merch, credits,
  settings, queue, and the persistent mini-player/bottom navigation.
- Use the original Mindinguflac logo and artwork assets.
- Do not add an AI Advisor tab. The advisor is an internal backend ranking step.
- Run the application backend locally on the phone with Python and serve the
  HTML/CSS/JavaScript UI through an authenticated loopback WebView session.
- Do not require Playwright, Chromium, Duck.ai, cloud Gemini, or Codex on the
  phone.
- Android advisor order: Gemini Nano/AICore, then an imported local Gemma model,
  then deterministic ranking. AI may reorder candidates but must not bypass
  content, identity, file-type, or audio validation.
- Keep cache and downloaded music under one app-managed Mindinguflac storage
  root. Do not ask the user to type either folder.
- Show and persist the selected download engine, service/source, and quality.
- Never label YouTube/AAC output as FLAC. FLAC selection must use a real
  lossless source and pass FLAC/audio validation.

## Required Android runtime

- [x] Embedded CPython backend with the existing Mindinguflac application
  modules and authenticated `127.0.0.1` HTTP API.
- [x] Package and import-test SpotiFLAC 3.9.0 (`a471fdc`) because Spotify
  metadata, music search, artist/album/playlist discovery, lyrics/enrichment,
  and the SpotiFLAC download path depend on it. — 169 files packaged in the
  APK; imports under the Android env; search, artist, album, playlist import,
  lyrics and artwork verified live against it.
- [x] Package SpotiFLAC's Android-compatible runtime dependencies. Desktop-only
  `pywebview` and browser automation must be replaced or guarded on Android;
  they must not make `import SpotiFLAC` fail. — all 31 wheels now install
  (needed `chaquopy-libffi 3.3`, which was missing and broke the build);
  `pydantic` is a pure-Python stand-in; the APK is confirmed free of
  `pywebview`, `pydoll`, Playwright and the desktop `libtorrent` wheel.
- [x] Package and import-test RapidFuzz for the existing fuzzy artist/title/
  album matching paths. Deterministic matching remains mandatory even when the
  on-device AI advisor is available. — RapidFuzz 3.14.6 full source
  distribution, pure-Python backend. Fixed two bugs that defeated this: the
  bootstrap prepended a four-function `compat` shim that shadowed the real
  package (breaking `rapidfuzz.process`/`rapidfuzz.distance`), and
  `backend_torrent` set `rapidfuzz = None` on Android.
- [x] Add jlibtorrent 2.0.12.9 Java bindings and the official ARM64 Android JNI
  library to the APK.
- [x] Add an Android jlibtorrent bridge which fetches magnet metadata, examines
  torrent files, selects the matching lossless track, prioritizes that file,
  and reports real byte/peer progress to the Python job manager.
- [ ] Compile and device-test the jlibtorrent bridge, including native library
  loading on an ARM64 phone and a real FLAC selection/download. — **compile
  done**: `compileDebugJavaWithJavac` builds the bridge against the shipped
  jar, every jlibtorrent API it calls is confirmed present by `javap`, and
  `lib/arm64-v8a/libjlibtorrent-2.0.12.9.so` (13,384,864 bytes) is in both
  APKs. The bridge's JSON contract and job loop are covered by unit tests with
  a fake engine. **Device test still outstanding.**
- [x] Package yt-dlp, Requests, PySocks, and Mutagen for the Android-compatible
  YouTube fallback path.
- [x] Audit every imported backend module and produce a packaged/imported
  dependency manifest; no backend option may be exposed if its runtime is
  absent. — `android_runtime/capabilities.py` imports all 17 packaged runtimes
  and probes the jlibtorrent JNI library; served on `/api/runtime`; the UI
  builds its engine picker from it and the download path clamps to it.
  `android-app/tools/audit_android_imports.py` reproduces the manifest.

## Backend wiring

- [x] Start the real local Python server before loading the WebView and perform
  authenticated health/settings preflight checks.
- [x] Wire `/api/service/download` to the actual service download manager and
  `/api/library/stream` to byte-range audio responses.
- [x] Keep the desktop torrent implementation unchanged while routing Android
  torrent jobs to the native jlibtorrent bridge instead of a CPython desktop
  `libtorrent` wheel.
- [x] Allow Android settings to select either YouTube audio or FLAC/BitTorrent;
  persist the corresponding source and quality instead of forcibly rewriting
  every request to YouTube/M4A. — fixed a frontend boot check that still
  required exactly `ytp-dl/youtube/m4a` and therefore made a saved torrent
  selection fail to start.
- [x] Enable the SpotiFLAC engine on Android only after the package, its provider
  extension mechanism, and its non-browser provider path pass runtime tests. —
  tested: the package imports and `ExtensionManager` works, but the non-browser
  provider path does **not** pass, because JavaScript extensions need Node.js
  (not in the APK) and no Python provider extension is bundled. The engine is
  therefore withheld, with that reason shown in Settings, and a request naming
  it is clamped server-side.
- [x] Verify music search, track/album/artist metadata, playlist import, related
  music, lyrics, and artwork against the embedded SpotiFLAC runtime. — live:
  60 search results, 23 artist top tracks all with artwork, 8 related artists,
  a 14-track album tracklist, a 14-track Spotify album import that persists,
  lyrics endpoint answering, artwork URLs on search results. (Noted: album
  metadata returned `year=None` for this release; the tracklist and artwork
  are fine.)
- [x] Verify deterministic and RapidFuzz filtering before on-device AI ranking,
  and validate Nano -> local Gemma -> deterministic fallback behavior. — the
  deterministic filter rejects video releases, non-audio categories and wrong
  artists before ranking; the advisor cannot introduce a candidate the filter
  rejected; Nano wins when it answers, Gemma when Nano is silent, the
  deterministic ranker when neither is, and no Android path reaches a cloud
  provider. The real Nano/Gemma models themselves need a device.
- [x] Verify cancellation, cache cleanup, interrupted-job recovery, duplicate
  jobs, and prefetch behavior for both YouTube and torrent engines. —
  cancellation, cache cleanup (stray partials removed, managed root kept),
  duplicate-job adoption, independent prefetch and Activity-reopen job-pool
  integrity verified live on the YouTube engine; interrupted-job recovery
  after real process death covered by unit tests on
  `ServiceDownloadManager._load_jobs`; the torrent engine's job loop
  (stall -> next candidate, failed start -> skip, cancel, missing file) is
  covered by unit tests against a fake native engine. Torrent behaviour on a
  live swarm needs a device.

## Interface and settings

- [x] Remove the separate Advisor navigation/tab and remove phone access to old
  Duck.ai, cloud Gemini, and Codex advisor settings.
- [x] Keep Home, Search, and Your Library as the phone's primary navigation.
- [x] Hide manual cache/music directory inputs on Android while retaining their
  app-managed backend values. — a settings POST that tries to set either is
  also rewritten back to the managed path, verified live.
- [x] Restore download engine, service/source, and quality controls for the
  supported Android engines. — the lists are now generated from the measured
  capability report, so desktop-only sources (`piratebay`, `yts`) and a lossy
  `MP3` quality for BitTorrent are no longer offered, and unavailable engines
  are listed with the reason rather than silently dropped.
- [x] Use the original Mindinguflac logo as the Android application icon.
- [ ] Complete visual comparison of all supplied phone references: spacing,
  typography, cards, lists, artist/profile details, now playing, lyrics,
  library filters, mini-player, and safe-area handling. — **blocked**: the
  reference screenshots are not in the repository (`docs/screenshots/` holds
  desktop captures only). They need to be supplied again.
- [ ] Test small/large phones, portrait/landscape, dark mode, status/navigation
  bars, scrolling, keyboard, back navigation, and external-link handling.

## Verification gates

- [x] Python compile and focused unit tests pass for Android configuration,
  backend routing, search/ranking, download jobs, and audio streaming. —
  `test/test_android_runtime.py`, 57/57 pass; `compileall` clean. Fixed a real
  bug it caught: the `416 Range Not Satisfiable` response carried no
  `Content-Length`, so a keep-alive player hung on the socket instead of
  seeing the error.
- [x] Java compilation and `assembleDebug` pass from a clean Android build. —
  also `assembleRelease`, which needed new ProGuard keep rules: R8 was
  stripping/renaming `AndroidTorrentEngine`, the advisors and jlibtorrent's
  SWIG layer, all of which are reached only reflectively or by JNI name.
- [x] APK inspection proves the SpotiFLAC, RapidFuzz, yt-dlp, Requests, Mutagen,
  Python runtime, jlibtorrent Java classes, and ARM64 `libjlibtorrent` binary are
  present. — `android-app/tools/inspect_apk.py`, all checks pass on both the
  debug and release APK.
- [ ] A fresh install starts without desktop-only imports, folder prompts, or an
  Advisor tab. — the three components are individually verified off-device
  (the import audit shows no desktop-only module loads; the settings view
  hides both folder inputs and rewrites any attempt to set them; the mobile
  navigation is Home/Search/Library only and the desktop advisor rows are
  CSS-hidden). Starting a fresh install still needs a device.
- [ ] On an ARM64 Android device: search returns music, artist/album/playlist
  pages load, YouTube audio plays, a selected FLAC is chosen by filename and
  metadata, torrent bytes advance, and the resulting FLAC plays through the
  range-stream endpoint. — the backend halves of these pass against the real
  embedded server on the host (search/artist/album/playlist, a `ytp-dl`
  download advancing real bytes, `200`/`206`/`416` range responses). WebView
  playback and the torrent half need a device.
- [x] Kill/relaunch retains settings and library data under the single managed
  storage root. — verified against the real backend: engine, service, quality,
  the imported playlist and both managed directories survive two
  stop/start cycles.
- [x] Offline/error cases show actionable UI errors instead of "no sound" or an
  empty result with no explanation. — a missing file is a `404` with a reason,
  a bad range is a `416` with the real size (was a hung socket), an engine
  whose runtime is absent is listed in Settings with the reason, and a failing
  advisor logs "Using deterministic FLAC ranking (...)" to the cache log
  rather than failing the job.

## Delivery

- [x] Record exact third-party versions and hashes in the Android README. —
  toolchain, jlibtorrent jars and the packaged `.so`, ML Kit/MediaPipe, the
  vendored Python sources, and all 32 bundled wheels with `SHA256SUMS`
  (verified with `shasum -a 256 -c`).
- [x] Produce the final debug/release APK and its SHA-256. — debug
  `ca8781956b2668f683f4a9bf4c26f1e0455cfba8582def8b6e44a83c08a8e47d`
  (61,156,002 bytes); release, unsigned,
  `08ea2021f65da86474b209323d7f1bd999b49dbcb568917b9742aabdd60afed3`
  (55,341,024 bytes). There is no signing config in the repository, so the
  release APK must be signed before distribution.
- [ ] Report device/API/ABI tested, engines tested, and any feature that remains
  unavailable. Do not describe the port as complete while a required gate above
  is unchecked.

## Outstanding

Everything still unchecked needs one of two things this pass could not supply.

**An ARM64 Android device or emulator image** (no device was attached and no
emulator system image is installed in the SDK):

- jlibtorrent JNI library loading and a real FLAC selection/download.
- Fresh-install startup, WebView playback, and the on-device Gemini
  Nano/Gemma advisors.
- The screen-size, orientation, dark-mode, system-bar, keyboard,
  back-navigation and external-link matrix.
- The final device/API/ABI report.

**The supplied phone reference screenshots**, which are not in the repository:

- The visual comparison of spacing, typography, cards, lists, artist/profile
  details, now playing, lyrics, library filters, mini-player and safe-area
  handling.
