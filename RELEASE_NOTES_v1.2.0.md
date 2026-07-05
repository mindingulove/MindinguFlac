# Mindinguflac v1.2.0

### Added
- Expanded synced lyrics support.
- Music video playback: the backend searches eight torrent providers (apibay, knaben, SolidTorrents, 1337x, KickAss, limetorrents, torlock, torrentdownloads) in parallel with a YouTube lookup; whichever returns a valid clip first is used, with YouTube as the automatic fallback when no torrent clip is found. An AI advisor (Duck.ai or Gemini) reranks torrent candidates in parallel before download begins.

### Updated
- SpotiFLAC → 1.3.1.
- Visible Settings footer, backend user-agent, and macOS About/bundle versions now report `1.2.0`.
- Windows build now ships as a single launcher exe. First run shows a native setup window (follows system light/dark theme) with an Unpack button; files are extracted to `%LOCALAPPDATA%\Mindinguflac\app\<version>\` and reused on every subsequent launch. Updating to a new version re-extracts automatically. Desktop and Start Menu shortcuts are offered during setup.

