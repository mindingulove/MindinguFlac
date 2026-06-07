# Mindinguflac v1.0.0

First stable release of the current Mindinguflac desktop experience. This release moves beyond the 0.9 preview line with a full tour-discovery system, richer sidebar context, stronger queue behavior, and more reliable metadata/download handling.

## Highlights

### Tour Discovery
- Added live artist tour lookup with a Settings toggle for **AI** or **Hypebot**.
- Hypebot mode fetches artist pages, follows matched artist URLs, extracts Bandsintown/Hypebot JSON-LD concert data, and falls back to the selected AI provider when Hypebot cannot find a reliable artist or result.
- AI tour lookup supports both **Gemini** and **DuckDuckGo/Duck.ai** backends through the existing AI provider setting.
- Added exact-name matching first, stricter fuzzy matching second, and safeguards against partial-name false matches.
- Added a direct Hypebot URL payload path so known artist URLs can be used without searching.
- Tour cache now stores timestamps, expiry metadata, Hypebot URLs, and stale/refresh flags so cached tour data renews correctly after 12 hours, even if the app was closed.
- Added a backfill utility for existing tour cache rows.

### Tour Page and Sidebar
- Added a full artist tour page with local "near me" grouping, other-country sections, event links, and live refresh.
- Sidebar tour cards now show cached results immediately, display no-tour messages instead of spinning forever, and only refresh when the cache is stale or missing.
- Tour hero images now use automatic contrast blending so large artist names remain readable over mixed light/dark backgrounds.
- Added better artist image selection for tour pages.

### Queue and Playback Experience
- Improved queue behavior around next/previous navigation and queue wrap-around.
- Added richer queue/sidebar overlays and better queue context handling.
- Improved prefetch and cancellation behavior so upcoming tracks are prepared without stale jobs fighting current playback.
- Hardened native playback handoff and macOS device behavior from the 0.9 line.

### Metadata, Downloads, and Reliability
- Added track credit caching and improved sidebar metadata loading.
- Hardened Spotify artist-about lookup with longer timeouts, retries, and cache fallback.
- Improved cache directory handling so unwritable/root-owned cache folders fall back to a writable runtime cache.
- Continued torrent/YTP-DL matching improvements from the 0.9 line, including safer scoring, DRM/noisy-result rejection, and provider fallback behavior.
- Added cleaner shutdown handling for browser-backed AI workers.

### Settings
- Added a **Tour source** setting with **AI** and **Hypebot** options.
- Kept AI provider selection independent, so Hypebot can use the currently selected AI provider as fallback.
- Included both Gemini and DuckDuckGo/Duck.ai AI backends in the release notes and supported tour fallback path.

## Assets

- `Mindinguflac-macos-arm64.zip` - macOS Apple Silicon desktop build.

## Previous v0.9 line

The v0.9 releases introduced the stronger fallback/download stack, Duck.ai/Gemini advisor work, cache cleanup, Spotify metadata fixes, and macOS native playback improvements that this v1.0.0 release builds on.
