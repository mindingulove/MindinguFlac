package com.mindinguflac.android;

/** Offline recognition of the buffered song, never the microphone. */
public final class LyricsAlignment {
    static { System.loadLibrary("lyrics_whisper"); }
    private LyricsAlignment() {}
    public static native byte[] transcribeNative(String modelPath, byte[] monoFloatPcm);
}
