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
- Python 3.10 available at `/opt/homebrew/bin/python3.10`

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

## On-device AI ranking

The Android build keeps the desktop ranking workflow in the Python backend,
but replaces desktop-only providers with this order:

1. Gemini Nano through Android AICore and ML Kit Prompt API.
2. A local Gemma MediaPipe `.task` bundle selected from the app's model picker.
3. The deterministic Python ranker, which is always available offline.

Ranking only *reorders* candidates that already passed deterministic and
RapidFuzz filtering; it cannot introduce a candidate the filter rejected, and
no Android path reaches a cloud provider. Open Settings to inspect the
on-device model status. There is no separate AI Advisor tab. If Nano is
supported but not downloaded, the app requests its AICore feature download.
For the second stage, choose **Install local Gemma model** and select a
compatible MediaPipe task bundle. The model is copied into private app storage;
no API key is stored or transmitted.

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
python3.10 tools/audit_android_imports.py /tmp/mf-stage app/python-wheels /tmp/manifest.json

# 3. Start the real embedded backend and exercise the HTTP API end to end
#    (capability report, settings persistence, search/artist/album/lyrics/
#    artwork, download jobs, cancellation, prefetch, range streaming).
python3.10 tools/verify_android_runtime.py /tmp/mf-stage /tmp/mf-device /tmp/verify.json

# 4. Prove the required runtime is inside a built APK.
python3 tools/inspect_apk.py app/build/outputs/apk/debug/app-debug.apk
```

Step 2 and 3 need a Python 3.10 interpreter with
`app/src/main/python/android-requirements.txt` installed, so the host package
set matches the APK's. The focused unit tests are
`../test/test_android_runtime.py` (run from the repository root with
`PYTHONPATH=. python test/test_android_runtime.py`).

### Results, 2026-10-09 (macOS arm64 host, no phone attached)

- `test/test_android_runtime.py`: 55/55 pass.
- `tools/audit_android_imports.py`: every module in the Android backend
  surface imports, no failures.
- `tools/verify_android_runtime.py`: 21/21 pass against the live network —
  including search (60 results), artist top tracks (23, all with artwork),
  related artists (8), a 14-track album tracklist, lyrics, a real `ytp-dl`
  download reporting byte progress, cancellation, duplicate-job adoption,
  independent prefetch, and `200`/`206`/`416` range responses.
- `tools/inspect_apk.py`: all checks pass for both the debug and release APK.
- `./gradlew :app:assembleDebug` from a clean `build/` and `./gradlew
  :app:assembleRelease`: both succeed; `compileDebugJavaWithJavac` compiles the
  jlibtorrent bridge against the shipped jar.

**Not yet verified:** everything that needs real arm64 hardware — the
jlibtorrent JNI library actually loading, a real FLAC selection and download
over BitTorrent, playback through the WebView, and the on-device Gemini
Nano/Gemma advisors. The capability probe reports the torrent engine as
unavailable off-device rather than pretending otherwise. The visual comparison
against the supplied phone reference screenshots is also outstanding.

## Third-party versions and hashes

Build toolchain: Gradle 8.7, Android Gradle Plugin 8.5.2, Chaquopy 17.0.0,
`compileSdk`/`targetSdk` 35, `minSdk` 26, ABI `arm64-v8a` only, embedded
CPython 3.10, JDK 17.

| Component | Version | SHA-256 |
| --- | --- | --- |
| `jlibtorrent-2.0.12.9.jar` (Java/SWIG bindings) | 2.0.12.9 | `c96316e640397249ecfbbe56c355afef472190b8d47d51a94a03e47eb60c219a` |
| `jlibtorrent-android-arm64-2.0.12.9.jar` (arm64 JNI) | 2.0.12.9 | `8e48600b74a9f497ce2c7e1e6a025ce550f039658baef986ad634298758d5b9d` |
| `lib/arm64-v8a/libjlibtorrent-2.0.12.9.so` as packaged | 2.0.12.9 | `56b23c87f1b1b9acba37eccab31d7a055543c3b3dbb8fec4c04e04234f9237cd` |
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
`typing-extensions 4.16.0`, `cryptography 42.0.8` (with `cffi 1.17.1`,
`pycparser 3.1`, `chaquopy-libffi 3.3`), `Pillow 11.0.0` (with
`chaquopy-libjpeg 1.5.3`, `chaquopy-freetype 2.9.1`),
`pycryptodome 3.21.0`, `urllib3 2.8.0`, `charset-normalizer 3.5.2`,
`idna 3.20`, `certifi 2026.7.22`.

### Built artifacts, 2026-10-09

| APK | Size | SHA-256 |
| --- | --- | --- |
| `app/build/outputs/apk/debug/app-debug.apk` | 61,156,002 bytes | `ca8781956b2668f683f4a9bf4c26f1e0455cfba8582def8b6e44a83c08a8e47d` |
| `app/build/outputs/apk/release/app-release-unsigned.apk` | 55,341,024 bytes | `08ea2021f65da86474b209323d7f1bd999b49dbcb568917b9742aabdd60afed3` |

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
