# Mindinguflac v1.2.7

This patch fixes the YouTube browser-login handoff in packaged desktop apps.

- Imports a signed-in YouTube browser session into Mindinguflac's private application data directory, allowing yt-dlp to reuse it for the current and later downloads.
- Checks the imported session from the local desktop UI after opening YouTube and automatically retries the failed download as soon as the user is signed in.
- Avoids relying on macOS browser focus/return events, which are not delivered reliably to the packaged webview.
- Stores imported browser cookies with owner-only permissions and excludes them from source control and release assets.
- Updates the Settings label, HTTP server header, backend user-agent, macOS bundle metadata, and release helper to version 1.2.7.
