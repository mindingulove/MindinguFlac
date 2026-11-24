package com.mindinguflac.android;

import androidx.media3.common.C;
import androidx.media3.common.audio.BaseAudioProcessor;
import androidx.media3.common.audio.AudioProcessor;
import androidx.media3.common.util.UnstableApi;
import java.nio.ByteBuffer;

/** Playback-only gated RMS matching; constants match volume_normalizer.py. */
@androidx.annotation.OptIn(markerClass = UnstableApi.class)
final class VolumeNormalizer extends BaseAudioProcessor {
    private volatile boolean enabled;
    private boolean lastEnabled;
    private double energy, windowEnergy, gain = 1, target = 1;
    private long frames;
    private int windowFrames;

    void setEnabled(boolean value) { enabled = value; }

    @Override protected AudioFormat onConfigure(AudioFormat format)
            throws UnhandledAudioFormatException {
        if (format.encoding != C.ENCODING_PCM_16BIT) throw new UnhandledAudioFormatException(format);
        // Remain in the PCM chain while bypassed, allowing a live toggle.
        return format;
    }

    @Override protected void onFlush() { resetLevel(); }

    private void resetLevel() {
        energy = windowEnergy = frames = windowFrames = 0;
        gain = target = 1;
    }

    @Override public void queueInput(ByteBuffer input) {
        boolean active = enabled;
        if (active != lastEnabled) { resetLevel(); lastEnabled = active; }
        ByteBuffer output = replaceOutputBuffer(input.remaining());
        if (!active) { output.put(input).flip(); return; }
        int startPosition = input.position();
        int channels = inputAudioFormat.channelCount;
        int frameCount = input.remaining() / (2 * channels);
        int window = Math.max(1, Math.round(inputAudioFormat.sampleRate * 0.4f));
        double peak = 0;
        for (int i = 0; i < frameCount; i++) {
            double sum = 0;
            for (int c = 0; c < channels; c++) {
                double sample = input.getShort() / 32768.0;
                sum += sample * sample;
                peak = Math.max(peak, Math.abs(sample));
            }
            windowEnergy += sum / channels;
            if (++windowFrames >= window) {
                double gate = Math.max(1e-5, frames > 0 ? energy / frames * 0.1 : 0);
                if (windowEnergy / windowFrames > gate) {
                    energy += windowEnergy;
                    frames += windowFrames;
                    target = Math.max(Math.pow(10, -24.0 / 20), Math.min(Math.pow(10, 12.0 / 20),
                            Math.pow(10, -18.0 / 20) / Math.sqrt(energy / frames)));
                }
                windowEnergy = windowFrames = 0;
            }
        }
        input.position(startPosition);
        double ceiling = peak > 0 ? 0.98 / peak : Double.POSITIVE_INFINITY;
        double start = Math.min(gain, ceiling);
        double end = Math.min(target + (start - target) * Math.exp(-frameCount / (inputAudioFormat.sampleRate * 0.5)), ceiling);
        for (int i = 0; i < frameCount; i++) {
            double scale = start + (end - start) * i / Math.max(1, frameCount - 1);
            for (int c = 0; c < channels; c++) output.putShort((short) Math.round(input.getShort() * scale));
        }
        gain = end;
        output.flip();
    }
}
