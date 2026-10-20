package com.mindinguflac.android;

import android.content.Context;
import android.media.AudioDeviceCallback;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import androidx.media3.common.AudioAttributes;
import androidx.media3.common.C;
import androidx.media3.common.MediaItem;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.DataSink;
import androidx.media3.datasource.DataSpec;
import androidx.media3.datasource.DefaultDataSource;
import androidx.media3.datasource.HttpDataSource;
import androidx.media3.datasource.TeeDataSource;
import androidx.media3.datasource.okhttp.OkHttpDataSource;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.OkHttpClient;

/**
 * Native playback for the "choose an output" path on Android.
 *
 * The WebView's audio element can only play on whatever output Android picks
 * for the whole device. ExoPlayer can be pointed at one specific output with
 * {@link ExoPlayer#setPreferredAudioDevice}, so when the user selects a device
 * in the app's output menu the page hands playback to this player instead —
 * the same contract the desktop app's native player implements (Python's
 * native_audio drives this class through Chaquopy, and the page drives Python
 * through /api/native_audio/*).
 *
 * Audio focus is deliberately not handled here: MediaPlaybackService already
 * holds it for the whole app, and a second holder would make the two fight.
 * Every public method may be called from any thread; ExoPlayer itself is only
 * touched on the main looper.
 */
@androidx.annotation.OptIn(markerClass = UnstableApi.class)
public final class NativeAudioPlayer {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final Object LOCK = new Object();

    private static volatile Context context;
    private static ExoPlayer player;
    private static AudioManager audioManager;
    private static AudioDeviceCallback deviceCallback;

    // Guarded by LOCK; read by status() from any thread.
    private static int streamId;
    private static int preferredDeviceId = -1;
    private static String preferredDeviceName = "";
    private static String error = "";
    private static int httpStatus;
    private static String notice = "";
    private static boolean ended;
    private static boolean wantPlaying;
    private static long startedAt;

    private NativeAudioPlayer() {}

    public static void initialize(Context appContext) {
        context = appContext.getApplicationContext();
    }

    public static boolean available() {
        return context != null;
    }

    // ------------------------------------------------------------------ outputs

    /** Connected outputs a user can pick, as JSON [{id, name, type}]. */
    public static String listOutputs() {
        JSONArray result = new JSONArray();
        AudioManager manager = audioManager();
        if (manager == null) return result.toString();
        Map<String, Boolean> seen = new HashMap<>();
        for (AudioDeviceInfo device : manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
            String type = selectableType(device.getType());
            if (type.isEmpty()) continue;
            String name = displayName(device, type);
            // One entry per physical device: Bluetooth often reports the same
            // headset several times (A2DP, LE audio, broadcast).
            String key = name + "|" + type;
            if (seen.containsKey(key)) continue;
            seen.put(key, true);
            try {
                result.put(new JSONObject().put("id", device.getId()).put("name", name).put("type", type));
            } catch (Exception ignored) {
            }
        }
        return result.toString();
    }

    /** Bluetooth/USB devices report their own name; wired jacks and HDMI
     *  usually report the phone's model, so those are labelled by type. */
    private static String displayName(AudioDeviceInfo device, String type) {
        String product = String.valueOf(device.getProductName() == null ? "" : device.getProductName()).trim();
        if (!product.isEmpty() && !product.equalsIgnoreCase(android.os.Build.MODEL)) return product;
        switch (type) {
            case "wired": return "Wired headphones";
            case "hdmi": return "HDMI";
            case "line": return "Line out";
            case "usb": return "USB audio";
            default: return "Bluetooth audio";
        }
    }

    private static String selectableType(int type) {
        switch (type) {
            case AudioDeviceInfo.TYPE_BLUETOOTH_A2DP:
            case 26: // TYPE_BLE_HEADSET (API 31)
            case 27: // TYPE_BLE_SPEAKER (API 31)
                return "bluetooth";
            case AudioDeviceInfo.TYPE_WIRED_HEADPHONES:
            case AudioDeviceInfo.TYPE_WIRED_HEADSET:
            case 22: // TYPE_USB_HEADSET
                return "wired";
            case AudioDeviceInfo.TYPE_USB_DEVICE:
            case AudioDeviceInfo.TYPE_USB_ACCESSORY:
            case AudioDeviceInfo.TYPE_DOCK:
                return "usb";
            case AudioDeviceInfo.TYPE_HDMI:
            case AudioDeviceInfo.TYPE_HDMI_ARC:
            case 29: // TYPE_HDMI_EARC (API 31)
                return "hdmi";
            case AudioDeviceInfo.TYPE_LINE_ANALOG:
            case AudioDeviceInfo.TYPE_LINE_DIGITAL:
                return "line";
            default:
                // Built-in speaker/earpiece are "This phone"; telephony and
                // SCO (call audio) are not music outputs.
                return "";
        }
    }

    private static AudioDeviceInfo findDevice(int id, String name) {
        AudioManager manager = audioManager();
        if (manager == null) return null;
        AudioDeviceInfo byName = null;
        for (AudioDeviceInfo device : manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
            if (selectableType(device.getType()).isEmpty()) continue;
            if (device.getId() == id) return device;
            // Bluetooth devices get a new id each time they reconnect, so a
            // saved selection is matched again by name.
            String product = displayName(device, selectableType(device.getType()));
            if (byName == null && name != null && !name.isEmpty() && product.equalsIgnoreCase(name.trim())) {
                byName = device;
            }
        }
        return byName;
    }

    private static AudioManager audioManager() {
        if (audioManager == null && context != null) audioManager = context.getSystemService(AudioManager.class);
        return audioManager;
    }

    /** Route playback to an output (id -1 = This phone). JSON {ok, error, device_id}. */
    public static String setOutput(int deviceId, String deviceName) {
        return onMain(() -> {
            JSONObject result = new JSONObject();
            AudioDeviceInfo device = null;
            if (deviceId >= 0 || (deviceName != null && !deviceName.isEmpty())) {
                device = findDevice(deviceId, deviceName);
                if (device == null) {
                    return result.put("ok", false)
                            .put("error", "Selected output is not connected: " + (deviceName == null || deviceName.isEmpty() ? deviceId : deviceName))
                            .toString();
                }
            }
            synchronized (LOCK) {
                preferredDeviceId = device == null ? -1 : device.getId();
                preferredDeviceName = device == null ? "" : displayName(device, selectableType(device.getType()));
                notice = "";
            }
            if (player != null) player.setPreferredAudioDevice(device);
            return result.put("ok", true).put("device_id", device == null ? -1 : device.getId()).toString();
        }, "{\"ok\":false,\"error\":\"Audio output switch timed out\"}");
    }

    // ----------------------------------------------------------------- playback

    /**
     * Start a local file (path) or remote stream (http/https URL).
     * headersJson: request headers for remote streams, as a JSON object.
     */
    public static String play(String source, String headersJson, int deviceId, String deviceName,
                              double volume, double positionSeconds) {
        return onMain(() -> {
            ensurePlayer(headersJson);
            AudioDeviceInfo device = deviceId >= 0 || (deviceName != null && !deviceName.isEmpty())
                    ? findDevice(deviceId, deviceName) : null;
            if ((deviceId >= 0 || (deviceName != null && !deviceName.isEmpty())) && device == null) {
                return new JSONObject().put("ok", false)
                        .put("error", "Selected output is not connected: " + deviceName).toString();
            }
            Uri uri = source.startsWith("http://") || source.startsWith("https://")
                    ? Uri.parse(source) : Uri.fromFile(new File(source));
            synchronized (LOCK) {
                streamId += 1;
                preferredDeviceId = device == null ? -1 : device.getId();
                preferredDeviceName = device == null ? "" : displayName(device, selectableType(device.getType()));
                error = "";
                httpStatus = 0;
                notice = "";
                ended = false;
                wantPlaying = true;
                startedAt = SystemClock.elapsedRealtime();
            }
            player.setPreferredAudioDevice(device);
            player.setVolume((float) Math.max(0, Math.min(1, volume)));
            player.setMediaItem(MediaItem.fromUri(uri), Math.max(0, Math.round(positionSeconds * 1000)));
            player.prepare();
            player.setPlayWhenReady(true);
            return new JSONObject().put("ok", true).put("stream_id", streamId).toString();
        }, "{\"ok\":false,\"error\":\"Native player did not start\"}");
    }

    public static void pause() {
        synchronized (LOCK) { wantPlaying = false; }
        onMain(() -> { if (player != null) player.setPlayWhenReady(false); return ""; }, "");
    }

    public static void resume() {
        synchronized (LOCK) { wantPlaying = true; ended = false; }
        onMain(() -> { if (player != null) player.setPlayWhenReady(true); return ""; }, "");
    }

    public static void stop() {
        synchronized (LOCK) { wantPlaying = false; }
        onMain(() -> {
            if (player != null) {
                player.stop();
                player.clearMediaItems();
            }
            return "";
        }, "");
    }

    public static void seek(double positionSeconds) {
        onMain(() -> {
            if (player != null) player.seekTo(Math.max(0, Math.round(positionSeconds * 1000)));
            synchronized (LOCK) { ended = false; }
            return "";
        }, "");
    }

    public static void setVolume(double volume) {
        onMain(() -> { if (player != null) player.setVolume((float) Math.max(0, Math.min(1, volume))); return ""; }, "");
    }

    /** Snapshot for the page's 500 ms poll. Positions are in seconds. */
    public static String status() {
        return onMain(() -> {
            JSONObject json = new JSONObject();
            synchronized (LOCK) {
                json.put("stream_id", streamId)
                        .put("device_id", preferredDeviceId)
                        .put("device_name", preferredDeviceName)
                        .put("error", error)
                        .put("http_status", httpStatus)
                        .put("notice", notice)
                        .put("ended", ended)
                        .put("want_playing", wantPlaying)
                        .put("elapsed", startedAt == 0 ? 0 : (SystemClock.elapsedRealtime() - startedAt) / 1000.0);
            }
            if (player == null) {
                return json.put("active", false).put("playing", false).put("buffering", false)
                        .put("position", 0).put("duration", 0).put("buffered", 0).toString();
            }
            long duration = player.getDuration();
            return json.put("active", player.getPlaybackState() != Player.STATE_IDLE || !error.isEmpty())
                    .put("playing", player.isPlaying())
                    .put("buffering", player.getPlaybackState() == Player.STATE_BUFFERING)
                    .put("position", player.getCurrentPosition() / 1000.0)
                    .put("duration", duration == C.TIME_UNSET ? 0 : duration / 1000.0)
                    .put("buffered", Math.max(0, player.getBufferedPosition() - player.getCurrentPosition()) / 1000.0)
                    .toString();
        }, "{\"active\":false,\"playing\":false,\"error\":\"Native player is not responding\"}");
    }

    // ----------------------------------------------------------------- internals

    private static String currentHeaders = "";

    private static void ensurePlayer(String headersJson) throws Exception {
        String headers = headersJson == null ? "" : headersJson;
        if (player != null && headers.equals(currentHeaders)) return;
        if (player != null) {
            player.release();
            player = null;
        }
        currentHeaders = headers;
        Map<String, String> requestHeaders = new HashMap<>();
        String userAgent = null;
        if (!headers.isEmpty()) {
            JSONObject object = new JSONObject(headers);
            Iterator<String> keys = object.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                if ("User-Agent".equalsIgnoreCase(key)) userAgent = object.getString(key);
                else requestHeaders.put(key, object.getString(key));
            }
        }
        // OkHttp negotiates HTTP/2 with ALPN. Monochrome's storage proxy
        // rejects HTTP/1.1 range requests (400 IncompleteBody), which is what
        // ExoPlayer's default HttpURLConnection source would send.
        OkHttpDataSource.Factory http = new OkHttpDataSource.Factory(new OkHttpClient.Builder().build())
                .setDefaultRequestProperties(requestHeaders);
        if (userAgent != null) http.setUserAgent(userAgent);
        // Remote streams pass through a recorder that keeps the first part of
        // the track on disk, so the music-video matcher can read the song's
        // audio without downloading it a second time.
        DefaultDataSource.Factory dataSource = new DefaultDataSource.Factory(context,
                () -> new TeeDataSource(http.createDataSource(), new StreamHeadRecorder()));
        player = new ExoPlayer.Builder(context)
                .setMediaSourceFactory(new DefaultMediaSourceFactory(dataSource))
                .setWakeMode(C.WAKE_MODE_NETWORK)
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(C.USAGE_MEDIA)
                        .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                        .build(), /* handleAudioFocus= */ false)
                .build();
        player.addListener(new Player.Listener() {
            @Override
            public void onPlaybackStateChanged(int state) {
                if (state == Player.STATE_ENDED) {
                    synchronized (LOCK) { ended = true; wantPlaying = false; }
                }
            }

            @Override
            public void onPlayerError(PlaybackException exception) {
                int status = 0;
                Throwable cause = exception.getCause();
                while (cause != null) {
                    if (cause instanceof HttpDataSource.InvalidResponseCodeException) {
                        status = ((HttpDataSource.InvalidResponseCodeException) cause).responseCode;
                        break;
                    }
                    cause = cause.getCause();
                }
                String message = exception.getMessage() == null ? exception.getErrorCodeName() : exception.getMessage();
                synchronized (LOCK) {
                    httpStatus = status;
                    error = status > 0 ? "Server returned " + status : message;
                    wantPlaying = false;
                }
            }
        });
        registerDeviceCallback();
    }

    // ------------------------------------------------------------ stream head

    /** Enough of a hi-res FLAC for the matcher's 90 s window. */
    private static final long HEAD_CAPTURE_BYTES = 48L * 1024 * 1024;
    private static final int HEAD_FILES_KEPT = 4;

    /**
     * Path of the recorded start of a stream, or "" if none was captured.
     * Used by Python (video sync) through Chaquopy.
     */
    public static String streamHeadPath(String url) {
        File file = headFile(url);
        return file != null && file.isFile() && file.length() > 0 ? file.getAbsolutePath() : "";
    }

    private static File headFile(String url) {
        if (context == null || url == null) return null;
        try {
            byte[] digest = MessageDigest.getInstance("SHA-1").digest(url.getBytes("UTF-8"));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) hex.append(String.format("%02x", b));
            File directory = new File(context.getCacheDir(), "stream-head");
            if (!directory.isDirectory() && !directory.mkdirs()) return null;
            return new File(directory, hex + ".audio");
        } catch (Exception ignored) {
            return null;
        }
    }

    private static void pruneHeads(File keep) {
        File[] files = keep.getParentFile().listFiles();
        if (files == null || files.length <= HEAD_FILES_KEPT) return;
        Arrays.sort(files, (a, b) -> Long.compare(b.lastModified(), a.lastModified()));
        for (int i = HEAD_FILES_KEPT; i < files.length; i++) {
            if (!files[i].equals(keep)) //noinspection ResultOfMethodCallIgnored
                files[i].delete();
        }
    }

    /**
     * Writes the bytes ExoPlayer reads from the start of a stream to a cache
     * file. Reads that begin elsewhere (seeks) are ignored, so the file only
     * ever holds a clean prefix of the track.
     */
    private static final class StreamHeadRecorder implements DataSink {
        private FileOutputStream out;
        private long written;

        @Override
        public void open(DataSpec spec) {
            close();
            if (spec.position != 0) return;
            File file = headFile(spec.uri.toString());
            if (file == null) return;
            try {
                out = new FileOutputStream(file, false);
                written = 0;
                pruneHeads(file);
            } catch (Exception ignored) {
                out = null;
            }
        }

        @Override
        public void write(byte[] buffer, int offset, int length) {
            if (out == null || written >= HEAD_CAPTURE_BYTES) return;
            int count = (int) Math.min(length, HEAD_CAPTURE_BYTES - written);
            try {
                out.write(buffer, offset, count);
                written += count;
            } catch (Exception ignored) {
                close();
            }
        }

        @Override
        public void close() {
            if (out == null) return;
            try {
                out.close();
            } catch (Exception ignored) {
            }
            out = null;
        }
    }

    private static void registerDeviceCallback() {
        AudioManager manager = audioManager();
        if (manager == null || deviceCallback != null) return;
        deviceCallback = new AudioDeviceCallback() {
            @Override
            public void onAudioDevicesRemoved(AudioDeviceInfo[] removed) {
                int current;
                synchronized (LOCK) { current = preferredDeviceId; }
                if (current < 0) return;
                for (AudioDeviceInfo device : removed) {
                    if (device.getId() != current) continue;
                    // The chosen output went away (Bluetooth off / out of
                    // range). Android would fall back on its own; make it
                    // explicit so the page's menu follows the real route.
                    if (player != null) player.setPreferredAudioDevice(null);
                    synchronized (LOCK) {
                        notice = "Audio output disconnected (" + preferredDeviceName + "); playing on This phone";
                        preferredDeviceId = -1;
                        preferredDeviceName = "";
                    }
                    return;
                }
            }
        };
        manager.registerAudioDeviceCallback(deviceCallback, MAIN);
    }

    private static String onMain(Callable<String> work, String fallback) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            try {
                return work.call();
            } catch (Exception exception) {
                return errorJson(exception, fallback);
            }
        }
        AtomicReference<String> result = new AtomicReference<>(fallback);
        CountDownLatch done = new CountDownLatch(1);
        MAIN.post(() -> {
            try {
                result.set(work.call());
            } catch (Exception exception) {
                result.set(errorJson(exception, fallback));
            } finally {
                done.countDown();
            }
        });
        try {
            done.await(3, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
        return result.get();
    }

    private static String errorJson(Exception exception, String fallback) {
        if (fallback.isEmpty()) return "";
        try {
            return new JSONObject().put("ok", false).put("error", String.valueOf(exception.getMessage())).toString();
        } catch (Exception ignored) {
            return fallback;
        }
    }
}
