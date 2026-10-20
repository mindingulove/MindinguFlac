package com.mindinguflac.android;

import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.os.SystemClock;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * Decodes the start of an audio or video file to mono float PCM for the
 * soundtrack matcher (video_sync.py), using Android's own MediaCodec decoders
 * instead of ffmpeg, which the APK does not ship.
 *
 * Supports whatever this phone can play: MP3, AAC/M4A/MP4, FLAC, Opus,
 * Vorbis, WAV. Anything else throws, and the matcher reports "not matched".
 */
public final class AudioPcmDecoder {
    private static final long TIMEOUT_US = 10_000;
    private static final long MAX_DECODE_MS = 45_000;

    private AudioPcmDecoder() {}

    /**
     * The first {@code maxSeconds} of the file's first audio track, downmixed
     * to mono and downsampled to {@code sampleRate}, as little-endian float32.
     */
    public static byte[] decodeMono(String path, double maxSeconds, int sampleRate) throws Exception {
        MediaExtractor extractor = new MediaExtractor();
        MediaCodec codec = null;
        try {
            extractor.setDataSource(path);
            int track = -1;
            MediaFormat format = null;
            for (int i = 0; i < extractor.getTrackCount(); i++) {
                MediaFormat candidate = extractor.getTrackFormat(i);
                String mime = candidate.getString(MediaFormat.KEY_MIME);
                if (mime != null && mime.startsWith("audio/")) {
                    track = i;
                    format = candidate;
                    break;
                }
            }
            if (track < 0) throw new IllegalArgumentException("no audio track");
            extractor.selectTrack(track);
            codec = MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME));
            codec.configure(format, null, null, 0);
            codec.start();

            int channels = format.containsKey(MediaFormat.KEY_CHANNEL_COUNT) ? format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) : 2;
            int sourceRate = format.containsKey(MediaFormat.KEY_SAMPLE_RATE) ? format.getInteger(MediaFormat.KEY_SAMPLE_RATE) : 44100;
            int encoding = AudioFormat.ENCODING_PCM_16BIT;
            Downsampler downsampler = new Downsampler(sourceRate, sampleRate, (int) Math.ceil(maxSeconds * sampleRate));
            long limitUs = (long) (maxSeconds * 1_000_000L);
            boolean inputDone = false;
            boolean outputDone = false;
            long started = SystemClock.elapsedRealtime();
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();

            while (!outputDone && !downsampler.full()) {
                if (SystemClock.elapsedRealtime() - started > MAX_DECODE_MS) break;
                if (!inputDone) {
                    int inputIndex = codec.dequeueInputBuffer(TIMEOUT_US);
                    if (inputIndex >= 0) {
                        ByteBuffer input = codec.getInputBuffer(inputIndex);
                        int size = input == null ? -1 : extractor.readSampleData(input, 0);
                        long time = extractor.getSampleTime();
                        if (size < 0 || time > limitUs) {
                            codec.queueInputBuffer(inputIndex, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inputDone = true;
                        } else {
                            codec.queueInputBuffer(inputIndex, 0, size, time, 0);
                            extractor.advance();
                        }
                    }
                }
                int outputIndex = codec.dequeueOutputBuffer(info, TIMEOUT_US);
                if (outputIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat output = codec.getOutputFormat();
                    channels = output.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    int rate = output.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    if (rate != sourceRate) {
                        sourceRate = rate;
                        downsampler = new Downsampler(sourceRate, sampleRate, downsampler.capacity);
                    }
                    if (output.containsKey(MediaFormat.KEY_PCM_ENCODING)) {
                        encoding = output.getInteger(MediaFormat.KEY_PCM_ENCODING);
                    }
                } else if (outputIndex >= 0) {
                    ByteBuffer output = codec.getOutputBuffer(outputIndex);
                    if (output != null && info.size > 0) {
                        output.position(info.offset);
                        output.limit(info.offset + info.size);
                        downsampler.push(output.slice().order(ByteOrder.LITTLE_ENDIAN), encoding, channels);
                    }
                    codec.releaseOutputBuffer(outputIndex, false);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) outputDone = true;
                }
            }
            return downsampler.toBytes();
        } finally {
            if (codec != null) {
                try {
                    codec.stop();
                } catch (Exception ignored) {
                }
                codec.release();
            }
            extractor.release();
        }
    }

    /**
     * Mono mix + box-filter downsampling: each output sample is the mean of
     * the source samples in its period, which also removes the content above
     * the new Nyquist rate instead of aliasing it into the matcher's bands.
     */
    private static final class Downsampler {
        final int capacity;
        private final double step;
        private final float[] out;
        private int count;
        private double sum;
        private int summed;
        private double nextBoundary;
        private long sourceIndex;

        Downsampler(int sourceRate, int targetRate, int capacity) {
            this.capacity = capacity;
            this.step = sourceRate / (double) targetRate;
            this.out = new float[capacity];
            this.nextBoundary = step;
        }

        boolean full() {
            return count >= capacity;
        }

        void push(ByteBuffer pcm, int encoding, int channels) {
            int bytesPerSample;
            switch (encoding) {
                case AudioFormat.ENCODING_PCM_FLOAT:
                case 22: // ENCODING_PCM_32BIT (API 31)
                    bytesPerSample = 4;
                    break;
                case 21: // ENCODING_PCM_24BIT_PACKED (API 31)
                    bytesPerSample = 3;
                    break;
                case AudioFormat.ENCODING_PCM_8BIT:
                    bytesPerSample = 1;
                    break;
                default:
                    bytesPerSample = 2;
            }
            int frameBytes = bytesPerSample * Math.max(1, channels);
            while (pcm.remaining() >= frameBytes && !full()) {
                double mono = 0;
                for (int c = 0; c < channels; c++) mono += readSample(pcm, encoding);
                mono /= channels;
                sum += mono;
                summed += 1;
                sourceIndex += 1;
                if (sourceIndex >= nextBoundary) {
                    out[count++] = (float) (sum / summed);
                    sum = 0;
                    summed = 0;
                    nextBoundary += step;
                }
            }
        }

        private static double readSample(ByteBuffer pcm, int encoding) {
            switch (encoding) {
                case AudioFormat.ENCODING_PCM_FLOAT:
                    return pcm.getFloat();
                case 22:
                    return pcm.getInt() / 2147483648.0;
                case 21: {
                    int b0 = pcm.get() & 0xFF, b1 = pcm.get() & 0xFF, b2 = pcm.get();
                    return ((b2 << 16) | (b1 << 8) | b0) / 8388608.0;
                }
                case AudioFormat.ENCODING_PCM_8BIT:
                    return ((pcm.get() & 0xFF) - 128) / 128.0;
                default:
                    return pcm.getShort() / 32768.0;
            }
        }

        byte[] toBytes() {
            ByteBuffer bytes = ByteBuffer.allocate(count * 4).order(ByteOrder.LITTLE_ENDIAN);
            for (int i = 0; i < count; i++) bytes.putFloat(out[i]);
            return bytes.array();
        }
    }
}
