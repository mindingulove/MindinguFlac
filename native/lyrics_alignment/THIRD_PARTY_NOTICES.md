The offline lyric timestamp recognizer uses whisper.cpp v1.9.5 (MIT), pinned
by commit and archive hash in assets.json. The shared library statically links
its GGML CPU implementation. Source is fetched only at build time.

The multilingual Whisper base model (MIT, OpenAI) is quantized as base-q5_1 by
the upstream whisper.cpp project. Its original model and conversion are
identified at https://github.com/ggml-org/whisper.cpp/tree/master/models.
The model checksum is pinned in assets.json and checked before packaging.
Model bytes are built assets, not downloaded during listening. Audio recognition
runs locally; it neither records the microphone nor uploads playback audio.

The upstream MIT license is copied alongside the bundled model during builds.
