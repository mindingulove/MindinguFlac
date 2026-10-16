# Mindinguflac v1.3.1

## Fixed
- Album pages load their tracks before optional artwork and metadata lookups, preventing the “Fetch is aborted” error. Slow artwork services no longer prevent opening an album.
- YouTube sign-in on desktop: open the dedicated sign-in window directly, keep Google/YouTube redirects inside the app, and save the session only after sign-in succeeds.
- YouTube Sign out on Windows: clear the app-owned session using the supported WebView2 cookie API.
- Android installation: replace the unsigned APK with a signed, verified APK that Android can install.
- Settings now displays version **1.3.1** on desktop and Android; Android versionCode is **4**.

## Android download
Download **Mindinguflac-android-arm64-v1.3.1-build4.apk** below. This explicit build filename avoids confusion with earlier downloads saved under the original v1.3.1 filename. Requires Android 8.0 or newer and a 64-bit ARM device (`arm64-v8a`). The `.apk.sha256` file contains its SHA-256 checksum. The APK uses the same signing certificate as the previous local Android builds, so those installations can update in place.
