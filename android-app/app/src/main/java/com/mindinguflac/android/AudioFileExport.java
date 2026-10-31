package com.mindinguflac.android;

import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import java.io.File;
import java.nio.ByteBuffer;

/** Save compressed playback audio without decoding or including video tracks. */
public final class AudioFileExport {
    private AudioFileExport() {}

    public static String saveAudio(String source, String destinationBase) throws Exception {
        MediaExtractor extractor = new MediaExtractor();
        MediaMuxer muxer = null;
        File temporary = null;
        boolean started = false;
        try {
            extractor.setDataSource(source);
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
            if (track < 0) throw new IllegalArgumentException("Playback file has no audio track");
            String mime = format.getString(MediaFormat.KEY_MIME);
            boolean webm = "audio/opus".equals(mime) || "audio/vorbis".equals(mime);
            temporary = new File(destinationBase + ".audio.part" + (webm ? ".webm" : ".m4a"));
            muxer = new MediaMuxer(temporary.getPath(), webm ? MediaMuxer.OutputFormat.MUXER_OUTPUT_WEBM
                                                          : MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            int outputTrack = muxer.addTrack(format);
            muxer.start();
            started = true;
            extractor.selectTrack(track);
            int capacity = format.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)
                    ? Math.max(1048576, format.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE)) : 1048576;
            ByteBuffer buffer = ByteBuffer.allocateDirect(capacity);
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            int samples = 0;
            while (true) {
                buffer.clear();
                int size = extractor.readSampleData(buffer, 0);
                if (size < 0) break;
                info.set(0, size, extractor.getSampleTime(), extractor.getSampleFlags());
                muxer.writeSampleData(outputTrack, buffer, info);
                samples++;
                extractor.advance();
            }
            if (samples == 0) throw new IllegalArgumentException("Playback file contains no audio samples");
            muxer.stop();
            started = false;
            return temporary.getPath();
        } catch (Exception exception) {
            if (temporary != null) temporary.delete();
            throw exception;
        } finally {
            extractor.release();
            if (muxer != null) {
                if (started) try { muxer.stop(); } catch (Exception ignored) {}
                muxer.release();
            }
        }
    }
}
