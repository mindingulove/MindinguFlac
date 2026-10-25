# Mindinguflac fixes: user requirements and verification plan

Updated 2026-10-19. This plan consolidates the user's feedback from this work session and marks the current implementation state so follow-up work can continue without losing requirements.

## Search and result presentation

- Preserve the earlier Spotify-like search results implementation. Do not replace the result list with a short artist-only list.
- Keep related tracks, albums, playlists, and artists visible; rank close matches first and unrelated artists toward the end, as Spotify does.
- Use the Spotify `SearchResultV2` result payload and query suggestions through the same path where applicable.
- Show artist avatar artwork from `visuals.avatarImage.sources` when square artist artwork is absent.
- Check: multiword searches for “Pink Floyd” retain songs/albums and do not put unrelated artists such as Guns N' Roses near the top; artist images render.

## Provider menu

- Keep provider order: Loosy - YouTube; Monochrome (FLAC); Torrent (Experimental); Experimental - Spotiflac.
- Torrent belongs below Monochrome and above Spotiflac.
- Check the desktop and Android provider selectors separately.

## Monochrome streaming, downloads, and matching

- Normal Play must stream the Monochrome `/track/<id>` resource directly. Do not create or download a local audio file just because playback started.
- Playback must pause/resume through byte ranges from the current playhead and recover after pauses or interrupted responses.
- Only the explicit Download button saves audio. Download must use the same Monochrome track resource and byte-range behavior, append/resume into a `.part` file, validate the completed FLAC, and rename it to `.flac`.
- Search by ISRC first when the job has one, then fall back to title plus artist. Accept an exact ISRC result even when its title spelling/version differs; otherwise require an exact title/artist match and reject a conflicting ISRC.
- Current explanation for the reported “no exact track match”: the old implementation only queried `title + artist`; it checked ISRC only among those returned rows. The current implementation queries ISRC first and then falls back to text.
- Regression fixed for Spotify “So Far Away - Remastered 1996” (`GBUM72102498`): Monochrome returns the Dire Straits recording as “So Far Away” (`GBF088500673`) with a catalog duration 5.76 seconds longer. The prior 5-second duration gate rejected the title/artist match despite it being the remaster label. Same-recording tolerance is now 8 seconds; live/edit title variants remain excluded. Focused Monochrome tests: 33 passed.
- Check: a title-variant result can resolve by ISRC; explicit download resumes after a broken response; stream mode makes no download request and writes no file.

## Audio/video and output-device synchronization

- Side video must pause when audio buffers and resume only when audio really enters `playing`; `canplay` alone must not resume the video. Keep manual pause intent respected.
- Current change: audio `waiting` pauses the side video; audio `playing` clears the buffer state and resumes it; playback visibility now accounts for audio buffering. Video seek alignment remains tied to the audio playhead.
- Current change: a stalled Monochrome direct stream now reopens the track URL at the saved playhead, with a guarded retry if playback still has not resumed. Buffering is reported as paused to the player, Dock/Touch Bar bridge, and Android now-playing state; a confirmed `playing` event restores the playing state.
- Follow-up from the pause/play regression: restore time seeks even when WebKit has no FLAC duration metadata; use track duration for seekbar/time display; keep a last-known direct-stream playhead; route Monochrome media errors through direct reconnect instead of starting a duplicate search; ignore late errors whose source URL was replaced. Verify a real pause/resume cycle and seekbar/Touch Bar alignment after installing the build.
- Latest buffering recovery update: Monochrome retries continue until playback advances, with increasing delay capped at 30 seconds; pausing or changing tracks cancels the retries. While buffering, replace the central play/pause glyph with an animated spinner and disable the button. FFmpeg native stream mode also retries HTTP/network failures (including 429) without writing an audio file.
- Live verification attempt: the workspace app streamed “Shout” from Monochrome; pausing held at 0:04, but resuming reproduced the silence (`currentTime` stayed at 4.85, `readyState` stayed 0, and no media error was reported). This exposed another case: a restored/manual direct-stream resume can enter waiting before `audioHasPlayed` is true, so reconnect eligibility now also recognizes an explicit direct-stream resume. Re-test a same-session play/pause/resume after this change; the Monochrome endpoint became unresponsive during the test, so the repaired path is not yet live-verified and the macOS build is intentionally withheld.
- Device routing update: direct Monochrome URLs now decode in a native FFmpeg pipe and send PCM to the selected CoreAudio output via sounddevice. No track file is created and the explicit Download button path remains separate. Native status now drives position, buffering, pause, resume, seek, and media controls; switching away from the selected device resumes the direct stream in the browser.
- Native stream startup now prebuffers 30 seconds of decoded PCM before opening audible playback, reducing stalls at the start. The UI stays in Buffering during this prebuffer, and the activity log reports the 30-second target.
- Latest report: the native direct-stream route could remain at Buffering while the cache activity log stayed empty. Native stream phase/progress is now mirrored to that log at startup, during prebuffer, on playback/pause/end, and every five seconds while waiting without progress; decoder/output errors are logged as errors.
- Latest playback regression: starting Monochrome direct playback now cancels queued prefetch jobs, and the upcoming-track prefetch hook skips both browser and native Monochrome direct streams. This avoids unrelated prefetch work interrupting a live stream.
- Live-window inspection found the current playback was using the browser route, not native output (`/api/native_audio/status` was idle). The browser path could stick at 0:00 because reconnect was blocked until the first `playing` event, and its 700 ms timer could repeatedly close a slow first response. The guard is removed, the first retry waits 5 seconds (backoff remains unlimited up to 30 seconds), and browser stream open/wait/error/recovery/retry events now post to the visible cache log.
- Buffer spinner visual: while buffering, the center control becomes a dark charcoal circle with a centered green arc; it stays disabled until the stream reports playback. Normal play/pause styling remains unchanged.
- Live device test: detected EDIFIER S351DB in CoreAudio and PortAudio; native direct stream advanced on that output, and two pause/resume cycles held the playhead while paused then advanced it after resume. EDIFIER later disconnected from macOS during follow-up verification, so it is currently absent from both device lists; final UI selection cannot be re-tested until it reconnects.
- Latest regression verification: EDIFIER S351DB reappeared. A real Monochrome stream started after prebuffer, then passed two pause/resume cycles with the phase staying paused, the position stable during pause, and position advancing after resume. The activity-log helper was exercised for buffering, started, paused, and decoder-error events; all appeared in the log snapshot.
- Latest pause-loop fix: WebKit's `waiting` event can arrive when a manual pause closes its ranged response. That event is now ignored while the user's pause intent is set, manual pause clears buffering and cancels retry timers, and the saved playhead is retained. If WebKit reports media error 4 for Monochrome's octet-stream FLAC, playback now falls back once to FFmpeg/native output, which waits for the 30-second PCM prebuffer before playback; this route uses the selected native output when one is selected, otherwise the system default.
- First-click autoplay regression: WebKit may reject `audio.play()` because Monochrome lookup completes after transient click activation expires. On macOS, a rejected Monochrome autoplay now hands the same URL and playhead to native audio automatically; the player remains locked in buffering until output starts, and the cache log records the handoff. A Playwright harness simulates this rejection and verifies the native fallback parameters.
- First switch back to “This computer”: its menu handler previously enumerated browser outputs before applying the default route, which could trigger a microphone permission wait on first use. A live native Monochrome stream now routes directly to the system default before that enumeration; it keeps the existing decoder/request and position. The source-level regression check verifies this fast path precedes output enumeration.
- First-open-only picker delay: `_renderConnectDevices()` was enumerating browser outputs and requesting temporary microphone permission to reveal labels, despite native CoreAudio already providing device names. Skip that browser step when native routing is available.
- Route acknowledgment regression: closing the picker before route confirmation left the user with no controls when the output open timed out. Keep the picker open until confirmed and refresh it after failure. The output switch now opens the target device before retiring the current output; if the target cannot open, it records the failure and leaves the current stream/output alive. It no longer aborts an active PortAudio stream from the request thread. Route confirmation waits up to 10 seconds; on timeout it restores the previous route selection.
- Latest queue-advance fix: WebKit may emit `ended` when a ranged FLAC response stalls around 0:24. If the saved playhead is short of the Spotify track duration, keep the same track and reconnect from that position instead of marking listening complete or advancing. The current Monochrome resolver lists only `tracks.monochrome.st` as a verified instance; duplicate parallel requests to that same host are avoided because they add traffic without providing a faster independent winner and may worsen rate limiting.
- Latest source checks: `node --check static/app.js`, Python compile checks, targeted native/Monochrome tests (15 passed), and `git diff --check` passed after the prefetch guard and pause-lock fix.
- Latest macOS build: arm64 PyInstaller app completed; deep strict codesign passed; packaged JS/CSS hashes match source; ffmpeg and PortAudio are present in the bundle.

## Buffering indicator and progress log UI

- Latest user report: “buffering shouldn't always display log instead of favourite addon.” The screenshot shows the footer player status area during buffering. Verify the intended relationship between the buffering indicator/progress-log affordance and the favorite/add-on control, then adjust so buffering does not replace or obscure the expected control.
- Keep progress logs available on demand; they should not take over the normal player/favorite UI merely because audio is buffering.

## Current verification checkpoint

- Passed: `node --check static/app.js`.
- Passed: `venv-macos/bin/python -m pytest test/test_native_audio.py test/test_backend_monochrome.py -q` (15 tests).
- Passed: `venv-macos/bin/python -m py_compile app.py native_audio.py`.
- Passed: `git diff --check`.
- Latest regression checks: `node --check static/app.js`, `venv-macos/bin/python -m unittest discover -s test -p 'test_native_audio.py'` (10 passed), and `venv-macos/bin/python test/verify_monochrome_playback_handoff.py` (autoplay handoff and default-device fast path passed).
- Latest route responsiveness checks: native output-switch lifecycle test verifies same stream identity and paused state through an acknowledged route change; Playwright/source harness verifies default routing bypasses browser device enumeration. Actual acoustic routing still needs confirmation with EDIFIER attached.
- Latest picker/route regression checks: native lifecycle test verifies the route request preserves stream identity and pause state without aborting the active output from the request thread; Playwright/source harness verifies native picker skips browser permission enumeration and closes only after route confirmation.
- Latest corrective package: rebuilt and reopened `dist/Mindinguflac.app`. It opens successfully on port 52035; `/api/audio/devices` reports native audio available and EDIFIER S351DB present; `/api/native_audio/status` is idle, so live Monochrome-to-EDIFIER playback remains untested in this process. Route handoff starts the replacement output before retiring the current output; on failure or timeout it restores the previous route and leaves the picker open.
- Latest build after removing the output-write lock: PyInstaller completed to `dist/Mindinguflac.app`; deep strict code-signature verification passed; packaged `static/app.js` matches source; the executable archive contains `native_audio`, and bundled FFmpeg/PortAudio are arm64 binaries. The currently supplied playback logs do not include route-selection events, so they cannot verify the physical device handoff.
- Latest packaged runtime check: rebuilt `dist/Mindinguflac.app`, deep strict code-signature verification passed, and packaged `static/app.js` SHA-256 matches the source. Reopened the app successfully. Its restored “So Far Away” Monochrome request was rejected by the provider with HTTP 429 before audible playback, so a real first-click autoplay and live device-switch test could not be completed against the service in this run.
- Built: arm64 macOS app with `JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" venv-macos/bin/python -m PyInstaller --noconfirm Mindinguflac.spec`.
- Passed: `codesign --verify --deep --strict dist/Mindinguflac.app`; bundled `static/app.js` matches source.
- Built arm64 macOS app after source checks and direct-output control tests with `JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" venv-macos/bin/python -m PyInstaller --noconfirm Mindinguflac.spec`.
- Passed: `codesign --verify --deep --strict dist/Mindinguflac.app`; bundled `static/app.js` SHA-256 matches source; bundled PortAudio dylib is present.
- Not verified live: app-UI route selection and Touch Bar state. Edifier disappeared from CoreAudio after the direct native stream/control test.
