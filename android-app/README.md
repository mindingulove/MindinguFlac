# Mindinguflac for Android

This is a standalone Android application. The APK embeds the existing Python
backend with Chaquopy and serves the HTML interface only on an authenticated
`127.0.0.1` port inside the app. It does not need the desktop application, a
companion service, Playwright, or an AI API token.

## Requirements

- Android 8.0 (API 26) or newer
- 64-bit ARM device (`arm64-v8a`)
- JDK 17
- Android SDK platform 35
- Python 3.12 available as `python3.12` on PATH. Set `MINDINGUFLAC_BUILD_PYTHON`
  to use another Python 3.12 executable.

## Build and install

```sh
cd android-app
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME="$HOME/Library/Android/sdk"
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Python packages declared in `app/src/main/python/android-requirements.txt` are
installed from `app/python-wheels/` during the build. `./gradlew
:app:assembleRelease` produces a minified, **unsigned** release APK; there is
no signing config in this repository, so sign it yourself before distributing.

## Download engines are offered only when their runtime is present

The phone ships a smaller runtime than the desktop app, so the engine picker is
built from measured capability rather than a hard-coded list.
`android_runtime/capabilities.py` imports every packaged runtime and probes the
jlibtorrent JNI library, the backend serves the result on `/api/runtime`, and
both the settings UI and the download path clamp to it. An engine whose runtime
is missing is shown as unavailable **with the reason**, never silently offered:

| Engine | On the phone | Why |
| --- | --- | --- |
| YouTube audio (`ytp-dl`) | available | `yt-dlp` + `mutagen` are packaged |
| FLAC / BitTorrent (`torrent`) | available once `libjlibtorrent` loads | native arm64 JNI library is in the APK |
| SpotiFLAC (`spotiflac`) | **withheld** | SpotiFLAC 3.9.0 imports and its extension manager works, but its download path needs a provider extension: JavaScript extensions require Node.js (not in the APK) and no Python provider extension is bundled |
| `monochrome`, `qobuz-dlp` | **withheld** | desktop-only runtimes, not packaged |

The engine, service/source and quality the user picks are persisted and survive
a kill/relaunch. Lossy sources are never labelled FLAC: the YouTube engine's
qualities are `best`/`m4a` only, the torrent engine's is `LOSSLESS` only, and
the native bridge selects a lossless file or fails.

## Playback on the phone

Audio plays in the WebView, which the system would otherwise stop the moment
the app leaves the screen. Two pieces keep it alive:

- `MediaPlaybackService` is a `mediaPlayback` foreground service holding a
  `MediaSession`, so the process stays at foreground importance and the track
  gets a notification, lock-screen controls and the system media-button
  session. It never touches audio itself — every control is relayed back to the
  page's own transport, so the page remains the single source of truth.
- `MainActivity` uses a `WebView` subclass that ignores the hidden-window
  notification. Chromium suspends media when the WebView's window goes away,
  and the foreground service alone does not prevent that.

The service holds audio focus but deliberately ignores focus *changes*: the
page's own `<audio>` element requests focus too, so reacting to the resulting
transient loss paused whichever track had just started. Chromium already
handles real interruptions from other apps for its element.

The arm64 JNI library is repacked from the upstream jar as plain
`libjlibtorrent.so`. Under its versioned name jlibtorrent finds it as a
classpath resource — the APK is the classpath root — and extracts a second copy
into writable cache on every cold start, which Android 16 already warns will
throw on a future release. Renaming it makes that lookup miss so
`System.loadLibrary` resolves it read-only from inside the APK instead.

## On-device AI ranking

The Android build keeps the desktop ranking workflow in the Python backend,
but replaces desktop-only providers with this order:

1. Gemini Nano through Android AICore and ML Kit Prompt API.
2. A local model run through MediaPipe's LLM Inference API
   (`LocalModelAdvisor.java`).
3. The deterministic Python ranker, which is always available offline.

Ranking only *reorders* candidates that already passed deterministic and
RapidFuzz filtering; it cannot introduce a candidate the filter rejected, and
no Android path reaches a cloud provider. Open Settings to inspect the
on-device model status. There is no separate AI Advisor tab. If Nano is
supported but not downloaded, the app requests its AICore feature download.

The second stage is Qwen2.5 1.5B Instruct (Apache-2.0, Alibaba), converted by
LiteRT Community — unlike Gemma's official MediaPipe bundle, that conversion
is **not** license-gated, so the app downloads and installs it itself: at
launch, automatically, if nothing is installed yet and the device is on an
unmetered (Wi-Fi) connection, since the bundle is ~1.5 GB. **Download now** in
Settings forces it immediately, including over mobile data. **Install from
file** keeps the old manual flow — pick any compatible MediaPipe `.task`
bundle, for a different model or a retry via a browser download — and shares
the same install slot, so whichever install (automatic or manual) finished
most recently is what ranking uses. No API key or account is ever stored or
transmitted.

## Storage

Cache and downloaded music live under one app-managed root,
`getExternalFilesDir(null)/Mindinguflac/{cache,music}`. The phone never asks
for either path, the manual folder inputs are hidden, and a settings POST that
tries to set them is rewritten back to the managed values.

## Verification

Three tools in `tools/` reproduce the gates outside Gradle.

```sh
# 1. Reproduce the APK's Python import root on the host.
tools/stage_android_sources.sh /tmp/mf-stage

# 2. Import every backend module under the Android env + sys.path layout and
#    print a packaged/imported dependency manifest.
python3.12 tools/audit_android_imports.py /tmp/mf-stage app/python-wheels /tmp/manifest.json

# 3. Start the real embedded backend and exercise the HTTP API end to end
#    (capability report, settings persistence, search/artist/album/lyrics/
#    artwork, download jobs, cancellation, prefetch, range streaming).
python3.12 tools/verify_android_runtime.py /tmp/mf-stage /tmp/mf-device /tmp/verify.json

# 4. Prove the required runtime is inside a built APK.
python3 tools/inspect_apk.py app/build/outputs/apk/debug/app-debug.apk
```

Step 2 and 3 need a Python 3.12 interpreter with
`app/src/main/python/android-requirements.txt` installed, so the host package
set matches the APK's. The focused unit tests are
`../test/test_android_runtime.py` (run from the repository root with
`PYTHONPATH=. python test/test_android_runtime.py`).

### Results, 2026-10-10

Host checks (macOS arm64):

- `test/test_android_runtime.py`: 57/57 pass.
- `tools/audit_android_imports.py`: every module in the Android backend
  surface imports, no failures.
- `tools/verify_android_runtime.py`: 25/25 pass against the live network —
  capability report, settings persistence across two kill/relaunch cycles,
  search, artist top tracks, related artists, album tracklist, a Spotify album
  import that persists, lyrics, a real `ytp-dl` download reporting byte
  progress, cancellation, duplicate-job adoption, independent prefetch, cache
  cleanup, and `200`/`206`/`416` range responses.
- `tools/inspect_apk.py`: all checks pass on both the debug and release APK.
- `./gradlew :app:assembleDebug :app:assembleRelease` from a deleted `build/`,
  `.gradle/` and root `build/`: succeeds in one pass.

Device checks — **Nothing A065 (`Pong`), Android 16, API 36, `arm64-v8a`,
1080x2412 @ 420dpi**, debug build installed fresh over USB:

- Starts clean: authenticated preflight passes, no folder prompt, no Advisor
  tab, zero `FATAL EXCEPTION` entries in logcat.
- jlibtorrent loads read-only from inside the APK
  (`base.apk!/lib/arm64-v8a/libjlibtorrent.so`), reporting jlibtorrent
  2.0.12.9 / libtorrent 2.0.12.0.
- Both engines work: `ytp-dl` plays and advances the queue, and the torrent
  engine selects and downloads a real FLAC through the native bridge.
- Playback survives backgrounding — measured advancing 44s → 69s with the
  launcher in the foreground — with lock-screen and notification transport
  controls, and the app holding the system media-button session.
- The local Gemma bundle ranks real candidates: the cache log records
  `YouTube AI advisor ranked 5 candidates first`, i.e. it beat the
  deterministic selector rather than timing out.
- Settings, the imported playlist and the managed storage root all survive a
  kill/relaunch.

**Not verified:** the visual comparison against the project's phone reference
screenshots, which are not in the repository, and the screen-size, orientation
and dark-mode matrix — everything above is one phone in portrait.

## Third-party versions and hashes

Build toolchain: Gradle 8.7, Android Gradle Plugin 8.5.2, Chaquopy 17.0.0,
`compileSdk`/`targetSdk` 35, `minSdk` 26, ABI `arm64-v8a` only, embedded
CPython 3.12, JDK 17.

| Component | Version | SHA-256 |
| --- | --- | --- |
| `jlibtorrent-2.0.12.9.jar` (Java/SWIG bindings) | 2.0.12.9 | `c96316e640397249ecfbbe56c355afef472190b8d47d51a94a03e47eb60c219a` |
| `jlibtorrent-android-arm64-2.0.12.9.jar` (arm64 JNI) | 2.0.12.9 | `8e48600b74a9f497ce2c7e1e6a025ce550f039658baef986ad634298758d5b9d` |
| `lib/arm64-v8a/libjlibtorrent.so` as packaged | 2.0.12.9 | `56b23c87f1b1b9acba37eccab31d7a055543c3b3dbb8fec4c04e04234f9237cd` |
| `com.google.mlkit:genai-prompt` | 1.0.0-beta4 | resolved from Google's Maven repository |
| `com.google.mediapipe:tasks-genai` | 0.10.21 | resolved from Google's Maven repository |

Vendored Python source (embedded in the APK rather than installed as a wheel):

| Package | Version | Why it is vendored |
| --- | --- | --- |
| SpotiFLAC | 3.9.0, upstream commit `a471fdc` | the wheel would force desktop-only `pywebview` and `pydoll` onto Android |
| RapidFuzz | 3.14.6, pure-Python implementation | no Android wheel for the native extension; `RAPIDFUZZ_IMPLEMENTATION=python` forces the Python backend |
| `pydantic` | compatibility surface, not upstream | Pydantic v2 needs the Rust `pydantic-core`, for which there is no Chaquopy wheel |

Bundled wheels are in `app/python-wheels/` with their SHA-256 sums in
`app/python-wheels/SHA256SUMS`; verify them with
`shasum -a 256 -c app/python-wheels/SHA256SUMS` from the repository root. The
pinned set is: `yt-dlp 2026.8.19`, `requests 2.34.2`, `mutagen 1.48.1`,
`PySocks 1.7.1`, `httpx 0.28.1` (with `h2 4.4.1`, `hpack 4.2.0`,
`hyperframe 6.1.0`, `httpcore 1.0.9`, `h11 0.16.0`, `socksio 1.0.0`,
`anyio 4.15.1`, `sniffio 1.3.1`, `exceptiongroup 1.3.1`), `aiofiles 25.1.0`,
`tenacity 9.2.1`, `tqdm 4.70.1`, `packaging 26.2`, `python-dotenv 1.2.4`,
`typing-extensions 4.16.0`, `cryptography 50.0.2` (with `cffi 2.0.0`,
`pycparser 3.1`, statically linked OpenSSL 3.5.9), `Pillow 12.3.0` (with
`chaquopy-libjpeg 1.5.3`, `chaquopy-freetype 2.9.1`),
`pycryptodome 3.21.0`, `urllib3 2.8.0`, `charset-normalizer 3.5.2`,
`idna 3.20`, `certifi 2026.7.22`.

The Python 3.12 CFFI 2.0.0 wheel comes from
https://pypi.flet.dev/cffi/; its published SHA-256 was checked on download.
The Python 3.12 pycryptodome wheel comes from https://chaquo.com/pypi-13.1/.
Cryptography 50.0.2 and Pillow 12.3.0 are built locally using Chaquopy commit
`75197ed5c8280c38881af0e03fede591f1abc11e`, Android NDK 27.3.13750724 and
API 24. Cryptography uses static OpenSSL 3.5.9 LTS built with
`scripts/build_android_openssl.sh`; its source checksum is pinned in that
script. The reproducible build steps are in
`.github/workflows/android-security-wheels.yml`. Runtime verification uses
`/api/runtime`, including native CFFI/Pillow imports and the loaded OpenSSL
version. The Python 3.12 runtime trial was tested on the physical phone through ADB.
The patched dependency build passed APK packaging checks; its device runtime
check is pending because the phone disconnected before installation.

### Built artifacts, 2026-10-11

Produced by a clean `./gradlew :app:assembleDebug :app:assembleRelease`.

| APK | Size | SHA-256 |
| --- | --- | --- |
| `app/build/outputs/apk/debug/app-debug.apk` | 86,591,856 bytes | `6c3ac4f287eb6aff8b6274b011e209b363539db7eba91bdbfde0ae53f65c681a` |
| `app/build/outputs/apk/release/app-release-unsigned.apk` | 66,093,477 bytes | `0f4f85955d525bfac168ec2b06c74513238536ff30ad310d4b85de595d259b6e` |

The release APK is unsigned: there is no signing config in this repository, so
sign it before distributing.

## Local development notes

The build installs Python dependencies from the bundled, hash-recorded wheel
directory with `--no-index`, so it is offline and reproducible.
`MINDINGUFLAC_ANDROID_WHEELS` can point to an additional trusted local wheel
directory.

`app/proguard-rules.pro` matters more than usual here: every Java class the
Python backend touches is reached reflectively through
`java.jclass("com.mindinguflac.android...")`, and jlibtorrent's SWIG layer
registers its natives by fully-qualified name. Without those keep rules a
minified release build strips or renames exactly the classes the backend needs,
and the failure only shows up on the phone.
