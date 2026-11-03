package com.mindinguflac.android;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;

import androidx.browser.customtabs.CustomTabsIntent;

import java.lang.ref.WeakReference;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Opens a Mornye provider's signed-session challenge in a Chrome Custom Tab,
 * as Mornye's own Android app does (LaunchMode.inAppBrowserView).
 *
 * The desktop solver drives a hidden Chromium; the phone has none, and a
 * WebView is challenged harder by Cloudflare, so Turnstile there waits for a
 * tap. A Custom Tab is the user's real browser, which Turnstile usually lets
 * through on its own. The page then redirects to the challenge's callback,
 * mornye://session-grant (the page accepts only Mornye's and SpotiFLAC's
 * schemes), which {@link MornyeGrantActivity} catches and passes to
 * {@link #deliver}; android_runtime/mornye_android.py waits in
 * {@link #awaitGrant}.
 *
 * Android does not let a backgrounded app open the browser, so then a "Tap to
 * verify" notification opens it instead, again as in Mornye's app.
 */
public final class MornyeVerification {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static volatile WeakReference<Activity> activity = new WeakReference<>(null);
    private static volatile Context appContext;
    private static volatile boolean resumed;
    public static final String ACTION_SHOW = "com.mindinguflac.android.VERIFY_MORNYE";
    private static final String CHANNEL_ID = "mornye_verification";
    private static final int NOTIFICATION_ID = 4417;
    // The challenge waiting to be opened from the notification.
    private static final AtomicReference<String> pendingUrl = new AtomicReference<>();
    // Whether a tab was opened over the app, so finish() should return to it.
    private static final AtomicBoolean tabOpened = new AtomicBoolean();
    // The state the open challenge expects back, and the grants that arrived.
    private static final AtomicReference<String> expectedState = new AtomicReference<>();
    private static final LinkedBlockingQueue<String> grants = new LinkedBlockingQueue<>();

    private MornyeVerification() {}

    public static void attach(Activity current) {
        activity = new WeakReference<>(current);
        appContext = current.getApplicationContext();
    }

    public static void detach(Activity current) {
        if (activity.get() == current) {
            activity = new WeakReference<>(null);
            resumed = false;
        }
    }

    public static void setResumed(Activity current, boolean value) {
        if (activity.get() == current) resumed = value;
    }

    /** Opens the challenge now if the app is in front, else offers it in a notification. */
    public static boolean request(String challengeUrl, String state) {
        Context context = appContext;
        if (context == null || challengeUrl == null || challengeUrl.isEmpty()) return false;
        grants.clear();
        expectedState.set(state == null ? "" : state);
        pendingUrl.set(challengeUrl);
        MAIN.post(() -> {
            Activity current = activity.get();
            if (resumed && current != null && !current.isFinishing()) {
                showPending(current);
            } else {
                notifyVerificationNeeded(context);
            }
        });
        return true;
    }

    /** Called by MornyeGrantActivity with mornye://session-grant?grant=...&state=... */
    public static void deliver(Uri link) {
        String grant = link.getQueryParameter("grant");
        String state = link.getQueryParameter("state");
        String expected = expectedState.get();
        if (grant == null || grant.trim().isEmpty() || expected == null || !expected.equals(state)) return;
        grants.offer(grant.trim());
    }

    /** The grant from the redirect, or "" if none arrived within {@code timeoutMs}. */
    public static String awaitGrant(long timeoutMs) throws InterruptedException {
        String grant = grants.poll(timeoutMs, TimeUnit.MILLISECONDS);
        return grant == null ? "" : grant;
    }

    /** Opens the challenge waiting for a tap, if any (from the notification's intent). */
    public static void showPending(Activity current) {
        MAIN.post(() -> {
            String url = pendingUrl.getAndSet(null);
            if (url == null || current.isFinishing()) return;
            cancelNotification(current);
            CustomTabsIntent tab = new CustomTabsIntent.Builder()
                    .setShowTitle(true)
                    .setUrlBarHidingEnabled(true)
                    .build();
            try {
                tab.launchUrl(current, Uri.parse(url));
            } catch (ActivityNotFoundException exc) {
                // No Custom Tabs browser: any browser still reaches the callback.
                current.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            }
            tabOpened.set(true);
        });
    }

    /** Ends the attempt: drops the notification and returns from the browser. */
    public static void finish(boolean verified) {
        Context context = appContext;
        pendingUrl.set(null);
        expectedState.set(null);
        MAIN.post(() -> {
            if (context == null) return;
            cancelNotification(context);
            if (verified && tabOpened.getAndSet(false)) {
                // MainActivity sits under the tab in the same task; CLEAR_TOP
                // closes the tab and returns to the running activity.
                Intent back = new Intent(context, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                                | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                try {
                    context.startActivity(back);
                } catch (RuntimeException ignored) {
                    // Blocked from the background: the user returns themselves.
                }
            }
            tabOpened.set(false);
        });
    }

    private static void cancelNotification(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager != null) manager.cancel(NOTIFICATION_ID);
    }

    private static void notifyVerificationNeeded(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            manager.createNotificationChannel(new NotificationChannel(
                    CHANNEL_ID, "Provider verification", NotificationManager.IMPORTANCE_HIGH));
        }
        Intent open = new Intent(context, MainActivity.class)
                .setAction(ACTION_SHOW)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent tap = PendingIntent.getActivity(context, NOTIFICATION_ID, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle("Tap to verify the Mornye provider")
                .setContentText("A quick Cloudflare check in your browser continues the download.")
                .setContentIntent(tap)
                .setAutoCancel(true)
                .build();
        manager.notify(NOTIFICATION_ID, notification);
    }
}
