# Lyric alignment to playing audio

Provider timestamps can belong to a different edit or include a fixed delay.
Lyrics cannot be cross-correlated as soundtracks, so the app independently
recognizes the start of the playing audio, then looks for the starts of lyric
phrases in those observed word timestamps. It does not send the lyrics as a
recognition prompt. All recognition runs on-device with whisper.cpp and the
multilingual quantized Whisper base model; no microphone or audio upload is used.

At least four independent line starts, three different phrases, a 25-second
span and an unambiguous consensus are required. Whole-phrase agreement tolerates recognition substitutions and low-confidence
individual words while requiring at least 70 percent coverage and a confident
phrase average. The first word must be observed; its time is never invented. Competing chorus
offsets and inconsistent edits are rejected. The matcher estimates a constant
offset, without stretching timestamps or guessing through inserted verses.
If recognition cannot establish a reliable match, the provider timing remains.
The UI distinguishes alignment in progress, a measured match and provider timing.

The existing video-sync decoder supplies 16 kHz mono PCM from the same local
file or already-buffered stream. Partial prefixes are retried, and one worker
limits recognition to one song at a time. A native CPU bridge is shared by the
ctypes desktop adapter and the Android JNI adapter. Android decodes through its
existing MediaCodec bridge. Results and manual nudges are stored per audio
source and lyrics hash, preventing one edition/provider's timings from leaking
to another. Lyrics follow the audible clock, including native output latency and measured
Web Audio output timestamps for browser playback. Unsupported output timing is
left unadjusted, and remote previews without CORS keep their original route.

Source/model versions and SHA-256 checksums are pinned in
`native/lyrics_alignment/assets.json`. `scripts/prepare_lyrics_alignment.py`
prepares them, with `--build-desktop` building the native bridge. PyInstaller and
Gradle invoke the preparation step. The model increases bundled assets by about
60 MB. Native sources are compiled from the verified archive during the build;
the application does not download models while playing music. MIT notices ship
beside the model. Android build 20 contains the JNI bridge and model.

Final retained-audio checks on macOS:

- Garota Nacional: five agreeing phrase starts across 99.58 seconds, measured
  delay +0.340 seconds, median residual 0.040 seconds.
- Save Tonight: ten agreeing phrase starts across 72.76 seconds, measured
  delay +0.200 seconds, median residual 0.100 seconds. Shifting the lyric
  timestamps by seven seconds changed the correction to -6.800 seconds.
- An unrelated existing Eye In The Sky buffer was rejected.

Word timing uses whisper.cpp's cross-attention DTW alignment with the base-model
heads preset. Approximate segment splits were insufficient for singing.
Matcher cache keys exclude earlier approximate results. Whole-phrase validation
recovers matches despite uncertain individual words, while retaining phrase
coverage, confidence, competing-offset and minimum-span requirements.

Browser clock compensation remains a separate measurement (0.007 seconds on the
observed desktop route). It uses output timestamps when routed through Web Audio,
or the reported default-output latency when the browser cannot reroute a Web
Audio destination. AudioContext setup has a bounded wait and never blocks normal
playback while waiting for autoplay permission. Named output routing is retained.

These are timestamp/phrase checks, not a claim of perfect timing for all songs.
Android build and JNI packaging checks do not establish physical-device speed
or recognition accuracy; a device run remains required.

The panel's own smooth scroll must not be treated as a manual scroll. Following
is paused by wheel, touch, navigation-key or scrollbar input rather than every
scroll event. Forced positioning jumps directly to the current line; ordinary
line changes retain smooth scrolling. This prevents long animations or old
timeouts from disabling lyric following after alignment has succeeded.
