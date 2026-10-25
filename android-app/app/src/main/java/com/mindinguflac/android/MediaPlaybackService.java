package com.mindinguflac.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.MediaMetadata;
import android.media.VolumeProvider;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;
import android.view.KeyEvent;

import org.json.JSONObject;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Keeps WebView playback alive in the background and puts it on the lock screen.
 *
 * The audio itself is an {@code <audio>} element inside the WebView, which the
 * system is free to suspend once the Activity stops — which is why playback
 * died the moment the app was backgrounded, and why nothing appeared in the
 * notification shade. A foreground service with {@code mediaPlayback} type
 * keeps the process at foreground importance so the element keeps running, and
 * a {@link MediaSession} gives the system the metadata and transport controls
 * it needs for the notification, the lock screen and Bluetooth media keys.
 *
 * This service never touches audio itself. Every control it exposes is relayed
 * back to the page through {@link MediaCommandRelay}, so the page stays the one
 * source of truth for what is playing.
 */
public final class MediaPlaybackService extends Service {

    static final String ACTION_UPDATE = "com.mindinguflac.android.action.UPDATE";
    static final String ACTION_PLAY_PAUSE = "com.mindinguflac.android.action.PLAY_PAUSE";
    static final String ACTION_PREVIOUS = "com.mindinguflac.android.action.PREVIOUS";
    static final String ACTION_NEXT = "com.mindinguflac.android.action.NEXT";
    static final String ACTION_STOP = "com.mindinguflac.android.action.STOP";
    static final String EXTRA_STATE = "state";

    private static final String TAG = "MindinguflacMedia";
    private static final String CHANNEL_ID = "mindinguflac_playback";
    private static final int NOTIFICATION_ID = 0x4D46;

    private final ExecutorService artworkExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService heartbeatExecutor = Executors.newSingleThreadExecutor();
    private final Handler heartbeatHandler = new Handler(Looper.getMainLooper());
    private final AtomicBoolean heartbeatInFlight = new AtomicBoolean(false);
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            if (!remotePlayback) return;
            renewRemoteSession();
            heartbeatHandler.postDelayed(this, 8000);
        }
    };
    private MediaSession session;
    private AudioManager audioManager;
    private PowerManager.WakeLock remoteWakeLock;
    private AudioFocusRequest focusRequest;
    private boolean hasStartedForeground;

    private String title = "";
    private String artist = "";
    private String album = "";
    private volatile String artworkUrl = "";
    private String apiToken = "";
    private String apiOrigin = "";
    private long durationMs;
    private long positionMs;
    private boolean playing;
    private boolean remotePlayback;
    private VolumeProvider remoteVolume;

    private String loadedArtworkUrl = "";
    private Bitmap loadedArtwork;

    @Override
    public void onCreate() {
        super.onCreate();
        audioManager = getSystemService(AudioManager.class);
        createChannel();
        session = new MediaSession(this, "Mindinguflac");
        session.setCallback(new MediaSession.Callback() {
            @Override
            public void onPlay() {
                MediaCommandRelay.playPause();
            }

            @Override
            public void onPause() {
                MediaCommandRelay.playPause();
            }

            @Override
            public void onSkipToPrevious() {
                MediaCommandRelay.previous();
            }

            @Override
            public void onSkipToNext() {
                MediaCommandRelay.next();
            }

            @Override
            public void onStop() {
                MediaCommandRelay.stop();
            }

            @Override
            public boolean onMediaButtonEvent(Intent intent) {
                KeyEvent event = intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT);
                if (event == null || event.getAction() != KeyEvent.ACTION_DOWN) {
                    return super.onMediaButtonEvent(intent);
                }
                switch (event.getKeyCode()) {
                    case KeyEvent.KEYCODE_MEDIA_PLAY:
                    case KeyEvent.KEYCODE_MEDIA_PAUSE:
                    case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                    case KeyEvent.KEYCODE_HEADSETHOOK:
                        MediaCommandRelay.playPause();
                        return true;
                    case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                        MediaCommandRelay.previous();
                        return true;
                    case KeyEvent.KEYCODE_MEDIA_NEXT:
                        MediaCommandRelay.next();
                        return true;
                    default:
                        return super.onMediaButtonEvent(intent);
                }
            }
        });
        session.setActive(true);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_PLAY_PAUSE.equals(action)) {
            MediaCommandRelay.playPause();
        } else if (ACTION_PREVIOUS.equals(action)) {
            MediaCommandRelay.previous();
        } else if (ACTION_NEXT.equals(action)) {
            MediaCommandRelay.next();
        } else if (ACTION_STOP.equals(action)) {
            MediaCommandRelay.stop();
            stopPlaybackService();
            return START_NOT_STICKY;
        } else if (ACTION_UPDATE.equals(action)) {
            applyState(intent.getStringExtra(EXTRA_STATE));
        }
        // A command that arrived before any metadata still has to post a
        // notification, or the system kills the service for not going
        // foreground in time.
        publish();
        return START_NOT_STICKY;
    }

    private void applyState(String json) {
        if (json == null) return;
        try {
            JSONObject value = new JSONObject(json);
            title = value.optString("title", title);
            artist = value.optString("artist", artist);
            album = value.optString("album", album);
            durationMs = value.optLong("duration_ms", durationMs);
            positionMs = value.optLong("position_ms", positionMs);
            playing = value.optBoolean("playing", playing);
            boolean remote = value.optBoolean("remote", remotePlayback);
            int volume = Math.max(0, Math.min(100, value.optInt("volume", remoteVolume == null ? 100 : remoteVolume.getCurrentVolume())));
            if (remote && remoteVolume == null) {
                remoteVolume = new VolumeProvider(VolumeProvider.VOLUME_CONTROL_ABSOLUTE, 100, volume) {
                    @Override public void onAdjustVolume(int direction) {
                        if (direction == AudioManager.ADJUST_RAISE) MediaCommandRelay.adjustVolume(0.05f);
                        else if (direction == AudioManager.ADJUST_LOWER) MediaCommandRelay.adjustVolume(-0.05f);
                    }
                    @Override public void onSetVolumeTo(int requested) {
                        MediaCommandRelay.setVolume(Math.max(0, Math.min(100, requested)) / 100f);
                    }
                };
                session.setPlaybackToRemote(remoteVolume);
                releaseAudioFocus();
            } else if (!remote && remoteVolume != null) {
                session.setPlaybackToLocal(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());
                remoteVolume = null;
            }
            remotePlayback = remote;
            if (remoteVolume != null) remoteVolume.setCurrentVolume(volume);
            apiToken = value.optString("token", apiToken);
            apiOrigin = value.optString("api_origin", apiOrigin);
            if (remote) {
                acquireRemoteWakeLock();
                heartbeatHandler.removeCallbacks(heartbeat);
                heartbeatHandler.post(heartbeat);
            } else {
                heartbeatHandler.removeCallbacks(heartbeat);
                releaseRemoteWakeLock();
            }
            String url = value.optString("artwork_url", artworkUrl);
            if (!url.equals(artworkUrl)) {
                artworkUrl = url;
                loadArtwork(url);
            }
        } catch (Exception error) {
            Log.w(TAG, "Ignoring malformed now-playing state: " + error);
        }
        if (playing && !remotePlayback) {
            holdAudioFocus();
        }
    }

    /** Refresh the receiver lease without relying on background WebView timers. */
    private void renewRemoteSession() {
        final String origin = apiOrigin;
        final String token = apiToken;
        if (origin == null || origin.isEmpty() || token == null || token.isEmpty()
                || !heartbeatInFlight.compareAndSet(false, true)) return;
        heartbeatExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                URL endpoint = new URL(origin + "/api/remote/status");
                connection = (HttpURLConnection) endpoint.openConnection();
                connection.setRequestMethod("GET");
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(7000);
                connection.setRequestProperty("X-Mindinguflac-Token", token);
                connection.setRequestProperty("Cache-Control", "no-cache");
                int status = connection.getResponseCode();
                if (status != 200) Log.w(TAG, "Remote keepalive returned HTTP " + status);
            } catch (Exception error) {
                Log.w(TAG, "Remote keepalive failed: " + error.getClass().getSimpleName());
            } finally {
                if (connection != null) connection.disconnect();
                heartbeatInFlight.set(false);
            }
        });
    }

    private void acquireRemoteWakeLock() {
        if (remoteWakeLock != null && remoteWakeLock.isHeld()) return;
        PowerManager power = getSystemService(PowerManager.class);
        if (power == null) return;
        remoteWakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Mindinguflac:RemoteControl");
        remoteWakeLock.setReferenceCounted(false);
        remoteWakeLock.acquire();
    }

    private void releaseRemoteWakeLock() {
        if (remoteWakeLock != null && remoteWakeLock.isHeld()) remoteWakeLock.release();
        remoteWakeLock = null;
    }

    private void publish() {
        session.setMetadata(new MediaMetadata.Builder()
                .putString(MediaMetadata.METADATA_KEY_TITLE, title)
                .putString(MediaMetadata.METADATA_KEY_ARTIST, artist)
                .putString(MediaMetadata.METADATA_KEY_ALBUM, album)
                .putLong(MediaMetadata.METADATA_KEY_DURATION, durationMs > 0 ? durationMs : -1L)
                .putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, loadedArtwork)
                .build());
        session.setPlaybackState(new PlaybackState.Builder()
                .setActions(PlaybackState.ACTION_PLAY
                        | PlaybackState.ACTION_PAUSE
                        | PlaybackState.ACTION_PLAY_PAUSE
                        | PlaybackState.ACTION_SKIP_TO_PREVIOUS
                        | PlaybackState.ACTION_SKIP_TO_NEXT
                        | PlaybackState.ACTION_STOP)
                .setState(playing ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED,
                        Math.max(0L, positionMs), playing ? 1.0f : 0.0f)
                .build());

        Notification notification = buildNotification();
        if (!hasStartedForeground) {
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    startForeground(NOTIFICATION_ID, notification,
                            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
                } else {
                    startForeground(NOTIFICATION_ID, notification);
                }
                hasStartedForeground = true;
            } catch (Exception error) {
                // Starting a foreground service is restricted while the app is
                // in the background. Fall back to a plain notification so the
                // user still sees something rather than nothing.
                Log.w(TAG, "Could not start the playback foreground service: " + error);
                NotificationManager manager = getSystemService(NotificationManager.class);
                if (manager != null) manager.notify(NOTIFICATION_ID, notification);
            }
        } else {
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.notify(NOTIFICATION_ID, notification);
        }
    }

    private Notification buildNotification() {
        Notification.Builder builder = new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(title.isEmpty() ? "Mindinguflac" : title)
                .setContentText(artist)
                .setSubText(album)
                .setLargeIcon(loadedArtwork)
                .setContentIntent(openAppIntent())
                .setDeleteIntent(servicePendingIntent(ACTION_STOP))
                .setOngoing(playing)
                .setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_PUBLIC);

        builder.addAction(new Notification.Action.Builder(
                Icon_previous(), "Previous", servicePendingIntent(ACTION_PREVIOUS)).build());
        builder.addAction(new Notification.Action.Builder(
                playing ? Icon_pause() : Icon_play(),
                playing ? "Pause" : "Play",
                servicePendingIntent(ACTION_PLAY_PAUSE)).build());
        builder.addAction(new Notification.Action.Builder(
                Icon_next(), "Next", servicePendingIntent(ACTION_NEXT)).build());

        Notification.MediaStyle style = new Notification.MediaStyle()
                .setMediaSession(session.getSessionToken())
                .setShowActionsInCompactView(0, 1, 2);
        builder.setStyle(style);
        return builder.build();
    }

    private android.graphics.drawable.Icon Icon_play() {
        return android.graphics.drawable.Icon.createWithResource(this,
                android.R.drawable.ic_media_play);
    }

    private android.graphics.drawable.Icon Icon_pause() {
        return android.graphics.drawable.Icon.createWithResource(this,
                android.R.drawable.ic_media_pause);
    }

    private android.graphics.drawable.Icon Icon_previous() {
        return android.graphics.drawable.Icon.createWithResource(this,
                android.R.drawable.ic_media_previous);
    }

    private android.graphics.drawable.Icon Icon_next() {
        return android.graphics.drawable.Icon.createWithResource(this,
                android.R.drawable.ic_media_next);
    }

    private PendingIntent openAppIntent() {
        Intent intent = new Intent(this, MainActivity.class)
                .setAction(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return PendingIntent.getActivity(this, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private PendingIntent servicePendingIntent(String action) {
        Intent intent = new Intent(this, MediaPlaybackService.class).setAction(action);
        return PendingIntent.getService(this, action.hashCode(), intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private void loadArtwork(String url) {
        if (url == null || url.isEmpty()) {
            loadedArtwork = null;
            loadedArtworkUrl = "";
            return;
        }
        final String requested = url;
        final String token = apiToken;
        final String origin = apiOrigin;
        artworkExecutor.execute(() -> {
            Bitmap bitmap = fetchBitmap(requested, token, origin);
            if (bitmap == null || !requested.equals(artworkUrl)) return;
            loadedArtwork = bitmap;
            loadedArtworkUrl = requested;
            // Re-publish so the lock screen picks up the cover once it lands.
            publish();
        });
    }

    private Bitmap fetchBitmap(String url, String token, String origin) {
        HttpURLConnection connection = null;
        try {
            URL target = new URL(url);
            connection = (HttpURLConnection) target.openConnection();
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(8000);
            if (token != null && !token.isEmpty() && origin != null && !origin.isEmpty()
                    && (target.getProtocol() + "://" + target.getAuthority()).equals(origin)) {
                // Never send the local API token to an artwork provider or redirect.
                connection.setInstanceFollowRedirects(false);
                connection.setRequestProperty("X-Mindinguflac-Token", token);
            }
            try (InputStream stream = connection.getInputStream()) {
                BitmapFactory.Options options = new BitmapFactory.Options();
                options.inPreferredConfig = Bitmap.Config.RGB_565;
                return BitmapFactory.decodeStream(stream, null, options);
            }
        } catch (Exception error) {
            Log.w(TAG, "Could not load notification artwork: " + error);
            return null;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    /**
     * Hold audio focus, but never react to losing it.
     *
     * Both halves of that matter. Holding focus is what keeps WebView audio
     * alive once the app is backgrounded — without it playback stops the
     * moment you leave the app, foreground service or not. But acting on the
     * focus callbacks is wrong here, because the page's own <audio> element
     * also requests focus: starting the next queue track made Chromium take
     * focus, which fired LOSS_TRANSIENT on this request, and pausing in
     * response killed the track that had just started. Chromium already
     * handles real interruptions from other apps for its own element, so this
     * listener deliberately does nothing.
     */
    private void holdAudioFocus() {
        if (audioManager == null || focusRequest != null) return;
        AudioAttributes attributes = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                .build();
        focusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                .setAudioAttributes(attributes)
                .setWillPauseWhenDucked(false)
                .setOnAudioFocusChangeListener(change -> {
                    // Intentionally empty — see the note above.
                })
                .build();
        audioManager.requestAudioFocus(focusRequest);
    }

    private void releaseAudioFocus() {
        if (audioManager != null && focusRequest != null) {
            audioManager.abandonAudioFocusRequest(focusRequest);
        }
        focusRequest = null;
    }

    private void stopPlaybackService() {
        releaseAudioFocus();
        stopForeground(STOP_FOREGROUND_REMOVE);
        hasStartedForeground = false;
        stopSelf();
    }

    private void createChannel() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(CHANNEL_ID) != null) return;
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Playback", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Shows the track Mindinguflac is playing");
        channel.setShowBadge(false);
        channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        manager.createNotificationChannel(channel);
    }

    @Override
    public void onDestroy() {
        heartbeatHandler.removeCallbacks(heartbeat);
        releaseRemoteWakeLock();
        releaseAudioFocus();
        if (session != null) {
            session.setActive(false);
            session.release();
        }
        artworkExecutor.shutdownNow();
        heartbeatExecutor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    /** Push the page's current now-playing state into the notification. */
    static void update(Context context, String json) {
        Intent intent = new Intent(context, MediaPlaybackService.class)
                .setAction(ACTION_UPDATE)
                .putExtra(EXTRA_STATE, json);
        context.startForegroundService(intent);
    }

    /** Tear the notification down when the page has nothing playing. */
    static void clear(Context context) {
        context.startService(new Intent(context, MediaPlaybackService.class)
                .setAction(ACTION_STOP));
    }
}
