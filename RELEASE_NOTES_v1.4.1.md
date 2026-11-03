# Mindinguflac v1.4.1

## Added
- Mornye failures fall back to Monochrome, then to YouTube for playback (straight to YouTube while Monochrome is cooling down). Lossless downloads keep the Mornye error rather than saving YouTube audio.
- YouTube Music catalog search (ytmusicapi) runs alongside the YouTube search, so songs whose plain search returns covers, live versions or nothing match the official release. A title-only search is the last resort.
- Every engine waits for the network to come back after a disconnect and then retries the song, instead of failing it. Network errors no longer blacklist a working YouTube video.
- YouTube sign-in on Android, as on the desktop, so downloads run as the signed-in user.

## Changed
- Monochrome and Mornye no longer prefetch upcoming songs: both limit requests per address, so only the song being played uses the quota. YouTube and torrent prefetch is unchanged.
- When the Mornye provider gateway answers 429, Mornye is skipped (and a running Mornye job is stopped) until the limit resets, with "Mornye download limit reached; it resets in about X h", and the song falls back at once instead of hanging.

## Fixed
- Mornye providers on Android failed every song (`not_found_on_amazon`): the extension bridge now offers the synchronous `fetch()` the extensions expect.
- YouTube rate-limiting ("try again later", then "Video unavailable" for every video) stops the candidate loop without blacklisting good videos.
- Device sync no longer duplicates Recent rows or revives removed ones when the other device sends them back.
