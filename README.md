# Mindinguflac

A high-performance, private music meta-search and personal streaming platform. Mindinguflac allows users to aggregate metadata from multiple open sources, discover new artists through high-fidelity discography mapping, play audio and music videos, follow synced lyrics, and manage a local media library with a modern, responsive interface.

Built with a Python backend and a Vanilla JS/CSS frontend, it functions as a local web server, a native desktop application for macOS and Windows, and an Android app that embeds the same Python backend on the phone (see [android-app/README.md](android-app/README.md)).

Mindinguflac uses SpotiFLAC `3.9.0` (`a471fdc`) through its extension-first provider API. SpotiFLAC no longer bundles download providers; install the provider extensions you trust under `~/.spotiflac/extensions`. The legacy service selections in Mindinguflac map to their installed extension IDs automatically.

Release history lives in [CHANGELOG.md](CHANGELOG.md).

## Core Philosophy

- **Metadata Centralization**: Aggregates data from MusicBrainz, Discogs, and other open databases to provide a comprehensive view of musical history.
- **Privacy First**: Operates entirely locally. No user accounts, no tracking, and no external subscriptions required.
- **High Fidelity**: Supports FLAC and high-bitrate audio management with automatic quality-tiering.
- **Interoperability**: Seamlessly bridges web technologies with native desktop capabilities (Media Sessions, System Integrations).

## Features

- **Modern UI**: A sleek, dark-themed interface inspired by professional digital audio workstations.
- **Smart Discovery**: Dynamic multi-source search that maps artist discographies across studio albums, compilations, and live recordings.
- **Local Library Management**: Organizes your personal music collection into a structured `Artist/Album/Track` hierarchy.
- **Native Integration**:
  - **macOS**: Full "Now Playing" integration, Touch Bar support, and Media Key handling.
  - **Windows**: Native audio output device selection and silent background processing.
- **Advanced Streaming**: Intelligent buffer management allowing you to listen while your media is being indexed or moved, with stable pause/resume across active-download and cached-file handoffs.
- **Synced Lyrics**: Fetches and displays timed lyrics from multiple providers, with LRCLIB and Amazon included alongside Spotify, Apple, and Musixmatch.
- **Music Video Playback**: Supports video playback and music-video fallback flows with persistent cache records, known-good video overrides, and safe YouTube fallback when a dedicated video source is unavailable.
- **Spotify Playlists**: Import any public Spotify playlist by link — Mindinguflac loads the full track list, artwork, and metadata, then lets you stream or download each track in lossless quality (see the *70s 80s 90s* playlist below).
- **Discogs Integration**: Optionally provide a Discogs personal token in Settings to fetch high-resolution vinyl sleeves, booklet images, and extended metadata for your album galleries.
- **Playlist Engine**: Create local playlists, manage queues, and import metadata from public share links.
- **High-Quality Trackers**: Integrated real-time health monitoring for public metadata swarms to ensure the most reliable connection.
- **Smart Parallel Prefetching**: Automatically downloads the next 5 tracks in your queue in parallel, ensuring instant transitions between songs.
- **Persistent SQLite Engine**: All successfully resolved Torrent magnets, YouTube URLs, video overrides, and enriched metadata (Spotify IDs, ISRCs, MusicBrainz IDs) are now saved in a local SQLite database for instant offline access and to prevent redundant searches.
- **Torrent Safety Filters**: Adult/video vocabulary is stored in the local SQLite database and checked before fuzzy scoring and again after torrent metadata exposes internal file paths. Terms found in the requested track title or album are allowed only for that request; unrelated adult/video terms are still blocked.
- **Optional AI Advisor**: Clean torrent and YouTube candidates can be ranked in parallel by Gemini or DuckDuckGo/Duck.ai. AI never sees candidates blocked by the local adult/video filter and cannot override metadata checks or the "first real byte progress wins" torrent race.
- **Improved YouTube Engine**: Smart quality-scoring and automatic skipping of age-restricted or blocked videos with persistent blacklisting, plus music-video fallback behavior for tracks without a reusable video source.
- **Visual Quality Indicators**: Real-time **HI-RES** and **HQ** badges in the player sidebar indicating the actual audio fidelity being streamed.
- **Rich Now Playing Sidebar**: Spotify-style right rail with artwork, quality badges, related music, artist information, credits, tour dates, and the next queue item.
- **Live Tour Dates**: A dedicated Spotify-style "All events" page lists an artist's upcoming concerts (venue, city, date, time, price), fetched via Hypebot/Bandsintown or the selected AI backend and cached locally with 12-hour renewal metadata.

## Screenshots

### Desktop

<p align="center">
  <img src="docs/screenshots/home.png" width="820" alt="Home">
  <br><i>Home — discovery, recently played, and global charts</i>
</p>

<p align="center">
  <img src="docs/screenshots/artist_detail.png" width="820" alt="Artist detail">
  <br><i>Artist — discography, top tracks, and biography</i>
</p>

<p align="center">
  <img src="docs/screenshots/albums.png" width="820" alt="Albums">
  <br><i>Albums — high-fidelity browsing with Discogs artwork</i>
</p>

<p align="center">
  <img src="docs/screenshots/lyrics.png" width="820" alt="Lyrics">
  <br><i>Lyrics — time-synced, with per-track offset correction</i>
</p>

<p align="center">
  <img src="docs/screenshots/queue.png" width="820" alt="Queue">
  <br><i>Queue — now playing and upcoming tracks, drag to reorder</i>
</p>

<p align="center">
  <img src="docs/screenshots/stats_1.png" width="820" alt="Listening statistics">
  <br><i>Statistics — listening history by period, artist, and genre</i>
</p>

<p align="center">
  <img src="docs/screenshots/settings.png" width="820" alt="Settings">
  <br><i>Settings — download engine, provider, and quality</i>
</p>

### Android

<p align="center">
  <img src="docs/screenshots/mobile/mobile_home.png" width="230" alt="Mobile home">
  <img src="docs/screenshots/mobile/mobile_album.png" width="230" alt="Mobile album">
  <img src="docs/screenshots/mobile/mobile_now_playing.png" width="230" alt="Mobile now playing">
</p>
<p align="center">
  <img src="docs/screenshots/mobile/mobile_library.png" width="230" alt="Mobile library">
  <img src="docs/screenshots/mobile/mobile_track_options.png" width="230" alt="Mobile track options">
</p>
<p align="center">
  <i>Android — home, album, now playing, library, and the track options sheet</i>
</p>

## Setup & Usage


### Prerequisites
- Python 3.12 (the Windows torrent build requires 3.12; `libtorrent` has no 3.13/3.14 wheels)
- FFmpeg (for audio processing)

### Virtual environments (per-OS)

This project is often developed on macOS and built for Windows from the **same
folder** (e.g. a Parallels shared drive). Because a venv contains native,
OS-specific binaries, macOS and Windows must use **separate** virtual
environments so they never overwrite each other:

| OS      | venv location                                   | Created/used by               |
|---------|-------------------------------------------------|-------------------------------|
| macOS   | `venv-macos` (in project folder)                | `run.sh`, `Mindinguflac.spec` |
| Windows | `venv-windows` (in project folder)              | `scripts/build_windows.ps1`   |

The macOS and Windows venvs are both git-ignored. Keep them separate and never
point one OS at the other's venv. Override the Windows location with the
`MINDINGUFLAC_VENV_DIR` environment variable only when needed.

### Setup (macOS)
```bash
python3.12 -m venv venv-macos
source venv-macos/bin/activate
pip install -r requirements.txt
python app.py            # or: ./run.sh (auto-creates venv-macos)
```

### Setup (Windows)
```powershell
# Build the desktop app (uses/creates .\venv-windows automatically):
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1

# Or to run from source, create/use the project venv:
py -3.12 -m venv .\venv-windows
.\venv-windows\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Windows desktop builds are always AMD64/x64, including on Windows-on-ARM or
Parallels. The build script rejects ARM64 Python and, when it can't find a usable
AMD64 interpreter, installs AMD64 Python 3.12 under
`%LOCALAPPDATA%\mindinguflac\python312-amd64` (falling back to the AMD64
`pythonx64` NuGet package under `%LOCALAPPDATA%\mindinguflac\python312-amd64-nuget`
if the python.org installer exits without creating the target interpreter).
Discovery is deliberately minimal: it uses `MINDINGUFLAC_PYTHON` if set, then the
hardcoded user install at
`C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe`, then the
installer-target paths.

> **Windows-on-ARM / Parallels gotcha:** do **not** verify the architecture with
> `platform.machine()` — an AMD64 Python running under x64 emulation prints
> `ARM64` there (it reports the native host arch via `PROCESSOR_ARCHITEW6432`),
> even though the interpreter is genuinely x64. The build script ignores
> `platform.machine()` and reads the real architecture from the `python.exe`
> PE header instead. To check arch yourself, look at the installed-apps entry
> (e.g. "Python 3.12.8 (64-bit)") rather than `platform.machine()`.

The interpreter must also be a full Python install with `venv` available. A
runtime/embedded folder that only has `python.exe`, DLLs, and no standard
library can exist on disk but is not usable for the Windows build.

Open your browser to `http://127.0.0.1:8888`.

### Optional AI advisor

The torrent and YouTube matching engines can use Duck.ai, Gemini, or Codex (GPT-5.4 Mini) as an advisor. Choose the provider in Settings. Codex selection opens the system default browser for login and stores the resulting credentials in `codex-auth`'s private token cache. The advisor is advisory only: deterministic filters, metadata checks, and libtorrent byte-progress still decide what downloads.

The AI receives the top 20 search results based on the local scoring algorithm. It evaluates their titles and metadata and returns a sorted list of the IDs it considers to be clean music matches. The torrent engine then attempts to download the AI's ranked candidates in the order provided (up to however many the AI selected), before falling back to the remaining unscored candidates.

> **Note on browser-backed providers:** Duck.ai and Gemini use long-running Playwright workers that drive their real browser frontends. On first run, the app automatically attempts to fetch the required browser binaries if they are missing. `codex-auth` is an unofficial alpha dependency, so Codex advisor compatibility can change if its upstream service changes.

To disable the advisor, explicitly set `MINDINGUFLAC_AI_RERANK_PROVIDER` to `none`:

```bash
export MINDINGUFLAC_AI_RERANK_PROVIDER=none
./run.sh
```

Alternative OpenAI-compatible local/provider endpoint:

```bash
export MINDINGUFLAC_AI_RERANK_URL="http://127.0.0.1:1234/v1/chat/completions"
export MINDINGUFLAC_AI_RERANK_MODEL="your-model"
./run.sh
```

If the endpoint, network, or service limit is unavailable, the torrent job continues with the local scoring and fallback path.

## TODO

- Spotify-style track suggestions and playlist-end recommendations

## Technical Implementation

- **Backend**: Python (BaseHTTPServer/Threading) optimized for low-latency API responses.
- **Frontend**: Single Page Application (SPA) using Vanilla JavaScript and CSS variables for theme management.
- **Desktop Wrapper**: Powered by `pywebview`, providing a native app feel while maintaining web-standard flexibility.
- **Audio Engine**: Custom native audio manager for Windows and macOS, bypassing browser limitations for high-bitrate playback.
- **Native Output Handoff**: On macOS app-only output devices, active browser streaming is paused when a native device is selected and no completed cache file exists. The player remembers the current position and starts native output from that position when the cache file finishes.

---

*Disclaimer: Mindinguflac is a research-oriented meta-search tool. Users are responsible for ensuring that their use of the platform and any media they index complies with local copyright laws and the terms of service of the metadata providers.*
