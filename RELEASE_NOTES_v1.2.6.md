# Mindinguflac v1.2.6

This release upgrades Mindinguflac from SpotiFLAC 1.6.0 to SpotiFLAC 3.7.0 at upstream commit `902bf67bc02819af4e10a2bf32cd1cd60dada353` and adapts the desktop app to SpotiFLAC's extension-first provider architecture.

- Moves all Spotify metadata integration to `SpotiFLAC.core.spotify_metadata`, preserving Spotify track, album, and artist IDs as well as Mindinguflac's stored ISRC and cross-service identifiers.
- Updates the download-stream integration for SpotiFLAC's resumable `.part` downloads without changing Mindinguflac's per-provider fallback and validation logic.
- Maps the existing Tidal, Qobuz, Amazon, Deezer, SoundCloud, and YouTube selections to installed SpotiFLAC extensions. SpotiFLAC 3.7.0 no longer bundles download providers, so a trusted extension must be installed under `~/.spotiflac/extensions`.
- Keeps Torrent fully independent from SpotiFLAC. Torrent source parsing, shared libtorrent sessions, job reference handling, and provider selection are unchanged.
- Updates the frozen-app endpoint cache redirect for SpotiFLAC 3.7.0's new cache location, keeping writes outside the signed application bundle.
- Updates the Settings version label, HTTP server header, backend user-agent, release helper, and macOS About/bundle metadata to 1.2.6.
- Rebuilds the Apple Silicon macOS desktop app with the SpotiFLAC extension bridge and provider runtime included.
- Shows an actionable login notification when the YouTube engine cannot find signed-in browser cookies. It opens YouTube in the system default browser and retries the same failed track after the user returns to Mindinguflac on macOS or Windows.
- Uses a native operating-system notification for that YouTube alert. macOS requests permission when Mindinguflac first opens, with the in-app Log in action retained as a fallback.
- Adds Codex as a third AI advisor. Selecting it opens the system default browser for PKCE login; authentication stays isolated from the rest of the OpenAI SDK and no token is exposed through Mindinguflac's local API.
- Removes the obsolete Qobuz user-token preference while keeping Qobuz downloads available through the installed SpotiFLAC extension.
- Consolidates duplicate Duck.ai/Gemini worker management, removes dead chat/debug paths, honors the selected AI provider without cross-provider fallback, and applies the saved advisor settings to video matching.
- Restricts browser-callable desktop actions to the app's own loopback origin and port.
- Restores missing album release years in album heroes and saved/favorite album rows, including older entries without a stored release ID.
- Keeps the Dock command synchronized as **Pause** during playback and **Play** while paused, for both native and browser audio paths.
- Restores the last selected song and exact saved timestamp after relaunch, paused and ready to continue.

The complete reviewed registry set is installed locally, including Tidal, Qobuz, Amazon, Deezer, Apple Music, SoundCloud, YouTube Music, Pandora, and Spotify Web extensions.
