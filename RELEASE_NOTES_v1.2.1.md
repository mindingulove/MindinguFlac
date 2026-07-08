# Mindinguflac v1.2.1

This release focuses on download reliability and packaged macOS stability.

## Fixed

- Fixed SpotiFLAC provider HTTP decompression failures that could stop cache jobs with `Error -3 while decompressing data: incorrect header check`.
- Provider decompression failures are now treated as provider failures so the configured fallback chain can continue.
- Added Apple Music to the SpotiFLAC fallback chain and mapped Apple lossless/Atmos quality requests to `ALAC` and `ATMOS`.
- Repaired provider downloads that arrive with the wrong file extension before audio validation and metadata embedding.
- Improved YouTube cookie-file discovery and retry behavior for cookie-gated or anti-bot YouTube downloads.
- Kept SpotiFLAC endpoint cache writes outside the signed macOS app bundle so packaged builds continue to pass code-signature verification.

## Updated

- Visible Settings footer, backend user-agent, release helper, and macOS About/bundle metadata now report `1.2.1`.
