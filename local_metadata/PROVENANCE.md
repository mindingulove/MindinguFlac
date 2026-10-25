# Retained metadata implementations

Ported from the locally retained SpotiFLAC 3.9.0 source, originally pinned to
`a471fdc5374101a53137949d449f41e76249148c`. The original MIT license is included.
No checkout, download or import of the unavailable SpotiFLAC repository is needed.

`artist_profile.py` retains Spotify artist profile parsing. `lyrics.py` retains
provider ordering, synced lyrics, fallback and response caching; the supporting
TTML/TOTP/cache modules are retained alongside it. HTTP pooling and cache paths
are owned by Mindinguflac. Optional direct Apple subscriber lyrics reuse Mornye's
HTTP/model helpers through the retained Apple client. These are independent of
Mornye's REST endpoint coverage.

Mornye's artist-profile and lyrics functions are the primary runtime path. These
retained implementations are selected only when the matching upstream function
is missing, and do not require the retired SpotiFLAC package or repository.
