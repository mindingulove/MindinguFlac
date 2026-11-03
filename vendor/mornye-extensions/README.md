# Bundled Mornye provider extensions

Unmodified Mornye extensions (JavaScript), shipped in the Android APK so the
Mornye engine works on a fresh install. `android_runtime/mornye_android.py`
copies each into Mornye's extension directory at startup when it is missing
or older than the installed copy; a newer installed copy is left alone.

Source: the Mornye project, https://github.com/mornyeapp/Mornye (formerly
zarzet/SpotiFLAC-Mobile), licensed LGPL-3.0. `spotify-web` comes from
https://github.com/zarzet/spotify-web. Versions are in each `manifest.json`.

To update: install or update the extensions in the desktop app, then copy
`~/Library/Application Support/Mindinguflac/mornye/extensions/` here.
