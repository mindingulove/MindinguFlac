# Mindinguflac v1.4.2

## Added
- Optional volume normalization in Playback settings, with adaptive level matching for browser and native playback on desktop and Android. The preference is saved; music files are unchanged.
- Android: open Spotify links (or Share > Mindinguflac) straight into the running app.
- Android: track progress on the Glyph lights of Nothing phones, and music controls in Google Maps.

## Fixed
- YouTube downloads failed for every song with "The page needs to be reloaded" when signed in to YouTube. yt-dlp is updated to 2026.11.23 on desktop and Android, and that error now also triggers the retry without the YouTube session.
