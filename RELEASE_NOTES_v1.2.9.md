# Mindinguflac v1.2.9

This release hardens Windows first-run extraction and fixes reserved device-name handling in bundled dependency data.

- Sanitizes every embedded ZIP path component before extraction, including Windows-reserved names such as `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, and `LPT1`–`LPT9`.
- Builds `bundle.zip` with portable forward-slash paths and verifies the finished archive before packaging the launcher.
- Preserves Cornwall's real `GB-CON` state code while reading its city data from the Windows-safe `_CON` directory.
- Rejects absolute paths and parent-directory traversal in the embedded archive.
- Aligns the Windows build's forced SpotiFLAC install with the pinned 3.9.0 commit used by the other desktop builds.
- Adds focused regression coverage for packaging, extraction, path traversal, and the Cornwall data fallback.
