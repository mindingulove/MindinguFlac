package com.mindinguflac.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import com.nothing.ketchum.Common;
import com.nothing.ketchum.Glyph;
import com.nothing.ketchum.GlyphFrame;
import com.nothing.ketchum.GlyphManager;
import com.nothing.ketchum.GlyphMatrixFrame;
import com.nothing.ketchum.GlyphMatrixManager;
import com.nothing.ketchum.GlyphMatrixObject;

/**
 * Shows the playing track's progress on a Nothing phone's Glyph Interface:
 * the progress strip (C1/D1) on Phone (1), (2), (2a), (2a) Plus and (3a), a
 * filling bar on the small A strip of Phone (4a)/(4b), and a ring on the
 * Glyph Matrix of Phone (3)/(4a) Pro.
 *
 * On Nothing OS 4 (Android 16) and later the system's Glyph Progress drives
 * the lights instead, and the SDK is not used (it would fight the system over
 * the same lights, and needs a debug key). Nothing's GlyphNotification
 * service (GlyphNotificationManagerV2) adds any app whose notification uses
 * {@code Notification.ProgressStyle} with a determinate progress, and lists
 * it under Settings > Glyph Interface > Glyph Progress. Promotion to a Live
 * Update is not required, so the notification is posted on an
 * IMPORTANCE_MIN channel: no status bar icon or chip next to the music one.
 *
 * Driven by {@link MediaPlaybackService}: the page only reports position on
 * play/pause/seek, so progress is extrapolated from the last report. Lights
 * are on while playing and off when paused or stopped. Everything is
 * best-effort; on any other phone, or if the Glyph service refuses (no key,
 * debug mode off, app not in the foreground), this does nothing.
 */
final class GlyphProgress {
    private static final String TAG = "MindinguflacGlyph";
    private static final long TICK_MS = 1000;
    private static final int API_LIVE_UPDATES = 36;
    private static final String LIVE_CHANNEL_ID = "mindinguflac_glyph_progress";
    private static final String OLD_LIVE_CHANNEL_ID = "mindinguflac_track_progress";
    private static final int LIVE_NOTIFICATION_ID = 0x4D47;

    private final Context context;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final boolean supported;
    private final boolean matrix;
    private final boolean liveUpdates;
    private String title = "";
    private String artist = "";
    private boolean livePosted;

    private GlyphManager strip;
    private GlyphMatrixManager matrixManager;
    private boolean connecting;
    private boolean ready;
    private boolean lit;

    private boolean playing;
    private long positionMs;
    private long durationMs;
    private long reportedAt;
    private int shownProgress = -1;

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            render();
            if (playing) handler.postDelayed(this, TICK_MS);
        }
    };

    GlyphProgress(Context context) {
        this.context = context.getApplicationContext();
        boolean nothing = Build.VERSION.SDK_INT >= 34
                && "nothing".equalsIgnoreCase(Build.MANUFACTURER);
        boolean isMatrix = false;
        boolean known = false;
        if (nothing) {
            try {
                isMatrix = Common.is23112() || Common.is25111p();
                known = isMatrix || stripDevice() != null;
            } catch (Throwable error) {
                Log.w(TAG, "Glyph device check failed: " + error);
            }
        }
        liveUpdates = nothing && Build.VERSION.SDK_INT >= API_LIVE_UPDATES;
        supported = known || liveUpdates;
        matrix = isMatrix;
        if (liveUpdates) createLiveChannel();
    }

    void setTrack(String title, String artist) {
        this.title = title == null ? "" : title;
        this.artist = artist == null ? "" : artist;
    }

    /** Latest playback state, from the service's now-playing update. */
    void update(boolean playing, long positionMs, long durationMs) {
        if (!supported) return;
        this.playing = playing;
        this.positionMs = Math.max(0, positionMs);
        this.durationMs = durationMs;
        this.reportedAt = SystemClock.elapsedRealtime();
        handler.removeCallbacks(tick);
        if (playing && durationMs > 0) {
            if (!liveUpdates) connect();
            handler.post(tick);
        } else {
            turnOff();
        }
    }

    void release() {
        handler.removeCallbacks(tick);
        if (!supported) return;
        turnOff();
        try {
            if (strip != null) {
                try { strip.closeSession(); } catch (Throwable ignored) {}
                strip.unInit();
            }
            if (matrixManager != null) matrixManager.unInit();
        } catch (Throwable error) {
            Log.w(TAG, "Glyph release failed: " + error);
        }
        strip = null;
        matrixManager = null;
        ready = false;
        connecting = false;
    }

    private void createLiveChannel() {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;
        // The first build used a LOW channel (status bar icon); channel
        // importance cannot be lowered by the app, so it gets a new one.
        manager.deleteNotificationChannel(OLD_LIVE_CHANNEL_ID);
        if (manager.getNotificationChannel(LIVE_CHANNEL_ID) != null) return;
        NotificationChannel channel = new NotificationChannel(
                LIVE_CHANNEL_ID, "Glyph progress", NotificationManager.IMPORTANCE_MIN);
        channel.setDescription("Shows the playing track's progress on the Glyph lights");
        channel.setShowBadge(false);
        channel.setSound(null, null);
        channel.enableVibration(false);
        manager.createNotificationChannel(channel);
    }

    private void postLiveUpdate(int progress) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;
        Intent open = new Intent(context, MainActivity.class)
                .setAction(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        Notification.Builder builder = new Notification.Builder(context, LIVE_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(title.isEmpty() ? "Mindinguflac" : title)
                .setContentText(artist)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setCategory(Notification.CATEGORY_PROGRESS)
                .setContentIntent(PendingIntent.getActivity(context, 1, open,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        Notification.Style style = progressStyle(progress);
        if (style == null) return;
        builder.setStyle(style);
        Notification notification = builder.build();
        manager.notify(LIVE_NOTIFICATION_ID, notification);
        livePosted = true;
    }

    /**
     * {@code new Notification.ProgressStyle().setProgress(progress)} (API 36,
     * max 100 with no segments), by reflection while the app compiles
     * against API 35.
     */
    private static Notification.Style progressStyle(int progress) {
        try {
            Class<?> type = Class.forName("android.app.Notification$ProgressStyle");
            Object style = type.getConstructor().newInstance();
            type.getMethod("setProgress", int.class).invoke(style, progress);
            return (Notification.Style) style;
        } catch (Throwable error) {
            Log.w(TAG, "ProgressStyle unavailable: " + error);
            return null;
        }
    }

    private void connect() {
        if (ready || connecting) return;
        connecting = true;
        try {
            if (matrix) {
                matrixManager = GlyphMatrixManager.getInstance(context);
                matrixManager.init(new GlyphMatrixManager.Callback() {
                    @Override public void onServiceConnected(ComponentName name) {
                        try {
                            matrixManager.register(Common.is23112() ? Glyph.DEVICE_23112 : Glyph.DEVICE_25111p);
                            onReady();
                        } catch (Throwable error) {
                            Log.w(TAG, "Glyph Matrix register failed: " + error);
                        }
                    }
                    @Override public void onServiceDisconnected(ComponentName name) {
                        onLost();
                    }
                });
            } else {
                strip = GlyphManager.getInstance(context);
                strip.init(new GlyphManager.Callback() {
                    @Override public void onServiceConnected(ComponentName name) {
                        try {
                            strip.register(stripDevice());
                            strip.openSession();
                            onReady();
                        } catch (Throwable error) {
                            Log.w(TAG, "Glyph session failed: " + error);
                        }
                    }
                    @Override public void onServiceDisconnected(ComponentName name) {
                        onLost();
                    }
                });
            }
        } catch (Throwable error) {
            Log.w(TAG, "Glyph service unavailable: " + error);
            connecting = false;
        }
    }

    private void onReady() {
        handler.post(() -> {
            connecting = false;
            ready = true;
            shownProgress = -1;
            if (playing) render();
        });
    }

    private void onLost() {
        handler.post(() -> {
            ready = false;
            connecting = false;
            lit = false;
        });
    }

    private void render() {
        if (!playing || durationMs <= 0) return;
        long now = positionMs + (SystemClock.elapsedRealtime() - reportedAt);
        int progress = (int) Math.max(0, Math.min(100, now * 100 / durationMs));
        if (liveUpdates) {
            // Re-post on each percent step, the Glyph's resolution.
            if (progress == shownProgress) return;
            try {
                postLiveUpdate(progress);
                shownProgress = progress;
            } catch (Throwable error) {
                Log.w(TAG, "Glyph progress notification failed: " + error);
            }
            return;
        }
        if (!ready) return;
        if (progress == shownProgress && lit) return;
        try {
            if (matrix) {
                matrixManager.setAppMatrixFrame(ringFrame(progress));
            } else if (isSmallStrip()) {
                showSmallStrip(progress);
            } else {
                GlyphFrame.Builder builder = strip.getGlyphFrameBuilder();
                GlyphFrame frame = (isPhone1() ? builder.buildChannelD() : builder.buildChannelC()).build();
                strip.displayProgress(frame, progress);
            }
            shownProgress = progress;
            lit = true;
        } catch (Throwable error) {
            Log.w(TAG, "Glyph progress failed: " + error);
        }
    }

    private void turnOff() {
        shownProgress = -1;
        if (livePosted) {
            livePosted = false;
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if (manager != null) manager.cancel(LIVE_NOTIFICATION_ID);
        }
        if (!lit) return;
        lit = false;
        try {
            if (matrixManager != null) matrixManager.closeAppMatrix();
            if (strip != null) strip.turnOff();
        } catch (Throwable error) {
            Log.w(TAG, "Glyph turn-off failed: " + error);
        }
    }

    /** Phone (4a)/(4b): A1 (top) .. An (bottom), filled from the bottom up. */
    private void showSmallStrip(int progress) {
        int count = isPhone4a() ? 6 : 4;
        int on = Math.round(progress * count / 100f);
        if (on <= 0) {
            strip.turnOff();
            return;
        }
        GlyphFrame.Builder builder = strip.getGlyphFrameBuilder();
        for (int i = 0; i < on; i++) builder.buildChannel(count - 1 - i);
        strip.toggle(builder.build());
    }

    /** A dim full ring with the played part bright, drawn clockwise from 12 o'clock. */
    private int[] ringFrame(int progress) {
        int size = Common.getDeviceMatrixLength();
        Bitmap bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        canvas.drawColor(Color.BLACK);
        Paint paint = new Paint();
        paint.setAntiAlias(false);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(size >= 20 ? 2f : 1f);
        float inset = size >= 20 ? 1.5f : 1f;
        RectF bounds = new RectF(inset, inset, size - inset, size - inset);
        paint.setColor(Color.rgb(40, 40, 40));
        canvas.drawArc(bounds, 0, 360, false, paint);
        if (progress > 0) {
            paint.setColor(Color.WHITE);
            canvas.drawArc(bounds, -90, 360f * progress / 100f, false, paint);
        }
        GlyphMatrixObject ring = new GlyphMatrixObject.Builder()
                .setImageSource(bitmap)
                .setPosition(0, 0)
                .build();
        return new GlyphMatrixFrame.Builder().addTop(ring).build(context).render();
    }

    private static String stripDevice() {
        if (Common.is20111()) return Glyph.DEVICE_20111;
        if (Common.is22111()) return Glyph.DEVICE_22111;
        if (Common.is23111()) return Glyph.DEVICE_23111;
        if (Common.is23113()) return Glyph.DEVICE_23113;
        if (Common.is24111()) return Glyph.DEVICE_24111;
        if (Common.is25111()) return Glyph.DEVICE_25111;
        if (Common.is25131()) return Glyph.DEVICE_25131;
        return null;
    }

    private static boolean isPhone1() { return Common.is20111(); }
    private static boolean isPhone4a() { return Common.is25111(); }
    private static boolean isSmallStrip() { return Common.is25111() || Common.is25131(); }
}
