# Mindinguflac v1.2.4

This release improves YouTube fallback reliability when YouTube asks the downloader to sign in and confirm it is not a bot.

- Automatically uses a signed-in Safari session on macOS, falling back to Chrome when Safari has no usable YouTube login.
- Automatically uses a signed-in Edge session on Windows, falling back to Chrome when Edge has no usable YouTube login.
- Does not require manually exporting or maintaining a `cookies.txt` file for normal desktop use.
- Shows the browser selected for YouTube authentication in the cache log.
- Includes the SpotiFLAC download module update to version 1.5.2.
- macOS (Apple Silicon and Intel) and Windows desktop builds are included.
